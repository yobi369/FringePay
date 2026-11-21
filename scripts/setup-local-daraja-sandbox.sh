#!/usr/bin/env bash
set -Eeuo pipefail

# Local Daraja sandbox bootstrap. Secrets are collected locally and written only
# to .env (mode 0600); they are never printed or sent to a remote service.

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "Docker is not installed. Install Docker Engine and the Compose plugin, then rerun this script."
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is unavailable. Install/enable the Docker Compose plugin."
command -v python3 >/dev/null 2>&1 || fail "python3 is required to generate local secrets."

if [[ -e .env ]]; then
  fail ".env already exists. Back it up and remove it only if you intentionally want to replace the local configuration."
fi

read_secret() {
  local prompt="$1" value
  while true; do
    IFS= read -r -s -p "$prompt" value
    printf '\n' >&2
    [[ -n "$value" ]] && break
    printf 'This value is required.\n' >&2
  done
  REPLY="$value"
}

printf '\nFringePay local Daraja sandbox setup\n'
printf 'Credentials are read silently and stored in a local .env file only.\n\n'

read_secret "Daraja Consumer Key: "
CONSUMER_KEY="$REPLY"
read_secret "Daraja Consumer Secret: "
CONSUMER_SECRET="$REPLY"
read_secret "Daraja Business Shortcode: "
SHORTCODE="$REPLY"
read_secret "Daraja Lipa Na M-Pesa Passkey: "
PASSKEY="$REPLY"

POSTGRES_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
CALLBACK_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
PII_KEY="$(python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"

umask 077
{
  printf 'FRINGEPAY_ENVIRONMENT=development\n'
  printf 'FRINGEPAY_API_PREFIX=/v1\n'
  printf 'POSTGRES_PASSWORD=%s\n' "$POSTGRES_PASSWORD"
  printf 'FRINGEPAY_DEFAULT_PROVIDER=daraja\n'
  printf 'FRINGEPAY_DARAJA_ENVIRONMENT=sandbox\n'
  printf 'FRINGEPAY_DARAJA_CONSUMER_KEY=%s\n' "$CONSUMER_KEY"
  printf 'FRINGEPAY_DARAJA_CONSUMER_SECRET=%s\n' "$CONSUMER_SECRET"
  printf 'FRINGEPAY_DARAJA_SHORTCODE=%s\n' "$SHORTCODE"
  printf 'FRINGEPAY_DARAJA_PASSKEY=%s\n' "$PASSKEY"
  printf 'FRINGEPAY_DARAJA_CALLBACK_URL=\n'
  printf 'FRINGEPAY_DARAJA_CALLBACK_SECRET=%s\n' "$CALLBACK_SECRET"
  printf 'FRINGEPAY_DARAJA_TRANSACTION_TYPE=CustomerPayBillOnline\n'
  printf 'FRINGEPAY_PII_ENCRYPTION_KEY=%s\n' "$PII_KEY"
} > .env
chmod 600 .env

unset CONSUMER_KEY CONSUMER_SECRET SHORTCODE PASSKEY POSTGRES_PASSWORD CALLBACK_SECRET PII_KEY

printf '\nBuilding and starting PostgreSQL, API, and worker...\n'
docker compose up --build -d

printf '\nLocal services started. Checking health endpoints...\n'
for attempt in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:8000/ready >/dev/null; then
    break
  fi
  sleep 2
done
curl --fail --silent http://127.0.0.1:8000/health >/dev/null || {
  docker compose ps
  docker compose logs --tail=80 api worker
  fail "FringePay API did not become healthy. Review the logs above."
}
curl --fail --silent http://127.0.0.1:8000/ready >/dev/null || {
  docker compose ps
  docker compose logs --tail=80 api worker
  fail "FringePay database readiness check failed. Review the logs above."
}

printf '\nSUCCESS: FringePay API and database are responding locally.\n'
printf 'API:       http://127.0.0.1:8000\n'
printf 'Readiness: http://127.0.0.1:8000/ready\n'
printf '\nNext: start a temporary HTTPS tunnel in a second terminal:\n'
printf '  cloudflared tunnel --url http://localhost:8000\n'
printf 'Then set FRINGEPAY_DARAJA_CALLBACK_URL in .env to:\n'
printf '  https://YOUR-TUNNEL.trycloudflare.com/v1/webhooks/daraja?token=THE_CALLBACK_SECRET_IN_DOTENV\n'
printf 'Do not paste the callback URL or secrets into public issues or chat.\n'
printf 'After editing .env, restart API and worker:\n'
printf '  docker compose up -d --force-recreate api worker\n'
