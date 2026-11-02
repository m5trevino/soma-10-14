"""TB-DEND-021: NEXUS Dendrite (FIXED — stage_name → "nexus").

Synthesises a StrategicBlueprintNode from the session's DirectiveNode and
ConstraintNode signals via LLM.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from store import Soma

try:  # run from soma/: `soma` is the inner package (soma/soma)
    from soma.helpers import get_receptor_config
except ImportError:  # pytest imports the repo as `soma`: soma.soma is inner
    from soma.soma.helpers import get_receptor_config

try:  # run from soma/: `machinetalk` is the sibling package
    from machinetalk.hashes import (JOURNAL_CONTRACT, JournalNonceError,
                                    journal_hash_for, journal_nonce)
except ImportError:  # pytest imports the repo as `soma`: soma.machinetalk
    from soma.machinetalk.hashes import (JOURNAL_CONTRACT, JournalNonceError,
                                         journal_hash_for, journal_nonce)

from pipeline.stage_complete import complete_stage


_DEFAULT_NEXUS_INSTRUCTION = (
    "You are the Nexus Dendrite. Review the directives and constraints "
    "below and synthesise a strategic blueprint. Return a JSON object:\n"
    '  {"blueprint_text": str, "directives_used": int, "constraints_used": int}\n'
    "Return ONLY the JSON object. No prose, no markdown, no explanation."
)


class NexusDendrite:
    """Active NEXUS — strategic blueprint synthesis."""

    def __init__(self, soma: Soma, llm_client: Any) -> None:
        self._soma = soma
        self._llm = llm_client

    def run(self, session_id: str) -> dict[str, Any]:
        """Create a StrategicBlueprintNode via LLM."""
        start = time.monotonic()
        # FIXED: "nexus" instead of undefined stage_name
        stage_name = "nexus"

        directives = [
            n for n in self._soma.query_by_type("DirectiveNode")
            if n.properties.get("session_id") == session_id
        ]
        constraints = [
            n for n in self._soma.query_by_type("ConstraintNode")
            if n.properties.get("session_id") == session_id
        ]

        # Build payload from signal source text
        parts: list[str] = []
        for d in directives:
            parts.append(d.properties.get("source_text", ""))
        for c in constraints:
            parts.append(c.properties.get("source_text", ""))
        payload = "\n".join(p for p in parts if p) or f"Session {session_id}: no directive or constraint signals"

        # Load ReceptorConfig instruction body
        config = get_receptor_config(self._soma, "nexus")
        instruction_body = (
            config.get("instruction_body", _DEFAULT_NEXUS_INSTRUCTION)
            if config else _DEFAULT_NEXUS_INSTRUCTION
        )

        # Call complete_stage
        stage_result = complete_stage(
            self._llm, stage_name, instruction_body, payload,
        )

        if not stage_result["ok"]:
            elapsed_ms = (time.monotonic() - start) * 1000
            return {
                "session_id": session_id,
                "error": stage_result["error"],
                "metrics": stage_result["metrics"],
            }

        result = stage_result["result"]
        blueprint_text = result.get("blueprint_text", "")
        if not blueprint_text:
            blueprint_text = payload

        blueprint_id = f"blueprint-{session_id}"
        # Overwrite: delete existing blueprint before creating fresh one
        existing = self._soma.get_node(blueprint_id)
        if existing:
            self._soma.delete_node(blueprint_id)
        self._soma.create_node("StrategicBlueprintNode", {
            "id": blueprint_id,
            "session_id": session_id,
            "blueprint_text": blueprint_text,
            "directive_count": result.get("directives_used", len(directives)),
            "constraint_count": result.get("constraints_used", len(constraints)),
        })
        # LINEAGE: link blueprint back to its input signals
        for d in directives:
            self._soma.create_edge(blueprint_id, "STRATEGIC_PLAN", d.id)
        for c in constraints:
            self._soma.create_edge(blueprint_id, "CONSTRAINED_BY", c.id)

        return {
            "session_id": session_id,
            "blueprint_id": blueprint_id,
            "directive_count": len(directives),
            "constraint_count": len(constraints),
            "metrics": stage_result["metrics"],
        }


# ── TB-INTRO-003: introbeaver entities → graph nodes (node create only) ──
#
# Reads the four introbeaver entity files and creates exactly one ``Entity``
# node per entity.  No edges are created, no checkpoint is written and the
# engine/LLM is never called.

ENTITY_NODE_TYPE = "Entity"

# filename → (entity_type used when a record states none, wrapper dict keys)
ENTITY_FILES: dict[str, tuple[str, tuple[str, ...]]] = {
    "soma_introbeaver_persons.json": (
        "PERSON", ("persons", "people", "entities", "items", "results")),
    "soma_introbeaver_orgs.json": (
        "ORG", ("orgs", "organisations", "organizations", "entities",
                "items", "results")),
    "soma_introbeaver_documents.json": (
        "DOCUMENT", ("documents", "docs", "entities", "items", "results")),
    "soma_introbeaver_events.json": (
        "EVENT", ("events", "entities", "items", "results")),
}

_NAME_KEYS = ("entity_name", "name", "title", "label")
_TYPE_KEYS = ("entity_type", "type", "kind", "category")
_CONTENT_KEYS = ("content", "description", "summary", "text", "detail", "value")


class EntityInputMissing(RuntimeError):
    """None of the four introbeaver entity files exist — nothing to store."""


@dataclass
class EntityInput:
    """What ``load_entity_rows`` found on disk and normalised."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    present: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    invalid: int = 0


