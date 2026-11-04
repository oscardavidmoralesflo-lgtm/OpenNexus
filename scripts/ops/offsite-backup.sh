#!/usr/bin/env bash
# Daily offsite backup: a dump of the database (application data and the
# WhatsApp sessions) plus .env.docker, which holds the ENCRYPTION_KEY that
# makes the dump usable, encrypted with BACKUP_PASSPHRASE and uploaded to a
# Backblaze B2 bucket. Copies older than BACKUP_KEEP_DAYS are deleted there.
#
# The dump runs while the stack keeps serving: pg_dump reads one consistent
# snapshot. rclone runs from its Docker image, so nothing is installed.
#
#   scripts/ops/offsite-backup.sh          run it now
#   cron: 30 4 * * *  cd /path/to/repo && scripts/ops/offsite-backup.sh >> backups/offsite.log 2>&1

source "$(dirname "$0")/common.sh"

RCLONE_IMAGE="rclone/rclone:1.68.2"

fail() {
  log "backup FAILED: $1"
  send_alert "🔴 Agentaria: falló el respaldo diario" "El respaldo fuera del servidor no se completó: $1

Revisa backups/offsite.log en el servidor. The offsite backup did not finish."
  exit 1
}
trap 'fail "unexpected error on line $LINENO"' ERR

export RCLONE_CONFIG_B2_TYPE=b2
RCLONE_CONFIG_B2_ACCOUNT="$(setting B2_KEY_ID)"; export RCLONE_CONFIG_B2_ACCOUNT
RCLONE_CONFIG_B2_KEY="$(setting B2_APPLICATION_KEY)"; export RCLONE_CONFIG_B2_KEY
BACKUP_PASSPHRASE="$(setting BACKUP_PASSPHRASE)"; export BACKUP_PASSPHRASE
bucket="$(setting B2_BUCKET)"
prefix="$(setting B2_PREFIX opennexus)"
keep="$(setting BACKUP_KEEP_DAYS 30)"

[ -n "$RCLONE_CONFIG_B2_ACCOUNT" ] && [ -n "$RCLONE_CONFIG_B2_KEY" ] && [ -n "$bucket" ] || fail "B2_KEY_ID, B2_APPLICATION_KEY and B2_BUCKET must be set in .env.ops"
[ "${#BACKUP_PASSPHRASE}" -ge 16 ] || fail "BACKUP_PASSPHRASE must be set in .env.ops, at least 16 characters"
[ -f "$STACK_ENV" ] || fail "$STACK_ENV not found"

umask 077
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="agentaria-$stamp.tar.enc"

log "dumping the database"
compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$work/opennexus.dump" || fail "pg_dump failed"
[ -s "$work/opennexus.dump" ] || fail "the dump is empty"
cp "$STACK_ENV" "$work/env.docker"
git -C "$REPO_DIR" rev-parse HEAD > "$work/revision" 2>/dev/null || true

log "encrypting"
tar -C "$work" -cf - opennexus.dump env.docker revision \
  | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:BACKUP_PASSPHRASE -out "$work/$archive" || fail "encryption failed"
rm -f "$work/opennexus.dump" "$work/env.docker"

rclone() {
  docker run --rm --user "$(id -u):$(id -g)" -v "$work:/data" \
    -e RCLONE_CONFIG_B2_TYPE -e RCLONE_CONFIG_B2_ACCOUNT -e RCLONE_CONFIG_B2_KEY \
    "$RCLONE_IMAGE" "$@"
}

log "uploading $archive ($(du -h "$work/$archive" | cut -f1))"
rclone copy "/data/$archive" "b2:$bucket/$prefix/" || fail "upload to Backblaze failed"
rclone delete --min-age "${keep}d" "b2:$bucket/$prefix/" || log "could not delete copies older than $keep days"
log "backup done: b2:$bucket/$prefix/$archive"
