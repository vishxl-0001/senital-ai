"""
Sentinel AI — Investigation Agent
Uses LLM to investigate alerts by analyzing logs, metrics, and deployment context.
This is the "detective" that gathers all evidence.
"""

import json
import structlog
from openai import AsyncOpenAI

from app.config import settings
from app.integrations.github import get_recent_commits
from app.integrations.prometheus import query_prometheus

log = structlog.get_logger()
client = AsyncOpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL if settings.OPENAI_BASE_URL else None
)

INVESTIGATION_PROMPT = """You are Sentinel AI, an expert Site Reliability Engineer investigating a production incident.

## Alert Information
- **Title:** {title}
- **Description:** {description}
- **Severity:** {severity}
- **Source:** {source}
- **Labels:** {labels}

## Additional Context Gathered
### Recent Deployments (GitHub)
{github_context}

### Metrics (Prometheus)
{prom_context}

## Your Task
Investigate this alert and provide a structured analysis. Think step by step:

1. **What is happening?** — Describe the symptoms clearly
2. **What could cause this?** — List the most likely causes (ranked by probability)
3. **What data would you check?** — Logs, metrics, recent deploys, config changes
4. **What's the likely impact?** — Which services/users are affected?
5. **What similar issues have you seen?** — Common patterns for this type of alert

## Response Format
Respond in valid JSON with this structure:
{{
    "symptoms": "Clear description of what's happening",
    "findings": [
        {{
            "category": "logs|metrics|deployment|config|dependency",
            "finding": "What was found",
            "relevance": "high|medium|low",
            "evidence": "Specific data points"
        }}
    ],
    "likely_causes": [
        {{
            "cause": "Description of potential cause",
            "probability": 0.0-1.0,
            "evidence": "Why you think this"
        }}
    ],
    "affected_services": ["service1", "service2"],
    "impact_assessment": "Description of impact on users/services",
    "investigation_summary": "2-3 sentence summary of findings"
}}
"""


async def investigate_incident(alert) -> dict:
    """
    Run AI investigation on an alert.
    Analyzes the alert context, fetches GitHub and Prometheus data, and generates structured findings.
    """
    log.info("🔍 Running AI investigation", alert_title=alert.title)

    # 1. Fetch GitHub Context
    github_context = "No recent deployments found or GitHub not configured."
    if settings.GITHUB_ORG:
        commits = await get_recent_commits(settings.GITHUB_ORG, limit=3)
        if commits:
            github_context = json.dumps(commits, indent=2)

    # 2. Fetch Prometheus Context
    prom_context = "No relevant metrics found."
    # Build a simple mock query based on alert title
    mock_query = f"sum(rate(http_requests_total{{pod=~'.*{alert.title}.*'}}[5m]))"
    metrics = await query_prometheus(mock_query)
    if metrics:
        prom_context = json.dumps(metrics, indent=2)

    prompt = INVESTIGATION_PROMPT.format(
        title=alert.title,
        description=alert.description or "No description provided",
        severity=alert.severity,
        source=alert.source,
        labels=json.dumps(alert.labels, indent=2),
        github_context=github_context,
        prom_context=prom_context
    )

    try:
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert SRE investigating production incidents. "
                        "IMPORTANT: Respond ONLY with raw valid JSON. No markdown, no code fences, no explanation — just JSON."
                    ),
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=2000,
        )

        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences if model adds them
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json.loads(raw)

        log.info(
            "✅ Investigation complete",
            findings_count=len(result.get("findings", [])),
            likely_causes_count=len(result.get("likely_causes", [])),
            tokens_used=response.usage.total_tokens,
        )

        return result

    except Exception as e:
        log.error("❌ Investigation failed", error=str(e))
        # Return a basic result on failure so pipeline can continue
        return {
            "symptoms": alert.description or alert.title,
            "findings": [],
            "likely_causes": [{"cause": "Investigation failed — manual review needed", "probability": 0.0, "evidence": str(e)}],
            "affected_services": list(alert.labels.values()) if alert.labels else [],
            "impact_assessment": "Unable to assess — investigation failed",
            "investigation_summary": f"Automated investigation failed: {str(e)}. Manual review required.",
        }
