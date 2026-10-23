# Falcon — Open Questions
TARGET: falcon | RUN: 20261022T141811Z-c590af | DATE: 2026-10-22T14:18Z

## O-01: tb-009-falcon.md missing
**Question:** Is machinetalk/tb-009-falcon.md present on disk? The fleet.py FLEET list references it at line 59 but tree output showed a gap between tb-008-spark.md and tb-010-eagle.md.
**Evidence needed:** `ls -la machinetalk/tb-009-falcon.md`
**Risk:** If missing, load_system_prompt("falcon") in engine.py will raise FileNotFoundError.

## O-02: rotator always None
**Question:** Why does __init__ accept a rotator parameter but run() never uses it?
**Evidence needed:** Review git history for rotator usage; check if any caller passes a non-None rotator.
**Impact:** Dead code or incomplete retry implementation.

## O-03: complete_stage imports from drafter_dendrite
**Question:** complete_stage() imports LLMClient and LLMResponse from pipeline.drafter_dendrite rather than a shared interface module.
**Evidence needed:** Verify LLMClient/LLMResponse are defined only in drafter_dendrite; check for circular import risk.
**Impact:** Refactoring drafter_dendrite may break complete_stage.

## O-04: SomaBridge vs FalconDendrite ID divergence
**Question:** Do SomaBridge.write_falcon() and FalconDendrite.run() ever operate on the same Soma instance?
**Evidence needed:** Trace call paths to confirm mutual exclusivity.
**Impact:** If both execute on the same session, stale nodes may coexist.

## O-05: Contract error downstream impact
**Question:** What happens when _build_contract_from_constraints() returns an error? The architecture node is created but the contract node and LOCKS edge are not. Does eagle still run?
**Evidence needed:** Check eagle's checkpoint readiness logic for contract/LOCKS edge dependency.
**Impact:** Silent failure — architecture exists but is not contract-locked.

## O-06: No unit test for run()
**Question:** test_tb_fix_001.py only tests create_constrained_by(). The full run() method (50-154) has no dedicated unit test.
**Evidence needed:** Confirm no other test file covers run().
**Impact:** Integration-only testing; regression risk for run() logic.

## O-07: Prompt file not in tree output
**Question:** machinetalk/tb-009-falcon.md was not listed in tree output for machinetalk/ directory (which showed up to tb-008-spark.md then jumped to tb-010-eagle.md).
**Evidence needed:** `cat machinetalk/tb-009-falcon.md`
**Impact:** If missing, fleet.py:59 entry is dead; if present but tree missed it, tree output may have been truncated.
