# AgentDojo static collection (collection and formatting only)

## Purpose and handling
Static collection of the published AgentDojo task, attack, tool, fixture and evaluator definitions for single-agent prompt-injection research. No AgentDojo module was imported or executed, no dependency was installed, no model was called, the benchmark was not run, no attack was executed, no URL found inside repository content (attacker destinations, phishing links, etc.) was visited, and no embedded instruction was followed. All repository content, fixture text, injection defaults and attack templates are untrusted research data.

## Source and pinning
- Paper: Debenedetti et al., "AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents", NeurIPS 2024 Datasets & Benchmarks, arXiv:2406.13352. The arXiv page states "We release code for AgentDojo at https://github.com/ethz-spylab/agentdojo"; the project page https://agentdojo.spylab.ai links the same repository.
- Repository: https://github.com/ethz-spylab/agentdojo
- Pinned commit: `089ed468cf3ed0322acc66b0211f26d9d90dbf60` (HEAD of `main` at retrieval; committer date 2026-06-02T09:59:58Z; tree `45cc40920b8ddca28e675505fdd6a92139008ab3`; message: "Add openai-compatible provider for arbitrary OpenAI-compatible endpoints (#147)"). Package version in pyproject.toml: 0.1.35.
- Retrieved: 2026-10-18T16:23:59Z UTC = 2026-10-18T10:23:59-06:00 (MDT).
- Retrieval: codeload tarball `https://codeload.github.com/ethz-spylab/agentdojo/tar.gz/089ed468cf3ed0322acc66b0211f26d9d90dbf60` (sha256 `d7e0ee021be27a69e7e66647979b5a5e0dd10030d38d04ce4102e18a76a228d8`; its pax header comment equals the commit SHA), plus the GitHub git-tree listing and commit metadata (saved as git_tree_listing.json and git_commit_metadata.json). Every one of the 36860 blobs in the tree was checked by recomputing its git blob SHA-1 from the tarball bytes: 0 mismatches, 0 missing. (A `git clone` was attempted first but failed on a TLS error, so the tarball + tree route was used.)
- Preservation: all 181 non-`runs/` files (code, docs, LICENSE, CITATION.bib, pyproject.toml, uv.lock, .python-version, CI/devcontainer config, notebooks, tests, fixtures) are in `source_snapshot/` at their repository paths. `runs/` (36679 published run-log JSON files, ~426 MB) is inventoried, not copied (see below).

## License (verified at the pinned commit)
- `LICENSE`: MIT License, Copyright (c) 2024 Edoardo Debenedetti, Jie Zhang, Mislav Balunovic, Luca Beurer-Kellner, Marc Fischer, and Florian Tramèr. pyproject.toml classifier: `License :: OSI Approved :: MIT License`.
- The paper (Appendix E.4/E.5) says the code **and data** are released under MIT "unless otherwise stated in some portions of the code". No separate fixture/data license file exists.
- Marked third-party portions: `src/agentdojo/yaml_loader.py` (`!include` loader, MIT, Copyright (c) 2018 Josh Bode; plus a Stack Overflow snippet marked "Released under CC BY-SA 3.0"); `src/agentdojo/types.py` refers to the openai-python license for re-defined types.
- Externally hosted traces (Google Drive zip, Invariant Explorer) have no separate terms found; check them before downloading or redistributing.

