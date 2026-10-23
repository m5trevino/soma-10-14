"""Extract lean, single-value metadata from session source files.

Scans a session directory, reads all chatset .json files and session.json,
pulls `extraction_output.extracted` fields, and returns them as:

  - Single values  : domain, sub_domain, sentiment, idea_maturity,
                     content_type, emotional_tone  (top frequency wins)
  - String arrays  : project_context (keywords only), topics

Also pulls `ask_user` tool calls and `linked_code_blocks` anchors.

Output is a lean JSON suitable for quick scanning and Soma hand-off.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from collections import Counter

# Fields to aggregate into frequency maps (top value = the "single" value)
FREQ_FIELDS = [
    "sentiment",
    "idea_maturity",
    "content_type",
    "emotional_tone",
    "sub_domain",
]

# Fields that are always the single last value seen (not aggregated)
SCAN_FIELDS = ["domain"]


def _is_project_keyword(text: str) -> bool:
    """Return True if text looks like a project keyword, not a file/path."""
    text = text.strip()
    if not text:
        return False
    # Exclude anything that looks like a file path or file name
    if "/" in text or "\\" in text:
        return False
    # Exclude common file extensions
    FILE_EXTS = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".html", ".css",
        ".md", ".txt", ".log", ".env", ".yml", ".yaml", ".toml", ".cfg",
        ".ini", ".db", ".sqlite", ".sql", ".sh", ".bat", ".ps1",
        ".rb", ".go", ".rs", ".java", ".cpp", ".c", ".h", ".hpp",
        ".css", ".scss", ".less", ".vue", ".svelte",
    }
    if any(text.lower().endswith(ext) for ext in FILE_EXTS):
        return False
    # Exclude paths that look like node_modules, src/, components/, utils/
    if text.lower().startswith(("node_modules", "src/", "components/", "utils/", "lib/")):
        return False
    return True


def extract_session_metadata(session_dir: str | Path) -> dict:
    """Build lean metadata for a single session.

    Parameters
    ----------
    session_dir : str or Path
        Path to the session directory (contains session.json + NNNNN.json files).

    Returns
    -------
    dict
        Lean metadata dict matching the Soma export schema.
    """
    session_dir = Path(session_dir).resolve()
    if not session_dir.is_dir():
        raise FileNotFoundError(f"session directory not found: {session_dir}")

    # ── Read session.json for top-level metadata ────────────────────────
    session_json_path = session_dir / "session.json"
    session_id = session_dir.name
    provider = ""
    total_sets = 0
    total_chars = 0

    if session_json_path.exists():
        try:
            sj = json.loads(session_json_path.read_text())
            session_id = sj.get("session_id", session_id)
            provider = sj.get("provider", "")
            total_sets = sj.get("total_sets", 0)
            total_chars = sj.get("total_session_chars", 0)
        except (json.JSONDecodeError, OSError):
            pass

    # ── Collect extraction output from every chatset .json ───────────────
    freq_counters: dict[str, Counter] = {f: Counter() for f in FREQ_FIELDS}
    domain_value = ""
    tool_calls: list[dict] = []
    anchors: list[dict] = []
    json_file_list: list[str] = []
    pc_counter: Counter = Counter()   # project context keyword -> count

    chatset_files = sorted(
        f for f in session_dir.iterdir()
        if f.is_file()
        and f.suffix == ".json"
        and f.name != "session.json"
        and not f.name.startswith("tool-")
    )

    for cf in chatset_files:
        json_file_list.append(cf.name)
        try:
            data = json.loads(cf.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        # ── extraction_output.extracted ────────────────────────────────
        eo = data.get("extraction_output")
        if not isinstance(eo, dict):
            continue
        extracted = eo.get("extracted")
        if not isinstance(extracted, dict):
            continue

        # Scan fields — last value wins
        for f in SCAN_FIELDS:
            v = extracted.get(f)
            if v and isinstance(v, str):
                domain_value = v

        # Frequency fields — count occurrences
        for f in FREQ_FIELDS:
            v = extracted.get(f)
            if v and isinstance(v, str):
                freq_counters[f][v] += 1

        # topics — collect unique keywords
        topics = extracted.get("topics", [])
        if isinstance(topics, list):
            for t in topics:
                if isinstance(t, str) and t:
                    freq_counters["topics"] = freq_counters.get("topics", Counter())
                    freq_counters["topics"][t] += 1

        # ── linked_tool_calls → "ask_user" ─────────────────────────────
        tcs = data.get("linked_tool_calls", [])
        if isinstance(tcs, list):
            for tc in tcs:
                if not isinstance(tc, dict):
                    continue
                if tc.get("tool_name") == "ask_user":
                    tool_calls.append({
                        "question": tc.get("arguments", {}).get("question", tc.get("question", "")),
                        "context_set": tc.get("set_number", ""),
                        "provider": tc.get("provider", ""),
                    })

        # ── linked_code_blocks → anchors ───────────────────────────────
        cbs = data.get("linked_code_blocks", [])
        if isinstance(cbs, list):
            for cb in cbs:
                if not isinstance(cb, dict):
                    continue
                anchors.append({
                    "file": cb.get("file", cb.get("path", "")),
                    "snippet": cb.get("snippet", cb.get("content", ""))[:200],
                    "set_number": cb.get("set_number", ""),
                })

    # ── project_context — keywords only, no file paths ─────────────────
    for cf in chatset_files:
        try:
            data = json.loads(cf.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        eo = data.get("extraction_output")
        if not isinstance(eo, dict):
            continue
        extracted = eo.get("extracted")
        if not isinstance(extracted, dict):
            continue
        for pc in extracted.get("project_context", []):
            if isinstance(pc, str) and _is_project_keyword(pc):
                pc_counter[pc] += 1

    # ── Build single-value fields (top frequency wins) ─────────────────
    def _top(freq_map: Counter) -> str:
        """Return the most common value, or empty string."""
        if not freq_map:
            return ""
        return freq_map.most_common(1)[0][0]

    # ── Build arrays ──────────────────────────────────────────────────
    project_context_keywords = [k for k, _ in pc_counter.most_common()]
    topics_list = [k for k, _ in freq_counters.get("topics", Counter()).most_common()]

    # ── Assemble result ────────────────────────────────────────────────
    result = {
        "session_id": session_id,
        "provider": provider,
        "total_sets": total_sets,
        "total_session_chars": total_chars,
        "file_count": len(chatset_files),
        "anchors": anchors,
        "tool_calls": tool_calls,
        "metadata": {
            "domain": domain_value,
            "sub_domain": _top(freq_counters["sub_domain"]),
            "project_context": project_context_keywords,
            "topics": topics_list,
            "sentiment": _top(freq_counters["sentiment"]),
            "idea_maturity": _top(freq_counters["idea_maturity"]),
            "content_type": _top(freq_counters["content_type"]),
            "emotional_tone": _top(freq_counters["emotional_tone"]),
        },
        "json_file_list": json_file_list,
    }

    return result


def write_metadata(session_dir: str | Path, output_path: str | Path | None = None) -> dict:
    """Extract metadata and write to a JSON file.

    If output_path is None, writes next to session.json as <session_id>.meta.json.
    Returns the metadata dict.
    """
    meta = extract_session_metadata(session_dir)
    if output_path is None:
        sj = Path(session_dir) / "session.json"
        if sj.exists():
            try:
                sid = json.loads(sj.read_text()).get("session_id", Path(session_dir).name)
            except Exception:
                sid = Path(session_dir).name
        else:
            sid = Path(session_dir).name
        output_path = Path(session_dir) / f"{sid}.meta.json"
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(meta, indent=2, default=str))
    return meta


# ── CLI: run against a single session or an entire vault ──────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python session_metadata.py <session_dir_or_vault> [output_dir]")
        print()
        print("  Single session:  python session_metadata.py /path/to/session")
        print("  Full vault:      python session_metadata.py /path/to/vault")
        sys.exit(1)

    target = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    if target.is_file() and target.name == "session.json":
        target = target.parent

    if target.is_dir() and (target / "session.json").exists():
        # Single session
        meta = write_metadata(target, output_dir)
        print(f"Wrote metadata for: {meta['session_id']}")
        print(f"  Provider: {meta['provider']}")
        print(f"  Sets: {meta['total_sets']} | Chars: {meta['total_session_chars']:,}")
        print(f"  Files: {meta['file_count']} | Anchors: {len(meta['anchors'])} | Tool calls: {len(meta['tool_calls'])}")
        md = meta["metadata"]
        print(f"  Domain: {md['domain']} | Sub-domain: {md['sub_domain']}")
        print(f"  Sentiment: {md['sentiment']} | Maturity: {md['idea_maturity']}")
        print(f"  Topics ({len(md['topics'])}): {', '.join(md['topics'][:5])}")
        print(f"  Project keywords ({len(md['project_context'])}): {', '.join(md['project_context'][:5])}")
    elif target.is_dir():
        # Full vault — batch mode
        sessions = sorted(d for d in target.iterdir() if (d / "session.json").exists())
        if not sessions:
            print(f"No session directories found under {target}")
            sys.exit(1)
        print(f"Processing {len(sessions)} sessions...")
        for s in sessions:
            try:
                meta = write_metadata(s, output_dir)
                sid = meta["session_id"]
                md = meta["metadata"]
                print(f"  ✓ {sid} | sets={meta['total_sets']} | domain={md['domain']} | sentiment={md['sentiment']}")
            except Exception as e:
                print(f"  ✗ {s.name}: {e}")
    else:
        print(f"Path not found: {target}")
        sys.exit(1)
