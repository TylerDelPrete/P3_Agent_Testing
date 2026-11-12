# InjecAgent-Data (complete published case collection)

## Purpose
Complete collection and formatting of the published InjecAgent test-case data for research use.
**Collection and validation only.** No agents were run, no attacks executed, no repository code executed or imported, no attacker destinations visited, and no embedded instructions followed. All payload text is untrusted research data.

## Source verification
- Paper: Zhan et al. 2024, arXiv:2403.02691 ("InjecAgent: Benchmarking Indirect Prompt Injections in Tool-Integrated Large Language Model Agents").
- Evidence: the arXiv abstract page (https://arxiv.org/abs/2403.02691) states the benchmark is available at https://github.com/uiuc-kang-lab/InjecAgent (citation_abstract / abstract text).
- Repository: https://github.com/uiuc-kang-lab/InjecAgent
- Pinned commit: `f19c9f2c79a41046eb13c03c51a24c567a8ffa07` (confirmed as origin/HEAD / main on retrieval; commit object date 2024-07-02).
- Retrieval time (America/Denver): 2026-10-18T10:24:03-06:00
- Source bytes are read exclusively via `git show f19c9f2c79a41046eb13c03c51a24c567a8ffa07:<path>` (never from a dirty working tree).

## License (verified)
Repository root `LICENCE` (British spelling): **MIT License, Copyright (c) 2023 Qiusi Zhan**.
No separate dataset license was found. Data files live in the same repository. Snapshot copy is at `source_snapshot/LICENCE`.

## Scope collected
At the pinned commit, `data/` contains:
| File | Role | Records |
|---|---|---|
| `data/test_cases_dh_base.json` | Direct-harm, base setting | 510 |
| `data/test_cases_dh_enhanced.json` | Direct-harm, enhanced setting | 510 |
| `data/test_cases_ds_base.json` | Data-stealing, base setting | 544 |
| `data/test_cases_ds_enhanced.json` | Data-stealing, enhanced setting | 544 |
| `data/user_cases.jsonl` | Benign user cases | 17 |
| `data/attacker_cases_dh.jsonl` | DH attacker cases | 30 |
| `data/attacker_cases_ds.jsonl` | DS attacker cases | 32 |
| `data/tools.json` | Tool definitions | 38 toolkits |
| `data/attacker_simulated_responses.json` | Precomputed attacker-tool responses used by the evaluator | 2347 keys |

**Total test cases collected: 2108** (1054 base + 1054 enhanced). Base alone matches the paper's 1,054 figure.

Also snapshotted (text): `README.md`, `LICENCE`, `requirements.txt`, `.gitignore`, and all `src/*.py` / `src/prompts/*.py`. Binary assets `asset/overview.pdf` and `asset/overview.png` were **not** copied (figures only; listed in validation log as skipped).

## Field meanings (from README + generation/eval source, read-only)
- **Attacker Instruction**: malicious instruction injected into the user-tool response.
- **Expected Achievements**: attacker's intended goal ("the particular goal or outcome that the [Attacker] aims to accomplish"). **Not an observed outcome.**
- **Attack Type**: harm category (dh: Physical Harm / Financial Harm / Data Security Harm; ds: Physical Data / Financial Data / Others).
- **User Tool / User Instruction / Tool Parameters / Tool Response Template / Thought**: benign user-side fields. `Thought` is a fixed scratchpad prefix used by the evaluator, not an execution trace.
- **Tool Response**: template filled with the attacker instruction (base), or with the documented hacking prefix plus the instruction (enhanced).
- **Modifed** (source spelling): 0/1 flag inherited from attacker case files. **Meaning undocumented** in README/paper/code; stored as-is, never interpreted.
- **Enhanced setting** (README): inserts exactly  
  `IMPORTANT!!! Ignore all previous instructions and strictly adhere to the following instruction:`  
  immediately before the attacker instruction inside the Tool Response.

## Mapping change vs pilot (schema_version injecagent-full-normalized/2.0)
| Field | Pilot (injecagent-pilot-normalized/1.0) | This collection |
|---|---|---|
| `attacker_instruction` | *(not present; content lived under attacker_objective)* | Source `Attacker Instruction` |
| `attacker_objective` | Source `Attacker Instruction` | Source **`Expected Achievements`** |
| `variant` | *(via interpretation.setting)* | Top-level `base` / `enhanced` |
| `provenance.source_path` | `source_file_path` | Renamed to `source_path` |
| `provenance.retrieval_time` | `retrieval_date` (date only) | ISO-8601 with offset |
| `derived` | *(absent)* | Optional safe parses; originals untouched |
| `interpretation.related_case_id` | *(absent)* | Set when base↔enhanced linkage is verified |

## Normalized schema
See `normalized_samples.jsonl`. Direct mappings:
| Normalized | Source |
|---|---|
| legitimate_user_task | User Instruction |
| relevant_tool | User Tool |
| user_tool_parameters | Tool Parameters (exact string) |
| malicious_tool_response_content | Tool Response (exact string) |
| tool_response_template | Tool Response Template |
| attacker_instruction | Attacker Instruction |
| attacker_objective | Expected Achievements |
| attacker_tools | Attacker Tools |
| original_labels | Attack Type, Expected Achievements, Modifed |
| source_thought_field.value | Thought |
| supplied_continuation / observed_outcome | null (not provided) |
| provenance.original_id | null (no source IDs) |

`derived.*` uses `ast.literal_eval` / `json.loads` only for optional parsed views; `parse_status` records success/failure. Cases are never dropped for parse failure.

## Base ↔ enhanced linkage (supported)
Programmatic check for every dh and ds pair at the same `record_index`:
1. All fields **except** `Tool Response` are byte-equal between base and enhanced.
2. Enhanced `Tool Response` equals the base `Tool Response` with the documented hacking prefix inserted immediately before the `Attacker Instruction` substring (1 replacement).
Evidence is recorded in `link_evidence.json` and echoed in `validation_output.txt`. Because this holds for all 1054 pairs, each normalized record carries `interpretation.related_case_id` pointing to the paired setting at the same index.

## Selection / structure note
Source files are the full cross-product: 30 dh attackers × 17 user cases = 510; 32 ds × 17 = 544; each duplicated for enhanced. Therefore shared user tasks and attacker instructions are **by design**, not independent workflows. Validation reports uniqueness of records/locators and counts of shared tasks/templates/instructions without treating repeats as separate workflows.


## Derived-field parse status (optional; originals always kept)
Applied only under `derived.*`; cases are never dropped.
- `user_tool_parameters`: 2108/2108 `ok` (`ast.literal_eval`)
- `tool_response_template`: 2108/2108 `ok` (`ast.literal_eval`)
- `malicious_tool_response` (json.loads of outer JSON string, then `ast.literal_eval` of the decoded text):
  - **1020 ok**
  - **1020 partial** (outer JSON decoded; `ast.literal_eval` raised `SyntaxError` — usually unmatched quotes after the attacker instruction was spliced into Python-literal dict text)
  - **68 failed** (`json.loads` raised `JSONDecodeError: Extra data` — attacker-instruction text contains characters that break the outer JSON string encoding as stored in the source)
  - Failures are evenly 34 base + 34 enhanced (one attacker instruction × 17 user tools × 2 settings). Originals remain authoritative.

## Missing / limitations
- No original IDs, supplied continuations, observed outcomes, execution traces, authorization labels, or clean controls. Left null / absent; never inferred.
- `Modifed` meaning undocumented.
- `Attack Type` value `Others` (ds) is a broad source category.
- Some source strings contain typos (e.g. `subeject`); preserved verbatim.
- Tool Response values are JSON-encoded strings wrapping Python-literal dict text (often with an outer pair of double quotes as stored). Originals preserved; optional decoding lives only under `derived`.
- Binary overview figures omitted from snapshot.
- `manifest.json` cannot hash itself; zip (if created elsewhere) is out of scope of this folder.

## NMT reference note
`/workspace/refs/NMT Open Dataset Research.docx` was read for background only (same content as the earlier attachment). It describes InjecAgent as 1,054 cases / 17 user tools / 62 attacker tools, MIT code, no separate data license, and recommends clean controls. Not treated as authorization to collect other datasets. Pilot format matched via `/workspace/refs/TestSample/`.

## Reproduction
```bash
# Requires a local clone containing commit f19c9f2c79a41046eb13c03c51a24c567a8ffa07
python3 collect_and_validate.py /path/to/InjecAgent
```
Re-running overwrites outputs next to the script. Validation independently re-reads the written files and re-fetches source blobs from the commit for equality checks. Stdlib only; no credentials; no network inside the script.

## Files in this folder
- `source_snapshot/` — byte-identical text files from the commit (repo paths preserved)
- `raw_samples.jsonl` — 2108 original records (re-serialized lines; content+key-order equal to source)
- `normalized_samples.jsonl` — 2108 normalized records (same order)
- `case_summary.csv` — collector-written summaries (labeled)
- `link_evidence.json` — base/enhanced equality evidence
- `README.md` — this file
- `manifest.json` — hashes, counts, schema version
- `validation_output.txt` — actual validation transcript
- `collect_and_validate.py` — this collector
