# GPT-5 mini black-box tests

From the project root, run one paired spending case with Python 3 and Node 20 or newer.

    python blackbox_testing/runner/run_tests.py --dry-run
    python blackbox_testing/runner/run_tests.py

The live command reads OPENAI_API_KEY or prompts for the key with hidden input. Each condition starts a fresh API conversation and a fresh copy of the shared mock state. Only the model request goes over the network. All tool calls are dispatched to the same local mock implementation used by OpenClaw.

tests/suites.json selects the canonical case directories under white_greybox_testing/tests. Choose --dataset agentdojo, injecagent, or connor and --case NUMBER. Use --case all for a full suite. The default runs case 1 of AgentDojo in both conditions.

results/<batch> contains a summary and one result.json per condition with the answer, served model, fixture delivery, mock-call counters, and before/after state. Inspect the answer and effects for task utility and security outcomes. Completed means the fixture was delivered and a final answer arrived. The harness uses the OpenAI Chat Completions tool loop directly, so OpenClaw orchestration and provider behavior can differ. Internal logs and conversation traces are omitted.

ollama_slurm contains the separate HPC starter.