def _as_text(value: Any) -> str:
    """Flatten a JSON value to the string stored in the node property."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _pick(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    """First non-empty string among ``keys``; empty string when none."""
    for key in keys:
        text = _as_text(row.get(key))
        if text:
            return text
    return ""


def _entity_props(name: str, entity_type: str, content: str,
                  source_file: str) -> dict[str, Any]:
    return {
        "entity_name": name,
        "entity_type": entity_type,
        "content": content,
        "source_file": source_file,
    }


def normalise_entity(raw: Any, default_entity_type: str,
                     source_file: str) -> dict[str, Any] | None:
    """Map one raw entity record to node properties.

    Returns ``None`` when the record carries no usable name — such a record
    is skipped and counted as invalid rather than given a invented name.
    Bare strings (``["Alice"]``) are accepted as name-only entities.  The
    entity type comes from the file the entity was listed in unless the
    record states one itself.
    """
    if isinstance(raw, str):
        name = raw.strip()
        if not name:
            return None
        return _entity_props(name, default_entity_type, name, source_file)
    if not isinstance(raw, dict):
        return None
    name = _pick(raw, _NAME_KEYS)
    if not name:
        return None
    entity_type = _pick(raw, _TYPE_KEYS) or default_entity_type
    content = _pick(raw, _CONTENT_KEYS)
    return _entity_props(name, entity_type.upper(), content, source_file)


def _rows_from_payload(payload: Any, default_entity_type: str,
                       source_file: str,
                       wrapper_keys: tuple[str, ...]) -> tuple[list[dict[str, Any]], int]:
    """Normalise a file payload; returns (rows, invalid_count).

    Accepts a bare list, a wrapper dict (``{"persons": [...]}``) or a
    single bare entity object.
    """
    if isinstance(payload, list):
        candidates: list[Any] = payload
    elif isinstance(payload, dict):
        candidates = [payload]
        for key in wrapper_keys:
            if isinstance(payload.get(key), list):
                candidates = payload[key]
                break
    else:
        return [], 1

    rows: list[dict[str, Any]] = []
    invalid = 0
    for raw in candidates:
        props = normalise_entity(raw, default_entity_type, source_file)
        if props is None:
            invalid += 1
        else:
            rows.append(props)
    return rows, invalid


def load_entity_rows(directory: str | Path = "/tmp") -> EntityInput:
    """Read the four introbeaver entity files — and nothing else.

    Raises ``ValueError`` when a file exists but is not valid JSON.
    """
    base = Path(directory)
    loaded = EntityInput()
    for filename, (entity_type, wrapper_keys) in ENTITY_FILES.items():
        path = base / filename
        if not path.is_file():
            loaded.missing.append(filename)
            continue
        loaded.present.append(filename)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"{path}: unreadable entity file ({exc})") from exc
        rows, invalid = _rows_from_payload(payload, entity_type, filename,
                                           wrapper_keys)
        loaded.rows.extend(rows)
        loaded.invalid += invalid
    return loaded


def entity_node_id(session_id: str, entity_type: str, entity_name: str) -> str:
    """Stable id: re-running the slice upserts instead of duplicating."""
    key = f"soma.entity:{session_id}:{entity_type}:{entity_name.casefold()}"
    return uuid.uuid5(uuid.NAMESPACE_URL, key).hex


class IntrobeaverEntityWriter:
    """Creates one graph node per introbeaver entity — node create only."""

    def __init__(self, soma: Soma) -> None:
        self._soma = soma

    def run(self, session_id: str, directory: str | Path = "/tmp",
            dry_run: bool = False) -> dict[str, Any]:
        loaded = load_entity_rows(directory)
        if not loaded.present:
            raise EntityInputMissing(
                "none of the introbeaver entity files exist in "
                f"{Path(directory)}: {', '.join(loaded.missing)}")

        node_ids: list[str] = []
        seen: set[tuple[str, str]] = set()
        duplicates = 0
        for row in loaded.rows:
            identity = (row["entity_type"], row["entity_name"].casefold())
            if identity in seen:
                duplicates += 1
                continue
            seen.add(identity)
            node_id = entity_node_id(session_id, row["entity_type"],
                                     row["entity_name"])
            if not dry_run:
                self._soma.create_node(ENTITY_NODE_TYPE, {
                    "id": node_id,
                    "session_id": session_id,
                    **row,
                })
            node_ids.append(node_id)

        saved_to = None if dry_run else self._soma.save()
        return {
            "session_id": session_id,
            "node_type": ENTITY_NODE_TYPE,
            "entity_files_present": loaded.present,
            "entity_files_missing": loaded.missing,
            "entities_read": len(loaded.rows),
            "entities_invalid": loaded.invalid,
            "duplicates_skipped": duplicates,
            "nodes_created": 0 if dry_run else len(node_ids),
            "node_ids": node_ids,
            "dry_run": dry_run,
            "saved_to": saved_to,
        }


# ── TB-PLAN-003: planbeaver plan items → graph nodes (node create only) ──
#
# Reads the planbeaver plan file and creates exactly one ``DirectivePlanNode``
# per plan item.  No edges are created, no checkpoint is written and the
# engine/LLM is never called.

PLAN_NODE_TYPE = "DirectivePlanNode"
PLAN_PATH = "/tmp/soma_planbeaver_plan.json"


def _plan_int(value: Any, index: int, field_name: str) -> int:
    """``priority`` as an int; a value that is not numeric is an error."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(
            f"plan item {index}: {field_name!r} must be an integer, "
            f"got {type(value).__name__}")
    try:
        return int(str(value).strip())
    except ValueError as exc:
        raise ValueError(
            f"plan item {index}: {field_name!r} is not an integer: {value!r}") from exc


