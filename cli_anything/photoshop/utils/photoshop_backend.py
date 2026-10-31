"""Backend that drives the *real* Adobe Photoshop application on macOS.

Transport: AppleScript -> Photoshop's ``AdobeScriptAutomation`` suite
(``do JavaScript``). Every CLI operation compiles a small ExtendScript
program, runs it inside the live Photoshop process, and parses the result.
Photoshop itself is a hard dependency: if it is not installed, the CLI
fails loudly with install guidance (HARNESS.md rule).

Engine facts verified live against Photoshop 2026 (27.10.0) on macOS:

- ``app.documents.add (w, h, res, name, mode, fill, bits)`` — ``bits`` is a
  plain number here; ``DocumentBits``/``BitsPerChannelType`` do NOT exist.
- Text layers use ``LayerKind.TEXT`` (``TEXT_LAYER`` is not defined).
- PSD save options class is ``PhotoshopSaveOptions`` (not ``PSDSaveOptions``).
- ``TIFFSaveOptions`` is not constructible in this engine (TIFF export is
  therefore not offered).
- ``ArtLayer.equalize()`` raises a general engine error (not offered).
- Saving/opening files directly from scripting works when *this* process
  (the terminal) holds AppleScript permission for Photoshop.
"""

from __future__ import annotations

import glob
import os
import subprocess
import tempfile

__all__ = [
    "PhotoshopError",
    "find_photoshop",
    "photoshop_running",
    "run_js",
    "strict_js",
    "qr",  # quote a Python string for embedding in ExtendScript
    "RS",  # record separator (between list entries)
    "US",  # unit separator (between record fields)
    "EXPECTED_MISSING_ERROR",
]

RS = "\x1e"  # record separator between packed list entries
US = "\x1f"  # field separator inside a packed record

# Photoshop reports "General Photoshop error" when an API is missing in the
# host engine (e.g. TIFFSaveOptions, equalize()); callers use it to produce a
# clean, actionable message instead of raw noise.
EXPECTED_MISSING_ERROR = "General Photoshop error occurred"


class PhotoshopError(RuntimeError):
    """Raised when the Photoshop backend cannot complete an operation."""


def _binary_paths() -> list[str]:
    try:
        # Also search one level deep: Photoshop often installs under a
        # version folder (/Applications/Adobe Photoshop 2026/Adobe Photoshop 2026.app).
        return sorted(
            glob.glob("/Applications/Adobe Photoshop*.app")
            + glob.glob("/Applications/*/Adobe Photoshop*.app"),
            reverse=True,
        )
    except OSError:
        return []


def find_photoshop() -> str:
    """Return the application *name* (no ``.app``) used for AppleScript ``tell``.

    Override target discovery with ``CLI_ANYTHING_PHOTOSHOP_APP`` (either a
    full ``*.app`` path or an application name).
    """
    override = os.environ.get("CLI_ANYTHING_PHOTOSHOP_APP", "").strip()
    if override:
        return os.path.basename(override.removesuffix(".app"))
    apps = _binary_paths()
    if not apps:
        raise PhotoshopError(
            "Adobe Photoshop not found in /Applications.\n"
            "Install Adobe Photoshop (Creative Cloud) or point "
            "CLI_ANYTHING_PHOTOSHOP_APP at your Photoshop .app bundle."
        )
    # examplar: 'Adobe Photoshop 2026.app'
    latest = os.path.basename(apps[0]).removesuffix(".app")
    return latest


