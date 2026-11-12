
# Slurm + Ollama researcher starter

This is a **starter implementation**, not a tested production HPC deployment. It assumes Slurm, an Ollama executable accessible to batch jobs, `curl`, a filesystem shared by login/compute nodes, and SSH access from the workstation to the compute node through the login host. Confirm the cluster usage policy before deployment.

## Install (on the HPC login node)

Copy this folder to shared storage accessible from compute nodes. Run `chmod +x serve.sh pull.sh hpc_llm.py`.

1. Install Ollama in accordance with HPC admin policy; configure `ollama_binary` in `config.json` to an absolute executable path if it is not on the job's PATH. Loading a module in your job scripts may be necessary.
2. Edit `config.json` for the site's GPU resource syntax, partition, memory, shared model path, and Slurm limits. `gpu_gres` examples: `gpu:1` or `gpu:a100:1` depending on site configuration. Make sure job nodes can access the model directory.
3. Edit `models.txt` (one name per line; `#` comments permitted).
4. Download weights using a CPU job: `python3 hpc_llm.py models pull` (needs outbound internet from CPU compute nodes; check download job log). If CPU jobs cannot reach the internet, ask HPC admins about an approved transfer node or offline model staging.
5. Start the inference allocation: `python3 hpc_llm.py start`. Slurm queues it and allocates the GPU when available.
6. Check node and remaining time: `python3 hpc_llm.py status`.
7. On your **workstation**, open the SSH tunnel shown in the status output, substituting your username and login hostname. This requires SSH into compute nodes (via ProxyJump) and SSH forwarding permission. The tunnel blocks while connected; run it in another terminal.
8. On your workstation: `curl http://127.0.0.1:6767/v1/models` or `pip install openai && python example_client.py`.
9. Stop early: `python3 hpc_llm.py stop`. Otherwise Slurm enforces a six-hour cap (subject to site policy).

## How it works

- `hpc_llm.py`: job submission, status, cancellation, and download job scheduling.
- `serve.sh`: binds Ollama to loopback on the allocated compute node. No public network exposure.
- `pull.sh`: starts a CPU-side Ollama daemon and sequentially downloads the manifest models into persistent storage.
- `models.txt`: declarative list of models to download.
- `example_client.py`: OpenAI SDK request to local or remote compatible provider via environment variables.

## Operational limitations

- No automatic reallocation or request-triggered Slurm scheduling; the allocated GPU remains reserved for six hours. `OLLAMA_KEEP_ALIVE=5m` unloads idle model weights from GPU memory, but does not release the Slurm GPU allocation.
- The CPU pull job needs an Ollama binary that runs without a GPU and network access to the model registry. Never run simultaneous pull and inference jobs writing into the same store; wait for downloads to finish.
- Compute node must allow `ssh -J USER@LOGIN_HOST USER@COMPUTE_NODE`. Some clusters prohibit this. Coordinate with administrators about a permitted loopback-forwarding solution; do not bind an unauthenticated Ollama service to `0.0.0.0` as a workaround.
- The 6-hour period starts when the job begins running, not when it is queued.
- For an API running continuously with on-demand Slurm allocation, add an authenticated long-lived gateway, request queue, Slurm job orchestration, readiness detection, inactivity/idle stop, and timeout/retry handling. This requires admin approval and much more careful concurrency control.
- Ollama supports a subset of OpenAI-compatible APIs, not strict feature parity. Multi-provider experiments should normalize tool and structured-output behavior, token accounting, and model options.
- Secure secrets using environment variables or your HPC secret management policy; don't commit API keys or research data to the repository. Avoid including sensitive prompt content in shared Slurm logs.

## Codex handoff

Read `PROJECT_GOAL.md` for mission, architecture, acceptance criteria, and next steps. `AGENTS.md` provides concise development instructions for Codex. The repository includes model **identifiers** in `models.txt`, not downloaded weights; run the model pull job to obtain those.