def _plan_str_list(value: Any, index: int, field_name: str) -> list[str]:
    """A list of strings (names/ids), never guessed from a scalar."""
    if value is None:
        return []
    if isinstance(value, str) or not isinstance(value, list):
        raise ValueError(
            f"plan item {index}: {field_name!r} must be a list of strings")
    result: list[str] = []
    for entry in value:
        text = _as_text(entry)
        if not text:
            raise ValueError(
                f"plan item {index}: {field_name!r} holds an empty entry")
        result.append(text)
    return result


def normalise_plan_item(raw: Any, index: int) -> dict[str, Any]:
    """Map one planbeaver plan item to ``DirectivePlanNode`` properties.

    A plan item without a ``type`` or ``description`` is rejected rather than
    given invented text: the node either carries the plan's own words or it is
    not written at all.  When the item states no ``id`` its position in the
    file becomes its stable identifier, so re-running against the same plan
    still upserts instead of duplicating.
    """
    if not isinstance(raw, dict):
        raise ValueError(
            f"plan item {index}: expected an object, got {type(raw).__name__}")
    plan_item_type = _as_text(raw.get("type"))
    if not plan_item_type:
        raise ValueError(f"plan item {index}: missing 'type'")
    description = _as_text(raw.get("description"))
    if not description:
        raise ValueError(f"plan item {index}: missing 'description'")
    if "priority" not in raw:
        raise ValueError(f"plan item {index}: missing 'priority'")
    if "dependencies" not in raw:
        raise ValueError(f"plan item {index}: missing 'dependencies'")
    return {
        "plan_item_id": _as_text(raw.get("id")) or f"PLAN-ITEM-{index}",
        "plan_item_type": plan_item_type,
        "description": description,
        "priority": _plan_int(raw.get("priority"), index, "priority"),
        "dependencies": _plan_str_list(
            raw.get("dependencies"), index, "dependencies"),
        "source_ref": _as_text(raw.get("source_ref")),
        "consumers": _plan_str_list(raw.get("consumers"), index, "consumers"),
        "session_id": _as_text(raw.get("session_id")),
        "nonce": _as_text(raw.get("nonce")),
        "plan_id": _as_text(raw.get("plan_id")),
        "chatset_hash": _as_text(raw.get("chatset_hash")),
    }