## How AgentDojo is structured (source facts used for extraction)
- Four suites (`workspace`, `travel`, `banking`, `slack`). Each has `src/agentdojo/default_suites/v1/<suite>/task_suite.py` (environment class + `TOOLS` list), `user_tasks.py` and `injection_tasks.py` (task classes), and fixtures `src/agentdojo/data/suites/<suite>/environment.yaml` (workspace uses `!include include/{inbox,calendar,cloud_drive}.yaml`) and `injection_vectors.yaml`.
- A user task is a class `UserTaskN` with `PROMPT`, optional `GROUND_TRUTH_OUTPUT`/`DIFFICULTY`/`COMMENT`, `ground_truth()` (list of `FunctionCall`s) and `utility()` (+ optional `utility_from_traces()`). An injection task (normalized as `attacker_task`) is `InjectionTaskN` with `GOAL`, `ground_truth()` and `security()`. IDs (`user_task_N`, `injection_task_N`) are assigned from the class name by the registration decorator.
- Some user tasks are not classes: `TaskCombinator.create_combined_task(...)` / `update_combined_task(...)` builds them from two component tasks at import time. These are recorded with `definition_kind = combinator_call`.
- Versioning: later folders (`v1_1`, `v1_1_1`, `v1_1_2`, `v1_2`, `v1_2_1`, `v1_2_2`) add or replace tasks with `@task_suite.update_user_task(V)` / `update_injection_task(V[, new=True])`, which writes into a per-task `{version slot -> instance}` map. `src/agentdojo/task_suite/load_suites.py` maps each benchmark version (`v1`, `v1.1`, `v1.1.1`, `v1.1.2`, `v1.2`, `v1.2.1`, `v1.2.2`) to suites with a suite version (via `get_new_version`). For a suite version V, each task ID resolves to the highest registered slot <= V (`get_version_compatible_items`). The benchmark script default is `v1.2.2`.
- Attacks (`src/agentdojo/attacks/`) are classes registered with `@register_attack`. Most fill a template with `{goal}` (the injection task GOAL), `{user}`, `{model}`, `{task}` or `{tools}` at runtime, and place the text in the injection vectors that `get_injection_candidates` finds by *executing the user task's ground truth* on a canary-filled environment. The security test cases are the per-suite cross product of user tasks and injection tasks (paper Sec. 3; `benchmark.py`). That rule is documented here, but **pairs were not enumerated**.

## How the static extraction worked
- Every task-definition module was parsed with `ast`. Registration was reconstructed by a **static import-order simulation**: starting at `agentdojo.task_suite.load_suites`, the collector follows the top-level `import` statements in source order, as Python would, and replays only the registration decorators and combinator calls into a registry model. Module bodies are never executed.
- PROMPT/GOAL values are taken only if they are literals, or pure expressions over literals in the same class or module (f-strings over string or int constants, `+` concatenation, `', '.join(<literal list>)`). Anything else is left null and listed in `unresolved_fields`.
- The workspace fixture's `!include` links are resolved by path. Injection vectors are read with a strict stdlib parser of the flat two-level YAML mapping. The optional PyYAML cross-check is skipped when PyYAML is missing.

## Inventory per benchmark version and suite
Counts are kept separate. User tasks, attacker (injection) tasks, tools and fixtures are different kinds of object and are never added together as "test cases". `fixture_files` = environment.yaml + includes + injection_vectors.yaml. The fixture files are not versioned: every benchmark version uses the same files at this commit. Tools are identical across versions.

