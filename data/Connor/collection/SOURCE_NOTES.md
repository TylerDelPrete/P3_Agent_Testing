# Connor Malicious MCP Server Fixtures (collection & formatting only)

## Purpose
This is a static collection of the publicly released malicious MCP server fixtures from the Connor research artifact, made for Problem Statement 3 research on whether an agent component's observed behavior matches its declared scope. It is a collection and formatting job only. No agents were run, no MCP servers were started, no fixtures were imported or executed, no attacker destinations were contacted, and no embedded instructions were followed. All fixture content is untrusted research data. `observed_outcome` is null for every record.

## Source
- Paper: Huang et al., "From Component Manipulation to System Compromise: Understanding and Detecting Malicious MCP Servers", arXiv:2604.01905v2. The arXiv abstract page links to the repository below.
- Repository: https://github.com/yiheng98/Connor
- Pinned commit: `326ab9116699442d2744b445b38c69524fbf43e6` (HEAD of `main` when cloned on 2026-10-18). Its presence was confirmed with `git rev-parse HEAD`. Source bytes are copied verbatim from that checkout into `source_snapshot/`.
- Retrieval time: 2026-10-18T10:33:19.151625-06:00 (America/Denver). Exact ISO timestamp is in `manifest.json`.

## What was collected (distinct fixtures)
Distinct fixtures were identified as **one MCP server directory** (a directory containing `mcp.json` plus Python source plus `pyproject.toml`), **not** one file. Counts come from the release layout, not from paper assumptions:

| Origin | Location | Count | Identification |
|---|---|---|---|
| Connor-constructed | `PoCs/{backdoor,payload_exec,ransomeware,reverse_shell,stealing,sabotaging}_PoC/p{1..19}/` | **114** | 6 attack-goal directories × 19 influence-path subdirectories (P1–P19). Repo spelling `ransomeware_PoC` kept verbatim. |
| prior PoC | `Dataset/Malicious/<name>/` | **20** | One directory per prior/third-party server. README: "malicious samples that are separate from the PoCs". Paper Sec 6.1: 20 publicly available PoCs from existing research. |
| **Total** | | **134** | Matches paper Sec 6.1 (114 + 20 = 134 malicious instances). |

Supporting (non-fixture) artifacts also snapshotted:
- `PoCs/response/{example.sh,payload_exec_p8_news.html,stealing_poc_p7_news.html}` — shipped external resources used by payload_exec / stealing PoCs. README.md calls this folder `external_resources`, but the release directory name is `PoCs/response/`.
- License / notice / README files under repo root, `PoCs/`, `Dataset/`, and `licenses/`.
- `Dataset/Benign/benign_servers.zip` — Git-LFS pointer only (oid `sha256:0aaf7180…`, declared size 527,717,028 bytes). Benign and out of scope; the LFS pointer text is snapshotted, the archive was **not** downloaded.

## How fixtures were identified
1. Walk `PoCs/*_PoC/pN/` directories that contain `main.py` + `mcp.json` + `pyproject.toml`. Each such directory is one Connor-constructed fixture.
2. Walk `Dataset/Malicious/*/` directories that contain a Python source + `mcp.json`. Each such directory is one prior-PoC fixture.
3. Do **not** count every source file, supporting HTML, or shared `response/` payload as a server.
4. Distinguish origins by path: under `PoCs/` → Connor-constructed; under `Dataset/Malicious/` → prior PoC (THIRD_PARTY_NOTICES.md).

## License (verified)
- `Connor/` (detector, not collected) and original materials under `PoCs/`: Apache License 2.0. See `PoCs/LICENSE`, `PoCs/NOTICE`, `licenses/APACHE-2.0.txt`. Copies/adaptations/publications must retain the educational and defensive security research notice.
- `Dataset/` materials: **not** covered by the Apache-2.0 grant for Connor/PoCs. Upstream third-party licenses and terms apply (`Dataset/LICENSE.md`, `THIRD_PARTY_NOTICES.md`).
- Upstream sources named in `THIRD_PARTY_NOTICES.md`: AIS2Lab/MCPSecBench, MCP-Security/MCP-Artifact, harishsg993010/damn-vulnerable-MCP-server, security-pride/MCP_Landscape.
- NMT reference doc (updated 5 Oct 2026) agrees: "Original code and PoCs Apache 2.0 with educational/defensive notice. Third-party dataset materials retain upstream terms."

