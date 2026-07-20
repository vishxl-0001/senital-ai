# 🛡️ Sentinel AI — Project Summary & Handover Document

**Date:** July 20, 2026
**Purpose:** Comprehensive overview of the project's current state, aims, and completed features to serve as a context handover for future AI assistants.

---

## 🎯 Our Aim / Objective
**Motto:** "Detect. Diagnose. Fix. — The AI SRE that doesn't just find the problem, it solves it."

Sentinel AI is designed to be an enterprise-ready, autonomous Site Reliability Engineering (SRE) platform. Its core objective is to ingest alerts from infrastructure monitors (like Prometheus), automatically run AI-driven diagnostic investigations (Root Cause Analysis), and execute (or recommend) remediation steps based on customizable enterprise policies. It is built to minimize system downtime and reduce pager fatigue for human engineers.

---

## 🏗️ Macro Accomplishments (High-Level Architecture & Features)

1. **Core Platform Foundation Built:**
   - **Backend:** Robust API built with Python 3.11, FastAPI, and SQLAlchemy (asyncpg). Structured with a scalable, modular directory structure.
   - **Frontend:** Next.js + React dashboard using modern aesthetics (Tailwind CSS, Recharts, Lucide Icons).
   - **Database:** PostgreSQL initialized with `pgvector` for AI embeddings, alongside Redis for caching and task queue brokering.
   - **Asynchronous Execution:** Celery workers integrated to handle heavy, long-running AI tasks without blocking the main API thread.
   - **Containerization:** The entire stack is orchestrated locally and in production using Docker and `docker-compose.yml`.

2. **Multi-Tenant Enterprise Architecture:**
   - **Data Isolation:** Successfully migrated single-tenant models to a multi-tenant architecture. All core database models and API endpoints are now isolated by `tenant_id`, derived automatically from Clerk organization IDs.
   - **API Security:** Implemented an authentication layer featuring secure API key management, ensuring third-party webhook integrations (like Prometheus alerts) are authenticated and routed to the correct tenant.
   - **Governance Dashboard:** Built an enterprise settings dashboard enabling users to manage API keys, webhook endpoints, and automated remediation policies.

3. **AI & Integration Pipelines:**
   - **LLM Engine:** Uses the Groq LLM API for fast, low-cost agent reasoning. Embeddings for RAG semantic search use the OpenAI Embeddings API (`text-embedding-3-small`, 1536-dim, stored in pgvector) — this replaced an earlier local `fastembed`/ONNX approach that caused Celery OOM (SIGKILL) on the 4GB VM.
   - **Agent Orchestration:** Utilized LangGraph and LangChain to build autonomous investigation agents capable of parsing alerts, deducing root causes, and formulating fix strategies.
   - **Communication & Alerting:** Integrated Slack Bolt/SDK for bi-directional communication — incident alerts, human-in-the-loop approval buttons (authorized, fail-closed), and natural-language `@mention` commands (`investigate`, `status`, `help`).
   - **Health Infrastructure:** Deployed comprehensive health check endpoints (`/api/v1/health`) ensuring Postgres, Redis, and API endpoints are actively monitored.

4. **Production Cloud Deployment (Azure):**
   - **Infrastructure Provisioning:** Evaluated and deployed the application to an Azure Virtual Machine (Standard_B2s_v2 running Ubuntu 24.04).
   - **Web Server & SSL:** Configured Caddy as a reverse proxy to manage domain routing and automatically provision SSL/TLS certificates.
   - **CI/CD Fixes:** Resolved complex Next.js build issues, particularly TypeScript type errors and Clerk middleware configuration bugs that blocked the production build pipeline.
   - **Public Access:** The platform is now publicly accessible and securely hosted at `sentinel-ai-vishxl.centralindia.cloudapp.azure.com`. Network troubleshooting was successfully completed to ensure browser subagents and users can interact with the live platform.

---

## 🔬 Micro Accomplishments (Technical Implementation Details)

