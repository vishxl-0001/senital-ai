# Production Readiness — Scaling & Redundancy

Status as of 2026-07-20. This documents what's done, what's left, and the
cost/redundancy decisions for growing past a pilot. It is a decision aid, not a
runbook — pick a tier based on how many paying tenants and what SLA you promise.

## Current topology

Everything runs on a single Azure VM (Standard_B2s_v2, ~8GB) via
`docker-compose.prod.yml`:

- `postgres` (pgvector/pg16) — data on a local Docker volume
- `redis` — Celery broker + cache
- `backend` (FastAPI, 2 uvicorn workers) — runs `db_migrate.py` on start
- `celery-worker` + `celery-beat` — async investigations, uptime checks
- `dashboard` (Next.js)
- `postgres-backup` — nightly `pg_dump`, local + optional off-box (Azure Blob SAS)
- Caddy (host) — TLS termination + reverse proxy

**Single point of failure:** if the VM reboots, OOMs, or its disk fails,
everything is down and — without off-box backups — data is at risk. This is
acceptable for a pilot with friendly clients, not for paid SLAs.

## Gaps closed in this pass

- **WebSocket tenant scoping** — `/ws` now authenticates the Clerk token on the
  handshake and routes incident broadcasts only to the owning tenant's
  connections. Was a cross-tenant metadata leak; was the hard blocker for a 2nd
  client.
- **Off-box backups** — `backup_postgres.sh` uploads each dump to Azure Blob via
  a container SAS URL (`AZURE_BACKUP_SAS_URL`), so a disk loss no longer loses
  the backups too. Still same-account; see B2 for cross-region.
- **`APP_ENV=production`** — disables SQL query echo and the mock-metrics path.
  Set in the VM `.env` (not just cosmetic — echo is log noise + overhead).
- **Stats query** — collapsed 6 per-poll queries to 3; all filters are index-
  backed (`tenant_id`, `status`). `loadtest_stats.py` added to validate under
  concurrent tenants before onboarding.

## Decision: database redundancy

The DB is the thing you cannot afford to lose. Three tiers, cheapest first.

### Tier A — stay on the VM, harden backups (pilot)
- Keep Postgres in Docker; rely on nightly `pg_dump` + off-box SAS upload.
- **RPO:** up to 24h (last nightly dump). **RTO:** manual restore, ~30–60 min.
- **Cost:** ~$0 beyond current VM + a few cents/GB Blob storage.
- **Use when:** pilot, <5 tenants, data loss of a day is survivable.
- **To improve RPO cheaply:** run the backup every 1–6h (`BACKUP_INTERVAL_SECONDS`).

### Tier B — Azure Database for PostgreSQL Flexible Server (recommended for paid)
- Move data off the VM to managed Postgres. VM keeps app containers only.
- Managed automated backups (point-in-time restore, 7–35 day window),
  patching, and optional **zone-redundant HA** (hot standby, automatic failover).
- **RPO:** ~5 min (PITR). **RTO:** minutes (HA) or a restore window (no-HA).
- **Cost (Central India, approx, confirm current pricing):**
  - Burstable B1ms/B2s, no HA: **~$25–60/mo** — good first paid tier.
  - General Purpose + zone-redundant HA: **~$250+/mo** — real SLA.
- **Migration:** needs `pgvector` (Flexible Server supports the `vector`
  extension — enable it in server parameters, then `CREATE EXTENSION vector`).
  Point `DATABASE_URL` at the managed host, drop the `postgres` service from the
  prod compose, restore the latest dump. `db_migrate.py` handles schema on boot.
- **Use when:** you charge money or promise uptime.

### Tier C — full HA app tier (scale)
- Only after Tier B. Multiple app VMs (or Azure Container Apps / AKS) behind a
  load balancer; Redis → Azure Cache for Redis; shared managed Postgres.
- Celery beat must run as a **single** instance (it's a scheduler) — pin it to
  one node or use a leader lock; workers scale freely.
- **Cost:** $500+/mo and real ops overhead. Don't do this until load or SLA
  demands it.

## Decision: app-tier availability

Independent of the DB, the single VM means app downtime on reboot/OOM.

- **Cheap mitigation (now):** Docker `restart: unless-stopped` (already set),
  and watch memory — Next.js builds are the OOM risk on 8GB. Build images one at
  a time on deploy if memory is tight.
- **Next step:** move the DB to Tier B first (removes the highest-stakes SPOF for
  the lowest cost), *then* consider a second app VM.

## Recommended path for "more clients"

1. **Now (done in this pass):** WS scoping, off-box backups, `APP_ENV=production`,
   stats optimization + load-test tool.
2. **Before charging:** move to Tier B managed Postgres (no HA, burstable) —
   biggest risk reduction per dollar.
3. **Before an SLA:** enable zone-redundant HA on the managed DB; run a load test
   (`loadtest_stats.py`) at your target tenant count.
4. **On growth:** Tier C app-tier HA.

## Load testing

```bash
cd backend
.venv/bin/python scripts/loadtest_stats.py \
  --base-url https://sentinel-ai-vishxl.centralindia.cloudapp.azure.com \
  --path /api/v1/incidents/stats \
  --token "<real_clerk_jwt>" \
  --concurrency 50 --duration 30
```

Watch p95/p99 latency and error rate. If p95 climbs under load, the VM's Postgres
is the likely bottleneck — another signal to move to Tier B.
