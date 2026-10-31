"""Export & file-conversion domain — all rendering happens in Photoshop itself.

Save options verified live on Photoshop 2026 (27.10.0):
- PNG: ``PNGSaveOptions``; JPEG: ``JPEGSaveOptions`` (quality 0..12);
- PSD uses ``PhotoshopSaveOptions`` (there is no ``PSDSaveOptions`` class).
- TIFF has no constructible save-options class in this engine, so TIFF is
  not offered (the CLI fails loudly for it rather than silently downgrading).

Output files are verified in Python after export: existence, size, and
format magic bytes.
"""
from __future__ import annotations

import os

from cli_anything.photoshop.core.documents import _DOC_HELPER, _doc_selector_js
from cli_anything.photoshop.utils.photoshop_backend import (
    PhotoshopError,
    US,
    qr,
    run_js,
    strict_js,
)

FORMATS = {
    "png": ("PNGSaveOptions", "photoshop"),
    "jpeg": ("JPEGSaveOptions", "photoshop"),
    "psd": ("PhotoshopSaveOptions", "photoshop"),
    "jpg": ("JPEGSaveOptions", "photoshop"),
}
MAGIC = {
    "png": b"\x89PNG\r\n\x1a\n",
    "jpeg": b"\xff\xd8\xff",
    "jpg": b"\xff\xd8\xff",
    "psd": b"8BPS",
}


def _first(raw: str, op: str) -> list[str]:
    from cli_anything.photoshop.utils.photoshop_backend import parse_records

    records = parse_records(raw)
    if not records:
        raise RuntimeError(f"{op}: empty response from Photoshop")
    return records[0]


def _check_overwrite(path: str, overwrite: bool) -> None:
    if os.path.exists(path) and not overwrite:
        raise PhotoshopError(f"refusing to overwrite existing file: {path} (pass --overwrite)")


def _verify_output(path: str, fmt: str) -> dict:
    if not os.path.isfile(path):
        raise PhotoshopError(f"Photoshop reported success but no file at {path}")
    size = os.path.getsize(path)
    if size == 0:
        raise PhotoshopError(f"export produced an empty file: {path}")
    with open(path, "rb") as handle:
        head = handle.read(8)
    want = MAGIC[fmt]
    if head[: len(want)] != want:
        raise PhotoshopError(
            f"output at {path} does not look like {fmt} (magic bytes mismatch)"
        )
    return {"output": path, "format": fmt, "bytes": size}


def _save_options_js(fmt: str, quality: int) -> str:
    cls, _ = FORMATS[fmt]
    if fmt in ("jpeg", "jpg"):
        if not 0 <= int(quality) <= 12:
            raise ValueError("JPEG quality range in Photoshop scripting is 0..12")
        return f"var o=new {cls}();o.quality={int(quality)};"
    return f"var o=new {cls}();"


def export_document(
    doc: str | int | None,
    out_path: str,
    fmt: str | None = None,
    quality: int = 8,
    overwrite: bool = False,
    timeout: float = 120.0,
) -> dict:
    """Save the target document to disk in a verified format."""
    fmt = (fmt or os.path.splitext(out_path)[1].lstrip(".").lower()) or "png"
    if fmt not in FORMATS:
        raise ValueError(
            "format must be png|jpg|jpeg|psd (TIFF save is unavailable in the scripting engine)"
        )
    if not os.path.isabs(out_path):
        raise ValueError("--out must be an absolute path")
    _check_overwrite(out_path, overwrite)
    js = (
        f"{_DOC_HELPER}"
        "var d=__pscli_doc(" + _doc_selector_js(doc) + ", true);"
        + _save_options_js(fmt, quality)
        + f"d.saveAs(new File({qr(out_path)}), o, true, Extension.LOWERCASE);"
        # NOTE: do NOT read d.path here — unsaved documents throw
        # "The document has not yet been saved" *after* the file was written.
        f"out=[String(d.name)].join('{US}');"
    )
    code = "var out;" + js + ";out;"
    _first(run_js(strict_js("export document", code), timeout=timeout), "export document")
    result = _verify_output(out_path, fmt)
    result["document"] = os.path.basename(out_path)
    return result


def convert_file(
    src_path: str,
    out_path: str,
    fmt: str | None = None,
    quality: int = 8,
    overwrite: bool = False,
    timeout: float = 120.0,
) -> dict:
    """Open src in Photoshop, export as fmt, close the temp document."""
    if not os.path.isabs(src_path):
        raise ValueError("--src must be an absolute path")
    if not os.path.isfile(src_path):
        raise PhotoshopError(f"source file not found: {src_path}")
    fmt = (fmt or os.path.splitext(out_path)[1].lstrip(".").lower()) or "png"
    if fmt not in FORMATS:
        raise ValueError("format must be png|jpg|jpeg|psd")
    if not os.path.isabs(out_path):
        raise ValueError("--out must be an absolute path")
    _check_overwrite(out_path, overwrite)
    js = (
        f"{_DOC_HELPER}"
        f"var d=app.open(new File({qr(src_path)}));"
        + _save_options_js(fmt, quality)
        + f"d.saveAs(new File({qr(out_path)}), o, true, Extension.LOWERCASE);"
        "d.close(SaveOptions.DONOTSAVECHANGES);"
        f"out=['converted'].join('{US}');"
    )
    code = "var out;" + js + ";out;"
    run_js(strict_js("export convert", code), timeout=timeout)
    return _verify_output(out_path, fmt)
