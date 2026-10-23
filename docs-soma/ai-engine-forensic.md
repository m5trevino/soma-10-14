# ai-engine — Forensic Deep Dive

TARGET: ai-engine | RUN: 20261022T144805Z-74928c | DATE: 2026-10-22T14:48Z | HOSTS EXAMINED: flintx (local), ubuntu-8gb-hel1-1 (remote, Hetzner)
CONFIDENCE SUMMARY: C1-heavy (remote runtime probes, source reads, DB schema, health endpoint) | SCOPE: Remote peacock-engine FastAPI service, app/main.py, peacock-engine.service
SCOPE: Full remote ai-engine application: FastAPI service, provider clients, model routing, key management, pipeline modes, and TurnKey integration on Hetzner. Excluded: all sibling components (soma, turn-key-profile-builder, soma-session-picker) — interfaces observed only from the target side.

---

## Mandate

Orchestrate multi-gateway AI model requests across 15+ provider pools with key rotation, rate-limit pacing, and structured response capture.

---

## Current State

The peacock-engine.service is **active (running)** since 2026-10-22T14:41:31 UTC on remote host ubuntu-8gb-hel1-1 (Hetzner, IP 100.87.51.23). The service runs a FastAPI application on 0.0.0.0:3099, managed by systemd with Restart=always.

The application is live and responsive: the `/health` endpoint returned `{"status":"ONLINE","system":"PEACOCK_ENGINE_V3","version":"3.0.0"}` confirming operational integrity across 10 monitored key pools and 160 model registrations.

The remote root at `/root/hetzner/ai-engine` contains 190 Python files across app/routes/, app/core/, app/providers/, and app/utils/. The local mirror at `/media/storage/ai-engine` is stale (mtime 2026-08-14, 69 days old) and must not be used as primary evidence.

---

## Key Paths and Entry Points

| Path | Host | Role | Entrypoint? | Lines | Mtime | Evidence |
|---|---|---|---|---|---|---|
| `/root/hetzner/ai-engine/app/main.py` | remote | FastAPI application root | Yes (main) | 417 | 2026-10-09 | E-001 |
| `/root/hetzner/ai-engine/run_engine.sh` | remote | Launcher: venv activation, uvicorn | Yes (service) | 62 | 2026-10-10 | E-002 |
| `/etc/systemd/system/peacock-engine.service` | remote | Systemd unit | No (unit) | 17 | 2026-10-22 | E-003 |
| `/root/hetzner/ai-engine/launch-peacock.sh` | remote | TUI launcher with SSH tunnel | No (aux) | 115 | 2026-10-10 | E-012 |
| `/root/hetzner/ai-engine/app/config.py` | remote | Model registry, performance modes | No (config) | 269 | 2026-10-14 | E-006 |
| `/root/hetzner/ai-engine/app/core/key_manager.py` | remote | Key pools, rotation strategies | No (core) | — | 2026-10-22 | E-007 |
| `/root/hetzner/ai-engine/app/core/striker.py` | remote | Core request execution engine | No (core) | 1121 | 2026-10-22 | E-008 |
| `/root/hetzner/ai-engine/app/core/config_store.py` | remote | Runtime config singleton | No (config) | 243 | 2026-10-22 | E-013 |
| `/root/hetzner/ai-engine/app/routes/unified_routes.py` | remote | Unified API routes | No (route) | 1535 | 2026-10-22 | C1 |
| `/root/hetzner/ai-engine/app/routes/chat.py` | remote | Chat API routes | No (route) | 711 | 2026-10-22 | C1 |
| `/root/hetzner/ai-engine/app/core/plan_executor.py` | remote | Plan execution engine | No (core) | 552 | 2026-10-22 | C1 |
| `/root/hetzner/ai-engine/peacock.db` | remote | SQLite database | No (data) | — (233KB) | 2026-10-22 | E-009 |
| `/root/hetzner/ai-engine/.env` | remote | Environment secrets (keys) | No (env) | 58 | 2026-09-29 | E-010 |
| `/root/hetzner/ai-engine/config/runtime_config.json` | remote | Runtime provider/pacer config | No (config) | 97 | 2026-10-22 | E-011 |
| `/root/hetzner/ai-engine/requirements.txt` | remote | Python dependencies | No (dep) | 18 | 2026-08-15 | E-014 |
| `/root/hetzner/ai-engine/turn-key/turnkey/sdk.py` | remote | TurnKey SDK | No (pkg) | 509 | 2026-10-22 | E-021 |
| `/media/storage/ai-engine/app/main.py` | local | Stale mirror | No (mirror) | 395 | 2026-08-14 | E-022 |

