# Wire-Up Guide: Soma → Session Picker Export Integration

## Purpose

This document tells you exactly how to wire Soma's runner to consume the JSON exported from the Session Picker.

---

## 1. Where the Export Goes

When you click **"Export N Favorites"** in the session picker, two things happen:

### A. Downloaded JSON file
- Filename: `soma_favorites_YYYY-MM-DD.json`
- Location: your browser's Downloads folder
- **This is the file you want to give to Soma**

### B. `data/soma_queue.json` (written automatically)
- Location: `/home/flintx/soma-10-14/data/soma_queue.json`
- Contains only session IDs (for the Soma runner queue mechanism)

---

## 2. The Exported JSON Structure

Each object in the exported array looks like this:

```json
{
  "session_id": "251201-mountmasterpro/12.01.25-copy",
  "provider": "aistudio",
  "total_sets": 13,
  "total_session_chars": 213264,
  "file_count": 69,
  "anchors": [
    {"file": "src/main.py", "snippet": "def process_queue(): ...", "set_number": "1"}
  ],
  "tool_calls": [
    {"question": "Should I proceed?", "context_set": "1", "provider": "aistudio"}
  ],
  "metadata": {
    "domain": "technical",
    "sub_domain": "software_development",
    "project_context": ["project", "debugging", "refactoring"],
    "topics": ["concurrency", "API routes", "file handling"],
    "sentiment": "ambitious",
    "idea_maturity": "developing",
    "content_type": "",
    "emotional_tone": ""
  },
  "json_file_list": ["17249.1.json", "17249.2.json", "17249.3.json"]
}
```

**Key fields for Soma:**
- `session_id` → identifies which session directory to process
- `metadata` → filtering, classification, analytics
- `anchors` → code block references for context
- `tool_calls` → ask_user questions from the session
- `json_file_list` → names of chatset JSON files to process

---

## 3. Wiring Soma's Runner

### Option A: Drop the Export Into Soma's Queue

If your runner already reads `data/soma_queue.json`, the export already writes there. No changes needed.

```bash
# 1. Pick favorites in the session picker
# 2. Click "Export N Favorites"
# 3. Run the Soma runner
python3 run_engine.py --queue data/soma_queue.json
```

### Option B: Consume the Full Export JSON Directly

Create or modify your runner script to load the full export:

```python
#!/usr/bin/env python3
"""
Soma runner — consumes Session Picker export JSON.
"""

import json
import sys
from pathlib import Path

def load_export(json_path: str) -> list[dict]:
    """Load exported favorites JSON."""
    with open(json_path) as f:
        return json.load(f)

def resolve_session_path(session_id: str, vault_path: str = "/media/storage/dendritic123/chat-logs/sessions") -> Path:
    """Resolve a session_id to its on-disk directory."""
    dir_name = session_id.split("/")[-1]
    candidate = Path(vault_path) / dir_name
    if candidate.exists():
        return candidate
    # Fallback: use session_id as-is
    candidate = Path(vault_path) / session_id
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"Session not found: {session_id} (tried {candidate})")

def run_session(session_data: dict, vault_path: str = "/media/storage/dendritic123/chat-logs/sessions"):
    """Process a single session from the export."""
    session_id = session_data["session_id"]
    meta = session_data["metadata"]
    
    # Resolve session directory
    session_dir = resolve_session_path(session_id, vault_path)
    
    # --- YOUR LOGIC HERE ---
    print(f"\n{'='*60}")
    print(f"Session: {session_id}")
    print(f"  Provider: {session_data['provider']}")
    print(f"  Sets: {session_data['total_sets']} | Chars: {session_data['total_session_chars']:,}")
    print(f"  Domain: {meta['domain']} | Sub: {meta['sub_domain']}")
    print(f"  Sentiment: {meta['sentiment']} | Maturity: {meta['idea_maturity']}")
    print(f"  Topics ({len(meta['topics'])}): {', '.join(meta['topics'][:5])}")
    print(f"  Project Context ({len(meta['project_context'])}): {', '.join(meta['project_context'][:5])}")
    print(f"  Anchors: {len(session_data['anchors'])}")
    print(f"  Tool Calls: {len(session_data['tool_calls'])}")
    
    # Process each chatset file
    for fname in session_data["json_file_list"]:
        chatset_path = session_dir / fname
        if chatset_path.exists():
            # ... load and process
            pass
    
    return session_dir

def main():
    # Default: use the auto-written queue file
    queue_path = Path.home() / ".soma_queue.json"
    
    # Or: specify the exported JSON directly
    if len(sys.argv) > 1:
        export_path = sys.argv[1]
    else:
        export_path = Path("/home/flintx/soma-10-14/data/soma_queue.json")
    
    if not export_path.exists():
        print(f"Error: {export_path} not found")
        sys.exit(1)
    
    # Load sessions from export
    if export_path.name.endswith(".json"):
        with open(export_path) as f:
            data = json.load(f)
        
        # Check if it's a queue file (has "selected" key) or export file (is a list)
        if isinstance(data, dict) and "selected" in data:
            # Queue format — just session IDs
            session_ids = data["selected"]
            sessions = session_ids
        elif isinstance(data, list):
            # Export format — full session objects
            sessions = data
    
    # Run each session
    for session in sessions:
        if isinstance(session, dict) and "session_id" in session:
            # Full session object
            run_session(session)
        else:
            # Session ID string — need to resolve
            session_id = session if isinstance(session, str) else session.get("session_id", "")
            if session_id:
                print(f"\nSkipping: {session_id} (not a full session object, need to resolve)")
                try:
                    resolve_session_path(session_id)
                    print(f"  ✓ Resolved: {resolve_session_path(session_id)}")
                except FileNotFoundError as e:
                    print(f"  ✗ {e}")

if __name__ == "__main__":
    main()
```

