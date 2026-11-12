#!/usr/bin/env bash
set -euo pipefail
models_dir="$1"; port="$2"; manifest="$3"; binary="$4"
export OLLAMA_MODELS="$models_dir" OLLAMA_HOST="127.0.0.1:$port" OLLAMA_NO_CLOUD=1
mkdir -p "$OLLAMA_MODELS"
"$binary" serve &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true; wait "$server_pid" 2>/dev/null || true' EXIT
for i in {1..60}; do
  if curl -fsS "http://127.0.0.1:$port/api/tags" >/dev/null 2>&1; then break; fi
  if ! kill -0 "$server_pid" 2>/dev/null; then echo 'Ollama server exited unexpectedly' >&2; exit 1; fi
  sleep 1
done
curl -fsS "http://127.0.0.1:$port/api/tags" >/dev/null
while IFS= read -r model || [[ -n "$model" ]]; do
  model="${model%%#*}"
  model="$(printf '%s' "$model" | xargs)"
  [[ -z "$model" ]] && continue
  echo "Pulling: $model"
  "$binary" pull "$model"
done < "$manifest"
