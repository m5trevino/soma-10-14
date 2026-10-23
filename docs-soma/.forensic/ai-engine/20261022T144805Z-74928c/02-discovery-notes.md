# Discovery Notes: ai-engine
TARGET: ai-engine | RUN: 20261022T144805Z-74928c

## 1. Target lock

- TARGET: ai-engine
- SLUG: ai-engine
- RUN ID: 20261022T144805Z-74928c
- STARTED: 2026-10-22T14:48:05Z
- HOSTS: local (flintx, MX Linux), remote (ubuntu-8gb-hel1-1, Hetzner)
- Remote root: /root/hetzner/ai-engine (authoritative)
- Local roots: /media/storage/ai-engine (stale mirror, mtime 2026-08-14), /home/flintx/novita-sandbox/ai-engine

## 2. Inventory summary

### Remote root file counts
- Python files in app/: 190
- Top-level files: 36
- Directories: app/routes/ (41 routers), app/core/ (55 files incl. engine_profiles/ subdirectory), app/providers/ (groq/ 24 files, ollama_cloud/ 9 files, opencode/ 11 files), app/utils/ (7 files), app/db/, app/client/, app/monitoring/, app/middleware/
- Vault/successful: 6,606 files (116 MB)
- Vault/failed: 3,968 files (166 MB)
- peacock.db: 233,472 bytes (11 tables)
- .env: 58 keys listed (names only)
- Turn-key package: 509 lines (SDK), 518 lines (__init__)

### Local mirror (stale)
- /media/storage/ai-engine: last modified 2026-08-14 (69 days old at time of run)
- app/main.py: 395 lines (vs. remote 417 lines — stale)

## 3. Entry points

### Remote
- `/root/hetzner/ai-engine/app/main.py` — 417 lines, mtime 2026-10-09T06:53
- `/root/hetzner/ai-engine/run_engine.sh` — 62 lines, launcher script
- `/root/hetzner/ai-engine/launch-peacock.sh` — 115 lines, TUI launcher
- `/root/hetzner/ai-engine/turn-key/turnkey/sdk.py` — 509 lines, SDK

### Local
- `/media/storage/ai-engine/app/main.py` — 395 lines, mtime 2026-08-14T20:41
- `/media/storage/ai-engine/launch-peacock.sh` — mtime 2026-08-14T20:40

### Conflict C-01
- Claim A: app/main.py is 395 lines, mtime 2026-08-14 [source: /media/storage/ai-engine]
- Claim B: app/main.py is 417 lines, mtime 2026-10-09 [source: remote /root/hetzner/ai-engine]
- Resolution: B (remote is authoritative per registry; local is stale mirror)
- Impact: All citations reference remote paths; local cited only for contrast

## 4. Runtime state

### Service
- Service: `peacock-engine.service`
- Loaded from: `/etc/systemd/system/peacock-engine.service`
- State: **active (running)** since 2026-10-22T14:41:31 UTC
- ExecStart: `/bin/bash /root/hetzner/ai-engine/run_engine.sh --no-proxy`
- Environment: PYTHONUNBUFFERED=1, EnvironmentFile=/root/hetzner/ai-engine/.env
- Restart: always (RestartSec=3)
- PID tree: 887 (bash) → 916 (uvicorn) → 918 (tee -a /tmp/peacock_engine.log)

### Health endpoint
- `/health` returned ONLINE as of 2026-10-22T14:49Z
- System: PEACOCK_ENGINE_V3 v3.0.0
- Performance mode: balanced (BLUE KEY, multiplier 1.15)
- Pacer: BALANCED burn_mode, 90% tpm_backpressure

### Key pools (live via health endpoint)
| Gateway | Pool size | Enabled | Visible |
|---|---|---|---|
| groq | 28 | true | true |
| opencode-go | 1 | false | false |
| openrouter | 1 | true | true |
| ollama | 2 | true | true |
| hetzner | 1 | true | true |
| merge | 1 | true | true |
| novita | 1 | true | true |
| xkiro | 1 | true | true |
| explabs | 1 | true | true |
| mistral | 1 | true | true |
| agnes | — (not in integrity) | true | true |
| aion | — (not in integrity) | true | true |
| bazaarlink | — (not in integrity) | true | true |
| cloudflare | — (not in integrity) | true | true |
| google | — (not in integrity) | true | true |
| arli | — (not in integrity) | true | true |

