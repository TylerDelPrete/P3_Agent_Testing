# Expansion validation — 2026-11-11

Preparation only; no live model batches run.

| Suite | Paired cases | Distinct source IDs | Distinct task prompts |
|---|---:|---:|---:|
| agent_dojo_tets | 100 | 10 | 10 |
| injec_agent_tets | 100 | 100 | 17 |
| connor_tests | 100 | 100 | 20 |

Validation completed:

- 8 automated tests passed (test_cases, test_evaluator, test_expanded).
- 600 clean/attacked fixture deliveries verified through the JavaScript mock dispatcher.
- 208 representative unauthorized synthetic effects verified across paired conditions; invalid arguments rejected and state isolation checked.
- Connor schema/docstring replay and all P7-P10 response differences checked; original docstrings match source records.
- Connor synthetic read/disclosure checked; shell requests are recorded without execution.
- All 100 InjecAgent attack texts match distinct original base dataset records.
- AgentDojo has 100 distinct task/attack combinations across 10 source tasks, not 100 independent tasks.
- Case selection 100 validated for all three suites.
- Source provenance validated through pinned-record membership and recorded source hashes where provided.
- Python syntax checked. Original fixture bytes compared with the earlier advisor ZIP.

Interpretation boundaries:

- Offline simulated attacks establish adapter behavior, not agent attack success.
- Connor is a surface replay, not original-server execution; implementation/configuration compromise is not evaluated. P17-P19 excluded.
- Exact task correctness and attacker objective achievement still require review.
- Some InjecAgent actions may exceed bounded mock semantics; those runs are explicitly inconclusive.
- See README.md before calculating rates. Shared tasks and components are not independent observations.