- **Database Migrations:** Configured Alembic for smooth, version-controlled schema updates.
- **Logging:** Implemented structured, JSON-friendly logging via `structlog` for better observability in production.
- **Real-Time Updates:** Engineered WebSocket routes (`websockets.py`) to stream live incident updates and AI thought processes directly to the Next.js dashboard.
- **API Routing:** Developed a comprehensive REST API suite:
  - `/api/v1/alerts` (Ingestion)
  - `/api/v1/incidents` (Tracking & Management)
  - `/api/v1/policies` (Remediation Rules)
  - `/api/v1/agent` (Triggering AI investigations)
  - `/api/v1/slack` (Slack events & interactivity)
  - `/api/v1/auth` (Tenant & API key verification)
- **Environment Management:** Hardened `.env` configurations for production, ensuring secrets (Clerk keys, DB passwords, API keys) are injected securely via Docker Compose.
- **CORS:** Configured robust CORS middleware allowing frontend domains (e.g., `localhost:3000`, Azure domain) to communicate seamlessly with the FastAPI backend.

---

## 🚀 Current State

The system has graduated from a local development prototype to a fully containerized, cloud-hosted production environment on Azure. The core loop—receiving a webhook, authenticating the tenant, triggering an AI diagnostic Celery task, and displaying the incident live on the Next.js dashboard—is functional and deployed. The platform relies on secure HTTPS via Caddy and is integrated with Clerk for multi-tenant identity management.

Since the initial prototype, a hardening program (Phases 1–5, items 1–19) landed the following. **This section is the source of truth for what is done — the git log is authoritative for specifics.**

- **Phase 1 — Tenant isolation:** Server-side enforcement. `tenant_id` is derived from the *verified* Clerk session JWT (`org_id` claim, incl. v2 nested org claim); the client never sends it. Endpoints return 403 without an active org.
- **Phase 2 — Real safety, no fabricated data:** No shell execution; K8s actions go through a typed whitelist (`restart_pod`, `rollback_deployment`, `scale_horizontal`, `clear_disk`). Prometheus returns real metrics — mock series are dev-only, opt-in, and logged loudly. Slack fix approvals are authorized and **fail closed** (empty allow-list ⇒ approve via dashboard only).
- **Phase 3 — Migrations & numbering:** Real Alembic migrations (no `create_all`); per-tenant sequential incident numbering (e.g. `ACME-1042`) so global volume doesn't leak.
- **Phase 4 — Durable pipeline & live UI:** Investigations run as durable Celery tasks (survive restarts, bounded concurrency); live incident updates stream to the dashboard over WebSocket; per-tenant Slack OAuth install stores a Fernet-encrypted bot token.
- **Phase 5 — Production ops:** Append-only audit log on every fix; per-caller rate limiting on webhook/agent/Slack endpoints; production docker-compose; automated Postgres backups.
- **External-mode monitoring:** Uptime checker (HTTP status/keyword/latency + SSL expiry) driven by Celery beat, with automatic recovery resolution and vendor webhook ingestion — lets the platform monitor sites without an in-cluster agent.
- **Dashboard completeness (July 2026):** Landing dashboard, Policies, and Runbooks pages are all wired to live backend data (no mock arrays remain). Slack `@mention` NL commands implemented.

## 🧭 Next Steps for the AI Assistant

1. **Expand Agent Skills:** Grow the LangGraph tool set beyond the current K8s whitelist — reading logs from more sources, cloud provider actions (AWS/Azure security groups), and DB queries — always routed through the typed-action whitelist in `app/engine/k8s_actions.py`.
2. **Runbook execution:** Runbooks are currently authored and stored (`app/api/runbooks.py` + `/runbooks` UI) but not yet auto-matched to an RCA and executed. Wire `trigger_pattern` matching into the orchestrator so a matching runbook can drive a fix.
3. **Policy edit/delete UI:** The Policies page supports list/create/seed; add enable-toggle, edit, and delete (backend `PATCH`/`DELETE` still to be added to `app/api/policies.py`).
4. **Tenant-scoped WebSocket:** `/ws` currently broadcasts to all clients (see note in `useIncidentStream.ts`). Scope broadcasts per tenant before relying on payloads as anything more than refresh hints.
5. **Monitoring the Azure VM:** Keep an eye on the B2s VM's memory and CPU, as Next.js builds, Celery, Postgres, and FastAPI on a 4GB instance require careful resource management.