Note: 11 pools imported from key_manager.py but only 10 appear in `/health` integrity. arli pool imported but not in integrity dict — may be handled differently.

### Models
- Total: 160 models across 15 gateways
- Active: 160, Frozen: 0, Deprecated: 0
- By gateway: groq(14), openrouter(4), hetzner(2), opencode-go(18), mistral(17), agnes(2), aion(6), bazaarlink(2), cloudflare(13), explabs(3), google(9), novita(9), xkiro(41), merge(1), ollama(19)

### Vault/Logs
- success_strikes.log: 6,997 lines
- failed_strikes.log: 4,276 lines
- _strike_events.jsonl: 1,031 lines
- vault/successful/: 6,606 files, 116 MB
- vault/failed/: 3,968 files, 166 MB
- provider_failures/failures.jsonl: 2,080,305 bytes (2026-10-22T10:23)

## 5. Data stores

### peacock.db (SQLite, read-only access confirmed)
- Path: /root/hetzner/ai-engine/peacock.db
- Size: 233,472 bytes
- Modified: 2026-10-22T03:06:44

| Table | Rows |
|---|---|
| key_usage | 49 |
| apps | 0 |
| conversations | 163 |
| messages | 326 |
| conversation_turns | 164 |
| batches | 0 |
| batch_items | 0 |
| project_buckets | 0 |
| memory_feedback | 0 |
| projects | 0 |
| codebase_scans | 0 |

### frozen_models.json
- Exists at root; loaded into FROZEN_IDS list at startup in config.py

## 6. Configuration and invariants

### .env keys (names only, values redacted)
AGNES_KEYS, AION_KEYS, ARLI_KEYS, BAZAARLINK_KEYS, CLOUDFLARE_KEYS, EXPLABS_KEYS, GROQ_KEYS, HETZNER_KEYS, MERGE_KEYS, MISTRAL_KEYS, NOVITA_KEYS, OPENCODE_GO_KEYS, OPENCODE_ZEN_KEYS, OPENROUTER_KEYS, XKIRO_KEYS

### config/runtime_config.json (mtime: 2026-10-22T14:41 — same minute as service start)
- pacer: burn_mode=BALANCED, tpm_backpressure_pct=90, default_concurrency=2
- cleanup: plan_retention_days=7, stress_retention_days=3, history_retention_days=30, interval_hours=6
- providers: 16 providers configured (opencode-go disabled)

### app/core/config_store.py (243 lines)
- RuntimeConfigStore singleton — reads/writes config/runtime_config.json
- Hot-reload: core modules read at decision time, not cached at startup

### app/core/key_manager.py
- KeyAsset model: label, account, key, cooldown_until, enabled
- RotationStrategy (ABC): ShuffleStrategy (Deck of Cards), RoundRobinStrategy
- KeyPool class: loads keys from comma-separated .env values, shuffles deck, rotates via strategy
- 11+ pool types imported: GroqPool, OllamaPool, OpencodeGoPool, OpenrouterPool, HetznerPool, ArliPool, NovitaPool, MergePool, AgnesPool, AionPool, BazaarlinkPool, CloudflarePool, XkiroPool, ExplabsPool, MistralPool, GooglePool, DeepSeekPool
- Cooldown removed: `on_cooldown` always returns False; `mark_cooldown` is no-op

### app/config.py (269 lines)
- ModelConfig (Pydantic): id, gateway, note, status, context_window, max_completion_tokens, tools_supported, etc.
- MODEL_REGISTRY: hardcoded list of 160+ models
- PERFORMANCE_MODES: stealth (3.0x), balanced (1.15x), apex (1.02x)
- FROZEN_FILE: frozen_models.json — read at import time

### app/utils/formatter.py (24,277 bytes)
- CLIFormatter with section_header, success, warning, gateway styling

## 7. Cross-component edges

### Turn-key SDK (`/root/hetzner/ai-engine/turn-key/turnkey/`)
- sdk.py (509 lines), loader.py (52 lines), rotator.py (38 lines), gateway_rotator.py (12K), profile_integration.py (2.8K), types.py (6.4K), machinetalk_client.py (2.2K)
- Installed as egg package: turnkey_sdk.egg-info
- Imported by engine core modules (striker, plan_executor)

### Health endpoints (provider-specific)
- `/health` (Ollama Cloud) — from app/routes/ollama_cloud_health.py
- `/health` (Groq) — from app/routes/groq_health.py
- `/health` (OpenCode) — from app/routes/opencode_health.py

