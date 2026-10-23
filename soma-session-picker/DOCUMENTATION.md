# Soma Session Picker — Full Documentation

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Installation & Setup](#installation--setup)
4. [UI Usage](#ui-usage)
5. [API Endpoints](#api-endpoints)
6. [CLI / Command Line](#cli--command-line)
7. [Export JSON Format](#export-json-format)
8. [Soma Integration](#soma-integration)

---

## Overview

The **Soma Session Picker** is a standalone web application for browsing, filtering, and selecting AI chat sessions from your session vault. It extracts metadata from on-disk source files (no database dependency), lets you hand-pick sessions into a persistent favorites list, and exports a lean JSON file that Soma's runner can consume.

### What It Does

- **Browse** all sessions in your vault (1000+ sessions supported)
- **Filter** by domain, provider, model, score, set count, sub-domain, sentiment, topics, project context
- **Favorites** — accumulate sessions across browsing sessions, persist across browser reloads
- **Export** — download a lean metadata JSON for your selected/favorite sessions
- **Run Engine** — writes `data/soma_queue.json` so Soma's runner picks up your selection

### Key Features

- **No database dependency** — reads everything from `session.json` and chatset `.json` files on disk
- **On-demand extraction** — metadata computed from source files the first time a session is accessed, then cached as `.meta.json`
- **Persistent favorites** — stored in `localStorage`, survives browser refresh
- **Two-column layout** — metadata detail panel (right) for inspecting individual sessions
- **Frequency-based metadata** — sentiment, topic, and project context are tallied across all chatsets in the session

---

## Architecture

```
soma-session-picker/
├── backend/
│   ├── main.py          # FastAPI backend (session API, metadata extraction)
│   ├── db.py            # SQLite connection for dev_sessions table
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx              # Main app component
│   │   ├── components/
│   │   │   ├── SessionTable.jsx       # Session rows + checkboxes + fav stars
│   │   │   ├── FilterBar.jsx          # Search, filters, sort controls
│   │   │   ├── SessionMetaPanel.jsx   # Right sidebar — extracted metadata
│   │   │   ├── FavoritesPanel.css     # Favorites sidebar styles
│   │   │   └── StatusBar.jsx          # Bottom status bar
│   │   └── main.jsx
│   └── dist/            # Production build
├── start.sh             # One-command launcher (backend + frontend)
└── data/                # (optional) queue output
```

### Data Flow

```
Disk (session.json + chatset NNNNN.json)
    │
    ▼
soma/machinetalk/session_metadata.py  ← extracts metadata on first access
    │
    ▼
backend/main.py  ← serves /api/sessions, /api/session/{id}/metadata
    │
    ▼
frontend/  ← React/Vite UI, fetches sessions, lets you select/export
    │
    ▼
Export JSON  ← downloaded file with full metadata for selected sessions
    │
    ▼
data/soma_queue.json  ← also written for Soma runner
```

---

## Installation & Setup

### Prerequisites

- Python 3.11+
- Node.js 18+ (for frontend)
- SQLite3 (for dev_sessions table)

### Quick Start

```bash
cd /home/flintx/soma-10-14/soma-session-picker
./start.sh
```

This starts:
- **Backend** on `http://localhost:8001` (FastAPI + Uvicorn)
- **Frontend** on `http://localhost:5174` (Vite dev server)

### Manual Start

#### Backend

```bash
cd /home/flintx/soma-10-14/soma-session-picker/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8001
```

#### Frontend

```bash
cd /home/flintx/soma-10-14/soma-session-picker/frontend
npm install
npm run dev         # dev server
# or
npm run build       # production build → frontend/dist/
```

### Configuration

Set via environment variables or defaults:

| Variable | Default | Description |
|----------|---------|-------------|
| `SESSIONS_PATH` | `/media/storage/dendritic123/chat-logs/sessions` | Root directory containing session folders |
| `QUEUE_OUTPUT_PATH` | `~/.soma_queue.json` | Where selected sessions are saved |

---

## UI Usage

### Session Picker URL

Open `http://localhost:5174` in your browser.

### Layout

```
┌────────────────────────────────────────────────────────────────────┐
│  Soma Session Picker            [★ Favorites (5)] [+ Add 3 to Favs]│
├────────────────────────────────────────────────────────────────────┤
│  [Search] [Domain▼] [Sub-domain▼] [Sentiment▼] [Topics▼] ... [Refresh]│
├──────────────────────────────────────────┬─────────────────────────┤
│  Sessions Table (center)                 │ Favorites Panel (left)  │
│  ┌─────┬───┬──────┬──────┬──────┬─────┐ │  session-id-1 [tech]    │
│  │ ★   │ ☐ │ Name │ Score│ Sets │ ... │ │  session-id-2 [refl]    │
│  ├───┼───┼──────┼──────┼──────┼─────┤ │  session-id-3 [amb]     │
│  │ ☆ │ ☑ │ ...  │ 50k  │ 13   │ ... │ │         [✕ remove]      │
│  └─────┴───┴──────┴──────┴──────┴─────┤ │                         │
│                                        │                         │
├──────────────────────────────────────────┤                         │
│  [Export 5 Favorites]                    │ Metadata Panel (right)  │
├──────────────────────────────────────────┤                         │
│  Total: 1234 | Filtered: 50 | Selected: 5│ │ Domain: technical     │
└──────────────────────────────────────────┴─────────────────────────┘
```

### Step-by-Step Usage

#### 1. Browse & Filter Sessions

- **Search** — type a session ID, domain, or topic
- **Domain** — filter by top-level domain (e.g., "technical", "creative")
- **Sub-Domain** — filter by extracted sub-domain (e.g., "software_development")
- **Sentiment** — filter by extracted sentiment (e.g., "ambitious", "reflective")
- **Topics** — filter by any topic keyword (e.g., "concurrency")
- **Project Context** — filter by project keyword
- **Min Score / Min Sets** — filter by engagement metrics
- **Sort / Order** — change sort column and direction

#### 2. Select Sessions

- **Check boxes** on individual sessions
- **Select All** — check the header checkbox to select all visible sessions
- **Favorites Star (☆/★)** — click to add/remove a single session from favorites

#### 3. Add to Favorites

- After checking boxes, click **"+ Add N to Favorites"** in the header
- The **Favorites** button (★) opens the left sidebar showing all accumulated favorites
- Favorites persist in `localStorage` — they survive browser refreshes

#### 4. View Session Details

- **Click any session row** to open the right sidebar with full extracted metadata
- Shows: domain, sub-domain, sentiment, idea_maturity, topics, project_context keywords, anchors (code blocks), tool calls (ask_user questions)
- Click the same row again to close the panel

#### 5. Export Favorites

1. Open **Favorites panel** (★ button in header)
2. Review your accumulated list
3. Click **"Export N Favorites"**
4. Downloads `soma_favorites_YYYY-MM-DD.json`
5. This JSON is also written to `data/soma_queue.json` for Soma runner

#### 6. Remove Favorites

- In the Favorites panel, click **✕** on any session to remove it
- Favorites are also managed via the star button on session rows

---

## API Endpoints

All endpoints are at `http://localhost:8001/api/...`

### `GET /api/health`

```
GET http://localhost:8001/api/health
```

**Response:**
```json
{
  "status": "ok",
  "engine": "soma-session-picker"
}
```

---

### `GET /api/sessions`

Return the full session list with search, filter, and sort.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `search` | string | `""` | Substring match on session_id, title, domain, topics |
| `domain` | string | `""` | Exact match on domain |
| `provider` | string | `""` | Exact match on provider |
| `model` | string | `""` | Exact match on model |
| `min_score` | int | `0` | Minimum total_score |
| `max_score` | int | `0` | Maximum total_score |
| `min_sets` | int | `0` | Minimum chat set count |
| `sort` | string | `"score"` | One of: score, sets, name, provider, domain, date, functions |
| `order` | string | `"desc"` | "desc" or "asc" |
| `limit` | int | `500` | Maximum results returned |
| `meta_sub_domain` | string | `""` | Substring match on sub-domain metadata |
| `meta_sentiment` | string | `""` | Substring match on sentiment metadata |
| `meta_topics` | string | `""` | Substring match on topics metadata |
| `meta_project_context` | string | `""` | Substring match on project_context metadata |

**Response:**
```json
{
  "sessions": [
    {
      "session_id": "251201-mountmasterpro/12.01.25-copy",
      "total_score": 125430,
      "code_blocks": 45,
      "inline_code": 1200,
      "functions": 89,
      "chat_set_count": 13,
      "total_session_chars": 213264,
      "provider": "aistudio",
      "model": "gemini-2.0-flash",
      "date": "2025-12-01",
      "domain": "technical",
      "title": "Code Issues Resolution",
      "session_dir_name": "12.01.25-copy",
      "meta_sub_domain": "software_development",
      "meta_sentiment": "ambitious, reflective",
      "meta_topics": "concurrency, database interactions, API routes",
      "meta_project_context": "project, debugging, refactoring"
    }
  ],
  "total": 50
}
```

---

### `GET /api/sessions/counts`

Return distinct values for filter dropdowns.

**Response:**
```json
{
  "providers": ["aistudio", "anthropic", "openai"],
  "domains": ["technical", "creative", "analysis"],
  "models": ["gemini-2.0-flash", "claude-sonnet-4-20250514"],
  "score_range": { "min": 1234, "max": 987654 }
}
```

---

### `GET /api/filter-options`

Return unique metadata values from on-disk extraction (populates the metadata filter dropdowns).

**Response:**
```json
{
  "sub_domain": ["software_development", "data_analysis", "creative_writing", ...],
  "sentiment": ["ambitious", "reflective", "cautious", "optimistic", ...],
  "topics": ["concurrency", "API routes", "PDF generation", ...],
  "project_context": ["debugging", "refactoring", "architecture", ...]
}
```

---

### `GET /api/session/{session_id}/metadata`

Return lean frequency-based metadata for a single session.

**Path Parameter:**
- `session_id` — URL-encoded session ID

**Response:**
```json
{
  "session_id": "251201-mountmasterpro/12.01.25-copy",
  "provider": "aistudio",
  "total_sets": 13,
  "total_session_chars": 213264,
  "file_count": 69,
  "anchors": [
    {
      "file": "src/main.py",
      "snippet": "def process_queue(queue): ...",
      "set_number": "1"
    }
  ],
  "tool_calls": [
    {
      "question": "Should I continue with the refactoring?",
      "context_set": "1",
      "provider": "aistudio"
    }
  ],
  "metadata": {
    "domain": "technical",
    "sub_domain": "software_development",
    "project_context": ["project", "debugging", "refactoring"],
    "topics": ["concurrency", "database interactions", "API routes"],
    "sentiment": "ambitious",
    "idea_maturity": "developing",
    "content_type": "",
    "emotional_tone": ""
  },
  "json_file_list": ["17249.1.json", "17249.2.json", ...]
}
```

**Caching:** On first request, a `.meta.json` file is written next to `session.json`. Subsequent requests read from this cached file.

---

### `POST /api/select`

Save selected session IDs to the queue JSON file.

**Request Body:**
```json
{
  "session_ids": ["session/id/1", "session/id/2"]
}
```

**Response:**
```json
{
  "selected": ["session/id/1", "session/id/2"],
  "count": 2,
  "timestamp": 1234567890
}
```

---

### `POST /api/select-with-metadata`

Save selected sessions and return full metadata for each.

**Request Body:**
```json
{
  "session_ids": ["session/id/1", "session/id/2"]
}
```

**Response:**
```json
{
  "selected": ["session/id/1", "session/id/2"],
  "count": 2,
  "timestamp": 1234567890,
  "metadata": [
    {
      "session_id": "...",
      "provider": "aistudio",
      ...
    }
  ]
}
```

---

### `GET /api/select/export`

Download selected sessions as a JSON file.

---

## CLI / Command Line

### Session Metadata Extraction

The metadata extraction logic lives in `soma/machinetalk/session_metadata.py`. It can be run standalone.

#### Extract a Single Session

```bash
cd /home/flintx/soma-10-14
python3 -m soma.machinetalk.session_metadata /path/to/session

# Or directly:
python3 soma/machinetalk/session_metadata.py /path/to/session
```

#### Batch Extract an Entire Vault

```bash
python3 soma/machinetalk/session_metadata.py /path/to/vault

# With custom output directory:
python3 soma/machinetalk/session_metadata.py /path/to/vault /path/to/output/dir
```

#### Output Per Session

```
Processing 452 sessions...
  ✓ 251201-mountmasterpro/12.01.25-copy | sets=13 | domain=technical | sentiment=ambitious
  ✓ 251130-gmail/11.30.reflection | sets=8 | domain=creative | sentiment=reflective
```

#### Writing to a File

```bash
python3 soma/machinetalk/session_metadata.py /path/to/session --output /path/to/output.json
```

#### CLI Usage

```
Usage: python session_metadata.py <session_dir_or_vault> [output_dir]

  Single session:  python session_metadata.py /path/to/session
  Full vault:      python session_metadata.py /path/to/vault
```

### Start Script

```bash
./soma-session-picker/start.sh
```

Starts both backend (port 8001) and frontend (port 5174).

Logs:
- Backend: `/tmp/soma-picker-backend.log`
- Frontend: `/tmp/soma-picker-frontend.log`

---

## Export JSON Format

When you click **"Export N Favorites"**, the downloaded file contains an array of session objects:

```json
[
  {
    "session_id": "251201-mountmasterpro/12.01.25-copy",
    "provider": "aistudio",
    "total_sets": 13,
    "total_session_chars": 213264,
    "file_count": 69,
    "anchors": [
      {
        "file": "src/main.py",
        "snippet": "def process_queue(queue): ...",
        "set_number": "1"
      }
    ],
    "tool_calls": [
      {
        "question": "Should I continue?",
        "context_set": "1",
        "provider": "aistudio"
      }
    ],
    "metadata": {
      "domain": "technical",
      "sub_domain": "software_development",
      "project_context": [
        "project keyword 1",
        "project keyword 2"
      ],
      "topics": [
        "concurrency",
        "database interactions",
        "API routes"
      ],
      "sentiment": "ambitious",
      "idea_maturity": "developing",
      "content_type": "",
      "emotional_tone": ""
    },
    "json_file_list": [
      "17249.1.json",
      "17249.2.json"
    ]
  }
]
```

### Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | Unique session identifier |
| `provider` | string | AI provider (e.g., "aistudio", "anthropic") |
| `total_sets` | int | Number of chat sets in the session |
| `total_session_chars` | int | Total character count |
| `file_count` | int | Number of source files referenced |
| `anchors` | array | Code block references (file, snippet, set_number) |
| `tool_calls` | array | ask_user tool calls (question, context_set, provider) |
| `metadata.domain` | string | Top-level domain classification |
| `metadata.sub_domain` | string | Sub-domain classification |
| `metadata.project_context` | array | Project keyword strings (no file paths) |
| `metadata.topics` | array | Topic keywords extracted from all chatsets |
| `metadata.sentiment` | string | Most frequent sentiment value |
| `metadata.idea_maturity` | string | Most frequent idea maturity value |
| `metadata.content_type` | string | Most frequent content type value |
| `metadata.emotional_tone` | string | Most frequent emotional tone value |
| `json_file_list` | array | Names of all chatset JSON files in the session |

---

## Soma Integration

### How Soma Consumes the Export

The session picker writes `data/soma_queue.json` with selected session IDs. Soma's runner reads this file to determine which sessions to process.

#### Queue File Format

```json
{
  "selected": [
    "session/id/1",
    "session/id/2"
  ],
  "count": 2,
  "timestamp": 1234567890
}
```

#### Soma Runner Command

```bash
# Run the selected sessions
python3 run_engine.py --queue data/soma_queue.json

# Or manually specify:
python3 run_engine.py --queue path/to/your/favorites.json
```

### Importing the Favorites JSON into Soma

To wire up Soma to consume the exported favorites JSON directly:

```python
import json

def load_favorites(json_path: str) -> list[dict]:
    """Load exported favorites JSON and return session data for Soma."""
    with open(json_path) as f:
        sessions = json.load(f)
    
    for session in sessions:
        session_id = session["session_id"]
        provider = session["provider"]
        total_sets = session["total_sets"]
        total_chars = session["total_session_chars"]
        metadata = session["metadata"]
        anchors = session["anchors"]
        tool_calls = session["tool_calls"]
        json_files = session["json_file_list"]
        
        # Use metadata for filtering/ranking
        domain = metadata.get("domain", "")
        sentiment = metadata.get("sentiment", "")
        topics = metadata.get("topics", [])
        project_context = metadata.get("project_context", [])
        
        # Use anchors for code reference
        for anchor in anchors:
            file_path = anchor["file"]
            snippet = anchor["snippet"]
            set_number = anchor["set_number"]
            # ... process anchor
        
        # Use tool_calls for follow-up questions
        for call in tool_calls:
            question = call["question"]
            # ... process tool call
        
        print(f"Loaded: {session_id} | domain={domain} | sentiment={sentiment}")
    
    return sessions
```

### Session Data Location

The export JSON contains file names in `json_file_list`. To get the actual session files:

```
SESSIONS_PATH/
├── session-id-1/
│   ├── session.json
│   ├── 17249.1.json
│   ├── 17249.2.json
│   ├── 17249.3.json
│   └── session-id-1.meta.json  ← cached extraction
├── session-id-2/
│   ├── session.json
│   └── ...
```

The session picker resolves session IDs by extracting the directory name from the session_id path and looking it up under `SESSIONS_PATH`.

### Environment Configuration

Before running Soma's runner, ensure these environment variables point to the correct locations:

```bash
export SESSIONS_PATH="/media/storage/dendritic123/chat-logs/sessions"
export QUEUE_OUTPUT_PATH="/home/flintx/soma-10-14/data/soma_queue.json"
```

---

## Troubleshooting

### Session Not Found

If a session doesn't appear in the picker:
1. Verify the session directory exists under `SESSIONS_PATH`
2. Verify it contains a `session.json` file
3. Check that the dev_sessions SQLite table has an entry for it

### Metadata Extraction Fails

If the metadata panel shows an error:
1. Verify the chatset JSON files contain `extraction_output.extracted` fields
2. Check the backend log: `tail -f /tmp/soma-picker-backend.log`
3. Run extraction manually: `python3 soma/machinetalk/session_metadata.py /path/to/session`

### Backend Won't Start

```bash
# Check for port conflicts
lsof -ti:8001

# Kill existing processes
kill $(lsof -ti:8001)

# Verify SQLite database exists
ls backend/data/soma_sessions.db
```

### Frontend Won't Build

```bash
cd frontend
rm -rf node_modules
npm install
npm run build
```
