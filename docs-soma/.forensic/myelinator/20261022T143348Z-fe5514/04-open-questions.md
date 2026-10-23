# Open Questions — Myelinator Forensic Deep Dive

TARGET: myelinator | RUN: 20261022T143348Z-fe5514

## Q-01: ToolRegistry — intentional stub or missing implementation?
`ToolRegistry.call()` always returns `ok=False`. The LLM match path (lines 100-107) attempts `create_soma_edge` tool calls but they always fail. Is this intentional (LLM matching is deprecated, deterministic overlap is the only path), or is ToolRegistry supposed to be implemented but is not yet?

## Q-02: LLM response structure during actual pipeline runs
The `_call_match_llm()` method assumes `response.tool_calls` is present and iterable. Is there evidence from pipeline execution logs that LLM responses actually contain tool_calls, or is this path never exercised?

## Q-03: SessionManifestNode persistence
`_write_manifest()` creates a SessionManifestNode with cleartext PINs as JSON. Is this node stored in an in-memory-only Soma graph, or is it persisted to disk/database? If persisted, cleartext PINs are at rest.

## Q-04: Matching algorithm precision
The deterministic text overlap uses substring matching (any lowered needle in lowered inv_text). What is the precision/recall of this approach? Are there known false-positive or false-negative cases documented?

## Q-05: SaltatoryGate verification dependency
`run_pipeline.py` line 5 references "Integrity check: VerifiedNodes count == OptimizedSlots count" and the SESSION_HANDOFF.md references SaltatoryGate as a verification gate between Myelinator and CodePublisher. How does SaltatoryGate consume OptimizedSlot output from myelinator?

## Q-06: Why the soma-grok duplicate
`soma-grok/soma/myelinator_olc.py` has the same content but a newer mtime (Oct 21 vs Oct 17). Is soma-grok a production/canonical copy, a development branch, or a backup? Which authority should be treated as the source of truth?
