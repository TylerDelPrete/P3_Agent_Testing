# Verification

- Three evidence evaluator tests passed: missing evidence, change/false-alert counting, and conflicting evidence.
- Offline run exercised the actual native plugin across baseline, denied search, and unchanged control: 1/1 seeded change detected; 0/1 false alerts; 3/3 claims supported. These are SIMULATED results, not model findings.
- Installed OpenClaw accepted all three generated configurations.
- Live execution attempted; this editing session blocks loopback model requests with WinError 10013. All three live claims were unknown and the runner returned a failing exit code, as intended.
- Run RUN_PILOT.cmd from your Windows desktop with LM Studio running to verify actual agent execution.
- Original source project was not modified. Copied data has per-file hashes in data/COPY_PROVENANCE.json.
