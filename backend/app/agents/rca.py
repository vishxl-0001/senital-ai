"""
Sentinel AI — RCA (Root Cause Analysis) Agent
Takes investigation findings and generates a definitive root cause analysis.
"""

import json
import structlog
from openai import AsyncOpenAI

from app.config import settings

log = structlog.get_logger()
client = AsyncOpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL if settings.OPENAI_BASE_URL else None
)

RCA_PROMPT = """You are Sentinel AI's Root Cause Analysis engine.

## Alert
- **Title:** {title}
- **Severity:** {severity}

## Investigation Findings
{investigation}

## Similar Past Incidents (Context)
{similar_incidents_text}

## Your Task
Based on the investigation findings and past incidents, determine the ROOT CAUSE of this incident.
Be specific and definitive. Don't just repeat symptoms — identify the underlying cause.

## Response Format (valid JSON):
{{
    "root_cause": "Clear, specific description of the root cause",
    "root_cause_category": "deployment|code_bug|infrastructure|configuration|dependency|resource_exhaustion|network|security",
    "confidence": 0.0-1.0,
    "evidence": [
        {{
            "type": "log|metric|deployment|correlation",
            "description": "What evidence supports this conclusion",
            "weight": "strong|moderate|weak"
        }}
    ],
    "timeline": [
        {{
            "time_offset": "-20min",
            "event": "What happened at this point"
        }}
    ],
    "impact": {{
        "affected_services": ["service1"],
        "estimated_users_affected": "number or range",
        "severity_justification": "Why this severity is appropriate"
    }},
    "rca_summary": "2-3 sentence executive summary suitable for a Slack message"
}}
"""


def adjust_confidence_for_metrics(result: dict, metrics_available: bool) -> dict:
    """
    Temper RCA confidence when no live metrics backed the investigation.

    Without Prometheus data the RCA is reasoning on logs + context only, so we
    cap and lightly penalize confidence and annotate the evidence — rather than
    letting the model report high confidence as if metrics had confirmed it.
    """
    if metrics_available:
        return result
    try:
        original = float(result.get("confidence") or 0.0)
    except (TypeError, ValueError):
        original = 0.0
    result["confidence"] = round(min(original, 0.6) * 0.9, 2)
    result.setdefault("evidence", []).append({
        "type": "metric",
        "description": (
            "Live metrics were unavailable (Prometheus not configured or "
            "unreachable); confidence reduced — RCA based on logs and context only."
        ),
        "weight": "weak",
    })
    return result


async def generate_rca(alert, investigation: dict, similar_incidents: list = None) -> dict:
    """
    Generate Root Cause Analysis from investigation findings and past similar incidents.
    """
    log.info("🔬 Generating RCA", alert_title=alert.title)

    similar_incidents_text = "No similar past incidents found."
    if similar_incidents:
        similar_incidents_text = json.dumps(similar_incidents, indent=2)

    prompt = RCA_PROMPT.format(
        title=alert.title,
        severity=alert.severity,
        investigation=json.dumps(investigation, indent=2),
        similar_incidents_text=similar_incidents_text
    )

    try:
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert SRE performing root cause analysis. Be specific and evidence-based. "
                        "IMPORTANT: Respond ONLY with raw valid JSON. No markdown, no code fences, no explanation — just JSON."
                    ),
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=2000,
        )

        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences if model adds them
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json.loads(raw)

        # Factor metric availability into the confidence score (no fabricated data).
        metrics_available = bool(investigation.get("metrics_available")) if investigation else False
        result = adjust_confidence_for_metrics(result, metrics_available)

        log.info(
            "✅ RCA complete",
            root_cause=result.get("root_cause", "Unknown"),
            confidence=result.get("confidence", 0),
            category=result.get("root_cause_category", "unknown"),
            tokens_used=response.usage.total_tokens,
        )

        return result

    except Exception as e:
        log.error("❌ RCA generation failed", error=str(e))
        return {
            "root_cause": "RCA generation failed — manual analysis required",
            "root_cause_category": "unknown",
            "confidence": 0.0,
            "evidence": [],
            "timeline": [],
            "impact": {"affected_services": [], "estimated_users_affected": "unknown"},
            "rca_summary": f"Automated RCA failed: {str(e)}",
        }
