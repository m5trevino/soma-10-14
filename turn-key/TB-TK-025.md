[[ ---
name: trevino-tk-025-provider-tools-context-badges
slice: TB-TK-025
status: unbuilt
---

# Add Provider/Tools/Context Badges to TurnKey Model Pool Cards

**Scope**: `profile_builder/solid/src/components/ModelPool.tsx` + `src/index.css` only.
**Hard gate**: DO NOT touch the `turnkey/` Python SDK, `DeckManager`, `StagePinner`, `PipelinePanel`, `ProfileIO`, `App.tsx`, `types.ts`, or any store file. This is a view-only frontend change.

**Framework**: SolidJS (TypeScript) + Vite
**Project root**: `/root/hetzner/ai-engine/turn-key/profile_builder/solid/`
**Build command**: `npm run build` (then refresh browser)
**Dev server**: `npm run dev`

## What the User Wants

In the **Available Models** grid, each model card currently shows name, id, tier badge, and context badge. Add three button-style badges on every card:

1. **Provider badge** — shows provider name (e.g. "OpenRouter", "Ollama", "xKiro"). Currently only in the filter dropdown, NOT on the card. **This is the only missing badge.**
2. **Tools badge** — already renders when `model.toolsSupported` is true. Keep it as-is.
3. **Context badge** — already renders showing context window size (e.g. "ctx 128K"). Keep it as-is.

## What to Edit (2 files ONLY)

### File 1: `src/components/ModelPool.tsx` (line 77)

In the card's right-side badge column (`<div style={{ display: 'flex', 'flex-direction': 'column', gap: '4px', 'align-items': 'center' }}>`), add the provider badge as the FIRST badge:

```tsx
<span class="badge badge-provider">{model.provider}</span>
```

Insert this as line 78 (after the opening `<div>` on line 77, before the existing tools badge). The final right-column stack should be:

```tsx
<div style={{ display: 'flex', 'flex-direction': 'column', gap: '4px', 'align-items': 'center' }}>
  <span class="badge badge-provider">{model.provider}</span>          ← ADD THIS
  {model.toolsSupported && <span class="badge badge-tools">tools</span>}   ← already exists
  <span class={`badge ${tierClass(model.tier)}`}>{model.tier || 'unknown'}</span>  ← already exists
  {model.contextWindow && <span class="badge badge-context">ctx {formatNumber(model.contextWindow)}</span>}  ← already exists
</div>
```

### File 2: `src/index.css`

Verify these CSS rules exist. Add them if missing:

```css
.badge-provider { background: #1f2937; color: var(--dim); border: 1px solid var(--border); }
.badge-tools { background: #1a3a2a; color: var(--green); border: 1px solid #238636; }
.badge-context { background: #1a2a3a; color: #58a6ff; border: 1px solid #1f6feb; }
```

The base `.badge` rule must exist (it does on line 56):
```css
.badge { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 12px; font-weight: 600; }
```

## Build & Verify

1. Run `npm run build` in `/root/hetzner/ai-engine/turn-key/profile_builder/solid/`
2. Open profile builder in browser
3. Confirm each card in the model grid shows four badges in this order:
   - Provider name (e.g., "OpenRouter")
   - "tools" (if `toolsSupported` is true)
   - Tier label (e.g., "free", "cheap", "expensive")
   - Context window (e.g., "ctx 128K")

## Files to NOT Touch

`turnkey/` directory, `stores/deckStore.ts`, `components/DeckManager.tsx`, `components/StagePinner.tsx`, `components/PipelinePanel.tsx`, `components/ProfileIO.tsx`, `App.tsx`, `types.ts`, `package.json`, `vite.config.ts`.

## Unbuilt Slices

- TB-TK-026: Add stage execution panel (visual pipeline runner with progress indicators)
- TB-TK-027: Add profile import from file upload (drag-and-drop .json profile import)
- TB-TK-028: Add export to clipboard / save to engine endpoints

]]