"""All Photoshop behaviors must be real; unit tests focus on the pure logic.

These tests intentionally never touch Photoshop — they verify every layer of
compiled logic that *around* the real app works hermetically.
"""
from __future__ import annotations

import os

import pytest

import cli_anything.photoshop.core.documents as documents_core
import cli_anything.photoshop.core.export as export_core
import cli_anything.photoshop.core.history as history_core
import cli_anything.photoshop.core.session as session_core
import cli_anything.photoshop.utils.photoshop_backend as backend


# ── qr() string escaping ───────────────────────────────────────────────────
def test_qr_escapes_quotes_and_backslash():
    assert backend.qr('say "hi"') == '"say \\"hi\\""'


def test_qr_escapes_newlines():
    assert backend.qr("a\nb") == '"a\\nb"'


def test_qr_escapes_control_chars():
    assert backend.qr("x\ty") == '"x\\ty"'


# ── parse_records packing ─────────────────────────────────────────────────
def test_parse_records_single_record():
    assert backend.parse_records("a\x1fb\x1fc") == [["a", "b", "c"]]


def test_parse_records_multiple():
    assert backend.parse_records("a\x1fb\x1ec\x1fd") == [["a", "b"], ["c", "d"]]


def test_parse_records_empty():
    assert backend.parse_records("") == []


def test_parse_records_preserves_leading_content():
    # layer names can legitimately contain newline-ish content; no stripping
    assert backend.parse_records("\x1fn")[0][:1] == [""]


# ── error translation ─────────────────────────────────────────────────────
def test_translate_busy_error():
    msg = backend._translate_osascript_error("execution error: ... (-1712)")
    assert "busy" in msg.lower() or "timed out" in msg.lower()


def test_translate_permission_error():
    msg = backend._translate_osascript_error(
        "Not authorized to send Apple events to Adobe Photoshop 2026. (-1743)")
    assert "Automation" in msg


def test_translate_passthrough():
    raw = "execution error: something very specific"
    assert backend._translate_osascript_error(raw) == raw


# ── app discovery ─────────────────────────────────────────────────────────
def test_find_photoshop_env_override(monkeypatch):
    backend2 = backend  # same module; find_photoshop() reads env each call
    monkeypatch.setenv("CLI_ANYTHING_PHOTOSHOP_APP", "/opt/Foo.app")
    assert backend2.find_photoshop() == "Foo"


def test_find_photoshop_real_install(monkeypatch):
    # Photoshop IS installed on this machine (hard dependency); name resolves.
    monkeypatch.delenv("CLI_ANYTHING_PHOTOSHOP_APP", raising=False)
    name = backend.find_photoshop()
    assert name.startswith("Adobe Photoshop")


# ── session state (locked writes) ─────────────────────────────────────────
def test_session_roundtrip(tmp_path):
    path = str(tmp_path / "session.json")
    state = session_core.record("doc new", "Probe", path=path)
    assert state["last_doc"] == "Probe"
    loaded = session_core.load_session(path=path)
    assert loaded["last_doc"] == "Probe"
    assert loaded["trail"][-1]["command"] == "doc new"


def test_session_corrupt_file_recovers(tmp_path):
    path = tmp_path / "session.json"
    path.write_text("{not json", encoding="utf-8")
    assert session_core.load_session(path=str(path))["last_doc"] is None


def test_session_clear(tmp_path):
    path = str(tmp_path / "session.json")
    session_core.record("layer list", "D", path=path)
    cleared = session_core.clear_session(path=path)
    assert cleared == {"last_doc": None, "trail": []}


# ── export validation ─────────────────────────────────────────────────────
def test_check_overwrite_refuses(tmp_path):
    target = tmp_path / "out.png"
    target.write_bytes(b"already here")
    with pytest.raises(Exception):
        export_core._check_overwrite(str(target), overwrite=False)


def test_check_overwrite_allows(tmp_path):
    target = tmp_path / "out.png"
    target.write_bytes(b"already here")
    export_core._check_overwrite(str(target), overwrite=True)


def test_verify_output_rejects_bad_magic(tmp_path):
    bad = tmp_path / "fake.png"
    bad.write_bytes(b"NOT A PNG AT ALL")
    with pytest.raises(Exception):
        export_core._verify_output(str(bad), "png")


def test_verify_output_accepts_png(tmp_path):
    good = tmp_path / "real.png"
    good.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
    result = export_core._verify_output(str(good), "png")
    assert result["format"] == "png" and result["bytes"] > 0


def test_verify_output_accepts_psd(tmp_path):
    good = tmp_path / "real.psd"
    good.write_bytes(b"8BPS" + b"\x00" * 10)
    assert export_core._verify_output(str(good), "psd")["format"] == "psd"


# ── documents helpers ─────────────────────────────────────────────────────
def test_strip_px():
    assert documents_core._strip_px("64 px") == 64.0


def test_doc_selector_js_none():
    assert documents_core._doc_selector_js(None) == "null"


def test_doc_selector_js_name():
    assert documents_core._doc_selector_js("My Doc") == '{s:\'name\',v:"My Doc"}'


def test_doc_selector_js_index():
    assert documents_core._doc_selector_js(2) == "{s:'index',v:2}"


def test_new_document_rejects_bad_bits():
    with pytest.raises(ValueError):
        documents_core.new_document(4, 4, bits=24)


# ── history / adjustments validation ──────────────────────────────────────
def test_history_step_rejects_zero():
    with pytest.raises(ValueError):
        history_core.history_step(None, 0)


def test_adjustment_requires_amount():
    import cli_anything.photoshop.core.adjustments as adj

    with pytest.raises(ValueError):
        adj.apply_adjustment(None, "posterize")
