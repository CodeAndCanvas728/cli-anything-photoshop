"""Adjustment domain: engine-verified per-layer adjustments.

Every method listed here was verified against Photoshop 2026 (27.10.0);
the engine rejects some DOM methods (``equalize``), so those are
deliberately NOT exposed.

Limitations surfaced to callers: adjustments apply to pixel-bearing layers
only — text/shape layers raise Photoshop's own engine error, shown verbatim.
"""
from __future__ import annotations

from cli_anything.photoshop.core.documents import _doc_selector_js
from cli_anything.photoshop.core.layers import _FIND_HELPER
from cli_anything.photoshop.utils.photoshop_backend import (
    US,
    parse_records,
    qr,
    run_js,
    strict_js,
)

ADJUSTMENTS = {
    "invert": "invert colors (negative)",
    "desaturate": "desaturate to grayscale values",
    "auto-contrast": "Photoshop auto contrast",
    "auto-levels": "Photoshop auto levels",
    "posterize": "posterize to N levels (1..255, uses --amount)",
    "threshold": "threshold at level (1..255, uses --amount)",
}

_METHODS = {
    "invert": "invert()",
    "desaturate": "desaturate()",
    "auto-contrast": "autoContrast()",
    "auto-levels": "autoLevels()",
    "posterize": "posterize({n})",
    "threshold": "threshold({n})",
}


def _first_record(raw: str, op: str) -> list[str]:
    records = parse_records(raw)
    if not records:
        raise RuntimeError(f"{op}: empty response from Photoshop")
    return records[0]


def apply_adjustment(
    doc: str | int | None,
    adjustment: str,
    layer: str | None = None,
    amount: int | None = None,
    timeout: float = 120.0,
) -> dict:
    """Apply one adjustment to the target (or active) layer."""
    if adjustment not in _METHODS:
        raise ValueError("unknown adjustment (see --help)")
    needs_amount = "{n}" in _METHODS[adjustment]
    if needs_amount:
        if amount is None:
            raise ValueError(f"{adjustment} requires --amount (integer 1..255)")
        if not 1 <= int(amount) <= 255:
            raise ValueError("amount must be within 1..255")
        call = _METHODS[adjustment].format(n=int(amount))
    else:
        call = _METHODS[adjustment]
    lname = qr(layer) if layer else "null"
    js = (
        f"{_FIND_HELPER}"
        "var d=__pscli_doc(" + _doc_selector_js(doc) + ", true);"
        f"var lname={lname};"
        "var l = (lname === null) ? d.activeLayer : __pscli_find(d, lname);"
        "d.activeLayer = l;"
        f"l.{call};"
        f"out=[String(l.name),String(d.historyStates.length)].join('{US}');"
    )
    code = "var out;" + js + ";out;"
    f = _first_record(
        run_js(strict_js(f"adj {adjustment}", code), timeout=timeout),
        f"adj {adjustment}",
    )
    return {"layer": f[0], "history_states": int(f[1])}