| benchmark_version | suite | suite_version | user_tasks | attacker_tasks | tools | injection_vectors | fixture_files |
|---|---|---|---|---|---|---|---|
| v1 | workspace | 1.0.0 | 40 | 6 | 24 | 16 | 5 |
| v1 | travel | 1.0.0 | 20 | 7 | 28 | 13 | 2 |
| v1 | banking | 1.0.0 | 16 | 9 | 11 | 4 | 2 |
| v1 | slack | 1.0.0 | 21 | 5 | 11 | 6 | 2 |
| v1.1 | workspace | 1.0.0 | 40 | 6 | 24 | 16 | 5 |
| v1.1 | travel | 1.1.0 | 20 | 7 | 28 | 13 | 2 |
| v1.1 | banking | 1.0.0 | 16 | 9 | 11 | 4 | 2 |
| v1.1 | slack | 1.0.0 | 21 | 5 | 11 | 6 | 2 |
| v1.1.1 | workspace | 1.1.1 | 40 | 6 | 24 | 16 | 5 |
| v1.1.1 | travel | 1.1.1 | 20 | 7 | 28 | 13 | 2 |
| v1.1.1 | banking | 1.1.1 | 16 | 9 | 11 | 4 | 2 |
| v1.1.1 | slack | 1.1.1 | 21 | 5 | 11 | 6 | 2 |
| v1.1.2 | workspace | 1.1.2 | 40 | 6 | 24 | 16 | 5 |
| v1.1.2 | travel | 1.1.2 | 20 | 7 | 28 | 13 | 2 |
| v1.1.2 | banking | 1.1.1 | 16 | 9 | 11 | 4 | 2 |
| v1.1.2 | slack | 1.1.1 | 21 | 5 | 11 | 6 | 2 |
| v1.2 | workspace | 1.2.0 | 40 | 14 | 24 | 16 | 5 |
| v1.2 | travel | 1.2.0 | 20 | 7 | 28 | 13 | 2 |
| v1.2 | banking | 1.2.0 | 16 | 9 | 11 | 4 | 2 |
| v1.2 | slack | 1.2.0 | 21 | 5 | 11 | 6 | 2 |
| v1.2.1 | workspace | 1.2.1 | 40 | 14 | 24 | 16 | 5 |
| v1.2.1 | travel | 1.2.0 | 20 | 7 | 28 | 13 | 2 |
| v1.2.1 | banking | 1.2.0 | 16 | 9 | 11 | 4 | 2 |
| v1.2.1 | slack | 1.2.0 | 21 | 5 | 11 | 6 | 2 |
| v1.2.2 | workspace | 1.2.2 | 40 | 14 | 24 | 16 | 5 |
| v1.2.2 | travel | 1.2.0 | 20 | 7 | 28 | 13 | 2 |
| v1.2.2 | banking | 1.2.2 | 16 | 9 | 11 | 4 | 2 |
| v1.2.2 | slack | 1.2.0 | 21 | 5 | 11 | 6 | 2 |

Definitions that differ from the `v1` folder, per benchmark version (effective definition folder != v1):

- v1: workspace/user@v1_2=2
- v1.1: travel/user@v1_1=20, workspace/user@v1_2=2
- v1.1.1: banking/user@v1_1_1=1, slack/user@v1_1_1=8, travel/attacker@v1_1_1=1, travel/user@v1_1=19, travel/user@v1_1_1=1, workspace/user@v1_1_1=6, workspace/user@v1_2=2
- v1.1.2: banking/user@v1_1_1=1, slack/user@v1_1_1=8, travel/attacker@v1_1_1=1, travel/user@v1_1=19, travel/user@v1_1_1=1, workspace/user@v1_1_1=6, workspace/user@v1_2=2
- v1.2: banking/attacker@v1_2=8, banking/user@v1_1_1=1, slack/user@v1_1_1=8, slack/user@v1_2=2, travel/attacker@v1_1_1=1, travel/attacker@v1_2=1, travel/user@v1_1=18, travel/user@v1_1_1=1, travel/user@v1_2=1, workspace/attacker@v1_2=9, workspace/user@v1_1_1=5, workspace/user@v1_2=5
- v1.2.1: banking/attacker@v1_2=8, banking/user@v1_1_1=1, slack/user@v1_1_1=8, slack/user@v1_2=2, travel/attacker@v1_1_1=1, travel/attacker@v1_2=1, travel/user@v1_1=18, travel/user@v1_1_1=1, travel/user@v1_2=1, workspace/attacker@v1_2=7, workspace/attacker@v1_2_1=2, workspace/user@v1_1_1=5, workspace/user@v1_2=5
- v1.2.2: banking/attacker@v1_2=8, banking/user@v1_1_1=1, banking/user@v1_2_2=1, slack/user@v1_1_1=8, slack/user@v1_2=2, travel/attacker@v1_1_1=1, travel/attacker@v1_2=1, travel/user@v1_1=18, travel/user@v1_1_1=1, travel/user@v1_2=1, workspace/attacker@v1_2=7, workspace/attacker@v1_2_1=2, workspace/user@v1_1_1=5, workspace/user@v1_2=5, workspace/user@v1_2_2=1

