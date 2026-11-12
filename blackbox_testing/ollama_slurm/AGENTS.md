
# Codex project instructions

Read `PROJECT_GOAL.md` and `SETUP.md` first. This repository is a starter for a Slurm-managed, time-limited Ollama inference API used in reproducible agentic-security research.

Important constraints:
- Never bypass Slurm, cluster policy, or compute-node networking restrictions.
- Keep unauthenticated Ollama bound to `127.0.0.1` on the allocated compute node; require approved SSH forwarding or an authenticated gateway.
- Default model manifest: `gemma3:1b`, `gemma3:12b`, `gemma3:27b`. Don't assume weights are shipped in this repository.
- Models persist in configured shared storage; jobs are ephemeral with six-hour maximum walltime.
- No embedded API secrets. Use environment variables and site-approved secret storage.
- Maintain portable OpenAI-compatible research clients via configurable endpoint/key/model.
- Document untested assumptions and provide mockable tests rather than claiming HPC integration success.

Start by auditing existing scripts, comparing CLI behavior against documentation, then propose and implement small reliable improvements. Prioritize correctness, clear failure reporting, portability, and security over orchestration complexity.

