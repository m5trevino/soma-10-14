# Open Questions — soma (20261022T095652Z-3411e1)

U-01 Does the installed turnkey SDK retry/rotate models inside `run_stage`? The soma adapter makes exactly one call. Need `/home/flintx/.local/lib/python3.11/site-packages/turnkey/sdk.py:run_stage` under target `turn-key`.
U-02 Did stages 2–4 ever complete for any session? No `stage2/3/4` artifacts and no `session_stages` entries; check `/tmp/soma_out`, archives, and `soma-grok/`.
U-03 Why are 11 checkpoints frozen at `distiller: RUNNING`? Check system log around 2026-10-18T10:18Z or a controlled reproducer.
U-04 Do nexus/spark/falcon gate requirements (`plan_hash_verification`) match the prompt output contract? Need one captured stage-2 response.
U-05 Which queue path does the session picker write at runtime? Needs a picker-scoped run.
U-06 Has `--soma-only` ever been run against the live `soma/output` tree? It writes the same `soma.json` through the non-atomic store.
U-07 Is `soma-grok/` an archive or a live duplicate? Its `run_sessions.py` mtime is newer (2026-10-21T19:37Z).
U-08 Per-stage latency and token cost from this host to the model engine. Not measured; requires a real model call (write to remote service).