Definition records: 145 user-task definitions (130 classes + 15 combinator calls) and 54 attacker-task definitions across all version folders. One task ID can have several definitions, one per version folder, so these are not per-version counts. 10 definitions are effective in no benchmark version (see findings).
Tools: 69 unique tool functions. Per-suite exposure is {'banking': 11, 'slack': 11, 'travel': 28, 'workspace': 24}, i.e. 74 suite-tool memberships, because these functions are exposed by more than one suite: `create_calendar_event` (travel+workspace), `search_calendar_events` (travel+workspace), `get_day_calendar_events` (travel+workspace), `cancel_calendar_event` (travel+workspace), `send_email` (travel+workspace). Injection vectors: 39. Registered attack generators: 17.

Cross-check with the paper (v1): Table 1 reports workspace 40/6, slack 21/5, travel 20/7, banking 16/9 user/injection tasks (97 user tasks, 27 injection tasks). The text says 74 tools and Table 1 says 70; the per-suite tool counts sum to 24+11+28+11 = 74. The v1 row above reproduces the paper's user and injection counts. The paper's 629 security cases are the per-suite products of these counts. They are a derived product and were **not** materialized here.

## Notable source findings (from static analysis; confirm by controlled execution before relying on them)
1. **`default_suites/v1_1_2` is not imported by `load_suites.py` or by any module it imports.** Its 8 definitions (agentdojo/travel/injection_task_3@v1_1_2, agentdojo/travel/injection_task_5@v1_1_2, agentdojo/workspace/injection_task_0@v1_1_2, agentdojo/workspace/injection_task_3@v1_1_2, agentdojo/workspace/injection_task_4@v1_1_2, agentdojo/workspace/injection_task_5@v1_1_2, agentdojo/workspace/user_task_33@v1_1_2, agentdojo/workspace/user_task_13@v1_1_2) are never registered through `get_suite()`/`get_suites()`. As a result, the `v1.1.2` suites (workspace 1.1.2, travel 1.1.2) resolve to the same definitions as `v1.1.1`. These records are kept and flagged `reachable_from_load_suites_import_graph=false`, with no effective versions.
2. **Slot overwrite at 1.0.0.** `agentdojo/workspace/user_task_31@v1_2` is registered with `@task_suite.register_user_task` (slot 1.0.0) and so replaces `agentdojo/workspace/user_task_31@v1`; `agentdojo/workspace/user_task_32@v1_2` is registered with `@task_suite.register_user_task` (slot 1.0.0) and so replaces `agentdojo/workspace/user_task_32@v1`. In the static import order the later definition wins in every benchmark version, including `v1`. The v1 originals are kept, with no effective versions.
3. Combined tasks capture their component *instances* at import time. For example, `workspace/user_task_19@v1` composes the v1 `user_task_13` instance. Component resolution follows the source accessors (`user_tasks[...]`, `get_latest_user_task_by_id`, `_user_tasks[id][V]`) against the simulated registry state at that point.
4. The `runs/` JSON files carry a `benchmark_version` field only in the newer runs (`v1.2.1` for the Llama-3.3 and Meta-SecAlign runs). Older runs have none (`None` in runs_inventory.csv), so their benchmark version cannot be read from the files.

