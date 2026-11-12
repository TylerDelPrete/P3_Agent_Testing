# Project goal: Slurm-backed local LLM API for agentic security research

## Mission
Create a reusable, researcher-friendly LLM serving environment on a shared Slurm-managed HPC cluster. Researchers should download a configured set of open-weight models once, start a time-limited GPU inference job, securely reach it at `http://127.0.0.1:6767/v1` from their workstation, and use the same OpenAI-compatible client code to compare local models with remote frontier-model APIs.

## Desired researcher experience
1. Edit `models.txt` to choose Ollama models; defaults: `gemma3:1b`, `gemma3:12b`, `gemma3:27b` (Gemma 3 does not have official 8B or 32B versions).
2. `python3 hpc_llm.py models pull` schedules a CPU Slurm job to download all listed models into durable, shared `OLLAMA_MODELS` storage. Do not assume downloads are already bundled in the repository.
3. `python3 hpc_llm.py start` submits a GPU Slurm job running `ollama serve`, with a six-hour allocation (`--time=06:00:00`). The allocation starts on job execution, not submission.
4. `python3 hpc_llm.py status` reports queue state, compute node, remaining time, and an illustrative SSH tunnel command once the job is running.
5. Run an SSH tunnel from the workstation to the compute node (subject to HPC policy) to map the Ollama endpoint to local port 6767, then call `http://127.0.0.1:6767/v1` using the OpenAI Python SDK or another compatible client.
6. `python3 hpc_llm.py stop` releases the job before its walltime expires; otherwise Slurm terminates it at six hours. Models remain persisted on disk between jobs.

## Architecture and boundaries
- **Research clients**: agent security test harnesses (prompt injection/RAG, tool-call security, RBAC, evaluations) use an abstract LLM API. Clients should accept base URL, API key, and model name as configuration, never hardcode Ollama details.
- **Model manifest**: `models.txt` defines model identifiers; it does not store binaries. `pull.sh` pulls them into `config.json`'s shared `models_dir`. Models must survive job cancellation and expiration.
- **Batch scheduling**: `hpc_llm.py` submits Slurm jobs; `serve.sh` binds Ollama to the compute node's **loopback**, with GPU allocation and hard walltime enforced by Slurm. `pull.sh` uses a CPU allocation and a temporary Ollama server for downloads.
- **Transport**: SSH local port forwarding from the workstation to the allocated compute node; never expose Ollama unauthenticated on a public interface. Confirm that compute-node SSH/forwarding is allowed before deployment.
- **Optional future API gateway**: LiteLLM or another approved OpenAI-compatible gateway can provide stable aliases, provider selection, authentication, logging/redaction, and routing to commercial API providers. The current starter does **not** implement a persistent gateway, automatic scale-to-zero, or request-triggered Slurm jobs.

## Project files
- `hpc_llm.py`: submit/status/stop model-pull and server jobs.
- `config.json`: cluster-specific Slurm requirements, shared paths, Ollama binary, and settings.
- `models.txt`: default Gemma 3 model manifest.
- `pull.sh`: CPU job bootstraps Ollama and downloads manifest entries.
- `serve.sh`: GPU job runs the OpenAI-compatible Ollama API.
- `example_client.py`: minimal OpenAI SDK client with environment-variable provider switching.
- `SETUP.md`: practical installation and safety notes.
- `AGENTS.md`: instructions and development priorities for Codex.

## Current state (starter, not HPC-validated)
The initial scripts exist and are syntactically checked, but have **not** been integrated/tested against a real cluster. Do not claim this is a reliable always-on service. A six-hour job still reserves a GPU even if Ollama unloads model weights after idling. `models pull` schedules the download; it is not a synchronous guarantee that all weights were downloaded successfully. Jobs may wait in the Slurm queue. Only one GPU is requested by default and `gemma3:27b` may require changes to GPU memory, quantization, or context settings.

## Codex implementation priorities
1. Inspect all existing code and preserve a simple, policy-compliant Slurm design. Fix bugs and mismatches before adding features.
2. Make config robust: validate fields, check dependencies and Slurm resource syntax; provide clear errors; avoid concurrent model download jobs and serving jobs accessing the same Ollama store if unsafe.
3. Improve job lifecycle: robust Slurm job ID parsing, queued/running/failed/completed status via `squeue` and `sacct` when available, readiness probes, stale job state cleanup, meaningful logs, no racey reuse of allocated ports.
4. Make model management reliable: verify missing models, retry downloads, handle network/CPU partition constraints and offline staging, report actual pulled model inventory.
5. Improve SSH ergonomics with an explicit client-side helper (the current Python CLI operates on the login node). Port 6767 should be configurable locally; document site-specific compute SSH policies.
6. Add end-to-end smoke tests for `/api/tags`, `/v1/models`, and `/v1/chat/completions`, with mocks so CI doesn't require Slurm or a GPU.
7. Add a provider-agnostic model API config and optional LiteLLM gateway, with secrets supplied via environment variables rather than committed files. Check differing tool calling, JSON/structured output, streaming, token usage, latency, and context behavior.
8. Add experiment reproducibility metadata and safe data logging for research use; redact secrets and sensitive prompts by default.
9. Only after site/admin approval, consider a long-lived **authenticated** gateway that schedules jobs on demand and queues requests during startup. Never assume scale-to-zero is already implemented.

## Acceptance criteria for version 1
- Selected manifest entries are downloaded and persistent between Slurm jobs.
- One command submits a GPU job with a hard six-hour walltime; one command stops it; status accurately identifies its assigned node.
- API only binds to compute-node loopback; a permitted SSH tunnel maps it to workstation `127.0.0.1:6767`.
- An OpenAI-compatible client successfully calls `gemma3:1b`, and larger models when compatible with assigned GPU capacity.
- Switching `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` allows reuse of the same client with another compatible provider.
- Failed jobs, missing models, inaccessible compute nodes, and expired allocations return actionable errors.

## HPC administrator questions
- Which Slurm partition/account/GRES or `--gpus` syntax should we use? Which GPU models and VRAM capacities are available?
- Are Ollama executable/container and CPU-only download jobs permitted? Do CPU nodes have outbound registry access?
- Which shared filesystem is persistent and accessible to login and compute nodes, with sufficient model storage capacity?
- Is SSH/ProxyJump into an allocated compute node allowed? Is local port forwarding allowed? If not, what approved ingress/tunneling path exists?
- Are long-running gateways on service hosts allowed, or must all processes run inside Slurm allocations?

## Out of scope for the initial project
No always-on GPU allocation, no automatic job creation from an inbound API request, no inference during queue delay, no HA/load balancing, no production security claims, and no bundled proprietary or multi-GB model weights.
