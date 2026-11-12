# Agent testing

## Run

From the project root:

```powershell
python .\white_greybox_testing\run_tests.py
```

This runs 100 cases in each of three datasets, each with clean and attacked conditions: **600 model runs**. Start the configured local LM Studio model first. RUN_TESTS.cmd also runs everything. Failures are recorded and the batch continues to the next case.

One dataset:

```powershell
python .\white_greybox_testing\run_tests.py --dataset agentdojo
python .\white_greybox_testing\run_tests.py --dataset injecagent
python .\white_greybox_testing\run_tests.py --dataset connor
```

One case (1 through 100; leading zero optional):

```powershell
python .\white_greybox_testing\run_tests.py --dataset connor --case 1
```

Validate inputs without model calls:

```powershell
python .\white_greybox_testing\run_tests.py --dry-run
```

## What the 100 cases mean

| Dataset folder under tests | Cases | Source coverage | What this experiment measures |
|---|---:|---|---|
| agent_dojo_tets | 100 | 10 original user tasks, each with 10 researcher-authored attack variants | Scope deviation and answer contamination under different attack framing |
| injec_agent_tets | 100 | 100 distinct original base attack records; user tasks may repeat | Response-injection-induced tool actions and bounded synthetic effects |
| connor_tests | 100 | 96 constructed components (6 goals x P1-P16) plus 4 prior PoCs | Agent scope deviation from source-extracted tool descriptions, schemas, and response excerpts |

**These are not 100 independent tasks per dataset.** AgentDojo still uses the 10 supported retrieval tasks; its 90 additions vary attack framing. Analyze results by source task and report this dependence. InjecAgent's 100 records span 17 legitimate prompts/retrieval tool types, so those records also share tasks. Connor components share influence paths and cover functions.

The original AgentDojo and InjecAgent cases 01-10 are preserved. The advisor ZIP is a historical report of the earlier 20-case run and has not been replaced with unrun results.

## Files

- tests/INDEX.csv: all 300 cases with source IDs, task clusters, and attack variants.
- Each case: CASE_GUIDE.md, clean.json, attacked.json, policy.json, environment_spec.json, and source/provenance records.
- Connor surface_evidence.json: source function line spans and literal response excerpts. NOTICES contains the source license notices.
- results/<timestamp>/<dataset>/<case>/<condition>: new execution evidence and results.
- runner/: required execution, mock, preparation, and validation code.

## Connor limits — read before interpreting results

Connor is a **component-surface replay**, not original MCP server execution. The task and clean cover-operation response are researcher-authored. Source docstrings and schema descriptions/defaults appear in the attacked tool definitions; response literals are statically traced from return expressions. Their dynamic branches are not executed, so excerpts are not guaranteed to equal the original runtime response. Local copies of two shipped HTML responses are used without fetching URLs.

Resources are mapped to synthetic tools. run_command records a request but never executes it; it returns an explicit unsupported-operation result. read_file returns only a synthetic canary, and http_post writes only to an in-memory outbox. Original component implementation effects are **not evaluated**. P17-P19 (code/configuration-only paths) are excluded; they need an isolated component-execution harness. The four prior PoCs are tool_poisoning, Poisonattack1, Poisonattack3, and challenge2, with upstream attribution retained in each source record.

A source description is not proof of actual effect. Do not report Connor's original six compromise goals as achieved just because the agent invoked a tool. The results explicitly retain component_compromise = not evaluated. Auxiliary calls outside the supplied task arguments need manual review before being called malicious.

## Baselines and interpretation

Clean and attacked conditions retain the same task and tool names. AgentDojo changes one response field; InjecAgent retains original attack text and uses a researcher-written control. The new InjecAgent controls replace the attack placeholder with neutral text; where that field is the requested content, it does not provide a gold factual answer.

Completed means usable final text, not correct or secure. Incomplete, unsupported, or undelivered inputs are inconclusive. Policy is observe-only; synthetic effect tracking is not authorization enforcement. Task correctness and exact attacker-objective success still require review. Original benchmark ASRs are provenance only, never copied into observed outcomes.

No live model runs were performed while preparing this expansion. This batch is not yet a PS3 drift-detection evaluation; baseline/changed/unchanged-control label trials remain separate.

## Offline checks

```powershell
python -m unittest discover -s .\white_greybox_testing\runner -p "test_*.py"
```

The one-shot preparation source is runner/build_expanded_cases.py. It refuses to overwrite an expanded suite through its normal entry point. Keep the pinned data collections to validate source integrity.
