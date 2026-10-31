"""Application control domain: probe, launch, quit the real Photoshop app.

`app info` deliberately avoids launching Photoshop (cheap probe via
``pgrep``); every other command implicitly launches Photoshop through
the AppleScript bridge when needed.
"""
from __future__ import annotations

import subprocess
import time

from cli_anything.photoshop.utils.photoshop_backend import (
    PhotoshopError,
    environments_app,
    photoshop_running,
    run_js,
    strict_js,
)

_LAUNCH_POLL_SECONDS = 1.0


def app_info(timeout: float = 60.0) -> dict:
    """Cheap, launch-free status: running state + version when up."""
    app = environments_app()
    if not photoshop_running():
        return {"app": app, "running": False}
    version_js = "out=[String(app.version),String(app.documents.length)].join('|');"
    raw = run_js(strict_js("app info", "var out;" + version_js + ";out;"), timeout=timeout)
    try:
        version, documents = raw.split("|", 1)
    except ValueError:
        version, documents = raw, "?"
    return {
        "app": app,
        "running": True,
        "version": version,
        "open_documents": documents,
    }


def launch_app(wait: float = 90.0) -> dict:
    """Start Photoshop if needed (``open -a``), wait until scriptable."""
    app = environments_app()
    if photoshop_running():
        info = app_info()
        info["launched"] = False
        return info
    try:
        subprocess.run(["open", "-a", app], timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PhotoshopError(f"could not launch {app}: {exc}") from exc
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        time.sleep(_LAUNCH_POLL_SECONDS)
        if photoshop_running():
            info = app_info()
            info["launched"] = True
            return info
    raise PhotoshopError(
        f"{app} did not become scriptable within {wait:.0f}s "
        "(first launch may show license dialogs — finish them once, then retry)"
    )


def quit_app(timeout: float = 30.0) -> dict:
    """Ask Photoshop to quit (AppleScript quit). Unsaved documents may prompt.

    Photoshop shows its own save-changes dialog when open documents have
    unsaved edits, which will simply time out this call — save or close
    documents first (``doc close``, ``export document``) for a clean exit.
    """
    app = environments_app()
    script = f'tell application "{app}" to quit'
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PhotoshopError(
            "quit timed out — Photoshop is likely showing a 'save changes?' "
            "dialog for a document with unsaved edits. Close/save documents "
            "first, or answer the dialog."
        ) from exc
    return {"app": app, "quit_request_exitcode": proc.returncode, "note": proc.stderr.strip()}