---

## Architecture and Data Flow

```text
┌──────────────────────────────────────────────────────────────────┐
│                        peacock-engine.service                     │
│                        ubuntu-8gb-hel1-1                          │
│                                                                   │
│  systemd → run_engine.sh → uvicorn → app.main:app                │
│       │                                                              │
│       ├─ EnvironmentFile: .env (15 *_KEYS)                         │
│       ├─ WorkingDirectory: /root/hetzner/ai-engine                 │
│       └─ Restart: always (RestartSec=3)                            │
│                                                                   │
│  app/main.py (417 lines)                                          │
│  ├─ init_db() → peacock.db                                       │
│  ├─ 38+ route routers mounted at /v1/*, /health, /*               │
│  ├─ CORSMiddleware (allow_all)                                    │
│  ├─ request_id_middleware (X-Request-Id header)                   │
│  ├─ global_exception_handler (JSON 500)                           │
│  └─ lifespan(): GroqRateTracker.load() + auto-save                │
│                                                                   │
│  Key routing path:                                                │
│  route → striker.py → KeyPool.deck → key_rotation → provider API │
│                                                                   │
│  Provider layers:                                                 │
│  ├── groq/        (24 files: client_factory, key_resolver,       │
│  │               model_router, tool_executor, tool_integration)   │
│  ├── ollama_cloud/ (9 files: similar structure)                   │
│  ├── opencode/     (11 files: anthropic_factory, openai_factory,  │
│  │               translator, sdk_resolver)                        │
│  ├── [inline]      openrouter, hetzner, merge, novita, arli,     │
│  │               google, agnes, aion, bazaarlink, cloudflare,    │
│  │               mistral, xkiro, explabs, deepseek               │
│  └── pydantic-ai     (model abstraction layer)                   │
│                                                                   │
│  Data flow:                                                       │
│  request → router → config_store → key_pool.pick → striker.execute
│  → httpx → provider API → response → vault/ → db.store           │
│                                                                   │
│  Persistence:                                                     │
│  ├── peacock.db (11 tables: key_usage, conversations, messages,   │
│  │   conversation_turns, batches, projects, codebase_scans,      │
│  │   memory_feedback, apps, project_buckets)                     │
│  ├── vault/successful/ (6,606 files, 116 MB)                     │
│  ├── vault/failed/ (3,968 files, 166 MB)                         │
│  ├── success_strikes.log (6,997 lines)                           │
│  ├── failed_strikes.log (4,276 lines)                            │
│  ├── _strike_events.jsonl (1,031 lines)                          │
│  ├── provider_failures/failures.jsonl (2MB)                      │
│  └── config/runtime_config.json (provider states, pacer)        │
└──────────────────────────────────────────────────────────────────┘
```

---

## Core Logic

### 1. Startup and initialization

`[remote] /root/hetzner/ai-engine/app/main.py:1-10` [E-001] — The application begins with `load_dotenv()`, imports the FastAPI framework, imports 38+ route modules, imports 15+ key pool classes from `app.core.key_manager`, and calls `init_db()` at module level.

`[remote] /root/hetzner/ai-engine/app/db/database.py` — `init_db()` creates all 11 tables via `CREATE TABLE IF NOT EXISTS` at import time. This is a fire-and-forget schema initialiser; no migration system exists. [E-009]

### 2. Lifespan hooks

`[remote] /root/hetzner/ai-engine/app/main.py:130-148` [E-001] — The `lifespan()` async context manager loads `GroqRateTracker` state from disk, starts an auto-save background task (30-second interval), and initialises `CleanupManager` with background scheduling for storage retention (TB-023a).

### 3. Request ID and exception middleware

`[remote] /root/hetzner/ai-engine/app/main.py:106-119` [E-001] — Every incoming request receives a 12-character UUID in `X-Request-Id`. The global exception handler catches all unhandled exceptions, logs to `peacock.errors`, and returns either the raw error (if DEBUG=1) or a generic message.

