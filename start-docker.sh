#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
fail() { printf '%s\n' "$*" >&2; exit 1; }
command -v docker >/dev/null || fail 'Install and start Docker Desktop (or Docker Engine + Compose): https://docs.docker.com/get-docker/'
docker compose version >/dev/null 2>&1 || fail 'Docker Compose v2 is required. Update Docker Desktop / install the Compose plugin.'
docker buildx version >/dev/null 2>&1 || fail 'Docker Buildx is required. Update Docker Desktop / install docker-buildx on Ubuntu.'
docker info >/dev/null 2>&1 || fail 'Docker is unavailable. Start Docker Desktop/service; on Linux check your Docker socket permissions.'
docker compose up --help | grep -q -- '--wait-timeout' || fail 'Update Docker Compose: --wait-timeout is required.'

# Do not source this file as shell code or import the developer .env.
unset DQ_DB_PASSWORD DQ_ROOT_PASSWORD DQ_HTTP_PORT
config=.docker.env
[[ ! -L "$config" ]] || fail '.docker.env must not be a symbolic link.'
port=${1:-}
if [[ -n "$port" ]]; then
  [[ "$port" =~ ^[1-9][0-9]{0,4}$ ]] && ((port <= 65535)) || fail 'Port must be 1..65535.'
fi
if [[ ! -e "$config" ]]; then
  # A lost config with existing volumes must never silently generate new credentials.
  volumes=$(docker volume ls --filter label=com.docker.compose.project=dq-desktop --format '{{.Name}}')
  [[ -z "$volumes" ]] || fail 'Existing dq-desktop volumes found but .docker.env is missing. Restore the original .docker.env; do not reset your data.'
  umask 077
  password=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
  root_password=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
  [[ ${#password} -eq 64 && ${#root_password} -eq 64 ]] || fail 'Unable to generate database credentials.'
  (set -o noclobber; printf 'DQ_DB_PASSWORD=%s\nDQ_ROOT_PASSWORD=%s\nDQ_HTTP_PORT=%s\n' "$password" "$root_password" "${port:-18000}" > "$config")
fi
chmod 600 "$config"
grep -Eq '^DQ_DB_PASSWORD=[a-f0-9]{64}$' "$config" || fail 'Invalid database password config; restore .docker.env.'
grep -Eq '^DQ_ROOT_PASSWORD=[a-f0-9]{64}$' "$config" || fail 'Invalid root password config; restore .docker.env.'
saved_port=$(sed -n 's/^DQ_HTTP_PORT=//p' "$config")
[[ "$saved_port" =~ ^[1-9][0-9]{0,4}$ ]] && ((saved_port <= 65535)) || fail 'Invalid port in .docker.env.'
if [[ -n "$port" && "$port" != "$saved_port" ]]; then
  umask 077
  temp=$(mktemp .docker.env.XXXXXX)
  sed "s/^DQ_HTTP_PORT=.*/DQ_HTTP_PORT=$port/" "$config" > "$temp"
  mv "$temp" "$config"
  saved_port=$port
fi
compose=(docker compose -p dq-desktop --env-file "$config" -f compose.yaml)
"${compose[@]}" config --quiet
printf '%s\n' 'Building and starting; first launch requires internet and may take several minutes.'
"${compose[@]}" up --build -d --quiet-pull --wait --wait-timeout 180 || fail 'Deployment failed. Check the error above (network, occupied port, or database). Retry the launcher after fixing it; data volumes are retained.'
url="http://127.0.0.1:$saved_port/setup"
printf 'Ready: %s\nConfigure your model and API key in the browser. Database is ready.\n' "$url"
if [[ "${DQ_NO_BROWSER:-0}" != 1 ]]; then
  if command -v open >/dev/null; then open "$url" || true
  elif command -v xdg-open >/dev/null; then xdg-open "$url" >/dev/null 2>&1 || true
  fi
fi