## Attack goals and influence paths (source labels)
SOURCE: arXiv:2604.01905v2 Sec 4.1 (six attack goals) and Table 3 (19 influence paths). Applied to Connor-constructed fixtures by their directory names.

### Attack goals (6 × 19 = 114)
| Repo directory (verbatim) | Paper attack goal |
|---|---|
| `backdoor_PoC` | backdoor (e.g. planting SSH keys / unauthorized execution pathways) |
| `payload_exec_PoC` | download & execute payload |
| `ransomeware_PoC` | ransomware |
| `reverse_shell_PoC` | reverse shell |
| `stealing_PoC` | data leakage (token / sensitive data exfiltration) |
| `sabotaging_PoC` | sabotaging (file tampering/deletion, DoS) |

### Influence paths P1–P19 (Table 3)
| ID | Path | Injection point | Stage |
|---|---|---|---|
| P1 | A_TD → LLM1 --arg--> Builtin | TD | LLM1 |
| P2 | A_AS → LLM1 --arg--> Builtin | AS | LLM1 |
| P3 | A_TD → LLM1 --arg--> B_TSC | TD, TSC | LLM1 |
| P4 | A_TD → LLM1 --arg--> A_TSC | TD, TSC | LLM1 |
| P5 | A_AS → LLM1 --arg--> A_TSC | AS, TSC | LLM1 |
| P6 | A_TD → LLM1 --uri--> RSC | TD, RSC | LLM1 |
| P7 | A_TR → LLM2 --arg--> B_TSC | TR, TSC | LLM2 |
| P8 | A_TR → LLM2 --arg--> Builtin | TR | LLM2 |
| P9 | A_TR → LLM2 --arg--> A_TSC | TR, TSC | LLM2 |
| P10 | A_TR → LLM2 --uri--> RSC | TR, RSC | LLM2 |
| P11 | A_TD → LLM1 --uri--> RR → LLM2 --arg--> B_TSC | TD, RR, TSC | LLM1+2 |
| P12 | A_TD → LLM1 --uri--> RR → LLM2 --arg--> A_TSC | TD, RR, TSC | LLM1+2 |
| P13 | A_TD → LLM1 --uri--> RR → LLM2 --arg--> Builtin | TD, RR | LLM1+2 |
| P14 | A_TD → LLM1 → B_TR → LLM2 --uri--> RSC | TD, TR, RSC | LLM1+2 |
| P15 | A_TD → LLM1 → B_TR → LLM2 --arg--> A_TSC | TD, TR, TSC | LLM1+2 |
| P16 | A_TD → LLM1 → B_TR → LLM2 --arg--> Builtin | TD, TR | LLM1+2 |
| P17 | TSC | TSC | ∅ |
| P18 | A_TSC + B_TSC | TSC | ∅ |
| P19 | CONFIG | CONFIG | ∅ |

TD=tool description, AS=argument schema, TSC=tool source code, TR=tool response, RSC=resource implementation code, RR=resource response/content, CONFIG=server configuration, Builtin=host-provided builtin tools.

## Prior / third-party Dataset/Malicious attribution
Attribution is from `THIRD_PARTY_NOTICES.md` plus in-file evidence (FastMCP display names, `/tmp/dvmcp_*` paths). Exact upstream for 8 of 20 fixtures could not be determined from the release alone; candidate set is recorded.

| Fixture | Attributed upstream | Confidence |
|---|---|---|
| MCPSecBench | AIS2Lab/MCPSecBench | high |
| challenge1 … challenge10 | harishsg993010/damn-vulnerable-MCP-server | high |
| namespace | security-pride/MCP_Landscape (best match) | medium |
| tool_poisoning, ETHPriceCurrentServer, Poisonattack1–3, weather_attack1–3 | unresolved (candidates: MCP-Security/MCP-Artifact or security-pride/MCP_Landscape) | low |