### 4. Router registration

`[remote] /root/hetzner/ai-engine/app/main.py:175-215` [E-001] — 38 routers are mounted at `/v1/*` prefixes. The registration order matters: `models_router` is explicitly noted as requiring precedence over `openai_compat_router` for the `/models` endpoint. WebUI routes (`/v1/webui/*`) are mounted after API routes to allow API paths to take priority.

### 5. SPA catch-all

`[remote] /root/hetzner/ai-engine/app/main.py:397-407` [E-001] — A `{full_path:path}` catch-all at the bottom serves `app/static/index.html` for all non-API routes, implementing a Single Page Application frontend.

### 6. Key pool loading and rotation

`[remote] /root/hetzner/ai-engine/app/core/key_manager.py:1-120` [E-007] — Each pool type (GroqPool, OllamaPool, etc.) is instantiated from a comma-separated `_KEYS` environment variable. The `KeyPool.__init__()` method splits entries by comma, optionally parses `label:key` format, shuffles the deck, and initialises a `ShuffleStrategy` (Deck of Cards) rotation.

The `ShuffleStrategy.get_next()` method returns `deck[pointer]` and increments the pointer. A `RoundRobinStrategy` is also available but not the default.

### 7. Request execution (striker)

`[remote] /root/hetzner/ai-engine/app/core/striker.py:1-100` [E-008] — The `striker` module is the core request execution engine. It imports from `pydantic_ai` (Agent abstraction), `httpx` (async HTTP), and all 17 key pool classes. Three httpx clients are configured: `direct_client` (no proxy), `tunnel_client` (SOCKS5 tunnel, optional), `proxy_client` (http proxy, optional), and a special `arli_client` with `Connection: close` to work around Arli's 1-parallel-request limit.

`[remote] /root/hetzner/ai-engine/app/core/striker.py:76-100` [E-008] — `ThrottleController` implements proactive request throttling based on the active `PEACOCK_PERF_MODE` performance mode (stealth=3.0x, balanced=1.15x, apex=1.02x).

### 8. Model registry

`[remote] /root/hetzner/ai-engine/app/config.py:1-269` [E-006] — The `ModelConfig` Pydantic model defines 17 fields (id, gateway, note, status, context_window, max_completion_tokens, tools_supported, input_price_1m, output_price_1m, etc.). The `MODEL_REGISTRY` is a hardcoded list of 160+ `ModelConfig` objects covering 15 gateways. The `PERFORMANCE_MODES` dict maps mode names to multipliers and colors.

### 9. Runtime configuration

`[remote] /root/hetzner/ai-engine/app/core/config_store.py:1-243` [E-013] — `RuntimeConfigStore` is a singleton that reads/writes `config/runtime_config.json`. It provides `get()`, `set()`, `save()`, and `reset()` methods. The default configuration covers pacer settings (burn_mode, tpm_backpressure_pct, default_concurrency), cleanup retention policies, performance mode, and 16 provider enable/disable flags.

### 10. Health endpoint

`[remote] /root/hetzner/ai-engine/app/main.py:226-320` [E-001] — The `/health` endpoint queries live state from `GroqPool.deck`, `GroqRateTracker`, `GroqPacer`, the `MODEL_REGISTRY`, and `config_store`. It returns pool sizes per gateway, provider flags, model counts by gateway and status, and pacer/governor snapshots.

---

## Configuration and Invariants

### Environment variables (names only)

Confirmed from `.env` key enumeration (E-010):

| Variable | Purpose |
|---|---|
| GROQ_KEYS | Comma-separated Groq API keys |
| OPENROUTER_KEYS | Comma-separated OpenRouter API keys |
| OPENCODE_GO_KEYS | Comma-separated OpenCode Go API keys |
| OPENCODE_ZEN_KEYS | Comma-separated OpenCode Zen API keys |
| HETZNER_KEYS | Comma-separated Hetzner API keys |
| MISTRAL_KEYS | Comma-separated Mistral API keys |
| XKIRO_KEYS | Comma-separated xKiro API keys |
| NOVITA_KEYS | Comma-separated Novita API keys |
| AGNES_KEYS | Comma-separated Agnes AI API keys |
| AION_KEYS | Comma-separated Aion Labs API keys |
| BAZAARLINK_KEYS | Comma-separated BazaarLink API keys |
| CLOUDFLARE_KEYS | Comma-separated Cloudflare API keys |
| EXPLABS_KEYS | Comma-separated Experiential Labs API keys |
| ARLI_KEYS | Comma-separated Arli AI API keys |

