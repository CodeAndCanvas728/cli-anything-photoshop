# TEST.md — cli-anything-photoshop

## Part 1 — Test plan (written before implementation)

### Inventory plan
- `test_core.py` — unit tests, synthetic data, no Photoshop: ~14 tests
- `test_full_e2e.py` — real Photoshop pipeline + installed-CLI subprocess: ~10 tests

### Unit test plan (`test_core.py`)
- `test_backend.py`-level logic (imported through modules):
  - `qr()` escaping (quotes, backslashes, newlines, control chars)
  - `parse_records()` splitting on RS/US, empty input handling
  - `_translate_osascript_error()` mapping: -1712 (busy/timeout), permission text, passthrough
  - `find_photoshop()` env override behavior (`CLI_ANYTHING_PHOTOSHOP_APP`)
  - session: locked save/load round-trip, corrupt-file recovery, record/clear
  - `export._check_overwrite` refusal without `--overwrite`
  - `export._verify_output` magic-byte checks (png/psd) on synthetic bytes
  - documents: `_strip_px('64 px')`, `_doc_selector_js` (null/name/index)
  - history `history_step` offset validation (0 rejected)
  - CLI: `--help` renders, group wiring, REPL default when no subcommand

### E2E test plan (`test_full_e2e.py`) — the REAL Photoshop, no graceful degradation
1. **Backend direct**: discover app, `run_js` lives (version string)
2. **Document workflow**: new 64×64 → info dims → layer new text/art → layer set
   opacity/visible → flip → rotate → resize-canvas → flatten → export PNG/JPG/PSD
   → close (discard) → PSD re-open round-trip
3. **Output verification**: PNG (`\x89PNG`), JPEG (`\xff\xd8\xff`), PSD (`8BPS`)
   magic bytes, sizes > 0 (never trust exit codes)
4. **Adjustments**: invert/desaturate/auto-contrast on art layer; posterize/threshold
   with amounts
5. **History**: states grow after mutations, undo steps back, redo steps forward
6. **Conversion**: PSD → JPEG convert via Photoshop, magic verified
7. **Subprocess tests** via `_resolve_cli("cli-anything-photoshop")` (installed
   command; `CLI_ANYTHING_FORCE_INSTALLED=1`): `--help`, `app info --json`,
   doc new → layer list → export → verify file (full pipeline in one flow)

### Realistic workflow scenario
- **"photo-touch-up pipeline"**: create doc → text layer watermark →
  adjustments on art layer → history walk-back → export PNG + PSD.
  Artifact paths printed for manual inspection.

## Part 2 — Test results (appended after implementation, Phase 6)

Executed on macOS against the real **Adobe Photoshop 2026 (27.10.0)** with
the installed CLI (`CLI_ANYTHING_FORCE_INSTALLED=1`):

```
$ PATH="$PWD/.venv/bin:$PATH" CLI_ANYTHING_FORCE_INSTALLED=1 \
    .venv/bin/python -m pytest cli_anything/photoshop/tests -q -s
40 passed in 14.74s
```

Key E2E results (real artifacts, paths printed during the run):

| Check | Result |
|---|---|
| `test_backend_lives` (live `do JavaScript`) | PASS — version 27.10.0 |
| doc new → info → layers → transforms → flatten | PASS |
| text set/get, visibility, opacity (quantized 42→41.96) | PASS |
| adjustments: invert/desaturate/auto-contrast/posterize/threshold | PASS on pixel layers; empty art layer fails LOUDLY (asserted) |
| history: list grows, undo/redo changes the current state | PASS |
| export PNG / JPEG / PSD with magic-byte verification | PASS (14,321 / 8,379 / 22,508 bytes) |
| PSD re-open round-trip (size + name) | PASS |
| PSD → JPEG conversion through Photoshop | PASS (12,417 bytes) |
| `TestCLISubprocess` (installed command, `_resolve_cli`) | PASS — help, app info JSON, full doc→export→close pipeline (PNG 5,073 bytes), clean error for missing layer |

### Coverage notes / gaps

- TIFF export and `equalize()` are **not covered** because the engine
  (Photoshop 2026) cannot perform them — the CLI errors loudly instead
  (asserted in `test_adjustments_flow` for empty layers only; TIFF is
  rejected by `export` argument validation, unit-covered).
- Adjustments on empty art layers fail by design (engine behavior);
  cover with pixel-bearing layers.
- AppleScript Automation permission is an environment prerequisite, not a
  test; the backend maps its failure to an actionable message
  (unit-tested translation).
- Layer names containing the `\x1e`/`\x1f` separators are outside the
  packing contract (documented limitation).