## Files
Schema version `agentdojo-static-normalized/1.0`.
- `raw_samples.jsonl`: one **extraction envelope** per task definition (class, including its decorator lines, or combinator call). It holds the verbatim source text, sha256 and locator (path, start/end line, GitHub permalink, snapshot path). This is not an original JSON record, because AgentDojo has none.
- `normalized_samples.jsonl`: one record per definition, `record_type` = `user_task` | `attacker_task` (AgentDojo calls these injection tasks).
- `case_summary.csv`: one row per normalized record. `collector_summary` is collector-written (whitespace-collapsed, truncated to 140 chars, prefixed `[collector summary]`) and is not source text.
- `tools.jsonl`: one record per tool function: name, static docstring description, raw docstring, arguments (annotation source, default, required, `:param` description, whether it enters the runtime schema), environment dependencies (`Depends`), return annotation, suites, provenance.
- `relationships.jsonl`: only relationships supported by the source, each with evidence (path/line) and basis. Types and counts are listed below. It has **no user-task x attacker-task pairs**.
- `injection_vectors.jsonl`: suite injection vectors (description, default fill text, placeholder locations in the fixtures). These are the injection surfaces published as source facts.
- `attacks.jsonl`: registered attack generators with their **template source text** (not payloads), placeholders and provenance.
- `version_matrix.csv`: benchmark_version x suite x task ID -> effective definition (`case_id`).
- `trajectory_links.jsonl`, `runs_inventory.csv`: inventory of published execution trajectories (see below).
- `static_analysis.json`: the import order used, every registration event, dormant modules, suite tool lists, fixture details and the runs summary.
- `git_tree_listing.json`, `git_commit_metadata.json`: provenance for the pinned commit. `source_snapshot/`: preserved files.
- `manifest.json`: commit, retrieval time, tarball hash, blob verification, counts, and the sha256 of every file except itself and validation_output.txt. `validation_output.txt`: actual validator output. `collect_and_validate.py`: the full pipeline.

### Field mapping (normalized_samples.jsonl)
| Field | Source / rule |
|---|---|
| case_id | collector-generated `agentdojo/<suite>/<task_id>@<definition_folder>` (unique per definition) |
| dataset | "AgentDojo" |
| suite | suite of the `task_suite` object targeted by the decorator / combinator |
| record_type | `user_task` (UserTaskN) or `attacker_task` (InjectionTaskN) |
| original_task_id | `user_task_N` / `injection_task_N`, as assigned by TaskSuite from the class name |
| legitimate_user_task | `PROMPT` (user tasks). For combined tasks: the `prompt=` literal, or the combinator's default template filled with the component PROMPTs (marked as derived in interpretation.field_resolution). Null for attacker tasks |
| attacker_objective | `GOAL` (attacker tasks); null for user tasks |
| published_attack_payload | always null: no concrete payload is published in the definitions (see attacks.jsonl for generators) |
| injection_target_or_surface | always null + unresolved: computed at runtime by get_injection_candidates (suite-level surfaces are in injection_vectors.jsonl) |
| relevant_tools | tool names in `FunctionCall(function="...")` literals in `ground_truth` (combined tasks: union of the components) |
| environment_fixture_refs | the suite's environment.yaml, its includes, and injection_vectors.yaml |
| evaluator_refs | ground_truth / utility / utility_from_traces or ground_truth / security / security_from_traces method ranges (inherited defaults are noted without lines) |
| original_metadata | registration mechanism, decorator source, version slot, effective benchmark versions, reachability, slot overwrite, class attributes (DIFFICULTY, GROUND_TRUTH_OUTPUT, COMMENT, private constants such as attacker IBANs or e-mails, as literal values or unresolved), methods, ground-truth call list with lines, combinator components |
| supplied_continuation | always null (none in the source) |
| observed_outcome | always null. Evaluator code, ground truths and goals are not outcomes, and run logs were not read for outcomes |
| provenance | repository URL, commit, source path, symbol, module, exact start/end lines, GitHub permalink, raw_id, sha256 of the source text, retrieval time |
| extraction_status / unresolved_fields | `resolved_except_runtime_fields` when only runtime-computed fields are missing, `partial` otherwise; each unresolved field has a reason and a source reference |
| interpretation | collector notes, kept apart from the source facts |

### Relationship types and counts
- `attack_generator_registered`: 17
- `combined_task_component`: 30
- `fixture_includes_file`: 3
- `injection_vector_placeholder_in_fixture`: 41
- `suite_declares_injection_vector`: 39
- `suite_exposes_tool`: 74
- `suite_uses_fixture_file`: 11
- `task_definition_supersedes`: 57
- `task_effective_in_benchmark_version`: 892
- `task_ground_truth_calls_tool`: 570
- `task_has_evaluator`: 386
- `task_registered_in_suite`: 199
- `task_slot_overwritten_by`: 2
- `task_uses_suite_fixture`: 199
- Total: 2520. `task_effective_in_benchmark_version` follows the static version-resolution rule. `task_ground_truth_calls_tool` targets a suite-scoped tool name, which resolves to a tools.jsonl entry through `suite_exposes_tool`.