### Runtime config (`config/runtime_config.json`)

- **pacer.burn_mode**: BALANCED (configurable via API)
- **pacer.tpm_backpressure_pct**: 90 (trips backpressure at 90% of model TPM)
- **pacer.default_concurrency**: 2
- **cleanup**: plan=7d, stress=3d, history=30d, runs every 6 hours
- **providers**: 16 entries, opencode-go disabled

### Performance modes (`app/config.py`)

| Mode | Name | Multiplier |
|---|---|---|
| stealth | BLACK KEY (Stealth) | 3.0x |
| balanced | BLUE KEY (Balanced) | 1.15x |
| apex | RED KEY (Apex) | 1.02x |

### Key pool invariants

- `KeyAsset.on_cooldown` always returns `False` — cooldown is effectively removed (E-007: `mark_cooldown` is a no-op)
- Cooldown removal is documented: "Cooldown removed — this is a no-op kept for call-site compatibility"
- Default rotation strategy: `ShuffleStrategy` (Deck of Cards, pointer increments linearly)
- `KeyPool.shuffle()` uses `random.shuffle()` on initialisation

### Database constraints

- `key_usage`: UNIQUE(gateway, account) — one row per key identity
- `apps`: UNIQUE(api_secret) — one secret per app
- Foreign keys: `messages.conversation_id` → `conversations.id` (ON DELETE CASCADE)
- Foreign keys: `conversation_turns.conversation_id` → `conversations.id` (ON DELETE CASCADE)
- Foreign keys: `batch_items.batch_id` → `batches.id` (ON DELETE CASCADE)

---

## Dependencies and Cross-Component Connections

### Upstream dependencies

| Dependency | Mechanism | Payload | Confidence |
|---|---|---|---|
| **TurnKey SDK** (`/root/hetzner/ai-engine/turn-key/turnkey/`) | Python import | SDK client, loader, rotator, machinetalk_client | C1 (E-021) |
| **peacock.db** | SQLite via `app.db.database` | Key usage tracking, conversation storage | C1 (E-009) |
| **Config JSON** | File read via `RuntimeConfigStore` | Provider states, pacer settings | C1 (E-011) |
| **Env secrets** | `python-dotenv` at startup | 15 *_KEYS variables | C1 (E-010) |
| **pydantic-ai** | pip dependency | Model abstraction (GroqModel, OpenAIModel, GoogleModel) | C1 (E-014) |
| **httpx** | pip dependency | Async HTTP clients (direct, tunnel, proxy, arli-specific) | C1 (E-008) |
| **rich** | pip dependency | CLIFormatter, ARSENAL_BLOCKS for terminal output | C1 |

### Downstream consumers

| Consumer | Mechanism | Payload | Confidence |
|---|---|---|---|
| **SSH TUI** | `launch-peacock.sh` creates SSH tunnel (local:3099 → server:3099) | TUI connects to health + API endpoints | C1 (E-012) |
| **Vault** | Striker writes successful/failed responses to vault/ | ~100KB captured response per file | C1 (E-018, E-019) |
| **Log files** | tee -a /tmp/peacock_engine.log | uvicorn stdout/stderr | C1 (E-004) |
| **Striker logs** | success_strikes.log, failed_strikes.log, _strike_events.jsonl | Strike event records | C1 (E-016, E-017) |
| **Provider failure log** | provider_failures/failures.jsonl (2MB) | Per-provider failure records | C1 |
| **Web UI** | Static file mount at / (SPA catch-all) | Vite-built frontend | C1 |

### Sibling component interfaces

| Component | Interface | Evidence |
|---|---|---|
| **TurnKey** | Installed as egg package at `/root/hetzner/ai-engine/turn-key/turnkey/`; SDK classes imported by striker and plan_executor | E-021 |
| **Soma** | Not directly imported in main.py or core modules. MachineTalk/CLI pipeline is a separate codebase at `/home/flintx/soma-10-14/` | — |
| **Soma session picker** | Not connected — separate FastAPI service on port 8001 | — |

