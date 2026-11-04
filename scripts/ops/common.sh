#!/usr/bin/env bash
# Shared helpers for the operations scripts. They run on the host, from the
# installation's repository directory, and read two files there:
#   .env.docker  the stack's settings (SMTP_*, ports), never modified here
#   .env.ops     backup and alert settings (see scripts/ops/env.ops.example)
# Values are read line by line, never sourced, so a secret with spaces or
# symbols cannot run as a command.

set -euo pipefail

OPS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$OPS_DIR/../.." && pwd)}"
STACK_ENV="${STACK_ENV:-$REPO_DIR/.env.docker}"
OPS_ENV="${OPS_ENV:-$REPO_DIR/.env.ops}"

# env_get FILE KEY: the value of KEY in FILE, without surrounding quotes.
env_get() {
  local file="$1" key="$2" line value
  [ -f "$file" ] || return 0
  line="$(grep -E "^${key}=" "$file" | tail -n 1 || true)"
  value="${line#*=}"
  value="${value%$'\r'}"
  if [[ "$value" == \"*\" || "$value" == \'*\' ]]; then value="${value:1:${#value}-2}"; fi
  printf '%s' "$value"
}

# setting KEY [DEFAULT]: .env.ops first, then .env.docker, then the default.
setting() {
  local value
  value="$(env_get "$OPS_ENV" "$1")"
  [ -n "$value" ] || value="$(env_get "$STACK_ENV" "$1")"
  printf '%s' "${value:-${2:-}}"
}

compose() {
  local cmd
  cmd="$(setting OPS_COMPOSE "docker compose --env-file $STACK_ENV")"
  (cd "$REPO_DIR" && $cmd "$@")
}

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

# send_alert SUBJECT BODY: e-mail ALERT_EMAIL through the stack's SMTP server.
# Uses curl, so nothing else needs installing. Never fails the caller.
send_alert() {
  local subject="$1" body="$2" host port user pass from security to scheme msg cfg rcpt
  host="$(setting SMTP_HOST)"; port="$(setting SMTP_PORT 587)"
  user="$(setting SMTP_USERNAME)"; pass="$(setting SMTP_PASSWORD)"
  from="$(setting SMTP_FROM "$user")"; security="$(setting SMTP_SECURITY starttls)"
  to="$(setting ALERT_EMAIL)"
  if [ -z "$host" ] || [ -z "$to" ] || [ -z "$from" ]; then
    log "alert not sent (set SMTP_* and ALERT_EMAIL): $subject"
    return 0
  fi
  scheme="smtp"; [ "$security" = "ssl" ] && scheme="smtps"
  msg="$(mktemp)"; cfg="$(mktemp)"
  chmod 600 "$msg" "$cfg"
  {
    printf 'From: %s\r\nTo: %s\r\nSubject: =?UTF-8?B?%s?=\r\n' "$from" "$to" "$(printf '%s' "$subject" | base64 -w0)"
    printf 'MIME-Version: 1.0\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n%s\r\n' "$body"
  } > "$msg"
  # Credentials go through a private config file, not the command line.
  [ -n "$user" ] && printf 'user = "%s:%s"\n' "$user" "${pass//\"/\\\"}" > "$cfg"
  local args=(--silent --show-error --max-time 30 --url "$scheme://$host:$port" --mail-from "$from" --upload-file "$msg" -K "$cfg")
  [ "$security" = "starttls" ] && args+=(--ssl-reqd)
  IFS=',' read -ra rcpt <<< "$to"
  for one in "${rcpt[@]}"; do one="${one// /}"; [ -n "$one" ] && args+=(--mail-rcpt "$one"); done
  curl "${args[@]}" || log "alert e-mail failed: $subject"
  rm -f "$msg" "$cfg"
}
