# MACHINE TALK — Complete Technical Specification

## Version: 2.0.0
## Classification: Sovereign Agent Communication Protocol

---

## TABLE OF CONTENTS

1. [What Is Machine Talk](#1-what-is-machine-talk)
2. [Why We Use Machine Talk](#2-why-we-use-machine-talk)
3. [Core Design Principles](#3-core-design-principles)
4. [Anatomy of a Machine Talk Prompt](#4-anatomy-of-a-machine-talk-prompt)
5. [The Two Flavors](#5-the-two-flavors)
6. [How It Works — Execution Flow](#6-how-it-works--execution-flow)
7. [Building Machine Talk Prompts](#7-building-machine-talk-prompts)
8. [Real-World Examples](#8-real-world-examples)
9. [Common Pitfalls](#9-common-pitfalls)
10. [Reference Files](#10-reference-files)

---

## 1. WHAT IS MACHINE TALK

**Machine Talk** is a structured prompt engineering protocol for transforming LLM interactions from **prose-based conversation** into **deterministic machine-to-machine communication**.

It enforces:
- **Strict JSON output** (no markdown fences, no prose wrappers)
- **Verbatim extraction** (no paraphrasing, no synonym substitution)
- **Schema-validated payloads** (every field typed, every required key enforced)
- **Processing sequences** (exact order of operations, no reordering)
- **Hard gates** (inviolable constraints that trigger failure if violated)
- **Exemplars** (concrete input/output examples for few-shot learning)

**Think of it as:** A compiler for natural language. You write prompts like code, the LLM executes them like functions, and the output is structured data instead of essays.

---

## 2. WHY WE USE MACHINE TALK

### The Problem It Solves

Traditional LLM prompts produce:
- **Prose bloat:** "Here's the deconstruction you asked for..." (200 words of fluff)
- **Markdown fences:** ```json ... ``` (breaks parsers)
- **Synonym drift:** User says "build CLI" → LLM outputs "create command-line interface" (breaks downstream matching)
- **Chronology loss:** User changes mind 3 times → LLM merges all 4 versions (ambiguity)
- **Noise retention:** Greetings, apologies, hedges, fillers all preserved (context pollution)

**Result:** Downstream agents must parse, clean, deduplicate, and resolve conflicts before they can act. This is slow, error-prone, and breaks determinism.

### The Machine Talk Solution

| Problem | Machine Talk Fix |
|---------|-----------------|
| Prose bloat | `[MODE::strict_json_output]` + `[HARD_GATES] prose_output → ∅` |
| Markdown fences | `[HARD_GATES] markdown_fences → ∅` |
| Synonym drift | `[TYPE_MAP]` enforces exact terminology, no synonyms |
| Chronology loss | `[PROCESSING_SEQUENCE]` step 5: `resolve_chronology (last_user_statement_wins)` |
| Noise retention | `[NOISE_DEFINITIONS]` + `[PROCESSING_SEQUENCE]` step 3: `strip_noise` |

**Result:** Output is pure JSON, validated against schema, ready for immediate consumption by downstream agents or scripts. Zero parsing. Zero cleanup. Zero ambiguity.

---

## 3. CORE DESIGN PRINCIPLES

### 1. **Zero Inference**
If the user didn't explicitly state it, it doesn't exist in the output. No implied requirements. No "helpful" additions.

### 2. **Verbatim Over Interpretation**
Extract exact substrings. Do not paraphrase. Do not "clean up" the user's language.

### 3. **Schema Before Generation**
Define the output contract first. The LLM fills slots; it doesn't invent structure.

### 4. **Processing Order Is Law**
Steps execute in exact sequence. No reordering. No skipping.

### 5. **Noise Is Measured, Not Ignored**
Track greetings, apologies, hedges, fillers. Compute `signal_quality = signal_bytes / total_bytes`.

### 6. **Chronology Is Resolved**
When the user contradicts themselves, the last statement wins. Record what was superseded.

### 7. **Hard Gates Are Fatal**
Violate a hard gate → output is invalid. No partial credit.

### 8. **Exemplars Are Mandatory**
Show the LLM exactly what good output looks like. Concrete > abstract.

---

## 4. ANATOMY OF A MACHINE TALK PROMPT

Every Machine Talk prompt follows this exact structure:

```markdown
# MACHINE TALK — TB-XXX: <AGENT_NAME>
# VERSION: <semantic_version>
# CLASSIFICATION: <role_description>

## IDENTITY
<One sentence: who this agent is, what its sole purpose is>

## INPUT CONTRACT
<JSON Schema or example of expected input structure>

## PROCESSING PROTOCOL
<Numbered list of exact steps, executed in order>
1. Step one
2. Step two
...

## OUTPUT CONTRACT
<JSON Schema or example of required output structure>

## HARD GATES
<Bulleted list of inviolable constraints>
- If X → fail
- You MUST NOT Y
- You MUST Z

## ERROR STATES
<Enumerated error conditions and how to emit them>
- `ERROR_NAME`: condition → emit this object

## [OPTIONAL] TYPE_MAP
<Enum definitions for controlled vocabulary>
  SIGNAL_TYPE → directive | constraint | preference | question
  SKIP_REASON → no_signal | static_only | noise_threshold

## [OPTIONAL] ANCHOR_SCHEMA
<Field-level schema with types and nullability>
  {
    field_name::type_or_null,
    ...
  }

## [OPTIONAL] NOISE_DEFINITIONS
<Patterns for identifying and stripping noise>
  greeting → "hi" | "hello" | "hey"
  apology → "my bad" | "sorry" | "i apologize"

## [OPTIONAL] USER_SIGNATURE_PATTERNS
<Patterns for extracting high-value user artifacts>
  heredoc_block → cat << 'EOF' ... EOF
  metadata_footer → 📑 Project: X ✔️

## [OPTIONAL] VERDICT_RULES
<Decision logic for PASS/SKIP/QUARANTINE>
  PASS → condition_a AND condition_b
  SKIP → condition_c OR condition_d

## [OPTIONAL] EXEMPLAR
<Concrete input/output example>
  {
    "example_field": "example_value"
  }
```

---

## 5. THE TWO FLAVORS

Machine Talk has two distinct use cases:

### Flavor 1: **Chat Distillation** (Dendritic Pattern)

**Purpose:** Compress raw chat transcripts into canonical, noise-free payloads.

**Example:** `tb-001-distiller.md`

**Key Features:**
- Computes `signal_quality` score (0.0-1.0)
- Tracks `noise_signature` (greeting_count, apology_count, etc.)
- Resolves chronology conflicts (last statement wins)
- Emits `skip_reason` for low-signal chats
- Extracts heredocs, metadata, constraints as artifacts

**Output Use:** Feeds downstream build agents (IntroBeaver, PlanBeaver, etc.)

---

### Flavor 2: **Inter-Agent Contracts** (Shelly Pattern)

**Purpose:** Define rigid communication protocols between autonomous agents.

**Example:** `SCHEMA.md`, `INTER_AGENT.md`, `diagnose.py`

**Key Features:**
- Envelope structure: `{role, mode, ts, server_id, instance_id, payload}`
- Role-specific payloads (e.g., `shell_diagnose` has 12 required keys)
- File-based signaling (agents read/write JSON files, no chat API)
- Validation via `schema.py` (raises `ValueError` on violation)
- Atomic writes (temp file + `os.replace`)

**Output Use:** Health monitoring, fleet orchestration, signal-based coordination.

---

## 6. HOW IT WORKS — EXECUTION FLOW

### Dendritic Chat Distillation Flow

```
┌─────────────────────────────────────────────────────────────┐
│ RAW_CHAT_SET (user + agent messages, unprocessed)           │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ DISTILLER AGENT (tb-001-distiller.md)                       │
│ 1. Hash original input                                      │
│ 2. Extract user signatures (heredocs, metadata, constraints)│
│ 3. Strip noise (greetings, apologies, hedges, fillers)      │
│ 4. Deduplicate (semantic hash match → keep first)           │
│ 5. Resolve chronology (last user statement wins)            │
│ 6. Classify signals (DIRECTIVE, CONSTRAINT, PREFERENCE)     │
│ 7. Merge fragments (same intent → single entry)             │
│ 8. Compute noise signature                                  │
│ 9. Compute signal quality                                   │
│ 10. Verdict (PASS | SKIP | QUARANTINE)                      │
│ 11. Emit JSON                                               │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ CANONICAL_PAYLOAD (validated JSON, ready for downstream)    │
│ - directives[]                                              │
│ - constraints[]                                             │
│ - preferences[]                                             │
│ - signal_quality: 0.72                                      │
│ - noise_signature: {...}                                    │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ DOWNSTREAM AGENTS (IntroBeaver, PlanBeaver, Drafter, etc.)  │
│ Each reads canonical payload, no re-parsing needed          │
└─────────────────────────────────────────────────────────────┘
```

### Shelly Inter-Agent Flow

```
┌─────────────────────────────────────────────────────────────┐
│ PROBE AGENT (probe_shell.py)                                │
│ - SSH into server                                           │
│ - Run nvidia-smi, ps, vllm health check                     │
│ - Write /workspace/shelly/health/raw/vast-4001.probe.json   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ DIAGNOSE AGENT (diagnose.py)                                │
│ - Read probe JSON                                           │
│ - Validate envelope (schema.py)                             │
│ - Apply rules (if gpu_util < 5% → state=online_broken)      │
│ - Write /workspace/shelly/health/status/vast-4001.status.json│
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ HEALTH BOARD (health_board.py)                              │
│ - Read all status files                                     │
│ - Render markdown table for humans                          │
│ - Emit signals (e.g., vast-4001.need_refeed)                │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ ORCHESTRATOR AGENT                                          │
│ - Read signals                                              │
│ - Act (refeed block, restart vllm, destroy/replace)         │
└─────────────────────────────────────────────────────────────┘
```

---

## 7. BUILDING MACHINE TALK PROMPTS

### Step 1: Define the Identity

**Bad:** "You are a helpful assistant that analyzes chat logs."

**Good:** "You are IntroBeaver. Your only purpose is to ingest a raw Chat Set and extract verbatim intent. You do not summarize. You do not interpret. You do not 'help.'"

**Rule:** One sentence. Name the agent. State its sole purpose. List what it does NOT do.

---

### Step 2: Define the Input Contract

**Bad:** "You'll get some chat messages."

**Good:**
```json
{
  "session_id": "string — UUIDv4",
  "timestamp_utc": "string — ISO 8601",
  "raw_chat_set": [
    {
      "role": "enum[USER, AGENT, SYSTEM, TOOL]",
      "content": "string — exact message text",
      "timestamp": "string — ISO 8601",
      "attachments": ["string — file paths or refs"]
    }
  ]
}
```

**Rule:** JSON object. Every field typed. Enums enumerated. Nullability explicit.

---

### Step 3: Define the Processing Protocol

**Bad:** "Analyze the chat and extract important stuff."

**Good:**
```
Execute in exact order. Do not skip. Do not reorder.

1. HASH: Compute SHA-256 of the entire raw_chat_set JSON string.
2. EXTRACT: Scan every content field where role == "USER".
3. TYPE: For each extraction, classify exactly one of: DIRECTIVE, CONSTRAINT, PREFERENCE, QUESTION.
4. ANCHOR: Record the exact substring from content that triggered the extraction.
5. CHAIN: Link each extraction to its source message index.
6. SIGN: Generate RSA-2048 signature of input_hash.
```

**Rule:** Numbered steps. Imperative mood. No ambiguity. Order is law.

---

### Step 4: Define the Output Contract

**Bad:** "Output JSON with the extracted info."

**Good:**
```json
{
  "introbeaver_output": {
    "session_id": "string",
    "input_hash": "string — SHA-256 hex",
    "extracted_count": "integer",
    "direct_verbatim_instructions": [
      {
        "entry_id": "string — TB001-{session_id}-{index}",
        "source_msg_index": "integer",
        "verbatim_text": "string — exact extracted sentence",
        "instruction_type": "enum[DIRECTIVE, CONSTRAINT, PREFERENCE, QUESTION]",
        "confidence": "float — 0.00 to 1.00"
      }
    ]
  }
}
```

**Rule:** Every field named. Every type specified. IDs follow naming convention.

---

### Step 5: Define Hard Gates

**Bad:** "Try to be accurate."

**Good:**
```
- If confidence < 0.85 on any extraction, flag as UNCERTAIN and require human resolution.
- If raw_anchor cannot be proven as a substring of the source content, discard the extraction.
- QUESTION entries block all downstream Beavers. Emit block_reason: "UNRESOLVED_QUESTION".
- You MUST NOT infer implied requirements.
- You MUST NOT synthesize across multiple messages.
- If raw_chat_set contains zero USER messages, emit extracted_count: 0 and status: "NO_INTENT".
```

**Rule:** Binary conditions. Clear failure modes. No "try".

---

### Step 6: Define Error States

**Bad:** "Handle errors gracefully."

**Good:**
```
- `INVALID_INPUT`: Input missing required fields → emit error object, halt.
- `HASH_MISMATCH`: If re-run on same Chat Set produces different hash → fatal internal error.
- `EXTRACTION_FAILURE`: Zero extractions from non-empty USER content → emit status: "LOW_SIGNAL" with warning.
```

**Rule:** Named errors. Exact emission format. Clear halting behavior.

---

### Step 7: Add an Exemplar

**Bad:** No example.

**Good:**
```json
{
  "session_id": "sess_abc123",
  "input_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "extracted_count": 3,
  "direct_verbatim_instructions": [
    {
      "entry_id": "TB001-sess_abc123-0",
      "source_msg_index": 2,
      "verbatim_text": "build a zero-dependency Python CLI",
      "instruction_type": "DIRECTIVE",
      "confidence": 0.95
    }
  ]
}
```

**Rule:** Concrete values. Realistic data. Matches schema exactly.

---

## 8. REAL-WORLD EXAMPLES

### Example 1: Chat Distillation (Dendritic)

**File:** `/home/flintx/dendritic/machine-talk/tb-001-distiller.md`

**Purpose:** Compress raw chat logs into canonical payloads.

**Key Sections:**
- `TYPE_MAP`: Defines SIGNAL_TYPE, COMPACTION_ACTION, ARTIFACT_TYPE
- `ANCHOR_SCHEMA`: 20-field output schema with nested objects
- `PROCESSING_SEQUENCE`: 11 steps, exact order
- `VERDICT_RULES`: PASS/SKIP/QUARANTINE logic
- `NOISE_DEFINITIONS`: Patterns for greetings, apologies, hedges, fillers
- `USER_SIGNATURE_PATTERNS`: Heredocs, metadata footers, constraint blocks

**Output:** JSON with `signal_quality`, `noise_signature`, `chronology_resolved`, `directives[]`, `constraints[]`.

---

### Example 2: Inter-Agent Health Contract (Shelly)

**File:** `/home/flintx/shelly/machine_talk/SCHEMA.md` + `schema.py`

**Purpose:** Validate health messages between probe/diagnose/orchestrator agents.

**Key Sections:**
- Envelope: `{role, mode, ts, server_id, instance_id, payload}`
- Role enum: `shell_probe`, `shell_diagnose`, `fleet_health`, etc.
- Payload schema: 12 required keys for `shell_diagnose`
- Validation: `validate_envelope()` raises `ValueError` on violation
- I/O: `write_status()` uses atomic temp file + `os.replace()`

**Output:** `/workspace/shelly/health/status/vast-4001.status.json`

---

### Example 3: Build Pipeline Agent (Dendritic)

**File:** `/home/flintx/dendritic/machine-talk/tb-005-planbeaver.md`

**Purpose:** Transform user intent into deterministic build plan.

**Key Sections:**
- `IDENTITY`: "You are PlanBeaver. Your only purpose is to transform raw user intent into a deterministic build plan. You do NOT write code."
- `PROCESSING PROTOCOL`: 6 steps (DECOMPOSE, FILE_MAP, FUNCTION_SPECS, DATA_CONTRACTS, SEQUENCE, RISK_FLAG)
- `OUTPUT CONTRACT`: Files[], data_contracts[], execution_sequence[], risk_flags[]
- `HARD GATES`: "You MUST NOT write implementation logic", "estimated_lines > 500 triggers automatic file decomposition"

**Output:** Plan with file paths, function signatures, dependencies, topological sort.

---

## 9. COMMON PITFALLS

### Pitfall 1: **Prose Creep**

**Symptom:** LLM outputs "Here's the extraction you requested..." before the JSON.

**Fix:** Add `[HARD_GATES] prose_output → ∅` and `[MODE::strict_json_output]`.

---

### Pitfall 2: **Synonym Drift**

**Symptom:** User says "build CLI" → LLM outputs "create command-line interface".

**Fix:** Add `[TYPE_MAP]` with exact terminology. Enforce "no synonyms" in hard gates.

---

### Pitfall 3: **Chronology Loss**

**Symptom:** User changes mind 3 times → output merges all 4 versions.

**Fix:** Add `[PROCESSING_SEQUENCE] resolve_chronology (last_user_statement_wins)` and `chronology_resolved` field in schema.

---

### Pitfall 4: **Noise Retention**

**Symptom:** Greetings, apologies, hedges all preserved in output.

**Fix:** Add `[NOISE_DEFINITIONS]` and `[PROCESSING_SEQUENCE] strip_noise`. Compute `signal_quality`.

---

### Pitfall 5: **Schema Violation**

**Symptom:** LLM omits required fields or invents new ones.

**Fix:** Add `[ANCHOR_SCHEMA]` with explicit types. Add validation step to processing sequence. Provide exemplar.

---

### Pitfall 6: **Inference Overreach**

**Symptom:** LLM adds "helpful" implied requirements not stated by user.

**Fix:** Add hard gate: "You MUST NOT infer implied requirements. If the user did not explicitly state it, it does not exist."

---

## 10. REFERENCE FILES

### Dendritic (Chat Distillation)

| File | Purpose |
|------|---------|
| `/home/flintx/dendritic/machine-talk/tb-001-distiller.md` | Chat distillation agent |
| `/home/flintx/dendritic/machine-talk/tb-004-introbeaver.md` | Intent extraction agent |
| `/home/flintx/dendritic/machine-talk/tb-005-planbeaver.md` | Build plan architect |
| `/home/flintx/dendritic/machine-talk/cli-manifest.json` | 7-agent pipeline manifest |

### Shelly (Inter-Agent Contracts)

| File | Purpose |
|------|---------|
| `/home/flintx/shelly/machine_talk/SCHEMA.md` | Envelope + payload schema |
| `/home/flintx/shelly/machine_talk/INTER_AGENT.md` | File paths + agent rules |
| `/home/flintx/shelly/machine_talk/AGENT_LAW.md` | Communication laws |
| `/home/flintx/shelly/machine_talk/schema.py` | Python validator + I/O helpers |
| `/home/flintx/shelly/machine_talk/diagnose.py` | Probe → diagnosis pure function |

---

## SUMMARY

**Machine Talk turns LLMs from chat partners into deterministic function executors.**

- **Structure:** Identity → Input → Processing → Output → Hard Gates → Errors → Exemplar
- **Discipline:** No prose, no markdown, no synonyms, no inference, no chronology loss
- **Validation:** Schema-first, hard gates, self-test scripts
- **Two Flavors:** Chat distillation (Dendritic) vs. inter-agent contracts (Shelly)

**Build it right, and your agents will communicate like machines: fast, precise, zero ambiguity.**