### Tailscale/Tunnel
- TUI uses SSH tunnel: local:3099 → server:3099 (from launch-peacock.sh)
- SSH key: ~/.ssh/hetzner, HostName: 100.87.51.23, User: root
- Also references IP 204.168.184.49

### Database writes
- init_db() in app/db/database.py called at module import time
- Tables: apps, batches, batch_items, codebase_scans, conversation_turns, conversations, key_usage, memory_feedback, messages, project_buckets, projects

## 8. Instructions and recency

| Document | Mtime | Authority |
|---|---|---|
| docs/ai-engine-forensic.md | 2026-10-22T10:26 | Prior forensic (this run) |
| config/runtime_config.json | 2026-10-22T14:41 | Active config (same as service start) |
| engine.log | 2026-10-10 | Historic log |
| ENGINE_STATUS_REPORT.md | — | Unconfirmed mtime |
| FACTORY_SETTINGS_REPORT.md | — | Unconfirmed mtime |
| REMOTE_USER_GUIDE.md | — | Unconfirmed mtime |

No AGENTS.md or target-local instruction files found in remote root.

## 9. Conflicts

### C-01 (already documented in section 3)
- Local app/main.py (395 lines) vs remote app/main.py (417 lines) — local is stale mirror

### C-02
- Claim A: key_manager.py imports 17 pool types (including GooglePool, DeepSeekPool)
- Claim B: `/health` integrity shows only 10 gateway pools (groq, opencode-go, openrouter, ollama, hetzner, merge, novita, xkiro, explabs, mistral)
- Resolution: Both coexist — striker.py imports GooglePool and DeepSeekPool; these may be loaded from env keys not yet populated or configured at startup but not yet in runtime config
- Impact: 5 pools (google, agnes, aion, bazaarlink, cloudflare, arli, deepseek) are in config_store defaults and/or striker imports but not in /health integrity — they may load from env at runtime

## 10. Unknowns and boundary gaps

### U-01
- Cannot determine which .env variable names hold key values beyond the *_KEYS pattern. Exact env var names (e.g., GROQ_KEYS) confirmed; individual key format unknown.
- **GAP**: Cannot read .env values (secret rule). Evidence: `grep -oP "^[A-Z_]+="` only shows key names.

### U-02
- The 13+ KeyPool instances in key_manager.py are imported into striker.py and main.py, but the runtime `/health` integrity dict only maps 10. The mapping between pool types and the integrity dict is unclear.
- **GAP**: Need to read app/core/key_manager.py fully to see which pool types are in the `INTEGRITY_POOLS` or similar dict vs. general imports.

### U-03
- app/client/sdk.py (4 files) vs turn-key/turnkey/sdk.py (509 lines). Two SDK surfaces exist — unclear which one the engine actually uses.
- **GAP**: Read app/client/sdk.py and determine if it is imported or dead code.

### U-04
- Vault/failed/ (166 MB) and vault/successful/ (116 MB) — each file ~95-104 KB. These appear to be captured responses. Format unknown.
- **GAP**: Sample one vault file to determine content structure.

### U-05
- `engine.log` (2026-10-10) is the only log at root level. The service writes to `/tmp/peacock_engine.log` via tee. No access to current live log.
- **GAP**: Read `/tmp/peacock_engine.log` head or tail.

### U-06
- app/core/engine_profiles/ has 20+ Python files including 15 test files. This is a significant sub-module for engine configuration. Full architecture unknown.
- **GAP**: Need to read engine_profiles/__init__.py and loader.py to understand its role.

### U-07
- Provider-specific subdirectories: groq/ (24 files), ollama_cloud/ (9 files), opencode/ (11 files). Each has client_factory.py, key_resolver.py, model_router.py, test_*.py. Other providers (openrouter, hetzner, merge, etc.) have no subdirectory.
- **GAP**: Determine where openrouter, hetzner, novita, arli, etc. providers are implemented — likely in app/config.py + app/core/striker.py directly.

## 11. Evidence index

