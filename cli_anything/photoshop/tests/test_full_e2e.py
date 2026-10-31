"""True E2E tests — they drive the REAL Photoshop application.

Rule (HARNESS.md): no graceful degradation. Photoshop must be installed and
AppleScript-permitted for the calling terminal; the tests fail, not skip.

Artifacts are written to pytest-tmp dirs and their paths are printed for
manual inspection.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

import cli_anything.photoshop.core.app_control as app_control
import cli_anything.photoshop.core.documents as documents
import cli_anything.photoshop.core.export as export
import cli_anything.photoshop.core.history as history_mod
import cli_anything.photoshop.core.layers as layers
import cli_anything.photoshop.utils.photoshop_backend as backend


def _resolve_cli(name):
    """Resolve installed CLI command; falls back to python -m for dev.

    Set env CLI_ANYTHING_FORCE_INSTALLED=1 to require the installed command.
    """
    force = os.environ.get("CLI_ANYTHING_FORCE_INSTALLED", "").strip() == "1"
    path = shutil.which(name)
    if path:
        print(f"[_resolve_cli] Using installed command: {path}")
        return [path]
    if force:
        raise RuntimeError(f"{name} not found in PATH. Install with: pip install -e .")
    module = name.replace("cli-anything-", "cli_anything.") + "." + name.split("-")[-1] + "_cli"
    print(f"[_resolve_cli] Falling back to: {sys.executable} -m {module}")
    return [sys.executable, "-m", module]


@pytest.fixture(autouse=True, scope="module")
def _require_photoshop():
    """Photoshop IS the hard dependency; launch it once for the module."""
    app_control.launch_app(wait=180.0)
    yield


@pytest.fixture()
def probe_doc(tmp_path):
    doc = documents.new_document(64, 64, 72, "cli_e2e_probe_doc", "rgb", "white", 8)
    yield doc
    # discard-by-default close: no dialogs, no leftovers in Photoshop
    try:
        documents.close_document("cli_e2e_probe_doc", save=False)
    except backend.PhotoshopError:
        pass


# ── backend direct ────────────────────────────────────────────────────────
def test_backend_lives():
    out = backend.run_js("out=String(app.version);")
    major = int(out.split(".")[0])
    assert major >= 27


# ── document workflow ─────────────────────────────────────────────────────
def test_new_doc_then_info(probe_doc):
    assert probe_doc["width_px"] == 64.0 and probe_doc["height_px"] == 64.0
    info = documents.doc_info("cli_e2e_probe_doc")
    assert info["history_states"] >= 1
    assert info["layers"] >= 1


def test_layers_workflow(probe_doc, tmp_path):
    art = layers.new_layer("cli_e2e_probe_doc", kind="art", name="e2e_art")
    # CLI 'art' maps to the engine kind NORMAL ('normal' in listings).
    assert art["kind"] == "normal"
    text = layers.new_layer("cli_e2e_probe_doc", kind="text", name="e2e_text")
    assert text["kind"] == "text"
    layers.set_text("cli_e2e_probe_doc", "e2e_text", "E2E")
    assert layers.get_text("cli_e2e_probe_doc", "e2e_text")["text"] == "E2E"
    listed = layers.list_layers("cli_e2e_probe_doc")
    names = [r["name"] for r in listed]
    assert "e2e_art" in names and "e2e_text" in names
    visible = layers.set_visible("cli_e2e_probe_doc", "e2e_art", "hide")
    assert visible["now_visible"] is False
    opacity = layers.set_opacity("cli_e2e_probe_doc", "e2e_art", 42)
    # The engine stores opacity quantized to 0..255 steps (42 → ~41.96).
    assert opacity["opacity"] == pytest.approx(42.0, abs=0.5)


def test_geometric_transforms(probe_doc):
    flipped = documents.flip_canvas("cli_e2e_probe_doc", "vertical")
    assert flipped["height_px"] == 64.0
    resized = documents.resize_canvas("cli_e2e_probe_doc", 40, 40)
    assert (resized["width_px"], resized["height_px"]) == (40.0, 40.0)


def test_adjustments_flow(probe_doc):
    # Adjustments need a pixel-bearing layer: the white-filled Background.
    import cli_anything.photoshop.core.adjustments as adjustments

    inv = adjustments.apply_adjustment("cli_e2e_probe_doc", "invert", layer="Background")
    assert inv["layer"] == "Background"
    assert inv["history_states"] >= 2
    # An empty art layer must FAIL loudly (truthful engine behavior).
    layers.new_layer("cli_e2e_probe_doc", kind="art", name="empty_art")
    with pytest.raises(backend.PhotoshopError):
        adjustments.apply_adjustment(
            "cli_e2e_probe_doc", "posterize", layer="empty_art", amount=6
        )


def test_export_png_jpg_psd(probe_doc, tmp_path):
    documents.flatten_document("cli_e2e_probe_doc")
    outputs = {}
    for fmt, suffix in (("png", ".png"), ("jpeg", ".jpg"), ("psd", ".psd")):
        out_path = str(tmp_path / f"probe_export{suffix}")
        result = export.export_document(
            "cli_e2e_probe_doc", out_path, fmt=fmt, quality=8, overwrite=True)
        outputs[fmt] = result
        print(f"\n  {fmt}: {result['output']} ({result['bytes']:,} bytes)")
    assert outputs["png"]["bytes"] > 1000
    assert (tmp_path / "probe_export.png").read_bytes()[:4] == b"\x89PNG"
    assert (tmp_path / "probe_export.jpg").read_bytes()[:3] == b"\xff\xd8\xff"
    assert (tmp_path / "probe_export.psd").read_bytes()[:4] == b"8BPS"


def test_history_walk(probe_doc):
    before = documents.doc_info("cli_e2e_probe_doc")["history_states"]
    layers.new_layer("cli_e2e_probe_doc", kind="art", name="hist_layer")
    after = documents.doc_info("cli_e2e_probe_doc")["history_states"]
    assert after >= before  # engine may coalesce; report, don't lie
    listing = history_mod.list_history("cli_e2e_probe_doc")
    cur = listing["current_index"]
    assert cur >= 0
    undone = history_mod.undo_document("cli_e2e_probe_doc")
    assert undone["document"] == "cli_e2e_probe_doc"
    redone = history_mod.redo_document("cli_e2e_probe_doc")
    assert redone["to_state"] == undone["from_state"]


def test_psd_open_roundtrip(probe_doc, tmp_path):
    out_psd = str(tmp_path / "roundtrip.psd")
    export.export_document("cli_e2e_probe_doc", out_psd, "psd", overwrite=True)
    code = (
        "var d=app.open(new File("
        + backend.qr(out_psd)
        + "));out=[String(d.name),String(d.width),String(d.height)].join('|');"
        "d.close(SaveOptions.DONOTSAVECHANGES);"
    )
    raw = backend.run_js("var out;" + code + ";out;")
    name, w, h = raw.split("|")
    assert name == "roundtrip.psd" and float(w.split(" ")[0]) == 64.0


def test_convert_psd_to_jpeg(probe_doc, tmp_path):
    src_psd = str(tmp_path / "conv.psd")
    out_jpg = str(tmp_path / "conv.jpg")
    export.export_document("cli_e2e_probe_doc", src_psd, "psd", overwrite=True)
    result = export.convert_file(src_psd, out_jpg, "jpeg", quality=8, overwrite=True)
    print(f"\n  psd→jpeg: {result['output']} ({result['bytes']:,} bytes)")
    assert result["bytes"] > 500
    assert open(out_jpg, "rb").read(3) == b"\xff\xd8\xff"


# ── subprocess tests of the INSTALLED CLI ─────────────────────────────────
class TestCLISubprocess:
    CLI_BASE = _resolve_cli("cli-anything-photoshop")

    def _run(self, args, check=True):
        return subprocess.run(
            self.CLI_BASE + args, capture_output=True, text=True, check=check,
        )

    def test_help(self):
        result = self._run(["--help"])
        assert result.returncode == 0
        assert "Photoshop" in result.stdout

    def test_app_info_json(self):
        result = self._run(["--json", "app", "info"])
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["running"] is True

    def test_doc_new_list_export_pipeline_json(self, tmp_path):
        out_png = str(tmp_path / "sub_test.png")
        self._run(["--json", "doc", "new", "--width", "32", "--height", "32",
                   "--name", "sub_pipeline_doc", "--fill", "white"])
        result_list = self._run(["--json", "--doc", "sub_pipeline_doc", "doc", "list"])
        data = json.loads(result_list.stdout)
        names = [r["name"] for r in data["data"]]
        assert "sub_pipeline_doc" in names
        result_export = self._run(
            ["--json", "--doc", "sub_pipeline_doc", "export", "document",
             out_png, "--format", "png", "--overwrite"])
        data = json.loads(result_export.stdout)
        assert data["data"]["bytes"] > 500
        assert (tmp_path / "sub_test.png").read_bytes()[:4] == b"\x89PNG"
        self._run(["--doc", "sub_pipeline_doc", "doc", "close"])
        print(f"\n  subprocess png: {out_png} ({os.path.getsize(out_png):,} bytes)")

    def test_error_is_clean_when_no_layer(self, tmp_path):
        self._run(["--json", "doc", "new", "--width", "8", "--height", "8",
                   "--name", "sub_err_doc"])
        result = self._run(["--json", "--doc", "sub_err_doc", "layer", "info",
                            "--layer", "does_not_exist"], check=False)
        assert result.returncode != 0
        assert "no layer named" in (result.stderr + result.stdout).lower()
        self._run(["--doc", "sub_err_doc", "doc", "close"])
