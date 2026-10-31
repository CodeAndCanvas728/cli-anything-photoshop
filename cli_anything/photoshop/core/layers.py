"""Layer domain: inspect and mutate layers of a live Photoshop document.

Layer addressing convention used across this module (and by the CLI):

- ``layer = None`` → the document's *active* layer
- ``layer = "name"`` → search the full nested tree for that name
  (top-level art layers first, then each layer set, depth-first)
"""
from __future__ import annotations

from cli_anything.photoshop.utils.photoshop_backend import (
    RS,
    US,
    parse_records,
    qr,
    run_js,
    strict_js,
)
from cli_anything.photoshop.core.documents import _DOC_HELPER, _doc_selector_js

BLEND_MODES = {
    "normal": "BlendMode.NORMAL",
    "multiply": "BlendMode.MULTIPLY",
    "screen": "BlendMode.SCREEN",
    "overlay": "BlendMode.OVERLAY",
    "darken": "BlendMode.DARKEN",
    "lighten": "BlendMode.LIGHTEN",
    "difference": "BlendMode.DIFFERENCE",
}

# Depth-first walk producing one packed row per layer/set; parent '' = root.
_WALK_HELPER = _DOC_HELPER + """
function __pscli_walk(container, depth, parentName, rows) {
  var sets = container.layerSets;
  for (var i = 0; i < sets.length; i++) {
    var s = sets[i];
    rows.push([s.name, 'layer_set', String(s.visible), String(s.opacity),
               String(depth), parentName].join(US));
    __pscli_walk(s, depth + 1, s.name, rows);
  }
  var arts = container.artLayers;
  for (var j = 0; j < arts.length; j++) {
    var a = arts[j];
    rows.push([a.name, String(a.kind), String(a.visible), String(a.opacity),
               String(depth), parentName].join(US));
  }
}
"""

# Depth-first search resolving a layer name anywhere in the tree.
_FIND_HELPER = _DOC_HELPER + """
function __pscli_find(docRef, lname) {
  function search(container) {
    var arts = container.artLayers;
    for (var i = 0; i < arts.length; i++) {
      if (arts[i].name === lname) return arts[i];
    }
    var sets = container.layerSets;
    for (var k = 0; k < sets.length; k++) {
      var hit = search(sets[k]);
      if (hit !== null) return hit;
    }
    return null;
  }
  var found = search(docRef);
  if (found === null)
    throw new Error('no layer named "' + lname + '" in this document (hint: layer full name list) try doc info');
  return found;
}
"""


def _kind(value: str) -> str:
    """Normalize enum-ish strings: 'LayerKind.TEXT' -> 'text'."""
    return value.replace("LayerKind.", "").replace("BlendMode.", "").lower()


def _first_record(raw: str, op: str) -> list[str]:
    records = parse_records(raw)
    if not records:
        raise RuntimeError(f"{op}: empty response from Photoshop")
    return records[0]


def _run(op: str, code: str, timeout: float) -> list[str]:
    return _first_record(
        run_js(strict_js(op, "var out;" + code + ";out;"), timeout=timeout), op
    )


def list_layers(doc: str | int | None = None, timeout: float = 120.0) -> list[dict]:
    """Every layer and layer set, nested included, depth-first."""
    js = (
        f"{_WALK_HELPER}"
        "var d=__pscli_doc(" + _doc_selector_js(doc) + ", true);"
        "var rows=[];"
        "__pscli_walk(d, 0, '', rows);"
        f"out=rows.join('{RS}');"
    )
    raw = run_js(strict_js("layer list", "var out;" + js + ";out;"), timeout=timeout)
    return [
        {
            "name": r[0],
            "kind": _kind(r[1]),
            "visible": r[2] == "true",
            "opacity": float(r[3]),
            "depth": int(r[4]),
            "parent": r[5],
        }
        for r in parse_records(raw)
    ]