### Local mirror (stale)

- `/media/storage/ai-engine` — last modified 2026-08-14, contains app/main.py at 395 lines (vs. remote 417)
- The local mirror includes older TUI assets (`peacock-engine-tui-core/`) and pre-registry model configurations
- Must be treated as historical intent only (R4)

---

## Known Gaps and Uncertainties

### G-01: .env value format unknown
- **What**: Individual API key values are not accessible (secret rule). Key names confirmed (e.g., GROQ_KEYS) but value format (single key, comma-separated, JSON array) must be inferred from code.
- **Why matters**: Determines how key pools are populated and how many keys each pool holds.
- **Evidence needed**: Read `.env` file contents (redacted for output).

### G-02: Integrity pool mapping incomplete
- **What**: `striker.py` imports 17 pool types (including GooglePool, DeepSeekPool), but `/health` integrity reports only 10. Five providers (google, agnes, aion, bazaarlink, cloudflare, arli, deepseek) are in config_store defaults but not in the integrity dict.
- **Why matters**: Could indicate pools not yet loaded, pools loaded differently, or a gap in the health endpoint's integrity reporting.
- **Evidence needed**: Read the full `key_manager.py` to find the `INTEGRITY_POOLS` or similar mapping dict, and read `striker.py` to see how each pool is used.

### G-03: Dual SDK surfaces
- **What**: Two SDK files exist: `/root/hetzner/ai-engine/app/client/sdk.py` (4 files in app/client/) and `/root/hetzner/ai-engine/turn-key/turnkey/sdk.py` (509 lines, installed as egg). Unclear which one the engine actually uses for TurnKey integration.
- **Why matters**: If both are live, they may serve different purposes; if one is dead code, it represents maintenance overhead.
- **Evidence needed**: Read `app/client/sdk.py` and search for import references in core modules.

### G-04: Vault file format unknown
- **What**: `vault/successful/` contains 6,606 files (~100KB each), and `vault/failed/` contains 3,968 files. These appear to be captured API responses but content structure is unknown.
- **Why matters**: Determines whether the vault is useful for debugging, replay, or audit purposes.
- **Evidence needed**: Sample one file from each vault directory.

### G-05: Live engine log inaccessible
- **What**: The service writes to `/tmp/peacock_engine.log` via `tee`, but the file was not accessible (SSH access confirmed, but the file may be large or truncated).
- **Why matters**: Would provide real-time request logging, error traces, and startup details.
- **Evidence needed**: `head` or `tail` of `/tmp/peacock_engine.log` on the remote.

### G-06: Engine profiles sub-module architecture
- **What**: `app/core/engine_profiles/` contains 20+ Python files including 15 test files (cache key, conditions, executors, normalizers, perf modes, resolvers, runners, token counters). Full architecture is unknown.
- **Why matters**: This is a major subsystem that influences how models are invoked and configured at runtime.
- **Evidence needed**: Read `engine_profiles/__init__.py`, `loader.py`, `executor.py`, and `resolver.py`.

### G-07: Inline vs. subdirectory provider implementation
- **What**: Only groq/, ollama_cloud/, and opencode/ have dedicated provider subdirectories. Other providers (openrouter, hetzner, merge, novita, arli, google, agnes, aion, bazaarlink, cloudflare, mistral, xkiro, explabs, deepseek) have no corresponding subdirectory. Their implementation is likely in `striker.py` itself or in `config.py` model routing.
- **Why matters**: Inconsistent provider architecture could indicate legacy code paths or incomplete migration.
- **Evidence needed**: Trace `openrouter` and `hetzner` model routing in `striker.py`.

### G-08: Dynamic models
- **What**: `dynamic_models.json` exists at the remote root. Its role in model registration (vs. the hardcoded `MODEL_REGISTRY` in config.py) is unclear.
- **Why matters**: If dynamic models can be loaded at runtime, this is a significant deviation from the static registry.
- **Evidence needed**: Read `dynamic_models.json` and search for its import in core modules.

---

## Evidence Log

