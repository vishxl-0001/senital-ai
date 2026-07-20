#!/bin/sh
# Sentinel AI — Postgres backup (Phase 5, item 18).
#
# Dumps the database with pg_dump, gzips it, prunes dumps older than the
# retention window, and (optionally) uploads off-box to Azure Blob Storage so a
# VM loss doesn't lose backups. Run on a schedule by the postgres-backup sidecar
# in docker-compose.prod.yml, or from cron on the host.
set -eu

: "${POSTGRES_HOST:=postgres}"
: "${POSTGRES_USER:=postgres}"
: "${POSTGRES_DB:=sentinel_ai}"
: "${BACKUP_DIR:=/backups}"
: "${BACKUP_RETENTION_DAYS:=7}"

# pg_dump reads the password from PGPASSWORD.
export PGPASSWORD="${POSTGRES_PASSWORD:-}"

mkdir -p "$BACKUP_DIR"
TS=$(date +%Y%m%d-%H%M%S)
OUT="$BACKUP_DIR/${POSTGRES_DB}-${TS}.sql.gz"

echo "[backup] dumping ${POSTGRES_DB} from ${POSTGRES_HOST} -> ${OUT}"
pg_dump -h "$POSTGRES_HOST" -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$OUT"
echo "[backup] wrote $(du -h "$OUT" | cut -f1) to ${OUT}"

# Retention: delete local dumps older than N days.
find "$BACKUP_DIR" -name "${POSTGRES_DB}-*.sql.gz" -mtime +"$BACKUP_RETENTION_DAYS" -delete
echo "[backup] pruned dumps older than ${BACKUP_RETENTION_DAYS} day(s)"

# ── Off-box copy to Azure Blob Storage (recommended for production) ──
# Two supported methods, tried in order:
#   1. AZURE_BACKUP_SAS_URL — a container-scoped SAS URL. Uploaded with curl
#      (no az CLI needed), so it works in the stock pgvector image. This is the
#      preferred method. Format:
#        https://<account>.blob.core.windows.net/<container>?<sas-token>
#      Mint one with "Add" + "Create" + "Write" permission scoped to the
#      backup container. curl is auto-installed if missing.
#   2. AZURE_STORAGE_CONNECTION_STRING + AZURE_BACKUP_CONTAINER — used only if
#      the az CLI happens to be present (it isn't in the default image).
BLOB_NAME="$(basename "$OUT")"
uploaded=0

if [ -n "${AZURE_BACKUP_SAS_URL:-}" ]; then
    # curl + a CA bundle are needed for the HTTPS PUT. The stock pgvector image
    # ships neither; install both (ca-certificates alone fixes curl error 77).
    if ! command -v curl >/dev/null 2>&1 || [ ! -s /etc/ssl/certs/ca-certificates.crt ]; then
        echo "[backup] installing curl + ca-certificates for Blob upload"
        (apt-get update -qq \
            && apt-get install -y -qq --no-install-recommends curl ca-certificates \
            && update-ca-certificates) >/dev/null 2>&1 \
            || apk add --no-cache curl ca-certificates >/dev/null 2>&1 || true
    fi
    if command -v curl >/dev/null 2>&1; then
        # Insert "/<blob>" before the "?<sas>" query string.
        base="${AZURE_BACKUP_SAS_URL%%\?*}"
        query="${AZURE_BACKUP_SAS_URL#*\?}"
        blob_url="${base%/}/${BLOB_NAME}?${query}"
        if curl -sS -f -X PUT -T "$OUT" \
                -H "x-ms-blob-type: BlockBlob" \
                -H "Content-Type: application/gzip" \
                "$blob_url" >/dev/null; then
            echo "[backup] uploaded ${BLOB_NAME} to Azure Blob via SAS"
            uploaded=1
        else
            echo "[backup] WARNING: SAS upload failed — dump kept locally at ${OUT}"
        fi
    else
        echo "[backup] WARNING: curl unavailable — skipping SAS upload"
    fi
fi

if [ "$uploaded" -eq 0 ] && [ -n "${AZURE_STORAGE_CONNECTION_STRING:-}" ] && [ -n "${AZURE_BACKUP_CONTAINER:-}" ]; then
    if command -v az >/dev/null 2>&1; then
        az storage blob upload \
            --container-name "$AZURE_BACKUP_CONTAINER" \
            --file "$OUT" --name "$BLOB_NAME" \
            --connection-string "$AZURE_STORAGE_CONNECTION_STRING" \
            --only-show-errors && echo "[backup] uploaded ${BLOB_NAME} to Azure Blob via az"
    else
        echo "[backup] AZURE_STORAGE_CONNECTION_STRING set but 'az' CLI not in image — use AZURE_BACKUP_SAS_URL instead"
    fi
fi

if [ "$uploaded" -eq 0 ] && [ -z "${AZURE_BACKUP_SAS_URL:-}" ] && [ -z "${AZURE_STORAGE_CONNECTION_STRING:-}" ]; then
    echo "[backup] NOTE: no off-box target configured (set AZURE_BACKUP_SAS_URL) — backups are LOCAL ONLY"
fi

echo "[backup] done"
