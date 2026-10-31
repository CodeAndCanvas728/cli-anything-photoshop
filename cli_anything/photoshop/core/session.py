"""Session state: tiny workspace memory persisted across CLI invocations.

Stores the last document used (so ``session status`` tells agents where they
left off) and a recent-commands trail. Saves use the locked-write pattern
from CLI-Anything's ``guides/session-locking.md`` (no bare ``open("w")``):
never truncates before the exclusive flock is held.
"""
from __future__ import annotations

import json
import os
import time

SESSION_DIR = os.path.join(
    os.path.expanduser("~"), ".cli-anything-photoshop"
)
SESSION_PATH = os.path.join(SESSION_DIR, "session.json")
TRAIL_LIMIT = 50


def load_session(path: str = SESSION_PATH) -> dict:
    """Read session state; missing or corrupt files yield a fresh state."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {"last_doc": None, "trail": []}
    except (OSError, json.JSONDecodeError):
        return {"last_doc": None, "trail": []}
    if not isinstance(data, dict):
        return {"last_doc": None, "trail": []}
    data.setdefault("last_doc", None)
    data.setdefault("trail", [])
    return data


def _locked_save_json(path: str, data: dict, **dump_kwargs) -> None:
    """Atomically write JSON with exclusive file locking (guide pattern)."""
    try:
        f = open(path, "r+")  # noqa: SIM115 — closed via `with f`
    except FileNotFoundError:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        f = open(path, "w")
    with f:
        locked = False
        try:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            locked = True
        except (ImportError, OSError):
            pass  # platform without flock — proceed unlocked
        try:
            f.seek(0)
            f.truncate()  # truncate INSIDE the lock
            json.dump(data, f, **dump_kwargs)
            f.flush()
        finally:
            if locked:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def record(command: str, doc: str | None, path: str = SESSION_PATH) -> dict:
    """Append a command to the trail and remember the document it touched."""
    state = load_session(path)
    state["last_doc"] = doc
    trail = state.get("trail", [])
    trail.append({"command": command, "doc": doc, "ts": round(time.time(), 3)})
    state["trail"] = trail[-TRAIL_LIMIT:]
    _locked_save_json(path, state)
    return state


def session_status(path: str = SESSION_PATH) -> dict:
    return load_session(path)


def clear_session(path: str = SESSION_PATH) -> dict:
    """Drop trail and last-doc memory."""
    fresh = {"last_doc": None, "trail": []}
    _locked_save_json(path, fresh)
    return fresh
