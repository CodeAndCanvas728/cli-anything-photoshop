# PHOTOSHOP.md — CLI-Anything harness analysis & SOP

Software: **Adobe Photoshop 2026** (`/Applications/Adobe Photoshop 2026/Adobe
Photoshop 2026.app`), macOS, closed-source, scripting version 27.10.0.
License: proprietary (Adobe Creative Cloud). There is no source repo; we build
the harness purely against the app's own automation surfaces, following
`cli-anything-plugin/HARNESS.md`.

## Phase 1 — Automation-surface analysis (closed GUI app)

Photoshop has no source, but ships a complete scripting stack:

1. **AppleScript scripting dictionary** —
   `Contents/Resources/Photoshop.sdef` (2567 lines, 13 suites). Its
   `AdobeScriptAutomation` suite exposes `do JavaScript` (`jsTx` — text to
   execute inside Photoshop's JS engine). This is the primary bridge.
2. **ExtendScript DOM** inside `do JavaScript`: `Application`, `Document`,
   `ArtLayer`, `LayerSets`, `TextItem`, save-options classes, history states.
3. **AppleScript permission**: the calling terminal needs
   *Privacy & Security → Automation* permission for Photoshop (verified
   live: `osascript -e 'tell app "Adobe Photoshop 2026" to get version'` →
   `27.10.0`).

**Transport decision (verified experimentally, 4 probe rounds):** every
operation runs a compiled ExtendScript program via
`osascript → do JavaScript`, reading the JS from a temp file
(`read (POSIX file "…") as «class utf8»`) — zero shell/AppleScript string
escaping issues. Python (`utils/photoshop_backend.py`) compiles snippets,
normalizes application state (`displayDialogs = NO`, units = px, restored in
a `finally` block), and maps osascript errors (−1712 busy/timeout,
−1743 permission) to actionable messages. This follows the HARNESS backend
rule: *the real software does the work* — the CLI is structured control of
the app, never a reimplementation.

## Engine facts verified live (design inputs)

| Fact (verified) | Consequence |
|---|---|
| `documents.add(w,h,res,name,mode,fill,bits)` — bits numeric; no `DocumentBits`/`BitsPerChannelType` | `doc new` uses 7-arg form, plain int bits |
| Text layers: `LayerKind.TEXT` (no `TEXT_LAYER`) | `layer new --kind text` |
| PSD save class: `PhotoshopSaveOptions` (not `PSDSaveOptions`) | `export document --format psd` |
| `TIFFSaveOptions` not constructible in engine | TIFF export not offered; loud error |
| `equalize()` raises general engine error | not exposed |
| PNG/JPEG save + PSD open verified with real files + magic bytes | E2E asserts outputs |
| `historyStates` list + `activeHistoryState` assignment | history undo/redo/step |
| `d.dirty` is `undefined` in this engine | not used anywhere |

## Phase 2 — CLI architecture

- **Subcommand CLI + stateful REPL** (REPL is the no-arg default).
- Command groups mirror Photoshop domains: `app`, `doc`, `layer`, `adj`,
  `history`, `export`, `session`, plus `open`.
- **Document targeting:** global `--doc <name|index>` (default active doc);
  layer commands take `--layer <name>` (default active layer; name search is
  depth-first incl. layer sets).
- **State model:** Photoshop owns per-document state/undo; the CLI adds a
  tiny workspace session (`~/.cli-anything-photoshop/session.json`, locked
  writes) remembering the last doc + recent commands.
- **Output:** human tables by default; `--json` wraps every result as
  `{"ok": true, "data": …}`. ExtendScript ↔ Python data flows as packed
  strings with `\x1e/\x1f` delimiters.

## Notable limitations (documented, not hidden)

- Photoshop must be running (or auto-launches); mutating commands act on a
  live app, and `doc close` defaults to *discarding* changes to never hang
  on a modal save dialog (explicit `--save` writes in place when the doc has
  a path).
- AppleScript permission prompt appears once per calling terminal.
- Layer names containing `\x1e`/`\x1f` are outside the packed-string
  contract (practically unreachable input).
