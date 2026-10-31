"""History domain: inspect and walk the document's undo history.

Photoshop keeps its own command history per document; the CLI surfaces it by
repositioning ``activeHistoryState`` (verified live: ``historyStates`` list
and stepping back one state). Undo = step back 1, redo = step forward 1.
"""
from __future__ import annotations

from cli_anything.photoshop.core.documents import _DOC_HELPER, _doc_selector_js
from cli_anything.photoshop.utils.photoshop_backend import (
    RS,
    US,
    parse_records,
    run_js,
    strict_js,
)


def _resolve_current_index_js() -> str:
    """Equal-object comparison finds the active state's list position."""
    return (
        "var cur=-1;"
        "for (var i=0;i<d.historyStates.length;i++){"
        "if (d.historyStates[i] === d.activeHistoryState) { cur=i; break; }"
        "}"
    )


def _first(raw: str, op: str) -> list[str]:
    records = parse_records(raw)
    if not records:
        raise RuntimeError(f"{op}: empty response from Photoshop")
    return records[0]


def list_history(
    doc: str | int | None = None, limit: int = 50, timeout: float = 120.0
) -> dict:
    """History states of the target document, current position highlighted."""
    if limit < 1:
        raise ValueError("limit must be >= 1")
    limit = min(int(limit), 500)
    js = (
        f"{_DOC_HELPER}"
        "var d=__pscli_doc(" + _doc_selector_js(doc) + ", true);"
        + _resolve_current_index_js()
        + f"var rows=[], start=Math.max(0, d.historyStates.length-{limit});"
        f"for (var i=start;i<d.historyStates.length;i++){{"
        f"rows.push([String(i), d.historyStates[i].name, (i===cur?'y':'n')].join('{US}'));"
        "}"
        # Metadata and row payloads travel as separate RS chunks so the
        # nested packing can never corrupt record boundaries.
        f"out=[String(d.historyStates.length), String(cur), String(d.name)].join('{US}')"
        f" + '{RS}' + rows.join('{RS}');"
    )
    code = "var out;" + js + ";out;"
    raw = run_js(strict_js("history list", code), timeout=timeout)
    chunks = raw.split(RS) if raw else []
    meta = chunks[0].split(US) if chunks else ["0", "-1", ""]
    states = [
        {"index": int(r[0]), "name": r[1], "current": r[2] == "y"}
        for r in (chunk.split(US) for chunk in chunks[1:])
        if len(r) >= 3
    ]
    return {
        "document": meta[2] if len(meta) > 2 else "",
        "states": states,
        "history_states": int(meta[0]),
        "current_index": int(meta[1]),
    }


def history_step(
    doc: str | int | None = None, offset: int = 0, timeout: float = 120.0
) -> dict:
    """Move the history cursor relative to the current state (+redo / -undo)."""
    if offset == 0:
        raise ValueError("offset must be non-zero (+1 to redo, -1 to undo)")
    js = (
        f"{_DOC_HELPER}"
        "var d=__pscli_doc(" + _doc_selector_js(doc) + ", true);"
        + _resolve_current_index_js()
        + f"var target=cur+({int(offset)});"
        "if (target < 0) throw new Error('cannot step before state 0');"
        "if (target > d.historyStates.length - 1) throw new Error("
        "'cannot step beyond the newest state');"
        "var prev=d.activeHistoryState.name;"
        "d.activeHistoryState=d.historyStates[target];"
        f"out=[String(d.name), prev, String(d.activeHistoryState.name)].join('{US}');"
    )
    code = "var out;" + js + ";out;"
    f = _first(run_js(strict_js("history step", code), timeout=timeout), "history step")
    return {"document": f[0], "from_state": f[1], "to_state": f[2]}


def undo_document(doc: str | int | None = None, timeout: float = 120.0) -> dict:
    """Reposition the history cursor one state back."""
    return history_step(doc, offset=-1, timeout=timeout)


def redo_document(doc: str | int | None = None, timeout: float = 120.0) -> dict:
    """Reposition the history cursor one state forward."""
    return history_step(doc, offset=1, timeout=timeout)