def photoshop_running(app_name: str | None = None) -> bool:
    """True when Photoshop is running right now (no auto-launch side effect)."""
    app = app_name or environments_app()
    probe = subprocess.run(
        ["pgrep", "-x", app],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return probe.returncode == 0


# Private module-level cache; refreshed on mismatch so swapping app bundles
# mid-session does not poison later calls.
_CACHED_APP: str | None = None


def environments_app() -> str:
    """Resolve (and remember) the Photoshop app name for the environment."""
    global _CACHED_APP
    if _CACHED_APP is None:
        _CACHED_APP = find_photoshop()
    return _CACHED_APP


def qr(text: str) -> str:
    """Escape a Python string for embedding as an ExtendScript string literal."""
    out = text.replace("\\", "\\\\").replace('"', '\\"')
    out = out.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return '"' + out + '"'


def strict_js(name: str, expr: str) -> str:
    """Wrap a JS expression so failures report a readable operation name."""
    return (
        f"try {{ {expr} }} catch (__e) {{ "
        f"throw new Error('{name}: ' + ('' + __e)); }}"
    )


_PRELUDE = """\
var RS = String.fromCharCode(30);
var US = String.fromCharCode(31);
var __pscli_dlg = app.displayDialogs; app.displayDialogs = DialogModes.NO;
var __pscli_units = app.preferences.rulerUnits; app.preferences.rulerUnits = Units.PIXELS;
"""

# Restores user preferences even when the operation raises. Dialog
# suppression must not leak into interactive Photoshop use.
_POSTLUDE = """\
app.displayDialogs = __pscli_dlg;
app.preferences.rulerUnits = __pscli_units;
"""

# Capture the snippet's `out` BEFORE wrapping up, because do JavaScript
# reports the last evaluated expression only.
_CAPTURE = """\
var __pscli_res = (typeof out !== 'undefined') ? out : undefined;
"""


def _wrap(code: str) -> str:
    """Add dialog-suppression, RS/US constants, restore, and result capture."""
    return (
        f"{_PRELUDE}try {{\n{code}\n{_CAPTURE}{_POSTLUDE}"
        "__pscli_res;\n"
        "} catch (__pscli_e) {\n"
        f"{_POSTLUDE}"
        "throw __pscli_e;\n}\n"
    )


def run_js(code: str, timeout: int = 120, app_name: str | None = None) -> str:
    """Execute ExtendScript code inside Photoshop and return its output text.

    Compiles to: ``with timeout`` ... ``tell application "Photoshop" to do
    JavaScript (read (POSIX file <tmp>) as «class utf8»)``. The code is
    written to a temp file first, which avoids all shell/AppleScript string
    escaping pitfalls (verified pattern on Photoshop 2026).
    """
    app = app_name or environments_app()
    try:
        secs = max(10, int(timeout))
    except (TypeError, ValueError):
        secs = 120

    tmpdir = tempfile.mkdtemp(prefix="cli_anything_photoshop_")
    js_path = os.path.join(tmpdir, "op.js")
    apple_script = (
        f"with timeout of {secs} seconds\n"
        f'tell application "{app}" to do JavaScript (read (POSIX file "{js_path}") as «class utf8»)\n'
        "end timeout"
    )
    try:
        with open(js_path, "w", encoding="utf-8") as handle:
            handle.write(_wrap(code))
        try:
            proc = subprocess.run(
                ["osascript", "-e", apple_script],
                capture_output=True,
                text=True,
                timeout=secs + 30,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PhotoshopError(
                f"osascript timed out after {secs + 30}s — Photoshop may be busy "
                "(modal dialog open, filter running, or startup in progress). "
                "Retry, or raise the timeout with --timeout."
            ) from exc
        if proc.returncode != 0:
            raise PhotoshopError(_translate_osascript_error(proc.stderr.strip()))
        return proc.stdout.rstrip("\n")
    finally:
        try:
            os.remove(js_path)
        except OSError:
            pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass


def _translate_osascript_error(stderr: str) -> str:
    stderr_l = stderr.lower()
    if "-1712" in stderr:
        return (
            "Photoshop timed out / is busy (modal dialog or long-running "
            "operation in progress). Close blocking dialogs and retry, "
            "or raise --timeout.\nRaw: " + stderr
        )
    if "not allowed assistive access" in stderr_l or "-25211" in stderr:
        return (
            "AppleScript automation permission missing. Grant permission to "
            "your terminal app in System Settings → Privacy & Security → "
            "Automation.\nRaw: " + stderr
        )
    if "doesn’t have the permission" in stderr_l or "-1743" in stderr:
        return (
            "AppleScript automation permission missing... (System Settings → "
            "Privacy & Security → Automation → Terminal → Adobe Photoshop 2026)\n"
            "Raw: " + stderr
        )
    return stderr or "osascript failed"


# ---------------------------------------------------------------------------
# Packed-output helpers: ExtendScript and Python agree on RS/US delimiters so
# lists of records round-trip as plain strings.
# ---------------------------------------------------------------------------


def parse_records(packed: str) -> list[list[str]]:
    """Split packed output text into a list of field lists."""
    if packed == "":
        return []
    records = []
    for chunk in packed.split(RS):
        if chunk == "":
            continue
        records.append(chunk.split(US))
    return records


def parse_single(packed: str) -> str:
    """Return the first field of packed output (``''`` if empty)."""
    records = parse_records(packed)
    if not records or not records[0]:
        return ""
    return records[0][0]
