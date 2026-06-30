import asyncio
import sys
import os

sys.path.append(os.path.dirname(__file__))

from app.db.database import async_session, engine
from app.models.incident import Incident, IncidentStatus, Policy
from sqlalchemy import select, update

async def main():
    async with async_session() as db:
        # Seed default policies if none exist
        result = await db.execute(select(Policy))
        policies = result.scalars().all()
        if not policies:
            print("Seeding default policies...")
            defaults = [
                Policy(
                    name="Auto-restart crashed pods",
                    description="Automatically restart pods that are in CrashLoopBackOff state",
                    action_type="restart_pod",
                    auto_approve=True,
                    conditions={"error_type": "CrashLoopBackOff"},
                    constraints={"max_restarts": 3, "cooldown_minutes": 5},
                ),
                Policy(
                    name="Auto-scale on high CPU",
                    description="Scale up replicas when CPU usage exceeds 85%",
                    action_type="scale_horizontal",
                    auto_approve=True,
                    conditions={"metric": "cpu_usage", "threshold": 85},
                    constraints={"max_replicas": 10, "scale_increment": 2},
                ),
                Policy(
                    name="Rollback bad deployments",
                    description="Rollback deployments when error rate spikes after deploy",
                    action_type="rollback_deployment",
                    auto_approve=False,
                    conditions={"error_rate_spike": True, "recent_deploy": True},
                    constraints={"approval_timeout_minutes": 15},
                    approval_timeout_minutes=15,
                ),
                Policy(
                    name="Clear disk space",
                    description="Clean temporary files and old logs when disk usage exceeds 90%",
                    action_type="clear_disk",
                    auto_approve=True,
                    conditions={"metric": "disk_usage", "threshold": 90},
                    constraints={"target_dirs": ["/tmp", "/var/log"], "max_clean_gb": 5},
                ),
                Policy(
                    name="Database operations (always manual)",
                    description="Database changes always require human approval",
                    action_type="database_operation",
                    auto_approve=False,
                    conditions={},
                    constraints={"require_approval": True, "no_timeout_auto": True},
                    approval_timeout_minutes=0,
                ),
            ]
            for policy in defaults:
                db.add(policy)
            await db.commit()
            print(f"Seeded {len(defaults)} policies.")
        else:
            print(f"Found {len(policies)} policies, skipping seeding.")

        # Clean up stuck incidents
        print("Cleaning up stuck incidents...")
        stuck_statuses = [
            IncidentStatus.INVESTIGATING,
            IncidentStatus.RCA_COMPLETE,
            IncidentStatus.FIX_PROPOSED,
            IncidentStatus.FIX_APPROVED,
            IncidentStatus.FIX_EXECUTING,
            IncidentStatus.FIX_MONITORING
        ]
        
        result = await db.execute(select(Incident).where(Incident.status.in_(stuck_statuses)))
        stuck_incidents = result.scalars().all()
        for inc in stuck_incidents:
            inc.status = IncidentStatus.FAILED
            inc.investigation_summary = "Pipeline failed or timed out during execution."
        
        await db.commit()
        print(f"Cleaned up {len(stuck_incidents)} stuck incidents.")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