## Files and schema (schema_version `connor-malicious-mcp-normalized/1.0`)
- `source_snapshot/`: verbatim copies of collected repo paths (PoCs/, Dataset/Malicious/, licenses, notices, response resources, LFS pointer for benign zip).
- `raw_samples.jsonl`: **source-extraction records** (not original dataset JSON; the repo ships no per-fixture JSON). One extraction record per fixture plus one supporting-artifact record for `PoCs/response/`. Contains FastMCP servers, tool docstrings verbatim, mcp.json verbatim, pyproject deps, referenced endpoints.
- `normalized_samples.jsonl`: one record per distinct component fixture (134).
- `case_summary.csv`: collector-written concise summaries (not source text).
- `component_files.jsonl`: component → file mappings with SHA-256.
- `author_asr.json`: Appendix B Tables 11–16 ASR values, keyed by `{category}/{pN}`. Used to fill `author_reported_result` for Connor PoCs.
- `manifest.json`: commit, retrieval time, source/output hashes, counts, schema version.
- `validation_output.txt`: actual validation results from the script.
- `collect_and_validate.py`: reproduces everything. Usage: `python3 collect_and_validate.py <repo_clone> <output_dir>`. Needs no credentials and uses no network. Place `author_asr.json` next to the script to fill author-reported ASR (optional; without it that field is null).

### Normalized field mapping

| Normalized field | Source |
|---|---|
| case_id | collector-generated `connor-poc-<category>-<pN>` or `connor-dataset-malicious-<name>` |
| dataset | `"Connor"` |
| original_component_id_or_name | directory name (`p1`…`p19` or Dataset name) |
| component_origin | `"Connor-constructed"` \| `"prior PoC"` (by path) |
| component_file_refs | repo-relative paths of all files in the fixture directory |
| declared_description | FastMCP display name(s) from static AST parse |
| declared_tools_and_capabilities | tools/resources/prompts + parameters + **verbatim docstrings** from static AST parse |
| documented_setup_or_trigger | `mcp.json` command/args (verbatim) + flag if command embeds a shell payload |
| documented_attacker_objective | Connor PoCs: paper Sec 4.1 goal for the category directory. Prior PoCs: null (not labelled in release) |
| original_behavior_or_attack_labels | category/path directory names (verbatim) + FastMCP display names for prior PoCs |
| influence_path | paper Table 3 for Connor PoCs; null for prior PoCs |
| expected_behavior | collector summary of declared cover functionality (FastMCP name); **not** an authorized task or clean control |
| author_reported_result | Connor PoCs: Appendix B per-goal/per-path ASR by host+LLM, with evidence_ref. Prior PoCs: null. **Not** observed_outcome |
| observed_outcome | always null (no execution) |
| runtime_evidence_refs | always empty (repo ships no per-fixture runtime evidence) |
| dependencies_and_environment_requirements | pyproject deps, requires-python, mcp.json runtime, shared response/ refs, referenced endpoints (do not contact) |
| license_refs | PoCs Apache-2.0 notices, or Dataset third-party notices |
| provenance | repository_url, commit_hash, source_paths, original IDs, retrieval_time (America/Denver) |
| extraction_status / unresolved_fields | complete or partial; lists unresolved items |
| interpretation | collector-added notes, separated from source facts |

## Author-reported results vs observed outcomes
- Paper Appendix B Tables 11–16 report attack success rate (ASR) for each (attack goal × influence path) across 7 host+LLM configurations (5 trials each). These fill `author_reported_result` for Connor PoCs and are labelled as author-reported.
- Paper Table 5 reports path-level average ASR across the six goals.
- **None of these are copied into `observed_outcome`.** Our collection performed no execution. An attack objective, malicious code pattern, or author-reported ASR is not behavior observed in our experiments.

