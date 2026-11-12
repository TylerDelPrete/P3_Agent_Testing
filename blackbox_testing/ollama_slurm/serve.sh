#!/usr/bin/env bash
set -euo pipefail
export OLLAMA_MODELS="$1" OLLAMA_HOST="127.0.0.1:$2" OLLAMA_KEEP_ALIVE="$3" OLLAMA_CONTEXT_LENGTH="$4"
export OLLAMA_NO_CLOUD=1
export OLLAMA_MAX_LOADED_MODELS=1
mkdir -p "$OLLAMA_MODELS"
echo "Ollama compute node: $(hostname) | job: ${SLURM_JOB_ID:-none} | port: $2"
exec "$5" serve