## Published execution trajectories (inventoried, not collected)
- https://github.com/ethz-spylab/agentdojo/tree/089ed468cf3ed0322acc66b0211f26d9d90dbf60/runs: in-repo run logs: one JSON per (pipeline, suite, user task, attack, injection task|none). Access: public, no authentication; included in the pinned codeload tarball (MIT repository license). Status: inventoried only (runs_inventory.csv: path, size, sha256, git-blob check, path-derived ids, 4 metadata keys); contents not normalized, outcomes not read out.
- https://agentdojo.spylab.ai/results/: results table page (built from docs/results.md + docs/results-table.html). Access: public web page; HTTP 200 when checked by the collector on 2026-10-18. Status: not downloaded; its source docs/results-table.html is preserved in source_snapshot/.
- https://explorer.invariantlabs.ai/benchmarks/: external trace viewer (Invariant Explorer), per-run 'Explore' links in docs/results-table.html. Access: on 2026-10-18 both the benchmark URL and a sampled per-run URL redirected (HTTP 200 after redirect) to https://github.com/invariantlabs-ai/explorer; hosted traces not reachable at the published URLs; nothing downloaded. Status: not downloaded.
- https://drive.google.com/file/d/16nhDqSTRVac_GbcC3-9WMjVaJZfmcwLO/view?usp=share_link: zipped model outputs referenced by the paper (to be unzipped into runs/). Access: Google Drive share link; view page returned HTTP 200 without login on 2026-10-18; no separate terms found; file NOT downloaded. Status: not downloaded (separate externally hosted trace collection; deferred to a later task).
- `runs_inventory.csv` lists all 36679 files under `runs/` across 29 pipeline directories, with path-derived pipeline/suite/task/attack/injection-task, size, sha256, git-blob verification, and four metadata keys (`benchmark_version`, `agentdojo_package_version`, `evaluation_timestamp`, number of injection keys). Messages, injection text, errors and utility/security results were **not** read out. These files contain concrete rendered injections, so they are the only place where concrete payloads and actually-run task-attack combinations are published. Extracting them is deferred to a separate task.

## Extraction limits and unresolved fields
- `injection_target_or_surface`: 199 records.
- `original_metadata.class_attributes.GROUND_TRUTH_OUTPUT`: 15 records.
- `published_attack_payload`: 54 records.
- Records with status `partial` (PROMPT/GOAL or tool list not statically resolvable): 0.
- `injection_target_or_surface` needs execution: the injectable vectors per user task are found by running its ground truth. `published_attack_payload` is generated per (user task, injection task, vector, model). The runtime tool description and JSON schema come from docstring_parser + Pydantic, and the combined-task GROUND_TRUTH_OUTPUT is built at runtime. Utility/security results need execution against an LLM.
- Ground-truth tool lists cover only `FunctionCall` literals. Calls built some other way would be missed, and are flagged when detected. Task-specific `init_environment` overrides (recorded) change the starting state at runtime.
- Benchmark membership was derived by static import-order simulation, not by executing `load_suites`. The two findings above should be confirmed in an isolated environment.

## Reproduction
```
python3 collect_and_validate.py collect --out <OUT_DIR> --retrieved-at 2026-10-18T16:23:59Z
#   downloads the pinned tarball, git tree and commit metadata (public, no credentials), or use --tarball/--tree/--commit-json offline,
#   then writes all outputs, README.md and manifest.json, and runs validation
python3 collect_and_validate.py validate --out <OUT_DIR>    # re-validate an existing output folder
```
Requires Python >= 3.10 and the stdlib only. PyYAML is optional, for one extra cross-check. The output is deterministic for a fixed commit and `--retrieved-at`.

