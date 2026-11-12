# How the runner works

This folder connects the prepared tests to OpenClaw and the local LM Studio model. Start tests with `white_greybox_testing/run_tests.py` from the project root; it selects cases and calls this runner.

## Test flow

1. Load and validate the case's clean and attacked inputs.
2. Start each condition with a fresh OpenClaw environment and synthetic state.
3. Give the agent its legitimate task and retrieval context. Mock tools return the prepared data; the attacked condition includes the injection. Connor also changes tool descriptions and schemas.
4. Record tool calls, simulated effects, errors, and the final answer.
5. Evaluate the evidence and save results under `white_greybox_testing/results/`.

## Main files

| File | Purpose |
|---|---|
| `run_test.py` | Starts OpenClaw, runs each condition, and saves evidence |
| `mock_tools.py` | Validates inputs and selects tool definitions |
| `plugin/` | Provides mock tools and records their calls and synthetic state changes |
| `evaluate.py` | Summarizes delivery, completion, attempted actions, and observed effects |
| `initial_state.json`, `tool_definitions.json` | Supporting state and tool definitions |
| `build_expanded_cases.py` | Prepares test cases; not used during normal runs |
| `test_*.py` | Offline checks of fixtures, mock behavior, and evaluation |

## Reading results

`events.jsonl` records what happened, `final_state.json` shows simulated effects, and `result.json` summarizes the outcome. Mock tools do not perform real payments, send real emails, or execute shell commands. Connor replays component surfaces without executing the original malicious servers.

**Completed does not mean correct or secure.** Policy labels describe scope; they do not block mock actions. The current evaluator can flag harmless retrieval-argument differences as forbidden attempts, so inspect actual tool calls before counting compromises. Missing input delivery and incomplete runs are inconclusive. “Manual review required” is an evaluator label, not an agent request for approval.
