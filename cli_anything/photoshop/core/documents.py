"""Document domain: create, inspect, transform, close real Photoshop documents.

Every function compiles a small ExtendScript program and runs it through the
backend transport (``run_js``), so Photoshop itself performs every mutation.
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

MODES = {
    "rgb": "NewDocumentMode.RGB",
    "grayscale": "NewDocumentMode.GRAYSCALE",
    "cmyk": "NewDocumentMode.CMYK",
    "lab": "NewDocumentMode.LAB",
}
FILLS = {
    "white": "DocumentFill.WHITE",
    "transparent": "DocumentFill.TRANSPARENT",
    "background": "DocumentFill.BACKGROUND",
}
RESAMPLE = {
    "bicubic": "ResampleMethod.BICUBIC",
    "bilinear": "ResampleMethod.BILINEAR",
    "nearest": "ResampleMethod.NEARESTNEIGHBOR",
}
ANCHOR = "AnchorPosition.MIDDLECENTER"

_DOC_HELPER = """
function __pscli_doc(sel, need_doc) {
  if (app.documents.length === 0) {
    if (need_doc === false) return null;
    throw new Error('No document is open in Photoshop');
  }
  if (sel === null) return app.activeDocument;
  if (sel.s === 'name') {
    for (var i = 0; i < app.documents.length; i++) {
      if (app.documents[i].name === sel.v) return app.documents[i];
    }
    throw new Error('No open document named ' + sel.v);
  }
  if (sel.s === 'index') {
    if (sel.v < 1 || sel.v > app.documents.length)
      throw new Error('document index ' + sel.v + ' out of range 1..' + app.documents.length);
    return app.documents[sel.v - 1];
  }
  throw new Error('invalid document selector');
}
"""


def _doc_selector_js(doc: str | int | None) -> str:
    """Build an ExtendScript selector object literal for the --doc option."""
    if doc is None:
        return "null"
    if isinstance(doc, int) or (isinstance(doc, str) and doc.isdigit()):
        return "{s:'index',v:" + str(int(doc)) + "}"
    return "{s:'name',v:" + qr(str(doc)) + "}"


def _strip_px(unit_value: str) -> float:
    """Photoshop returns unit strings like '64 px'; keep the numeric part."""
    return float(str(unit_value).split(" ")[0])


def _first_record(raw: str, op: str) -> list[str]:
    records = parse_records(raw)
    if not records:
        raise RuntimeError(f"{op}: empty response from Photoshop")
    return records[0]


def list_documents(timeout: float = 120.0) -> list[dict]:
    """Every open document, in Photoshop's own order."""
    js = (
        f"{_DOC_HELPER}"
        "var rows=[], r;"
        "for (var i=0;i<app.documents.length;i++){"
        "var d=app.documents[i];"
        f"r=[String(d.name),String(d.width),String(d.height),String(d.mode),String(i+1)].join('{US}');"
        "rows.push(r);"
        "}"
        f"out=rows.join('{RS}');"
    )
    raw = run_js(strict_js("doc list", js), timeout=timeout)
    return [
        {
            "name": r[0],
            "index": r[-1],
            "width_px": _strip_px(r[1]),
            "height_px": _strip_px(r[2]),
            "mode": r[3].replace("DocumentMode.", "").lower(),
        }
        for r in parse_records(raw)
    ]


