"""
Sentinel AI — Alert Orchestrator
Main pipeline: Dedup → Investigate → RCA → Fix Plan → Policy → Execute → Health Monitor
This is where the magic happens.
"""

import structlog
from datetime import datetime

from app.db.database import async_session
from app.models.incident import Incident, IncidentTimeline, IncidentStatus, Severity
from app.agents.investigator import investigate_incident
from app.agents.rca import generate_rca
from app.agents.remediation import generate_fix_plan
from app.engine.policy import check_policy
from app.engine.executor import execute_fix
from app.engine.dedup import is_duplicate, generate_fingerprint
from app.engine.health_monitor import monitor_health_post_fix
from app.engine.rag import generate_embedding, find_similar_incidents
from app.integrations.slack_bot import send_incident_to_slack
from app.api.websockets import manager as ws_manager

log = structlog.get_logger()

async def _broadcast(incident: Incident):
    """Helper to broadcast incident updates to connected WebSockets."""
    await ws_manager.broadcast_incident_update({
        "id": str(incident.id),
        "title": incident.title,
        "status": incident.status.value,
        "severity": incident.severity.value if incident.severity else None,
    })

async def _add_timeline(db, incident_id, event_type: str, title: str, description: str = "", data: dict = None, actor: str = "ai", tenant_id: str = None):
    """Helper to add a timeline event to an incident."""
    event = IncidentTimeline(
        incident_id=incident_id,
        tenant_id=tenant_id,
        event_type=event_type,
        title=title,
        description=description,
        data=data or {},
        actor=actor,
    )
    db.add(event)