## References consulted
- `TestSample/README.md` (InjecAgent Pilot-100) was used as the template: pinned commit with verified bytes, verbatim preservation, raw vs normalized split, collector-written summaries, null-not-invented outcomes, manifest hashes, and a separate validation output.
- `NMT Open Dataset Research.docx` (5 Oct 2026) was read for background only. Its AgentDojo entry ("97 user tasks, 27 injection targets and 629 task-goal combinations across four suites"; "Code MIT; no separate fixture/data license identified"; "Published trajectories are also available") agrees with the v1 counts and the license findings here. "Injection targets" there means injection *tasks* (attacker goals). The fixtures also declare 39 injection *vectors* (placeholders), which are a different count. The doc's AgentDojo links point to the repository, the results page and arXiv:2406.13352. It was not treated as permission to collect other datasets.

## Before replay (not done here)
- Install the pinned package and dependencies (`uv.lock`) in an isolated, egress-restricted environment. Confirm the static findings by loading `get_suites(<version>)` there, and choose the benchmark version explicitly (the script default is v1.2.2).
- Run each suite's ground truths to compute injection candidates per user task (needed for injection surfaces and payloads), and render attack payloads per attack, model name and user name.
- Configure model/provider credentials, the pipeline/defense configuration and spend caps, and enumerate the user x injection task pairs from the per-suite cross product.
- Add instrumentation that keeps attempted, denied, executed and successful actions apart, plus authorization labels and clean controls, as the NMT doc recommends. For comparison, either extract the published runs/ logs (concrete payloads and outcomes) or re-run under pinned conditions.