def layer_info(
    doc: str | int | None = None,
    layer: str | None = None,
    timeout: float = 120.0,
) -> dict:
    """Detail of one layer; includes pixel bounds and text content for text layers."""
    lname = qr(layer) if layer else "null"
    js = (
        f"{_FIND_HELPER}"
        "var d=__pscli_doc(" + _doc_selector_js(doc) + ", true);"
        f"var lname={lname};"
        "var l = (lname === null) ? d.activeLayer : __pscli_find(d, lname);"
        "var istext = (String(l.typename) === 'ArtLayer' && String(l.kind) === 'LayerKind.TEXT');"
        "var text = istext ? String(l.textItem.contents) : '';"
        "var b=''; try { b=String(l.bounds); } catch(e) {}"
        f"out=[String(l.name),String(l.kind),String(l.visible),String(l.opacity),"
        f"String(l.blendMode),b,text].join('{US}');"
    )
    f = _run("layer info", js, timeout)
    info = {
        "name": f[0],
        "kind": _kind(f[1]),
        "visible": f[2] == "true",
        "opacity": float(f[3]),
        "blend_mode": _kind(f[4]),
        "bounds": f[5],
    }
    if info["kind"] == "text":
        info["text"] = f[6]
    return info


def new_layer(
    doc: str | int | None = None,
    kind: str = "art",
    name: str | None = None,
    timeout: float = 120.0,
) -> dict:
    """Add a layer; kind 'art' (pixel) or 'text' (kind assignment verified)."""
    if kind not in ("art", "text"):
        raise ValueError("kind must be 'art' or 'text'")
    lname = "CLI Layer" if name is None else name
    kind_js = (
        "LayerKind.NORMAL" if kind == "art" else "LayerKind.TEXT"
    )
    js = (
        f"{_FIND_HELPER}"
        "var d=__pscli_doc(" + _doc_selector_js(doc) + ", true);"
        "var l=d.artLayers.add();"
        f"l.kind={kind_js};"
        f"l.name={qr(lname)};"
        "d.activeLayer=l;"
        f"out=[String(l.name),String(l.kind)].join('{US}');"
    )
    f = _run("layer new", js, timeout)
    return {"name": f[0], "kind": _kind(f[1])}


def _resolve_js(doc_sel: str, layer: str | None, activate: bool) -> str:
    """JS snippet binding __pscli_t to the target layer object."""
    lname = qr(layer) if layer else "null"
    return (
        "var d=__pscli_doc(" + doc_sel + ", true);"
        f"var lname={lname};"
        "var __pscli_t = (lname === null) ? d.activeLayer : __pscli_find(d, lname);"
        + ("d.activeLayer = __pscli_t;" if activate else "")
    )


def rename_layer(
    doc: str | int | None = None,
    layer: str | None = None,
    new_name: str = "",
    timeout: float = 120.0,
) -> dict:
    """Rename the target layer."""
    if not new_name:
        raise ValueError("--new-name is required")
    js = f"{_FIND_HELPER}" + _resolve_js(_doc_selector_js(doc), layer, False) + (
        f"var old=String(__pscli_t.name);"
        f"__pscli_t.name={qr(new_name)};"
        f"out=[old,String(__pscli_t.name)].join('{US}');"
    )
    f = _run("layer rename", js, timeout)
    return {"old_name": f[0], "new_name": f[1]}


def delete_layer(
    doc: str | int | None = None, layer: str | None = None, timeout: float = 120.0
) -> dict:
    """Delete the target layer (Photoshop refuses to remove a Background-only doc)."""
    js = f"{_FIND_HELPER}" + _resolve_js(_doc_selector_js(doc), layer, False) + (
        "var n=String(__pscli_t.name);"
        "__pscli_t.remove();"
        f"out=[n].join('{US}');"
    )
    return {"deleted": _run("layer delete", js, timeout)[0]}


def set_visible(
    doc: str | int | None = None,
    layer: str | None = None,
    state: str = "toggle",
    timeout: float = 120.0,
) -> dict:
    """Show / hide / toggle the target layer."""
    if state not in ("show", "hide", "toggle"):
        raise ValueError("state must be show|hide|toggle")
    want = {"show": True, "hide": False, "toggle": None}[state]
    js = f"{_FIND_HELPER}" + _resolve_js(_doc_selector_js(doc), layer, False) + (
        f"var want={(str(want).lower() if want is not None else 'null')};"
        "var cur=Boolean(__pscli_t.visible);"
        "var nv=(want===null)?(!cur):want;"
        "__pscli_t.visible=nv;"
        f"out=[String(__pscli_t.name),String(cur),String(nv)].join('{US}');"
    )
    f = _run("layer visible", js, timeout)
    return {"name": f[0], "was_visible": f[1] == "true", "now_visible": f[2] == "true"}