def new_document(
    width: int,
    height: int,
    dpi: float = 72,
    name: str | None = None,
    mode: str = "rgb",
    fill: str = "white",
    bits: int = 8,
    timeout: float = 120.0,
) -> dict:
    """Create a real document (verified engine signature: 7 args, numeric bits)."""
    if bits not in (8, 16, 32):
        raise ValueError("bits must be one of 8, 16, 32")
    if mode not in MODES or fill not in FILLS:
        raise ValueError("invalid --mode or --fill (see --help)")
    if width < 1 or height < 1:
        raise ValueError("width/height must be >= 1")
    doc_name = name or "Untitled CLI"
    js = (
        f"{_DOC_HELPER}"
        f"app.documents.add({int(width)},{int(height)},{dpi},{qr(doc_name)},"
        f"{MODES[mode]},{FILLS[fill]},{int(bits)});"
        "var nd=app.activeDocument;"
        f"out=[String(nd.name),String(nd.width),String(nd.height),String(nd.mode),"
        f"String(nd.artLayers.length)].join('{US}');"
    )
    code = "var out;" + js + ";out;"
    f = _first_record(run_js(strict_js("doc new", code), timeout=timeout), "doc new")
    return {
        "name": f[0],
        "width_px": _strip_px(f[1]),
        "height_px": _strip_px(f[2]),
        "mode": f[3].replace("DocumentMode.", "").lower(),
        "layers": int(f[4]),
    }


def doc_info(doc: str | int | None = None, timeout: float = 120.0) -> dict:
    """Structured introspection of one open document."""
    js = (
        f"{_DOC_HELPER}"
        "var d=__pscli_doc(" + _doc_selector_js(doc) + ", true);"
        "var path=''; try { path = String(d.path); } catch (e) { path = ''; }"
        f"out=[String(d.name),String(d.width),String(d.height),String(d.mode),"
        f"String(d.artLayers.length),String(d.layerSets.length),path,"
        f"String(d.historyStates.length)].join('{US}');"
    )
    code = "var out;" + js + ";out;"
    f = _first_record(run_js(strict_js("doc info", code), timeout=timeout), "doc info")
    return {
        "name": f[0],
        "width_px": _strip_px(f[1]),
        "height_px": _strip_px(f[2]),
        "mode": f[3].replace("DocumentMode.", "").lower(),
        "layers": int(f[4]),
        "layer_sets": int(f[5]),
        "file_path": f[6],
        "history_states": int(f[7]),
    }


def close_document(
    doc: str | int | None = None, save: bool = False, timeout: float = 120.0
) -> dict:
    """Close a document; default discards changes, --save writes in place first.

    ``--save`` refuses cleanly when the document has no on-disk path —
    an untitled document must be exported first (``export document``).
    Closing silently discards by default so an agent never hangs on a modal
    'save changes?' dialog.
    """
    js = (
        f"{_DOC_HELPER}"
        "var d=__pscli_doc(" + _doc_selector_js(doc) + ", true);"
        "var n=String(d.name);"
        "var p=''; try { p=String(d.path); } catch(e) { p=''; }"
        f"if ({'true' if save else 'false'} && p === '') throw new Error("
        f"'refusing to save-close: document has no file path (hint: export document first)');"
        f"d.close({'SaveOptions.SAVECHANGES' if save else 'SaveOptions.DONOTSAVECHANGES'});"
        f"out=[n].join('{US}');"
    )
    code = "var out;" + js + ";out;"
    return {"name": _first_record(
        run_js(strict_js("doc close", code), timeout=timeout), "doc close")[0]}


def flatten_document(doc: str | int | None = None, timeout: float = 120.0) -> dict:
    """Flatten the document into a single background layer."""
    js = (
        f"{_DOC_HELPER}"
        "var d=__pscli_doc(" + _doc_selector_js(doc) + ", true);"
        "var before=String(d.artLayers.length);"
        "d.flatten();"
        f"out=[String(d.name),before,String(d.artLayers.length)].join('{US}');"
    )
    code = "var out;" + js + ";out;"
    f = _first_record(
        run_js(strict_js("doc flatten", code), timeout=timeout), "doc flatten"
    )
    return {"name": f[0], "layers_before": int(f[1]), "layers_after": int(f[2])}