| ID | Host | Kind | Locator | Captured At | Proves | Confidence |
|---|---|---|---|---|---|---|
| E-001 | remote | file | /root/hetzner/ai-engine/app/main.py | 2026-10-22T14:50Z | FastAPI app structure, 417 lines, 38+ routers | C1 |
| E-002 | remote | file | /root/hetzner/ai-engine/run_engine.sh | 2026-10-22T14:51Z | Launcher: venv activation, uvicorn start, port 3099 | C1 |
| E-003 | remote | file | /etc/systemd/system/peacock-engine.service | 2026-10-22T14:50Z | Service unit: ExecStart, restart=always, .env file | C1 |
| E-004 | remote | runtime | systemctl status peacock-engine.service | 2026-10-22T14:48Z | Service active, PID 887, uvicorn on 3099 | C1 |
| E-005 | remote | runtime | curl http://127.0.0.1:3099/health | 2026-10-22T14:53Z | ONLINE, 160 models, 10 pools in integrity | C1 |
| E-006 | remote | file | /root/hetzner/ai-engine/app/config.py | 2026-10-22T14:51Z | 269 lines, ModelConfig schema, 160+ models, 3 perf modes | C1 |
| E-007 | remote | file | /root/hetzner/ai-engine/app/core/key_manager.py | 2026-10-22T14:52Z | KeyAsset, KeyPool, RotationStrategy, 17 pool imports | C1 |
| E-008 | remote | file | /root/hetzner/ai-engine/app/core/striker.py | 2026-10-22T14:53Z | 1121 lines, pydantic-ai Agent, httpx clients, ThrottleController | C1 |
| E-009 | remote | datastore | /root/hetzner/ai-engine/peacock.db | 2026-10-22T14:52Z | 11 tables, 233KB, key_usage(49), conversations(163), messages(326) | C1 |
| E-010 | remote | file | /root/hetzner/ai-engine/.env | 2026-10-22T14:52Z | 15 *_KEYS variables (names only) | C1 |
| E-011 | remote | file | /root/hetzner/ai-engine/config/runtime_config.json | 2026-10-22T14:49Z | 97 lines, 16 providers, pacer, cleanup config | C1 |
| E-012 | remote | file | /root/hetzner/ai-engine/launch-peacock.sh | 2026-10-22T14:50Z | TUI launcher, SSH tunnel to 204.168.184.49 | C1 |
| E-013 | remote | file | /root/hetzner/ai-engine/app/core/config_store.py | 2026-10-22T14:52Z | 243 lines, RuntimeConfigStore singleton | C1 |
| E-014 | remote | file | /root/hetzner/ai-engine/requirements.txt | 2026-10-22T14:52Z | 18 deps: fastapi, uvicorn, pydantic-ai-slim, httpx, rich, tiktoken | C1 |
| E-015 | remote | file | /root/hetzner/ai-engine/app/main.py imports | 2026-10-22T14:52Z | 38+ route modules, 5 core imports, 15 key pools | C1 |
| E-016 | remote | file | /root/hetzner/ai-engine/success_strikes.log | 2026-10-22T14:52Z | 6,997 successful strikes logged | C1 |
| E-017 | remote | file | /root/hetzner/ai-engine/failed_strikes.log | 2026-10-22T14:52Z | 4,276 failed strikes logged | C1 |
| E-018 | remote | file | /root/hetzner/ai-engine/vault/successful/ | 2026-10-22T14:52Z | 6,606 files, 116 MB total | C1 |
| E-019 | remote | file | /root/hetzner/ai-engine/vault/failed/ | 2026-10-22T14:52Z | 3,968 files, 166 MB total | C1 |
| E-020 | remote | directory | /root/hetzner/ai-engine/app/ | 2026-10-22T14:50Z | 190 Python files, routes/core/providers/utils/db/client subdirs | C1 |
| E-021 | remote | file | /root/hetzner/ai-engine/turn-key/turnkey/sdk.py | 2026-10-22T14:50Z | 509 lines, TurnKey SDK installed as egg package | C1 |
| E-022 | local | file | /media/storage/ai-engine/app/main.py | 2026-10-22T14:48Z | 395 lines, mtime 2026-08-14 — stale mirror | C1 |

## 12. Report plan

1. **Mandate** — one sentence
2. **Current State** — service active, 160 models, 11 key pools, 190 Python files
3. **Key Paths and Entry Points** — table of all key files
4. **Architecture and Data Flow** — ASCII diagram
5. **Core Logic** — main.py → routers → striker → key pools → providers
6. **Configuration and Invariants** — config_store, key_manager, runtime_config.json
7. **Dependencies and Cross-Component Connections** — TurnKey, provider subdirs, DB
8. **Known Gaps** — U-01 through U-07
9. **Evidence Log** — E-001 through E-022
