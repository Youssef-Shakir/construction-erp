#!/usr/bin/env bash
# =============================================================================
# Production update: pull -> backup DB -> rebuild -> health check -> rollback.
#
#   scripts/update.sh            # update to the latest origin/$DEPLOY_BRANCH (default main)
#   scripts/update.sh --force    # rebuild even if there are no new commits
#
# Safe to run from cron. Uses a lock so two updates never overlap.
# Compose files come from COMPOSE_FILE in .env (e.g. docker-compose.yml:docker-compose.tunnel.yml).
# Database migrations run automatically when the new erp container starts
# (RUN_MIGRATIONS=1). If the new version fails its health check, the CODE is
# rolled back automatically; a migration is NOT reversed - restore the backup
# printed below if needed:
#   docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < backups/<file>.dump
# =============================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRANCH="${DEPLOY_BRANCH:-main}"
KEEP_BACKUPS="${KEEP_BACKUPS:-14}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

cd "$APP_DIR"
mkdir -p backups logs
LOG="logs/update-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

COMPOSE=(docker compose)   # reads COMPOSE_FILE from .env
log() { echo "[$(date '+%F %T')] $*"; }

# One update at a time
exec 9>"$APP_DIR/.update.lock"
flock -n 9 || { log "Another update is running - exiting."; exit 1; }

[ -f .env ] || { log "ERROR: .env missing in $APP_DIR"; exit 1; }
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    log "ERROR: local changes in tracked files - commit or discard them first:"
    git status --short --untracked-files=no
    exit 1
fi

OLD_SHA="$(git rev-parse HEAD)"
log "Current version: $(git log -1 --format='%h %s')"
git fetch --prune origin "$BRANCH"
NEW_SHA="$(git rev-parse "origin/$BRANCH")"

if [ "$OLD_SHA" = "$NEW_SHA" ] && [ "$FORCE" -eq 0 ]; then
    log "Already up to date."
    exit 0
fi
log "Updating to: $(git log -1 --format='%h %s' "$NEW_SHA")"
git --no-pager log --oneline "$OLD_SHA..$NEW_SHA" || true

# 1. Database backup (only if the db container is running)
if "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx db; then
    BACKUP="backups/erp-$(date +%Y%m%d-%H%M%S)-${OLD_SHA:0:7}.dump"
    log "Backing up database -> $BACKUP"
    "${COMPOSE[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$BACKUP"
    [ -s "$BACKUP" ] || { log "ERROR: backup is empty - aborting"; rm -f "$BACKUP"; exit 1; }
    ls -1t backups/erp-*.dump | tail -n +"$((KEEP_BACKUPS + 1))" | xargs -r rm -f
else
    log "db not running yet - skipping backup (first deployment?)"
fi

wait_healthy() {
    local cid status waited=0
    while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
        cid="$("${COMPOSE[@]}" ps -q erp)"
        status="$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo starting)"
        [ "$status" = healthy ] && return 0
        [ "$status" = unhealthy ] && return 1
        sleep 5; waited=$((waited + 5))
    done
    return 1
}

deploy() {
    "${COMPOSE[@]}" build --pull erp
    "${COMPOSE[@]}" up -d --remove-orphans
}

# 2. Switch code, rebuild, restart
git checkout --quiet --detach "$NEW_SHA"
log "Building and restarting..."
if deploy && wait_healthy; then
    git checkout --quiet -B "$BRANCH" "$NEW_SHA"
    docker image prune -f >/dev/null
    log "OK - now running $(git log -1 --format='%h %s')"
    exit 0
fi

# 3. Rollback
log "ERROR: new version is not healthy. Last app logs:"
"${COMPOSE[@]}" logs --tail 60 erp || true
log "Rolling back code to ${OLD_SHA:0:7}"
git checkout --quiet --detach "$OLD_SHA"
deploy && wait_healthy && log "Rollback OK (database backup: ${BACKUP:-none})" \
    || log "ROLLBACK FAILED - check: ${COMPOSE[*]} logs erp"
git checkout --quiet -B "$BRANCH" "$OLD_SHA"
exit 1
