#!/usr/bin/env bash
# Uptime check: is the app answering? Run every few minutes from cron. It
# e-mails ALERT_EMAIL when the API, the web gateway or the database stop
# answering twice in a row, and again when they recover, never on every run.
#
#   cron: */5 * * * *  cd /path/to/repo && scripts/ops/check-health.sh >> backups/health.log 2>&1

source "$(dirname "$0")/common.sh"

state_file="$(setting HEALTH_STATE_FILE "$REPO_DIR/backups/.health-state")"
mkdir -p "$(dirname "$state_file")"
api_url="$(setting HEALTH_API_URL "http://127.0.0.1:$(setting API_PORT 8000)/health")"
web_url="$(setting HEALTH_WEB_URL "http://127.0.0.1:$(setting WEB_PORT 3000)/")"

problems=()
curl -fsS --max-time 10 -o /dev/null "$api_url" || problems+=("API ($api_url)")
code="$(curl -s --max-time 15 -o /dev/null -w '%{http_code}' "$web_url" || true)"
[[ "$code" =~ ^(2|3) ]] || problems+=("web ($web_url → ${code:-no answer})")
compose exec -T db sh -c 'pg_isready -q -U "$POSTGRES_USER"' >/dev/null 2>&1 || problems+=("database")

previous="$(cat "$state_file" 2>/dev/null || echo "ok 0")"
read -r prev_state prev_count <<< "$previous"

if [ ${#problems[@]} -eq 0 ]; then
  if [ "$prev_state" = "down" ]; then
    send_alert "✅ Agentaria volvió a funcionar" "La plataforma vuelve a responder normalmente ($(date))."
    log "recovered"
  fi
  echo "ok 0" > "$state_file"
  exit 0
fi

count=$(( ${prev_count:-0} + 1 ))
detail="$(printf -- '- %s\n' "${problems[@]}")"
log "not answering ($count): ${problems[*]}"
if [ "$prev_state" != "down" ] && [ "$count" -ge 2 ]; then
  send_alert "🔴 Agentaria no responde" "Estas partes de la plataforma no responden desde hace unos minutos:

$detail

Revisa el servidor: docker compose ps y los logs. These parts of the platform stopped answering."
  echo "down $count" > "$state_file"
else
  echo "$( [ "$prev_state" = "down" ] && echo down || echo failing ) $count" > "$state_file"
fi
