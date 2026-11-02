---
name: "cli-anything-photoshop"
description: "Agent-native CLI for controlling the real Adobe Photoshop 2026 app on macOS: documents, layers, text, adjustments, history, PNG/JPEG/PSD export and conversion — every command runs inside the live Photoshop via AppleScript."
---

# cli-anything-photoshop

Control the **running** Photoshop 2026 application from the command line.
All rendering and mutation happens inside Photoshop (AppleScript `do
JavaScript` bridge); nothing is reimplemented in Python.

## Install prerequisites

1. **Adobe Photoshop** (Creative Cloud) — hard dependency; verified with
   Photoshop 2026 v27.10.0. Any recent version at
   `/Applications/Adobe Photoshop*.app` is auto-detected
   (override: `CLI_ANYTHING_PHOTOSHOP_APP=/path/to/Photoshop.app`).
2. **AppleScript permission**: your terminal app needs
   *System Settings → Privacy & Security → Automation* access
   to Photoshop (first `osascript` call prompts once).
3. Install the CLI in a venv: `cd photoshop/agent-harness && python -m venv
   .venv && .venv/bin/pip install -e .` then use `.venv/bin/cli-anything-photoshop`
   (or activate the venv).

## Key rules for agents

- Always pass `--json` before the subcommand for machine-readable output:
  `cli-anything-photoshop --json layer list` → `{"ok": true, "data": …}`.
- Target a specific document with the **global** `--doc <name|index>`
  (before the subcommand). Default target = active document.
- Mutating commands act on the live app: Photoshop auto-launches when needed
  (`app info` is launch-free). Use `--timeout` for slow operations.
- `doc close` **discards changes by default** (`--save` only when the doc
  has a file path) — no modal save-dialog hang.
- Errors are on stderr with actionable text (e.g. Automation permission,
  Photoshop busy).
- TIFF export is not offered (engine limitation); equalize() is not exposed
  (verified failure) — posterize/threshold take `--amount`.
- `doc resize-image` **fails on Photoshop 27.10** with every argument form
  (`--width`, `--height`; both together is refused by the CLI): Photoshop
  answers `Illegal argument - argument 3, Numeric value expected`. Do not
  retry variants. To get an exact pixel size, set it before Photoshop sees the
  file: it opens an SVG at 300 dpi, so an SVG with root `width="1280"` exports
  at 5333 px. Render from a copy whose root `width`/`height` are scaled by
  72/300 (307.2 x 153.6 gives exactly 1280 x 640), editing only the root
  `<svg>` line. Then `export convert in.svg out.png --overwrite`.
  *Verified 2026-11-03:* 1280 x 640 PNG from a scaled copy; the three
  `resize-image` forms each failed. Photoshop's PNG export is also
  uncompressed-heavy (2.4 MB for a flat 1280 x 640 card): recompress it with
  `vert convert in.png -t png -q medium -o out.png` (23 KB, no visible change).

## Command groups (all support `--json`; context before subcommand)

```bash
cli-anything-photoshop app info                       # status, no launch
cli-anything-photoshop app launch [--wait N]
cli-anything-photoshop app quit
cli-anything-photoshop open /abs/path/image.tif       # open file as doc

cli-anything-photoshop --doc "Name" doc list          # open documents
cli-anything-photoshop doc new --width 1920 --height 1080 \
   [--dpi 72] [--name CLI] [--mode rgb|grayscale|cmyk|lab] \
   [--fill white|transparent|background] [--bits 8|16|32]
cli-anything-photoshop --doc "CLI" doc info
cli-anything-photoshop --doc "CLI" doc flatten
cli-anything-photoshop --doc "CLI" doc resize-image --width 512         # BROKEN on PS 27.10, see Key rules
cli-anything-photoshop --doc "CLI" doc resize-canvas --width 100 --height 80
cli-anything-photoshop --doc "CLI" doc rotate --degrees 90            # 90|-90|180
cli-anything-photoshop --doc "CLI" doc flip --axis vertical
cli-anything-photoshop --doc "CLI" doc close [--save]

cli-anything-photoshop --doc "CLI" layer list         # depth-first, nested included
cli-anything-photoshop --doc "CLI" layer info [--layer NAME]
cli-anything-photoshop --doc "CLI" layer new --kind text --name Watermark
cli-anything-photoshop --doc "CLI" layer text-get --layer Watermark
cli-anything-photoshop --doc "CLI" layer text-set --layer Watermark "© 2026"
cli-anything-photoshop --doc "CLI" layer visible --layer L --state hide
cli-anything-photoshop --doc "CLI" layer opacity --layer L 50
cli-anything-photoshop --doc "CLI" layer blend --layer L multiply
cli-anything-photoshop --doc "CLI" layer select --layer L   # make active
cli-anything-photoshop --doc "CLI" layer rename --old --layer L --new-name N2
cli-anything-photoshop --doc "CLI" layer delete --layer L
cli-anything-photoshop --doc "CLI" layer merge-down --layer L

cli-anything-photoshop --doc "CLI" adj run invert [--layer L]
cli-anything-photoshop --doc "CLI" adj run posterize --amount 8 --layer L
cli-anything-photoshop --doc "CLI" adj run threshold --amount 128 [--layer L]
# also: desaturate | auto-contrast | auto-levels

cli-anything-photoshop --doc "CLI" history list
cli-anything-photoshop --doc "CLI" history undo      # one state back
cli-anything-photoshop --doc "CLI" history redo      # one state forward
cli-anything-photoshop --doc "CLI" history step -- -3

cli-anything-photoshop --doc "CLI" export document /abs/out.png [--format png|jpg|jpeg|psd] [--quality 0-12] [--overwrite]
cli-anything-photoshop export convert /abs/in.psd /abs/out.jpg [--overwrite]

cli-anything-photoshop session status                # last doc + trail (~/.cli-anything-photoshop)
cli-anything-photoshop repl                          # interactive (also the no-arg default)
```

## Verified workflows (examples)

```bash
# Watermark pipeline on a new code-generated canvas:
cli-anything-photoshop --json doc new --width 1080 --height 240 --name Stamp --fill transparent
cli-anything-photoshop --doc Stamp --json layer new --kind text --name WM
cli-anything-photoshop --doc Stamp layer text-set --layer WM "Made with CLI-Anything"
cli-anything-photoshop --doc Stamp export document /tmp/stamp.psd --overwrite
cli-anything-photoshop --doc Stamp doc close          # discards the in-app doc

# Convert anything Photoshop opens (TIFF→JPEG, PNG→PSD, …):
cli-anything-photoshop export convert /abs/input.tiff /abs/output.jpg --overwrite
```

## JSON contract

`{"ok": true, "data": <payload>}` — payload shape per command is stable:
documents/rows use keys `name|index|width_px|height_px|mode`;
layers `name|kind|visible|opacity|depth|parent`; export results
`output|format|bytes`. Errors exit non-zero with a message on stderr.