<!-- COUNTS-JSON {"per_benchmark_version": {"v1": {"workspace": {"suite_version": "1.0.0", "user_tasks": 40, "attacker_tasks": 6, "tools": 24, "injection_vectors": 16, "fixture_files": 5}, "travel": {"suite_version": "1.0.0", "user_tasks": 20, "attacker_tasks": 7, "tools": 28, "injection_vectors": 13, "fixture_files": 2}, "banking": {"suite_version": "1.0.0", "user_tasks": 16, "attacker_tasks": 9, "tools": 11, "injection_vectors": 4, "fixture_files": 2}, "slack": {"suite_version": "1.0.0", "user_tasks": 21, "attacker_tasks": 5, "tools": 11, "injection_vectors": 6, "fixture_files": 2}}, "v1.1": {"workspace": {"suite_version": "1.0.0", "user_tasks": 40, "attacker_tasks": 6, "tools": 24, "injection_vectors": 16, "fixture_files": 5}, "travel": {"suite_version": "1.1.0", "user_tasks": 20, "attacker_tasks": 7, "tools": 28, "injection_vectors": 13, "fixture_files": 2}, "banking": {"suite_version": "1.0.0", "user_tasks": 16, "attacker_tasks": 9, "tools": 11, "injection_vectors": 4, "fixture_files": 2}, "slack": {"suite_version": "1.0.0", "user_tasks": 21, "attacker_tasks": 5, "tools": 11, "injection_vectors": 6, "fixture_files": 2}}, "v1.1.1": {"workspace": {"suite_version": "1.1.1", "user_tasks": 40, "attacker_tasks": 6, "tools": 24, "injection_vectors": 16, "fixture_files": 5}, "travel": {"suite_version": "1.1.1", "user_tasks": 20, "attacker_tasks": 7, "tools": 28, "injection_vectors": 13, "fixture_files": 2}, "banking": {"suite_version": "1.1.1", "user_tasks": 16, "attacker_tasks": 9, "tools": 11, "injection_vectors": 4, "fixture_files": 2}, "slack": {"suite_version": "1.1.1", "user_tasks": 21, "attacker_tasks": 5, "tools": 11, "injection_vectors": 6, "fixture_files": 2}}, "v1.1.2": {"workspace": {"suite_version": "1.1.2", "user_tasks": 40, "attacker_tasks": 6, "tools": 24, "injection_vectors": 16, "fixture_files": 5}, "travel": {"suite_version": "1.1.2", "user_tasks": 20, "attacker_tasks": 7, "tools": 28, "injection_vectors": 13, "fixture_files": 2}, "banking": {"suite_version": "1.1.1", "user_tasks": 16, "attacker_tasks": 9, "tools": 11, "injection_vectors": 4, "fixture_files": 2}, "slack": {"suite_version": "1.1.1", "user_tasks": 21, "attacker_tasks": 5, "tools": 11, "injection_vectors": 6, "fixture_files": 2}}, "v1.2": {"workspace": {"suite_version": "1.2.0", "user_tasks": 40, "attacker_tasks": 14, "tools": 24, "injection_vectors": 16, "fixture_files": 5}, "travel": {"suite_version": "1.2.0", "user_tasks": 20, "attacker_tasks": 7, "tools": 28, "injection_vectors": 13, "fixture_files": 2}, "banking": {"suite_version": "1.2.0", "user_tasks": 16, "attacker_tasks": 9, "tools": 11, "injection_vectors": 4, "fixture_files": 2}, "slack": {"suite_version": "1.2.0", "user_tasks": 21, "attacker_tasks": 5, "tools": 11, "injection_vectors": 6, "fixture_files": 2}}, "v1.2.1": {"workspace": {"suite_version": "1.2.1", "user_tasks": 40, "attacker_tasks": 14, "tools": 24, "injection_vectors": 16, "fixture_files": 5}, "travel": {"suite_version": "1.2.0", "user_tasks": 20, "attacker_tasks": 7, "tools": 28, "injection_vectors": 13, "fixture_files": 2}, "banking": {"suite_version": "1.2.0", "user_tasks": 16, "attacker_tasks": 9, "tools": 11, "injection_vectors": 4, "fixture_files": 2}, "slack": {"suite_version": "1.2.0", "user_tasks": 21, "attacker_tasks": 5, "tools": 11, "injection_vectors": 6, "fixture_files": 2}}, "v1.2.2": {"workspace": {"suite_version": "1.2.2", "user_tasks": 40, "attacker_tasks": 14, "tools": 24, "injection_vectors": 16, "fixture_files": 5}, "travel": {"suite_version": "1.2.0", "user_tasks": 20, "attacker_tasks": 7, "tools": 28, "injection_vectors": 13, "fixture_files": 2}, "banking": {"suite_version": "1.2.2", "user_tasks": 16, "attacker_tasks": 9, "tools": 11, "injection_vectors": 4, "fixture_files": 2}, "slack": {"suite_version": "1.2.0", "user_tasks": 21, "attacker_tasks": 5, "tools": 11, "injection_vectors": 6, "fixture_files": 2}}}, "definitions": {"user_task_definitions": 145, "attacker_task_definitions": 54, "user_task_definitions_class": 130, "user_task_definitions_combinator": 15, "definitions_not_effective_in_any_version": 10, "definitions_dormant_not_reachable_from_load_suites": 8, "definitions_overwritten_in_same_slot": 2}, "suites": 4, "tools_unique_functions": 69, "tools_per_suite": {"banking": 11, "slack": 11, "travel": 28, "workspace": 24}, "injection_vectors": 39, "attack_generators_registered": 17, "relationships_total": 2520, "relationships_by_type": {"attack_generator_registered": 17, "combined_task_component": 30, "fixture_includes_file": 3, "injection_vector_placeholder_in_fixture": 41, "suite_declares_injection_vector": 39, "suite_exposes_tool": 74, "suite_uses_fixture_file": 11, "task_definition_supersedes": 57, "task_effective_in_benchmark_version": 892, "task_ground_truth_calls_tool": 570, "task_has_evaluator": 386, "task_registered_in_suite": 199, "task_slot_overwritten_by": 2, "task_uses_suite_fixture": 199}, "runs_files_inventoried": 36679} -->