---

## 4. Wiring Session Filtering by Metadata

The exported JSON has full metadata for each session. You can filter before running:

```python
def filter_by_domain(sessions: list[dict], domain: str) -> list[dict]:
    return [s for s in sessions if s["metadata"]["domain"] == domain]

def filter_by_sentiment(sessions: list[dict], sentiment: str) -> list[dict]:
    return [s for s in sessions if s["metadata"]["sentiment"] == sentiment]

def filter_by_topic(sessions: list[dict], topic: str) -> list[dict]:
    return [s for s in sessions if topic in s["metadata"]["topics"]]

def filter_by_min_chars(sessions: list[dict], min_chars: int) -> list[dict]:
    return [s for s in sessions if s["total_session_chars"] >= min_chars]

def filter_by_set_count(sessions: list[dict], min_sets: int) -> list[dict]:
    return [s for s in sessions if s["total_sets"] >= min_sets]

# Usage:
export = load_export("soma_favorites_2026-10-18.json")
technical = filter_by_domain(export, "technical")
ambitious = filter_by_sentiment(export, "ambitious")
concurrent = filter_by_topic(export, "concurrency")
long_sessions = filter_by_min_chars(export, 100000)
```

---

## 5. Wiring Anchors and Tool Calls

### Processing Code Anchors

```python
def extract_anchors(sessions: list[dict]) -> list[dict]:
    """Gather all anchors across favorite sessions."""
    all_anchors = []
    for session in sessions:
        for anchor in session.get("anchors", []):
            all_anchors.append({
                "session_id": session["session_id"],
                "file": anchor["file"],
                "snippet": anchor["snippet"],
                "set_number": anchor["set_number"],
            })
    return all_anchors

# Use: show code context when processing a session
```

### Processing ask_user Questions

```python
def extract_questions(sessions: list[dict]) -> list[dict]:
    """Gather all ask_user questions across sessions."""
    questions = []
    for session in sessions:
        for tc in session.get("tool_calls", []):
            questions.append({
                "session_id": session["session_id"],
                "question": tc["question"],
                "set": tc["context_set"],
                "provider": tc["provider"],
            })
    return questions
```

---

## 6. Full End-to-End Workflow

```
Step 1: Browse sessions
  → ./soma-session-picker/start.sh
  → http://localhost:5174
  → Filter by domain, sentiment, topics
  → Check boxes on good sessions
  → Click "+ Add N to Favorites"
  → Repeat: browse more, add more favorites

Step 2: Export
  → Click ★ Favorites button
  → Review the list
  → Click "Export N Favorites"
  → File saved: ~/Downloads/soma_favorites_2026-10-18.json

Step 3: Process with Soma
  → python3 run_engine.py --queue data/soma_queue.json
  → OR: python3 run_engine.py /path/to/soma_favorites_2026-10-18.json
  
Step 4: Filter/analyze results
  → Load the export JSON in your analysis script
  → Filter by metadata fields
  → Process anchors, tool calls, etc.
```

---

## 7. File Locations Quick Reference

| Item | Location |
|------|----------|
| Session Picker UI | `http://localhost:5174` |
| Session Picker Backend | `soma-session-picker/backend/main.py` |
| Exported Favorites | `~/Downloads/soma_favorites_YYYY-MM-DD.json` |
| Queue File (auto-written) | `/home/flintx/soma-10-14/data/soma_queue.json` |
| Session Vault | `/media/storage/dendritic123/chat-logs/sessions/` |
| Session Metadata Source | `soma/machinetalk/session_metadata.py` |
| Cached Metadata | `soma-10-14/SESSION_DIR/*.meta.json` |
| Full Documentation | `soma-session-picker/DOCUMENTATION.md` |

---

## 8. Metadata Extraction

When the session picker first loads metadata for a session, it creates a cache file:

```
SESSIONS_PATH/
├── session-id-1/
│   ├── session.json
│   ├── 17249.1.json
│   ├── 17249.1.meta.json  ← extracted metadata (cached)
│   └── 17249.2.json
└── session-id-2/
    ├── session.json
    └── 17249.1.meta.json
```

This is read-only and auto-generated. You can also run extraction manually:

```bash
python3 soma/machinetalk/session_metadata.py /path/to/session
```

---

## Summary

The export JSON is the bridge. It contains everything Soma needs:
- `session_id` for locating the session
- `metadata` for filtering and classification
- `anchors` for code context
- `tool_calls` for ask_user questions
- `json_file_list` for processing the actual chatsets

Wire it into your runner and you're done.
