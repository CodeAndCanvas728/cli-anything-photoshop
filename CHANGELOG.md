# Changelog

All notable changes to `cli-anything-photoshop`. Semantic versioning; each
release is a git tag on `main` that the CLI-Hub registry entry pins.

## 1.0.1 — 2026-10-31

- **Fail clearly off macOS.** `find_photoshop()` now checks the platform
  before looking for the app, so Linux/Windows get
  "cli-anything-photoshop requires macOS … there is no Linux or Windows
  backend" instead of the misleading "Adobe Photoshop not found in
  /Applications". Documentation already said macOS-only; behaviour now
  matches it. Covered by a unit test.

## 1.0.0 — 2026-10-31

- First release. Drives the running Adobe Photoshop application on macOS
  through AppleScript / ExtendScript (`do JavaScript`); no reimplementation
  in Python.
- Command groups: `app`, `open`, `doc`, `layer`, `adj`, `history`, `export`,
  `session`, plus a REPL as the no-argument default. Global `--json`,
  `--doc <name|index>` and `--timeout`.
- Exports PNG / JPEG / PSD with magic-byte verification; converts any file
  Photoshop can open. Adjustments need pixel-bearing layers. The engine has
  no constructible TIFF save options and no `equalize()`, so those are not
  offered rather than silently downgraded.