def plan_node_id(session_id: str, plan_item_id: str) -> str:
    """Stable id: re-running the slice upserts instead of duplicating."""
    key = f"soma.directive_plan:{session_id}:{plan_item_id}"
    return uuid.uuid5(uuid.NAMESPACE_URL, key).hex


class PlanInputMissing(RuntimeError):
    """The planbeaver plan file does not exist — nothing to store."""


@dataclass
class PlanInput:
    """What ``load_plan_items`` read: normalised items plus plan-wide values."""

    items: list[dict[str, Any]] = field(default_factory=list)
    session_id: str = ""
    plan_id: str = ""
    chatset_hash: str = ""
    nonce: str = ""


def _single_value(items: list[dict[str, Any]], key: str) -> str:
    """The one non-empty value of ``key`` across ``items`` ('' when none).

    Two different values mean the file mixes plans/sessions/nonces, which
    would make the stored nodes mutually inconsistent — that is an error.
    """
    values = sorted({item[key] for item in items if item[key]})
    if len(values) > 1:
        raise ValueError(
            f"plan items disagree on {key!r}: {', '.join(values[:4])}"
            f"{' …' if len(values) > 4 else ''}")
    return values[0] if values else ""


def load_plan_items(path: str | Path = PLAN_PATH) -> PlanInput:
    """Read and normalise the planbeaver plan file — and nothing else.

    Raises ``PlanInputMissing`` when the file is absent and ``ValueError``
    when it is unreadable, not a JSON array, or holds an unusable item.
    """
    plan_path = Path(path)
    if not plan_path.is_file():
        raise PlanInputMissing(
            f"planbeaver plan file not found: {plan_path}")
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{plan_path}: unreadable plan file ({exc})") from exc
    if not isinstance(payload, list):
        raise ValueError(
            f"{plan_path}: expected a list of plan items, "
            f"got {type(payload).__name__}")

    loaded = PlanInput(items=[normalise_plan_item(raw, i)
                             for i, raw in enumerate(payload)])
    loaded.session_id = _single_value(loaded.items, "session_id")
    loaded.plan_id = _single_value(loaded.items, "plan_id")
    loaded.chatset_hash = _single_value(loaded.items, "chatset_hash")
    loaded.nonce = _single_value(loaded.items, "nonce")
    return loaded


class PlanbeaverPlanNodeWriter:
    """Creates one ``DirectivePlanNode`` per plan item — node create only."""

    def __init__(self, soma: Soma) -> None:
        self._soma = soma

    def run(self, session_id: str | None = None,
            plan_path: str | Path = PLAN_PATH,
            dry_run: bool = False,
            plan: PlanInput | None = None) -> dict[str, Any]:
        loaded = plan if plan is not None else load_plan_items(plan_path)
        if not session_id:
            session_id = loaded.session_id
        elif loaded.session_id and session_id != loaded.session_id:
            raise ValueError(
                f"--session-id {session_id!r} does not match the plan's "
                f"session_id {loaded.session_id!r}")
        if not session_id:
            raise ValueError(
                "no session_id: the plan items carry none and none was given")

        node_ids: list[str] = []
        seen: set[str] = set()
        duplicates = 0
        for item in loaded.items:
            plan_item_id = item["plan_item_id"]
            if plan_item_id in seen:
                duplicates += 1
                continue
            seen.add(plan_item_id)
            node_id = plan_node_id(session_id, plan_item_id)
            if not dry_run:
                self._soma.create_node(PLAN_NODE_TYPE, {
                    "id": node_id,
                    "session_id": session_id,
                    "plan_id": loaded.plan_id or item["plan_id"],
                    "plan_item_id": plan_item_id,
                    "plan_item_type": item["plan_item_type"],
                    "description": item["description"],
                    "priority": item["priority"],
                    "dependencies": item["dependencies"],
                    "source_ref": item["source_ref"],
                    "consumers": item["consumers"],
                    "chatset_hash": loaded.chatset_hash or item["chatset_hash"],
                    "nonce": loaded.nonce or item["nonce"],
                })
            node_ids.append(node_id)

        saved_to = None if dry_run else self._soma.save()
        return {
            "session_id": session_id,
            "plan_id": loaded.plan_id,
            "nonce": loaded.nonce,
            "node_type": PLAN_NODE_TYPE,
            "plan_items_read": len(loaded.items),
            "duplicates_skipped": duplicates,
            "nodes_created": 0 if dry_run else len(node_ids),
            "node_ids": node_ids,
            "dry_run": dry_run,
            "saved_to": saved_to,
        }


