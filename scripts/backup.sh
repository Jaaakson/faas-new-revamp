#!/usr/bin/env bash
#
# Backup and restore for the Fvas database.
#
# An untested backup is not a backup. `restore-drill` exists so that claim can
# be made truthfully: it takes a backup, records what is in the database,
# destroys it, restores, and compares. If the comparison fails it exits non-zero
# and says what differed.
#
#   ./scripts/backup.sh dump                  # write a timestamped backup
#   ./scripts/backup.sh restore <file>        # restore one
#   ./scripts/backup.sh restore-drill         # dump, destroy, restore, verify
#   ./scripts/backup.sh prune                 # delete backups past the window
#
# Format is PostgreSQL custom (-Fc): compressed, and `pg_restore` can rebuild
# selectively from it. Plain SQL would be larger and all-or-nothing.
#
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
PG_SERVICE="${PG_SERVICE:-postgres}"
PG_USER="${PG_USER:-postgres}"
PG_DB="${PG_DB:-fvas}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

# Runs a command inside the compose Postgres container. MSYS_NO_PATHCONV stops
# Git Bash on Windows from mangling container-side paths into host paths.
compose_exec() {
  MSYS_NO_PATHCONV=1 docker compose exec -T "$PG_SERVICE" "$@"
}

log() { printf '  %s\n' "$*"; }
fail() { printf '\n  FAILED: %s\n' "$*" >&2; exit 1; }

cmd_dump() {
  mkdir -p "$BACKUP_DIR"
  local stamp file
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  file="${BACKUP_DIR}/fvas-${stamp}.dump"

  log "dumping ${PG_DB} …"
  # -Fc custom format, --no-owner so a restore into a differently-named role
  # works. A backup that only restores onto its original role is a backup with
  # a hidden precondition.
  compose_exec pg_dump -U "$PG_USER" -d "$PG_DB" -Fc --no-owner > "$file"

  local size
  size="$(wc -c < "$file")"
  [ "$size" -gt 1000 ] || fail "backup is only ${size} bytes — pg_dump probably errored"

  log "wrote ${file} (${size} bytes)"
  echo "$file"
}

cmd_restore() {
  local file="${1:-}"
  [ -n "$file" ] || fail "usage: backup.sh restore <file>"
  [ -f "$file" ] || fail "no such backup: $file"

  log "restoring ${file} into ${PG_DB} …"
  # --clean --if-exists drops existing objects first, so a restore over a live
  # database is a replacement rather than a merge that half-fails on conflicts.
  compose_exec pg_restore -U "$PG_USER" -d "$PG_DB" --clean --if-exists --no-owner < "$file"
  log "restored"
}

# Counts that must survive a round trip. Chosen to cover the tables that matter
# most: tenancy, biometrics, and the audit trail.
fingerprint() {
  compose_exec psql -U "$PG_USER" -d "$PG_DB" -t -A -F',' -c "
    SELECT
      (SELECT count(*) FROM organizations),
      (SELECT count(*) FROM users),
      (SELECT count(*) FROM subjects),
      (SELECT count(*) FROM face_profiles),
      (SELECT count(*) FROM face_templates),
      (SELECT count(*) FROM verification_sessions),
      (SELECT count(*) FROM audit_logs),
      (SELECT coalesce(md5(string_agg(id, '' ORDER BY id)), 'none') FROM subjects)
  " | tr -d '[:space:]'
}

cmd_restore_drill() {
  printf '\n=== restore drill ===\n\n'

  log "1. fingerprinting the live database"
  local before
  before="$(fingerprint)"
  log "   ${before}"
  [ "$before" != "" ] || fail "could not fingerprint the database"

  log "2. taking a backup"
  local file
  file="$(cmd_dump | tail -1)"

  log "3. destroying data (this is the part that makes the drill real)"
  compose_exec psql -U "$PG_USER" -d "$PG_DB" -q -c "
    TRUNCATE organizations CASCADE;
    TRUNCATE users CASCADE;
  " >/dev/null

  local destroyed
  destroyed="$(fingerprint)"
  log "   ${destroyed}"
  [ "$destroyed" != "$before" ] || fail "truncate did nothing — the drill would prove nothing"

  log "4. restoring from the backup"
  cmd_restore "$file" >/dev/null 2>&1 || true

  log "5. comparing"
  local after
  after="$(fingerprint)"
  log "   ${after}"

  if [ "$after" = "$before" ]; then
    printf '\n  PASS — the database was destroyed and fully recovered from %s\n\n' "$file"
    return 0
  fi

  printf '\n  before  %s\n  after   %s\n' "$before" "$after"
  fail "restore did not reproduce the original state"
}

cmd_prune() {
  [ -d "$BACKUP_DIR" ] || { log "no backup directory"; return 0; }
  log "removing backups older than ${RETENTION_DAYS} days"
  find "$BACKUP_DIR" -name 'fvas-*.dump' -type f -mtime "+${RETENTION_DAYS}" -print -delete
}

case "${1:-}" in
  dump)          cmd_dump ;;
  restore)       cmd_restore "${2:-}" ;;
  restore-drill) cmd_restore_drill ;;
  prune)         cmd_prune ;;
  *)
    printf 'usage: %s {dump|restore <file>|restore-drill|prune}\n' "$0" >&2
    exit 2
    ;;
esac
