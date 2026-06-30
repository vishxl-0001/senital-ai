"""
Sentinel AI — Remediation Agent
THE DIFFERENTIATOR — Generates actionable fix plans based on RCA.
Goes beyond just diagnosis to actually propose (and later execute) fixes.
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

REMEDIATION_PROMPT = """You are Sentinel AI's Remediation Engine.

## Alert
- **Title:** {title}
- **Severity:** {severity}

## Root Cause Analysis
{rca}

## Investigation Context
{investigation}

## Your Task
Generate a specific, actionable fix plan to resolve this incident.
The fix must be:
1. SPECIFIC — exact commands/actions, not vague suggestions
2. SAFE — include a rollback plan
3. VERIFIABLE — include health checks to confirm the fix worked

## Available Fix Types
- restart_pod: Restart the affected pod(s)
- rollback_deployment: Rollback to the previous working version
- scale_horizontal: Increase replica count
- scale_vertical: Increase resource limits (CPU/memory)
- clear_disk: Clean temporary files and old logs
- config_change: Modify configuration
- network_fix: Fix network-related issues
- custom: Custom fix requiring specific commands

## Response Format (valid JSON):
{{
    "fix_type": "One of the fix types above",
    "fix_summary": "One-line description of the fix",
    "risk_level": "low|medium|high",
    "estimated_fix_time_seconds": 60,
    "steps": [
        {{
            "order": 1,
            "action": "Specific action description",
            "command": "kubectl rollback deployment/service-name -n namespace",
            "expected_result": "What should happen after this step",
            "is_destructive": false
        }}
    ],
    "rollback_plan": {{
        "description": "How to undo this fix if it makes things worse",
        "steps": [
            {{
                "order": 1,
                "action": "Rollback step",
                "command": "Specific rollback command"
            }}
        ]
    }},
    "health_checks": [
        {{
            "check": "What to verify",
            "command": "kubectl get pods -n namespace",
            "success_criteria": "All pods in Running state",
            "wait_seconds": 30
        }}
    ],
    "blast_radius": {{
        "affected_services": ["service1"],
        "affected_users": "estimate",
        "can_cascade": false,
        "cascade_risk": "Description of cascade risk if any"
    }},
    "recommendation": "auto_fix|approve_first|manual_only",
    "reasoning": "Why you recommend this approach for this specific fix"
}}
"""


async def generate_fix_plan(alert, investigation: dict, rca: dict) -> dict:
    """
    Generate a specific, actionable fix plan based on RCA.
    This is what makes Sentinel AI different from every other tool.
    """
    log.info("🔧 Generating fix plan", alert_title=alert.title)

    prompt = REMEDIATION_PROMPT.format(
        title=alert.title,
        severity=alert.severity,
        rca=json.dumps(rca, indent=2),
        investigation=json.dumps(investigation, indent=2),
    )

    try:
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert SRE generating fix plans for production incidents. "
                        "Be specific with commands. Always include rollback plans. "
                        "Prioritize safety over speed. "
                        "IMPORTANT: Respond ONLY with raw valid JSON. No markdown, no code fences, no explanation — just JSON."
                    ),
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=2500,
        )

        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences if model adds them
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json.loads(raw)

        log.info(
            "✅ Fix plan generated",
            fix_type=result.get("fix_type", "Unknown"),
            risk_level=result.get("risk_level", "unknown"),
            steps_count=len(result.get("steps", [])),
            recommendation=result.get("recommendation", "manual_only"),
            tokens_used=response.usage.total_tokens,
        )

        return result

    except Exception as e:
        log.error("❌ Fix plan generation failed", error=str(e))
        return {
            "fix_type": "manual",
            "fix_summary": "Fix plan generation failed — manual intervention required",
            "risk_level": "unknown",
            "steps": [],
            "rollback_plan": {"description": "N/A", "steps": []},
            "health_checks": [],
            "blast_radius": {"affected_services": [], "can_cascade": False},
            "recommendation": "manual_only",
            "reasoning": f"Automated fix plan generation failed: {str(e)}",
        }
