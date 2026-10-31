# cli-anything-photoshop

Agent-native CLI for **Adobe Photoshop 2026** on macOS. Every command talks
to the *real* running Photoshop through AppleScript (`do JavaScript`) — the
app does all rendering and editing; the CLI is a structured, scriptable
control surface built with the CLI-Anything HARNESS.md methodology.

## Requirements

- Adobe Photoshop installed in `/Applications` (built & verified against
  Photoshop 2026 v27.10.0; overrides via `CLI_ANYTHING_PHOTOSHOP_APP`).
- macOS + AppleScript Automation permission for your terminal.
- Python 3.10+.

## How to run

```bash
cd photoshop/agent-harness
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/cli-anything-photoshop --help
```

No arguments starts the **REPL**. Global options before the subcommand:
`--json`, `--doc <name|index>`, `--timeout <seconds>`.

## Command overview

| Group | Purpose |
|---|---|
| `app` | info (launch-free probe), launch, quit |
| `open` | open a file as a document |
| `doc` | new/list/info/flatten/resize/rotate/flip/close |
| `layer` | list/info/new (art/text)/text-get/text-set/visible/opacity/blend/select/rename/delete/merge-down |
| `adj` | invert, desaturate, auto-contrast, auto-levels, posterize, threshold |
| `history` | list, undo, redo, step |
| `export` | document → png/jpg/psd (magic bytes verified); convert any openable file |
| `session` | last-doc + command trail memory |
| `repl` | interactive mode |

Run tests: `.venv/bin/python -m pytest cli_anything/photoshop/tests -v`
(unit tests are hermetic; `test_full_e2e.py` drives the real Photoshop).

Agent usage: read `skills/SKILL.md` (also installed for skill discovery
under `cli_anything/photoshop/skills/SKILL.md`).

More background: `../PHOTOSHOP.md`.