async def process_alert(alert):
    """
    Main orchestration pipeline. Called when an alert is received.

    Full lifecycle:
    1. Dedup check (skip if duplicate)
    2. Create incident in DB
    3. AI Investigation
    4. Root Cause Analysis
    5. Fix Plan Generation
    6. Policy Check (auto vs manual)
    7. Execute fix (if approved)
    8. Health monitoring post-fix
    9. Resolve or rollback
    """
    log.info(
        "🔍 Starting investigation pipeline",
        alert_title=alert.title,
        source=alert.source,
        severity=alert.severity,
    )

    # Defensive: every incident-creating path must supply a tenant. Without one
    # we cannot scope the incident, so we refuse rather than create an
    # unattributed (NULL-tenant) row that would be visible across tenants.
    if not getattr(alert, "tenant_id", None):
        log.error(
            "Refusing to process alert with no tenant_id",
            alert_title=alert.title,
            source=alert.source,
        )
        return {"status": "rejected", "reason": "missing tenant_id"}

    async with async_session() as db:
        try:
            # ── Step 1: Deduplication ──
            duplicate, existing = await is_duplicate(alert, db)
            if duplicate:
                log.info(
                    "🔁 Duplicate alert — skipping pipeline",
                    existing_incident=str(existing.id),
                )
                return {"status": "duplicate", "existing_incident_id": str(existing.id)}

            # ── Step 2: Create Incident ──
            fingerprint = generate_fingerprint(alert)
            # Allocate a per-tenant incident number (atomic; creates the tenant
            # row on first use). Sequential within the tenant, not global.
            from app.engine.numbering import allocate_incident_number
            incident_number = await allocate_incident_number(db, alert.tenant_id)
            incident = Incident(
                tenant_id=alert.tenant_id,
                incident_number=incident_number,
                title=alert.title,
                source=alert.source,
                source_alert_id=fingerprint,
                severity=Severity(alert.severity.lower()) if alert.severity else Severity.MEDIUM,
                status=IncidentStatus.INVESTIGATING,
                source_payload=alert.raw_payload,
                investigation_started_at=datetime.utcnow(),
            )
            db.add(incident)
            await db.commit()
            await db.refresh(incident)

            await _add_timeline(db, incident.id, "alert", "Alert received",
                                f"Source: {alert.source} | Severity: {alert.severity}",
                                {"fingerprint": fingerprint}, "system", tenant_id=alert.tenant_id)
            await db.commit()

            log.info("📝 Incident created", incident_id=str(incident.id))

            # ── Step 3: Investigate ──
            log.info("📋 Step 3: Investigating alert...")
            investigation = await investigate_incident(alert)

            incident.investigation_summary = investigation.get("investigation_summary")
            incident.impact_description = investigation.get("impact_assessment")
            incident.affected_services = investigation.get("affected_services", [])
            await _add_timeline(db, incident.id, "investigation", "Investigation complete",
                                investigation.get("investigation_summary", ""),
                                {"findings_count": len(investigation.get("findings", []))}, tenant_id=alert.tenant_id)
            await db.commit()

            # ── Step 4: Generate RCA (with RAG) ──
            log.info("🔬 Step 4: Generating Root Cause Analysis (with RAG)...")
            
            # Find similar past incidents
            search_text = f"{alert.title} {alert.description}"
            alert_embedding = await generate_embedding(search_text)
            similar_incidents = await find_similar_incidents(db, alert_embedding, limit=2, tenant_id=alert.tenant_id)
            incident.similar_incidents = similar_incidents
            
            rca = await generate_rca(alert, investigation, similar_incidents=similar_incidents)

            incident.root_cause = rca.get("root_cause")
            incident.rca_evidence = rca.get("evidence")
            incident.rca_confidence = rca.get("confidence")
            incident.rca_completed_at = datetime.utcnow()
            
            # Save embedding for future incidents
            if incident.root_cause:
                embedding = await generate_embedding(incident.root_cause)
                if embedding:  # Only set it if it's not empty, otherwise pgvector crashes
                    incident.rca_embedding = embedding
                
            incident.status = IncidentStatus.RCA_COMPLETE
            await _add_timeline(db, incident.id, "rca", "RCA complete",
                                rca.get("root_cause", ""),
                                {"confidence": rca.get("confidence"), "category": rca.get("root_cause_category")}, tenant_id=alert.tenant_id)
            await db.commit()

            # ── Step 5: Generate Fix Plan ──
            log.info("🔧 Step 5: Generating fix plan...")
            fix_plan = await generate_fix_plan(alert, investigation, rca)

            incident.fix_plan = fix_plan
            incident.fix_type = fix_plan.get("fix_type")
            incident.rollback_plan = fix_plan.get("rollback_plan")
            incident.status = IncidentStatus.FIX_PROPOSED
            await _add_timeline(db, incident.id, "fix", "Fix plan generated",
                                fix_plan.get("fix_summary", ""),
                                {"fix_type": fix_plan.get("fix_type"), "risk_level": fix_plan.get("risk_level"),
                                 "steps_count": len(fix_plan.get("steps", []))}, tenant_id=alert.tenant_id)
            await db.commit()

            # ── Step 6: Policy Check ──
            log.info("🔐 Step 6: Checking policy...")
            policy_decision = await check_policy(fix_plan, db, tenant_id=alert.tenant_id)

            incident_data = {
                "id": str(incident.id),
                "title": incident.title,
                "severity": incident.severity.value,
                "rca": rca,
                "fix_plan": fix_plan,
            }

            if policy_decision.approved:
                # ── Step 7: Auto-Execute Fix ──
                log.info("✅ Fix auto-approved by policy, executing...")
                incident.status = IncidentStatus.FIX_APPROVED
                incident.fix_approval = "auto"
                await _add_timeline(db, incident.id, "fix", "Fix auto-approved",
                                    f"Policy: {policy_decision.policy_name or 'default'}",
                                    actor="system", tenant_id=alert.tenant_id)
                await db.commit()

                incident.status = IncidentStatus.FIX_EXECUTING
                incident.fix_started_at = datetime.utcnow()
                await db.commit()

                fix_result = await execute_fix(fix_plan, incident_id=str(incident.id))
                incident.fix_result = fix_result

                if fix_result["status"] == "success":
                    # ── Step 8: Health Monitor ──
                    log.info("🏥 Step 8: Monitoring health post-fix...")
                    incident.status = IncidentStatus.FIX_MONITORING
                    await db.commit()

                    health = await monitor_health_post_fix(fix_plan, incident_id=str(incident.id))

                    if health["status"] == "rollback_needed":
                        log.error("🔴 Health degraded — marking as failed")
                        incident.status = IncidentStatus.FAILED
                        await _add_timeline(db, incident.id, "rollback", "Health degraded post-fix",
                                            health.get("reason", ""), health, tenant_id=alert.tenant_id)
                    else:
                        incident.status = IncidentStatus.RESOLVED
                        incident.resolved_at = datetime.utcnow()
                        if incident.detected_at:
                            incident.mttr_seconds = (incident.resolved_at - incident.detected_at).seconds
                        await _add_timeline(db, incident.id, "fix", "Incident resolved",
                                            f"MTTR: {incident.mttr_seconds}s",
                                            {"health_status": health["status"]}, tenant_id=alert.tenant_id)
                else:
                    incident.status = IncidentStatus.FAILED
                    await _add_timeline(db, incident.id, "fix", "Fix execution failed",
                                        fix_result.get("results", [{}])[-1].get("output", ""), tenant_id=alert.tenant_id)

                await db.commit()
                incident_data["fix_result"] = fix_result
                await send_incident_to_slack(
                    incident_data, channel="#incidents",
                    is_resolved=(incident.status == IncidentStatus.RESOLVED),
                )
            else:
                # ── Needs Human Approval ──
                log.info("⚠️ Fix requires human approval, notifying Slack...")
                await _add_timeline(db, incident.id, "fix", "Awaiting human approval",
                                    policy_decision.reason, actor="system", tenant_id=alert.tenant_id)
                await db.commit()
                await send_incident_to_slack(incident_data, channel="#incidents")

            log.info(
                "🎯 Pipeline complete",
                alert_title=alert.title,
                incident_id=str(incident.id),
                root_cause=rca.get("root_cause"),
                fix_type=fix_plan.get("fix_type"),
                confidence=rca.get("confidence"),
                status=incident.status.value,
            )

        except Exception as e:
            log.error(
                "❌ Pipeline failed",
                alert_title=alert.title,
                error=str(e),
            )
            try:
                incident.status = IncidentStatus.FAILED
                await _add_timeline(db, incident.id, "error", "Pipeline failed", str(e),
                                    tenant_id=alert.tenant_id)
                await db.commit()
            except Exception:
                pass
            raise