def set_opacity(
    doc: str | int | None = None,
    layer: str | None = None,
    value: float = 0,
    timeout: float = 120.0,
) -> dict:
    """Set layer opacity percent (0-100; engine accepts fractional values).

    The engine stores opacity quantized to 0..255 steps, so the returned
    value can differ from the request (42 → ~41.96).
    """
    if not 0 <= value <= 100:
        raise ValueError("opacity must be within 0..100")
    js = f"{_FIND_HELPER}" + _resolve_js(_doc_selector_js(doc), layer, False) + (
        f"__pscli_t.opacity={value};"
        f"out=[String(__pscli_t.name),String(__pscli_t.opacity)].join('{US}');"
    )
    f = _run("layer opacity", js, timeout)
    return {"name": f[0], "opacity": float(f[1])}


def set_blend_mode(
    doc: str | int | None = None,
    layer: str | None = None,
    mode: str = "",
    timeout: float = 120.0,
) -> dict:
    """Blend mode subset supported by the engine enum (see --help)."""
    if mode not in BLEND_MODES:
        raise ValueError("mode must be one of: " + ", ".join(BLEND_MODES))
    js = f"{_FIND_HELPER}" + _resolve_js(_doc_selector_js(doc), layer, False) + (
        "__pscli_t.blendMode=" + BLEND_MODES[mode] + ";"
        f"out=[String(__pscli_t.name),String(__pscli_t.blendMode)].join('{US}');"
    )
    f = _run("layer blend", js, timeout)
    return {"name": f[0], "blend_mode": _kind(f[1])}


def get_text(
    doc: str | int | None = None, layer: str | None = None, timeout: float = 120.0
) -> dict:
    """Read the text of a text layer (clean error on other kinds)."""
    js = f"{_FIND_HELPER}" + _resolve_js(_doc_selector_js(doc), layer, False) + (
        "if (String(__pscli_t.typename) !== 'ArtLayer' || String(__pscli_t.kind) !== 'LayerKind.TEXT')"
        "throw new Error('layer is not a text layer (kind: ' + String(__pscli_t.kind) + ')');"
        f"out=[String(__pscli_t.textItem.contents)].join('{US}');"
    )
    return {"text": _run("layer text-get", js, timeout)[0]}


def set_text(
    doc: str | int | None = None,
    layer: str | None = None,
    value: str = "",
    timeout: float = 120.0,
) -> dict:
    """Write new text into a text layer."""
    js = f"{_FIND_HELPER}" + _resolve_js(_doc_selector_js(doc), layer, False) + (
        "if (String(__pscli_t.typename) !== 'ArtLayer' || String(__pscli_t.kind) !== 'LayerKind.TEXT')"
        "throw new Error('layer is not a text layer (kind: ' + String(__pscli_t.kind) + ')');"
        "__pscli_t.textItem.contents=" + qr(value) + ";"
        f"out=[String(__pscli_t.textItem.contents)].join('{US}');"
    )
    return {"text": _run("layer text-set", js, timeout)[0]}


def merge_down(
    doc: str | int | None = None, layer: str | None = None, timeout: float = 120.0
) -> dict:
    """Merge the target layer into the one directly below (engine `merge()`)."""
    js = f"{_FIND_HELPER}" + _resolve_js(_doc_selector_js(doc), layer, True) + (
        "var before=d.artLayers.length;"
        "var merged=d.activeLayer.merge();"
        f"out=[String(merged.name),String(before),String(d.artLayers.length)].join('{US}');"
    )
    f = _run("layer merge-down", js, timeout)
    return {"merged_into": f[0], "layers_before": int(f[1]), "layers_after": int(f[2])}


def select_layer(
    doc: str | int | None = None, layer: str | None = None, timeout: float = 120.0
) -> dict:
    """Make the target layer active; returns its info."""
    js = f"{_FIND_HELPER}" + _resolve_js(_doc_selector_js(doc), layer, True) + (
        f"out=[String(__pscli_t.name),String(__pscli_t.kind)].join('{US}');"
    )
    f = _run("layer select", js, timeout)
    return {"name": f[0], "kind": _kind(f[1])}
