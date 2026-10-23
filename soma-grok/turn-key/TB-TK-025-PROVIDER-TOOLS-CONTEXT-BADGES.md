# Tracer Bullet: Add Provider/Tools/Context Badges to TurnKey Model Pool Cards

**Slice**: TB-TK-025 — Three badge buttons on each model card in `ModelPool.tsx`
**Scope**: Frontend only — `profile_builder/solid/src/components/ModelPool.tsx` + `src/index.css`
**Hard gate**: DO NOT touch the `turnkey/` Python SDK. DO NOT touch `DeckManager`, `StagePinner`, `PipelinePanel`, or `ProfileIO`. This is a **view-only** UI change.

---

## Context for the Bot

- **Framework**: SolidJS (TypeScript) + Vite
- **Project root**: `/root/hetzner/ai-engine/turn-key/profile_builder/solid/`
- **Build command**: `npm run build` (then refresh browser)
- **Dev server** (if running): `npm run dev`
- **Source file to edit**: `src/components/ModelPool.tsx`
- **CSS to augment**: `src/index.css`
- **Data flow**: `App.tsx` fetches from `GET /v1/models` (engine), maps to `ModelEntry[]`, stores in `useDeckStore().setAvailableModels()`. Each `ModelEntry` has: `id`, `name`, `provider`, `tier?`, `toolsSupported?`.

## What the User Wants

In the **Available Models** grid (the `model-pool-grid` div), each model card currently shows the name, id, tier badge, and context badge. The user wants **three button-style badges** on every card:

1. **Provider badge** — shows the provider name (e.g. "OpenRouter", "Ollama", "xKiro", "Google"). Currently only in the filter dropdown, not on the card.
2. **Tools badge** — already renders when `model.toolsSupported` is true. Keep it.
3. **Context badge** — already renders showing context window size. Keep it.

The badges should look like the existing `badge-*` CSS classes but styled for their specific semantic (provider = neutral, tools = green, context = blue/teal).

---

## Step-by-Step

### STEP 1 — Add provider badge to the card

In `ModelPool.tsx`, in the card template (lines 68-83), add a provider badge **inside** the right-side column (`<div style={{ display: 'flex', 'flex-direction': 'column', gap: '4px', 'align-items': 'center' }}>`) as the **first** badge.

**Patch location**: After the opening tag of the right-column div on line 77, add:

```tsx
<span class="badge badge-provider">{model.provider}</span>
```

This places the provider name as the top badge in the vertical stack on the right side of each card.

### STEP 2 — Verify tools badge is present and correct

Line 78 already contains:
```tsx
{model.toolsSupported && <span class="badge badge-tools">tools</span>}
```

Verify it exists and is NOT removed. It's already correct — just confirm it's still there.

### STEP 3 — Verify context badge is present and correct

Line 80 already contains:
```tsx
{model.contextWindow && <span class="badge badge-context">ctx {formatNumber(model.contextWindow)}</span>}
```

Verify it exists and is NOT removed. It formats as "ctx 128K" or "ctx 2M" etc. This is already correct — just confirm it's still there.

### STEP 4 — Add CSS for provider badge styling

In `src/index.css`, after the existing `.badge-provider` line (line 63), verify the CSS rule exists. Add it if missing:

```css
.badge-provider { background: #1f2937; color: var(--dim); border: 1px solid var(--border); }
```

Also verify the existing badge CSS rules are present (line 56-66):
```css
.badge { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 12px; font-weight: 600; }
.badge-provider { background: #1f2937; color: var(--dim); border: 1px solid var(--border); }
.badge-pinned { background: #1a3a2a; color: var(--green); border: 1px solid #238636; }
.badge-deck { background: #2a1f36; color: var(--purple); border: 1px solid #6e40c9; }
.badge-tools { background: #1a3a2a; color: var(--green); border: 1px solid #238636; }
.badge-context { background: #1a2a3a; color: #58a6ff; border: 1px solid #1f6feb; }
.badge-apex { background: #3a2a1a; color: var(--yellow); border: 1px solid #9e6a03; }
.badge-balanced { background: #1a3a1a; color: var(--green); border: 1px solid #238636; }
.badge-stealth { background: #1a2a2a; color: #58a6ff; border: 1px solid #1f6feb; }
.badge-unknown { background: #1a1a2a; color: var(--dim); border: 1px solid var(--border); }
```

If `.badge-tools` and `.badge-context` are missing, add them.

### STEP 5 — Verify the card layout

The card layout structure should be:
```
<div class="pool-item">
  <!-- Left: name + id -->
  <div style={{ flex: 1, minWidth: 0 }}>
    <div>model.name</div>
    <div style="font-size:11px;color:dim">{model.id}</div>
  </div>
  <!-- Right: vertical stack of badges -->
  <div style={{ display:flex, flexDirection:column, gap:4px, alignItems:'center' }}>
    <span class="badge badge-provider">{model.provider}</span>  ← ADDED
    {model.toolsSupported && <span class="badge badge-tools">tools</span>}  ← ALREADY EXISTS
    <span class={`badge ${tierClass(model.tier)}`}>{model.tier || 'unknown'}</span>  ← ALREADY EXISTS
    {model.contextWindow && <span class="badge badge-context">ctx {formatNumber(model.contextWindow)}</span>}  ← ALREADY EXISTS
  </div>
</div>
```

### STEP 6 — Build and verify

Run `npm run build` in `/root/hetzner/ai-engine/turn-key/profile_builder/solid/`
Verify the built output contains the provider badge rendering.
Open the profile builder in a browser and confirm each card shows four badges:
  1. Provider name (e.g., "OpenRouter")
  2. "tools" (if `toolsSupported` is true)
  3. Tier label (e.g., "free", "cheap", "expensive")
  4. Context window (e.g., "ctx 128K")

---

## Files to Modify (ONLY these)

| File | Action |
|------|--------|
| `profile_builder/solid/src/components/ModelPool.tsx` | Add provider badge line after line 77 |
| `profile_builder/solid/src/index.css` | Verify/add `.badge-tools` and `.badge-context` CSS rules if missing |

## Files to NOT Touch

- `turnkey/` directory (Python SDK)
- `profile_builder/solid/src/stores/deckStore.ts`
- `profile_builder/solid/src/components/DeckManager.tsx`
- `profile_builder/solid/src/components/StagePinner.tsx`
- `profile_builder/solid/src/components/PipelinePanel.tsx`
- `profile_builder/solid/src/components/ProfileIO.tsx`
- `profile_builder/solid/src/App.tsx`
- `profile_builder/solid/src/types.ts`