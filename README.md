# p3 — Agent security testing

We test whether an LLM agent follows malicious instructions in external data or tool components. Each case runs **clean** and **attacked**, then we compare answers, tool calls, and simulated effects. OpenClaw uses a local LM Studio model and mock tools; no real emails, payments, or shell commands are executed by those tools.

| Dataset | Tests |
|---|---|
| AgentDojo | 100 attack variants across 10 everyday tasks |
| InjecAgent | 100 original tool-response attack records |
| Connor | 100 component adaptations; original malicious server code is not executed |

## Run

See [SETUP_AND_RUN.txt](SETUP_AND_RUN.txt) for installation, model configuration, and server ports.

Start LM Studio with the model configured in OpenClaw. Requires Windows, Python 3, Node.js, and OpenClaw installed through npm. From the project root:

```powershell
python .\white_greybox_testing\run_tests.py --dataset agentdojo
python .\white_greybox_testing\run_tests.py --dataset injecagent
python .\white_greybox_testing\run_tests.py --dataset connor
```

Omit `--dataset` to run everything. Add `--case 1` for one case or `--dry-run` to check inputs without running the model.

## Where things are

| Folder | Contents |
|---|---|
| `white_greybox_testing/tests/` | Clean inputs, attacks, and source records |
| `white_greybox_testing/runner/` | Runner, mock tools, and evaluator |
| `white_greybox_testing/results/` | Current run results and logs |
| `data/` | Collected source datasets and provenance |
| `blackbox_testing/` | Planned black-box testing and Slurm/Ollama starter |
| `docs/` | Detailed notes, validation, and historical files in `archive/` |

**Completed does not mean correct or secure.** Incomplete or undelivered tests are inconclusive. The evaluator currently overcounts retrieval-argument differences as forbidden attempts, so review actual tool actions. These are adapted tests with repeated tasks, not official benchmark results.