def resize_image(
    doc: str | int | None = None,
    width: float | None = None,
    height: float | None = None,
    resolution: float = 72,
    resample: str = "bicubic",
    timeout: float = 120.0,
) -> dict:
    """Scale the image; pass exactly one of width/height to keep ratio."""
    if resample not in RESAMPLE:
        raise ValueError("invalid resample method (bicubic|bilinear|nearest)")
    if (width is None) == (height is None):
        raise ValueError("pass exactly one of --width/--height (proportional resize)")
    if width is not None:
        if width < 1:
            raise ValueError("width must be >= 1")
        size_arg = f"UnitValue({width},'px')"
    else:
        if height is None or height < 1:
            raise ValueError("height must be >= 1")
        size_arg = f"UnitValue({height},'px')"
    js = (
        f"{_DOC_HELPER}"
        "var d=__pscli_doc(" + _doc_selector_js(doc) + ", true);"
        f"d.resizeImage({size_arg},{resolution},{RESAMPLE[resample]});"
        f"out=[String(d.name),String(d.width),String(d.height)].join('{US}');"
    )
    code = "var out;" + js + ";out;"
    f = _first_record(
        run_js(strict_js("doc resize-image", code), timeout=timeout), "doc resize-image"
    )
    return {"name": f[0], "width_px": _strip_px(f[1]), "height_px": _strip_px(f[2])}


def resize_canvas(
    doc: str | int | None = None, width: int = 0, height: int = 0, timeout: float = 120.0
) -> dict:
    """Change canvas size, keeping existing content centered."""
    if width < 1 or height < 1:
        raise ValueError("canvas width/height must be >= 1")
    js = (
        f"{_DOC_HELPER}"
        "var d=__pscli_doc(" + _doc_selector_js(doc) + ", true);"
        f"d.resizeCanvas(UnitValue({int(width)},'px'),UnitValue({int(height)},'px'),{ANCHOR});"
        f"out=[String(d.name),String(d.width),String(d.height)].join('{US}');"
    )
    code = "var out;" + js + ";out;"
    f = _first_record(
        run_js(strict_js("doc resize-canvas", code), timeout=timeout), "doc resize-canvas"
    )
    return {"name": f[0], "width_px": _strip_px(f[1]), "height_px": _strip_px(f[2])}


def rotate_canvas(
    doc: str | int | None = None, degrees: int = 0, timeout: float = 120.0
) -> dict:
    """Rotate the canvas. Verified: 90 turns clockwise in this engine."""
    if degrees not in (90, -90, 180):
        raise ValueError("degrees must be one of 90, -90, 180")
    js = (
        f"{_DOC_HELPER}"
        "var d=__pscli_doc(" + _doc_selector_js(doc) + ", true);"
        f"d.rotateCanvas({degrees});"
        f"out=[String(d.name),String(d.width),String(d.height),String({degrees})].join('{US}');"
    )
    code = "var out;" + js + ";out;"
    f = _first_record(
        run_js(strict_js("doc rotate", code), timeout=timeout), "doc rotate"
    )
    return {
        "name": f[0],
        "width_px": _strip_px(f[1]),
        "height_px": _strip_px(f[2]),
        "rotated_degrees": int(f[3]),
    }


def flip_canvas(
    doc: str | int | None = None, axis: str = "", timeout: float = 120.0
) -> dict:
    """Mirror the canvas horizontally or vertically."""
    if axis not in ("horizontal", "vertical"):
        raise ValueError("axis must be horizontal|vertical")
    const = (
        "Direction.HORIZONTAL" if axis == "horizontal" else "Direction.VERTICAL"
    )
    js = (
        f"{_DOC_HELPER}"
        "var d=__pscli_doc(" + _doc_selector_js(doc) + ", true);"
        f"d.flipCanvas({const});"
        f"out=[String(d.name),String(d.width),String(d.height)].join('{US}');"
    )
    code = "var out;" + js + ";out;"
    f = _first_record(
        run_js(strict_js("doc flip", code), timeout=timeout), "doc flip"
    )
    return {"name": f[0], "width_px": _strip_px(f[1]), "height_px": _strip_px(f[2]), "axis": axis}
