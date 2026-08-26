#!/usr/bin/env bash
#
# Deployment adapter.
#
# The release workflow calls three verbs — `current`, `release`, `rollback` —
# and knows nothing about the host behind them. That indirection is the point:
# swapping Fly for Render or ECS is this file, not the pipeline.
#
#   ./scripts/deploy.sh current                   # print the live revision
#   ./scripts/deploy.sh release <image-ref>       # roll out an image
#   ./scripts/deploy.sh rollback <revision>       # go back to a known-good one
#
# ── Status ────────────────────────────────────────────────────────────────────
#
# **This has not been run against a real host.** No account, domain, or registry
# exists for this project yet. The Fly implementation below is written against
# flyctl's documented interface and is unverified; `DEPLOY_TARGET=noop` is what
# the local pipeline rehearsal actually exercises.
#
# Recorded here rather than in a commit message because someone will reach for
# this script during an incident, and "untested" is the first thing they need to
# know.
#
set -euo pipefail

DEPLOY_TARGET="${DEPLOY_TARGET:-noop}"
FLY_APP="${FLY_APP:-fvas-api}"

log() { printf '  deploy: %s\n' "$*" >&2; }
fail() { printf '  deploy FAILED: %s\n' "$*" >&2; exit 1; }

# ── Fly.io ────────────────────────────────────────────────────────────────────

fly_current() {
  # Only the image matters for rollback; machine ids change on every deploy.
  flyctl status --app "$FLY_APP" --json 2>/dev/null \
    | python -c "import json,sys; print(json.load(sys.stdin)['Machines'][0]['config']['image'])" \
    || true
}

fly_release() {
  local image="$1"
  # --strategy rolling keeps capacity during the swap. `immediate` would take
  # the service down for the duration of the pull, which on a 1 GB image with
  # baked models is not a moment.
  flyctl deploy --app "$FLY_APP" --image "$image" --strategy rolling --wait-timeout 300
}

fly_rollback() {
  local image="$1"
  log "rolling back to ${image}"
  flyctl deploy --app "$FLY_APP" --image "$image" --strategy immediate --wait-timeout 300
}

# ── No-op ─────────────────────────────────────────────────────────────────────
# Lets the pipeline be rehearsed end to end without a host. It prints what it
# would do and succeeds, so a failure anywhere else in the workflow is
# unambiguously that step's fault.

noop_current()  { echo "noop://previous"; }
noop_release()  { log "would release $1"; }
noop_rollback() { log "would roll back to $1"; }

# ── Dispatch ──────────────────────────────────────────────────────────────────

case "${1:-}" in
  current)
    case "$DEPLOY_TARGET" in
      fly)  fly_current ;;
      noop) noop_current ;;
      *)    fail "unknown DEPLOY_TARGET: $DEPLOY_TARGET" ;;
    esac
    ;;
  release)
    [ -n "${2:-}" ] || fail "usage: deploy.sh release <image-ref>"
    case "$DEPLOY_TARGET" in
      fly)  fly_release "$2" ;;
      noop) noop_release "$2" ;;
      *)    fail "unknown DEPLOY_TARGET: $DEPLOY_TARGET" ;;
    esac
    ;;
  rollback)
    [ -n "${2:-}" ] || fail "usage: deploy.sh rollback <revision>"
    case "$DEPLOY_TARGET" in
      fly)  fly_rollback "$2" ;;
      noop) noop_rollback "$2" ;;
      *)    fail "unknown DEPLOY_TARGET: $DEPLOY_TARGET" ;;
    esac
    ;;
  *)
    printf 'usage: %s {current|release <image>|rollback <revision>}\n' "$0" >&2
    exit 2
    ;;
esac