| ID | Host | Kind | Locator | Captured At | Proves | Confidence |
|---|---|---|---|---|---|---|
| E-001 | remote | file | /root/hetzner/ai-engine/app/main.py | 2026-10-22T14:50Z | FastAPI app: 417 lines, 38+ routers, lifespan, SPA catch-all | C1 |
| E-002 | remote | file | /root/hetzner/ai-engine/run_engine.sh | 2026-10-22T14:51Z | Launcher: venv activate, kill stale port, uvicorn 3099 | C1 |
| E-003 | remote | file | /etc/systemd/system/peacock-engine.service | 2026-10-22T14:50Z | Service unit: ExecStart, Restart=always, .env file | C1 |
| E-004 | remote | runtime | systemctl status peacock-engine.service | 2026-10-22T14:48Z | active (running), PID 887→916(uvicorn), port 3099 | C1 |
| E-005 | remote | runtime | curl http://127.0.0.1:3099/health | 2026-10-22T14:53Z | ONLINE, 160 models, 10 pools, balanced perf mode | C1 |
| E-006 | remote | file | /root/hetzner/ai-engine/app/config.py | 2026-10-22T14:51Z | ModelConfig schema, 160+ models, 3 perf modes, FROZEN_IDS | C1 |
| E-007 | remote | file | /root/hetzner/ai-engine/app/core/key_manager.py | 2026-10-22T14:52Z | KeyAsset, KeyPool, RotationStrategy, 17 pool imports, cooldown removed | C1 |
| E-008 | remote | file | /root/hetzner/ai-engine/app/core/striker.py | 2026-10-22T14:53Z | 1121 lines, pydantic-ai Agent, 4 httpx clients, ThrottleController | C1 |
| E-009 | remote | datastore | /root/hetzner/ai-engine/peacock.db | 2026-10-22T14:52Z | 11 tables: key_usage(49), conversations(163), messages(326), etc. | C1 |
| E-010 | remote | file | /root/hetzner/ai-engine/.env | 2026-10-22T14:52Z | 15 *_KEYS variables confirmed (names only) | C1 |
| E-011 | remote | file | /root/hetzner/ai-engine/config/runtime_config.json | 2026-10-22T14:49Z | 16 providers, pacer config, cleanup config | C1 |
| E-012 | remote | file | /root/hetzner/ai-engine/launch-peacock.sh | 2026-10-22T14:50Z | TUI launcher: SSH tunnel to 204.168.184.49:3099 | C1 |
| E-013 | remote | file | /root/hetzner/ai-engine/app/core/config_store.py | 2026-10-22T14:52Z | RuntimeConfigStore singleton, hot-reload | C1 |
| E-014 | remote | file | /root/hetzner/ai-engine/requirements.txt | 2026-10-22T14:52Z | 18 deps: fastapi, uvicorn, pydantic-ai-slim, httpx, rich, tiktoken | C1 |
| E-015 | remote | file | /root/hetzner/ai-engine/app/main.py (lines 21-56, 151-163) | 2026-10-22T14:52Z | 38+ import lines, router registration | C1 |
| E-016 | remote | file | /root/hetzner/ai-engine/success_strikes.log | 2026-10-22T14:52Z | 6,997 successful strikes | C1 |
| E-017 | remote | file | /root/hetzner/ai-engine/failed_strikes.log | 2026-10-22T14:52Z | 4,276 failed strikes | C1 |
| E-018 | remote | file | /root/hetzner/ai-engine/vault/successful/ | 2026-10-22T14:52Z | 6,606 files, 116 MB | C1 |
| E-019 | remote | file | /root/hetzner/ai-engine/vault/failed/ | 2026-10-22T14:52Z | 3,968 files, 166 MB | C1 |
| E-020 | remote | directory | /root/hetzner/ai-engine/app/ (file listing) | 2026-10-22T14:50Z | 190 Python files, 7 subdirectory categories | C1 |
| E-021 | remote | file | /root/hetzner/ai-engine/turn-key/turnkey/sdk.py | 2026-10-22T14:50Z | 509 lines, installed as egg package | C1 |
| E-022 | local | file | /media/storage/ai-engine/app/main.py | 2026-10-22T14:48Z | 395 lines, mtime 2026-08-14 — stale mirror | C1 |