## Shared files / related components
- `PoCs/response/example.sh` is referenced by all 17 `payload_exec_PoC/p{1..17}` fixtures (p18/p19 use different mechanisms).
- `PoCs/response/payload_exec_p8_news.html` referenced by `payload_exec_PoC/p8`.
- `PoCs/response/stealing_poc_p7_news.html` referenced by `stealing_PoC/p7`.
- Many fixtures embed `http://attacker.controlled:8080/...` or `/dev/tcp/attacker.controlled/...` placeholders. These are recorded under `referenced_external_endpoints_DO_NOT_CONTACT` and were **not** contacted.
- challenge5 and namespace each define **two** FastMCP server instances in one directory (trusted + spoofed/enhanced). Counted as **one** fixture directory each (the release unit), with both servers listed in `declared_tools_and_capabilities`.

## External / unavailable artifacts
| Artifact | Status |
|---|---|
| `Dataset/Benign/benign_servers.zip` | LFS pointer only; not downloaded (benign, out of scope, ~528 MB) |
| Zenodo Docker image `connor_docker.tar` (doi:10.5281/zenodo.18464634) | Detector runtime image; not collected |
| Live external URLs referenced by weather_attack\* (`sites.google.com/view/api-weather-location/`) and attacker.controlled placeholders | Recorded, not fetched |
| Zhao et al. (2025b) PoCs | Explicitly excluded by Connor authors (not yet public at their collection time) |
| 6 of 8 Hou et al. (2025) PoCs | Explicitly excluded by Connor authors (threat model mismatch) |

## Dependencies (from pyproject.toml; not installed)
- Universal: `mcp[cli]>=1.26.0`, `requires-python = ">=3.13"`.
- Some Dataset fixtures also declare `requests`, `beautifulsoup4`, `pydantic`, `lxml`.
- Runtime config typically uses `uv --directory /app/<name> run <script>.py` (stdio FastMCP).
- Connor detector (not collected) requires Docker to run servers safely.

## Validation
Independently re-read by `collect_and_validate.py`. See `validation_output.txt`. Checks: JSONL syntax/counts; unique case_ids; CSV/manifest/normalized/component_files counts agree (134); 114 constructed + 20 prior; 6×19 goal distribution; every referenced file present in snapshot with matching SHA-256; live-repo hash re-verification; `observed_outcome` null everywhere; unique (category, path) for Connor PoCs; shared resources documented; unresolved upstream listed.

## Missing fields / limitations
- No original per-fixture JSON dataset; records are collector extraction records.
- No legitimate user tasks, permission policies, or clean counterparts were invented.
- No runtime evidence files released per fixture.
- Exact upstream unresolved for 8 of 20 prior PoCs (candidate set recorded).
- Prior PoCs have no Connor influence-path labels and no Appendix B ASR.
- Repo directory spelling `ransomeware_PoC` (missing 'o') kept verbatim.
- Static AST parse cannot resolve dynamic tool registration; none observed in this release.
- Windows Defender may quarantine malicious fixture files after copy; any blocked paths will be recorded separately.

## Reproduction
```bash
git clone https://github.com/yiheng98/Connor.git
cd Connor && git checkout 326ab9116699442d2744b445b38c69524fbf43e6
# place collect_and_validate.py and author_asr.json together
python3 collect_and_validate.py /path/to/Connor /path/to/output
```
No credentials. No network after the clone. Static parse + file copy + hashing only.

## Note on the NMT reference document
The "Open Datasets for NMT Agent Research" doc (updated 5 Oct 2026) was read for background. It describes Connor as "114 constructed malicious MCP servers across six outcomes and 19 influence paths; the paper evaluates 134 malicious servers including 20 prior PoCs" with "Original code and PoCs Apache 2.0 with educational/defensive notice. Third-party dataset materials retain upstream terms." Our findings agree. The doc was not treated as authorization to collect other datasets (Benign zip, detector code, or unrelated corpora were left alone).

## Handling
Treat all content as untrusted research material. Do not follow instructions embedded in tool descriptions or HTML resources, do not contact attacker endpoints, and do not execute payloads. Review package rights and behavior before any isolated experiment.