def plan_main(argv: list[str] | None = None) -> int:
    """CLI: store planbeaver plan items as ``DirectivePlanNode`` nodes.

    Node create only: no edges, no checkpoint, no engine call.  Prints the
    supplied nonce and ``nodes: <n>`` on stdout.
    """
    parser = argparse.ArgumentParser(
        description="TB-PLAN-003 — create one DirectivePlanNode per "
                    "planbeaver plan item. Node create only: no edges, no "
                    "checkpoint, no engine call.")
    parser.add_argument("--plan", default=PLAN_PATH,
                        help=f"planbeaver plan file (default: {PLAN_PATH})")
    parser.add_argument("--session-id", default=None,
                        help="session the plan belongs to "
                             "(default: taken from the plan items)")
    parser.add_argument("--store", default=None,
                        help="graph store path "
                             "(default: somas/<session_id>/soma.json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="read and validate only; write nothing")
    args = parser.parse_args(argv)

    try:
        plan = load_plan_items(args.plan)
    except PlanInputMissing as exc:
        print(json.dumps({"ok": False, "error": "PLAN_INPUT_MISSING",
                          "detail": str(exc), "nodes_created": 0}, indent=2))
        return 1
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": "PLAN_INPUT_INVALID",
                          "detail": str(exc), "nodes_created": 0}, indent=2))
        return 2

    session_id = args.session_id or plan.session_id
    if not session_id:
        print(json.dumps({"ok": False, "error": "PLAN_SESSION_MISSING",
                          "detail": "plan items carry no session_id",
                          "nodes_created": 0}, indent=2))
        return 2
    store_path = args.store or str(
        Path(__file__).resolve().parent.parent / "somas" /
        session_id / "soma.json")

    soma = Soma() if args.dry_run else Soma(store_path)
    try:
        result = PlanbeaverPlanNodeWriter(soma).run(
            session_id, args.plan, dry_run=args.dry_run, plan=plan)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": "PLAN_INPUT_INVALID",
                          "detail": str(exc), "store": store_path,
                          "nodes_created": 0}, indent=2))
        return 2
    finally:
        soma.close()

    print(f"NONCE: {result['nonce']}")
    print(f"nodes: {result['nodes_created'] if not args.dry_run else len(result['node_ids'])}")
    print(json.dumps({"ok": True, "store": store_path, **result}, indent=2))
    return 0


# ── TB-OUTRO-003: outrobeaver journal → JournalNode (node create only) ──
#
# Reads ``/tmp/soma_outrobeaver_journal.json`` and creates exactly one
# ``JournalNode`` per journal event.  No edges are created, the engine/LLM is
# never called and no progress is rendered: the node write is the whole
# operation.  The journal hash is the canonical SHA-256 of the parsed journal
# (``hashes.journal_hash_for``); the same value is stamped on every node so a
# node can be traced back to the exact journal it came from.

JOURNAL_NODE_TYPE = "JournalNode"
JOURNAL_PATH = "/tmp/soma_outrobeaver_journal.json"


class JournalInputMissing(RuntimeError):
    """The outrobeaver journal file does not exist — nothing to store."""


class PriorJournalNonce(ValueError):
    """The graph already holds this session's journal under another nonce.

    Re-offering a different nonce would mix two runs' events under one
    session id, so the write is refused rather than overwriting the record.
    """


def _required_text(event: dict[str, Any], index: int, name: str) -> str:
    """A journal field that must be a non-empty string (never guessed)."""
    value = event.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"journal event {index}: missing {name!r}")
    return value.strip()


def _confidence(event: dict[str, Any], index: int) -> float:
    """``confidence`` as a float in 0..1; anything else is an error."""
    value = event.get("confidence")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"journal event {index}: 'confidence' must be a number, "
            f"got {type(value).__name__}")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ValueError(
            f"journal event {index}: 'confidence' {number} is outside 0..1")
    return number


def _turn_index(event: dict[str, Any], index: int) -> int:
    """``turn_index`` as an int; its position in the file when absent.

    The position is the same fallback ``normalise_plan_item`` uses for a plan
    item's id: the journal's own order is the only turn number available, and
    re-reading the same file yields the same one.
    """
    if "turn_index" not in event:
        return index
    value = event.get("turn_index")
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(
            f"journal event {index}: 'turn_index' must be an integer, "
            f"got {type(value).__name__}")
    try:
        return int(str(value).strip())
    except ValueError as exc:
        raise ValueError(
            f"journal event {index}: 'turn_index' is not an integer: "
            f"{value!r}") from exc


def _tool_calls(value: Any, index: int) -> list:
    """``tool_calls`` as a list; a missing value is an empty list."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(
            f"journal event {index}: 'tool_calls' must be a list")
    return list(value)


def normalise_journal_event(raw: Any, index: int) -> dict[str, Any]:
    """Map one journal event to ``JournalNode`` properties.

    The five fields the contract requires — ``session_id``, ``event_type``,
    ``timestamp``, ``source``, ``confidence`` — are taken from the event or
    the event is rejected: a node either carries the journal's own values or
    it is not written at all.
    """
    if not isinstance(raw, dict):
        raise ValueError(
            f"journal event {index}: expected an object, got "
            f"{type(raw).__name__}")
    event_id = _as_text(raw.get("event_id"))
    if not event_id:
        raise ValueError(f"journal event {index}: missing 'event_id'")
    return {
        "event_id": event_id,
        "entry_id": _as_text(raw.get("entry_id")),
        "session_id": _required_text(raw, index, "session_id"),
        "event_type": _required_text(raw, index, "event_type"),
        "timestamp": _required_text(raw, index, "timestamp"),
        "source": _required_text(raw, index, "source"),
        "confidence": _confidence(raw, index),
        "confidence_basis": _as_text(raw.get("confidence_basis")),
        "turn_index": _turn_index(raw, index),
        "state_delta": _as_text(raw.get("state_delta")),
        "content_hash": _as_text(raw.get("content_hash")),
        "content_hash_local": _as_text(raw.get("content_hash_local")),
        "content_hash_verified": bool(raw.get("content_hash_verified", False)),
        "nonce": _as_text(raw.get("nonce")),
        "chatset_hash": _as_text(raw.get("chatset_hash")),
        "tool_calls": _tool_calls(raw.get("tool_calls"), index),
    }


@dataclass
class JournalInput:
    """What ``load_journal`` read: normalised events plus journal-wide values."""

    contract: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    session_id: str = ""
    nonce: str = ""
    chatset_hash: str = ""
    journal_hash: str = ""


def load_journal(path: str | Path = JOURNAL_PATH,
                 nonce: str | None = None) -> JournalInput:
    """Read and normalise the outrobeaver journal — and nothing else.

    Raises ``JournalInputMissing`` when the file is absent, ``ValueError``
    when it is unreadable, is not a JSON object, declares a different
    contract, or holds an event that breaks the field contract, and
    ``JournalNonceError`` when the journal's nonces conflict or disagree with
    the supplied ``nonce``.
    """
    journal_path = Path(path)
    if not journal_path.is_file():
        raise JournalInputMissing(f"journal file not found: {journal_path}")
    try:
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{journal_path}: unreadable journal ({exc})") from exc
    if not isinstance(payload, dict):
        raise ValueError(
            f"{journal_path}: expected a journal object, got "
            f"{type(payload).__name__}")

    contract = _as_text(payload.get("contract"))
    if contract and contract != JOURNAL_CONTRACT:
        raise ValueError(
            f"{journal_path}: contract {contract!r} is not "
            f"{JOURNAL_CONTRACT!r}")

    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        raise ValueError(
            f"{journal_path}: 'events' must be a list, got "
            f"{type(raw_events).__name__}")
    loaded = JournalInput(
        contract=contract,
        events=[normalise_journal_event(raw, i)
                for i, raw in enumerate(raw_events)])
    loaded.session_id = _single_value(loaded.events, "session_id")
    loaded.chatset_hash = _single_value(loaded.events, "chatset_hash")
    header_session = _as_text(payload.get("session_id"))
    if header_session and loaded.session_id and header_session != loaded.session_id:
        raise ValueError(
            f"{journal_path}: header session_id {header_session!r} != "
            f"event session_id {loaded.session_id!r}")
    header_chatset = _as_text(payload.get("chatset_hash"))
    if (header_chatset and loaded.chatset_hash
            and header_chatset != loaded.chatset_hash):
        raise ValueError(
            f"{journal_path}: header chatset_hash {header_chatset!r} != "
            f"event chatset_hash {loaded.chatset_hash!r}")
    loaded.chatset_hash = loaded.chatset_hash or header_chatset
    loaded.nonce = journal_nonce(payload, nonce)
    loaded.journal_hash = journal_hash_for(payload)
    return loaded


def journal_node_id(session_id: str, event_id: str) -> str:
    """Stable id: re-running the slice upserts instead of duplicating."""
    key = f"soma.journal:{session_id}:{event_id}"
    return uuid.uuid5(uuid.NAMESPACE_URL, key).hex


class JournalNodeWriter:
    """Creates one ``JournalNode`` per outrobeaver journal event."""

    def __init__(self, soma: Soma) -> None:
        self._soma = soma

    def _existing_nonce(self, session_id: str) -> str:
        """The nonce already stored on this session's JournalNodes ('')."""
        nonces = {n.properties.get("nonce") or ""
                  for n in self._soma.query_session(JOURNAL_NODE_TYPE,
                                                    session_id)}
        return " ".join(sorted(n for n in nonces if n))

    def run(self, session_id: str | None = None,
            journal_path: str | Path = JOURNAL_PATH,
            dry_run: bool = False,
            journal: JournalInput | None = None,
            nonce: str | None = None) -> dict[str, Any]:
        loaded = journal if journal is not None else load_journal(journal_path,
                                                                  nonce)
        if nonce and loaded.nonce and nonce != loaded.nonce:
            raise JournalNonceError(
                f"supplied nonce {nonce} != journal nonce {loaded.nonce}")
        supplied_nonce = nonce or loaded.nonce
        if not supplied_nonce:
            raise JournalNonceError(
                "no nonce supplied and the journal carries none")
        if not session_id:
            session_id = loaded.session_id
        elif loaded.session_id and session_id != loaded.session_id:
            raise ValueError(
                f"--session-id {session_id!r} does not match the journal's "
                f"session_id {loaded.session_id!r}")
        if not session_id:
            raise ValueError(
                "no session_id: the journal events carry none and none was "
                "given")

        prior = self._existing_nonce(session_id)
        if prior and prior != supplied_nonce:
            raise PriorJournalNonce(
                f"nonce {supplied_nonce} rejected: this session's journal "
                f"nodes are already stored under prior nonce {prior}")

        node_ids: list[str] = []
        seen: set[str] = set()
        duplicates = 0
        for event in loaded.events:
            event_id = event["event_id"]
            if event_id in seen:
                duplicates += 1
                continue
            seen.add(event_id)
            node_id = journal_node_id(session_id, event_id)
            if not dry_run:
                self._soma.create_node(JOURNAL_NODE_TYPE, {
                    "id": node_id,
                    "session_id": session_id,
                    "event_id": event_id,
                    "entry_id": event["entry_id"],
                    "event_type": event["event_type"],
                    "timestamp": event["timestamp"],
                    "source": event["source"],
                    "confidence": event["confidence"],
                    "confidence_basis": event["confidence_basis"],
                    "turn_index": event["turn_index"],
                    "state_delta": event["state_delta"],
                    "content_hash": event["content_hash"],
                    "content_hash_local": event["content_hash_local"],
                    "content_hash_verified": event["content_hash_verified"],
                    "tool_calls": event["tool_calls"],
                    "nonce": supplied_nonce,
                    "chatset_hash": event["chatset_hash"] or loaded.chatset_hash,
                    "journal_contract": loaded.contract or JOURNAL_CONTRACT,
                    "journal_hash": loaded.journal_hash,
                })
            node_ids.append(node_id)

        saved_to = None if dry_run else self._soma.save()
        return {
            "session_id": session_id,
            "node_type": JOURNAL_NODE_TYPE,
            "journal_contract": loaded.contract or JOURNAL_CONTRACT,
            "journal_hash": loaded.journal_hash,
            "nonce": supplied_nonce,
            "chatset_hash": loaded.chatset_hash,
            "events_read": len(loaded.events),
            "duplicates_skipped": duplicates,
            "nodes_created": 0 if dry_run else len(node_ids),
            "node_ids": node_ids,
            "dry_run": dry_run,
            "saved_to": saved_to,
        }


def journal_main(argv: list[str] | None = None) -> int:
    """CLI: store outrobeaver journal events as ``JournalNode`` nodes.

    Node create only: no edges, no engine call, no progress rendering.  Prints
    ``NONCE:``, ``JOURNAL_HASH:`` and ``nodes: <n>`` on stdout.  Exits 0 on
    success, 1 when the journal is missing, 2 when the journal or its nonce is
    rejected.
    """
    parser = argparse.ArgumentParser(
        prog="python3 nexus_dendrite.py journal",
        description="TB-OUTRO-003 — create one JournalNode per outrobeaver "
                    "journal event. Node create only: no edges, no engine "
                    "call.")
    parser.add_argument("--journal", default=JOURNAL_PATH,
                        help=f"outrobeaver journal (default: {JOURNAL_PATH})")
    parser.add_argument("--session-id", default=None,
                        help="session the journal belongs to "
                             "(default: taken from the journal)")
    parser.add_argument("--store", default=None,
                        help="graph store path "
                             "(default: somas/<session_id>/soma.json)")
    parser.add_argument("--nonce", default=None,
                        help="supplied nonce (default: the journal's nonce)")
    parser.add_argument("--dry-run", action="store_true",
                        help="read and validate only; write nothing")
    args = parser.parse_args(argv)

    try:
        journal = load_journal(args.journal, args.nonce)
    except JournalInputMissing as exc:
        print(json.dumps({"ok": False, "error": "JOURNAL_INPUT_MISSING",
                          "detail": str(exc), "nodes_created": 0}, indent=2))
        return 1
    except JournalNonceError as exc:
        print(json.dumps({"ok": False, "error": "NONCE_REJECTED",
                          "detail": str(exc), "nodes_created": 0}, indent=2))
        return 2
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": "JOURNAL_INPUT_INVALID",
                          "detail": str(exc), "nodes_created": 0}, indent=2))
        return 2

    session_id = args.session_id or journal.session_id
    if not session_id:
        print(json.dumps({"ok": False, "error": "JOURNAL_SESSION_MISSING",
                          "detail": "journal events carry no session_id",
                          "nodes_created": 0}, indent=2))
        return 2
    store_path = args.store or str(
        Path(__file__).resolve().parent.parent / "somas" /
        session_id / "soma.json")

    soma = Soma() if args.dry_run else Soma(store_path)
    try:
        result = JournalNodeWriter(soma).run(
            session_id, args.journal, dry_run=args.dry_run, journal=journal,
            nonce=args.nonce)
    except PriorJournalNonce as exc:
        print(json.dumps({"ok": False, "error": "NONCE_REJECTED",
                          "detail": str(exc), "store": store_path,
                          "nodes_created": 0}, indent=2))
        return 2
    except JournalNonceError as exc:
        print(json.dumps({"ok": False, "error": "NONCE_REJECTED",
                          "detail": str(exc), "store": store_path,
                          "nodes_created": 0}, indent=2))
        return 2
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": "JOURNAL_INPUT_INVALID",
                          "detail": str(exc), "store": store_path,
                          "nodes_created": 0}, indent=2))
        return 2
    finally:
        soma.close()

    print(f"NONCE: {result['nonce']}")
    print(f"JOURNAL_HASH: {result['journal_hash']}")
    print(f"nodes: {result['nodes_created'] if not args.dry_run else len(result['node_ids'])}")
    print(json.dumps({"ok": True, "store": store_path, **result}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI: store introbeaver entities as graph nodes (node create only)."""
    parser = argparse.ArgumentParser(
        description="TB-INTRO-003 — create one graph node per introbeaver "
                    "entity. Node create only: no edges, no checkpoint.")
    parser.add_argument("--session-id", required=True,
                        help="session the entities belong to")
    parser.add_argument("--store", default=None,
                        help="graph store path "
                             "(default: somas/<session_id>/soma.json)")
    parser.add_argument("--entities-dir", default="/tmp",
                        help="directory holding the four entity files "
                             "(default: /tmp)")
    parser.add_argument("--dry-run", action="store_true",
                        help="read and validate only; write nothing")
    args = parser.parse_args(argv)

    store_path = args.store or str(
        Path(__file__).resolve().parent.parent / "somas" /
        args.session_id / "soma.json")

    soma = Soma() if args.dry_run else Soma(store_path)
    try:
        result = IntrobeaverEntityWriter(soma).run(
            args.session_id, args.entities_dir, dry_run=args.dry_run)
    except EntityInputMissing as exc:
        print(json.dumps({
            "ok": False,
            "error": "ENTITY_INPUT_MISSING",
            "detail": str(exc),
            "store": store_path,
            "nodes_created": 0,
        }, indent=2))
        return 1
    except ValueError as exc:
        print(json.dumps({
            "ok": False,
            "error": "ENTITY_INPUT_INVALID",
            "detail": str(exc),
            "nodes_created": 0,
        }, indent=2))
        return 2
    finally:
        soma.close()

    print(json.dumps({"ok": True, "store": store_path, **result},
                     indent=2))
    return 0


if __name__ == "__main__":
    # ``plan`` selects the plan-node writer, ``journal`` the journal-node
    # writer; every other argument set keeps the introbeaver entity writer's
    # CLI unchanged.
    _argv = sys.argv[1:]
    if _argv and _argv[0] == "plan":
        raise SystemExit(plan_main(_argv[1:]))
    if _argv and _argv[0] == "journal":
        raise SystemExit(journal_main(_argv[1:]))
    raise SystemExit(main())