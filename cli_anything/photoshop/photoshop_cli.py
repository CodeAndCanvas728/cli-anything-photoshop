"""cli-anything-photoshop — a stateful, agent-native CLI for Adobe Photoshop.

Every command drives the *real* Photoshop application on macOS through the
AppleScript / ExtendScript bridge (see ``utils/photoshop_backend.py``).
Default invocation (no subcommand) enters the REPL, per HARNESS.md.

Global options (place before the subcommand):

    cli-anything-photoshop --json --doc "My Shot" layer list

- ``--json`` machine-readable output for every command (agent mode)
- ``--doc`` target a specific open document by name or 1-based index
  (default: the active document)
- ``--timeout`` seconds to wait on Photoshop operations (default 120)
"""
from __future__ import annotations

import json as _json
import shlex

import click

from cli_anything.photoshop.core import adjustments, app_control, documents, export
from cli_anything.photoshop.core import history as history_mod
from cli_anything.photoshop.core import layers, session as session_mod
from cli_anything.photoshop.utils.photoshop_backend import PhotoshopError
from cli_anything.photoshop.utils.repl_skin import ReplSkin

SOFTWARE = "photoshop"
VERSION = "1.0.0"


class Obj(dict):
    """Click context object with attribute access."""


def _emit(ctx: click.Context, data) -> None:
    """Unified output: --json → stable JSON, else concise human format."""
    if ctx.obj["json"]:
        click.echo(_json.dumps({"ok": True, "data": data}, indent=2))
        return
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (list, dict)):
                continue
            click.secho(f"{key}: ", fg="cyan", nl=False)
            click.echo(value)
    else:
        click.echo(data)


def _emit_rows(ctx: click.Context, rows: list[dict], columns: list[str]) -> None:
    if ctx.obj["json"]:
        click.echo(_json.dumps({"ok": True, "data": rows}, indent=2))
        return
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) if rows else len(c) for c in columns}
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    click.secho(header, fg="cyan")
    click.secho("-" * len(header), fg="cyan")
    for r in rows:
        click.echo("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in columns))


def _touch(ctx: click.Context, command: str, doc=None) -> None:
    try:
        session_mod.record(command, doc)
    except OSError:
        pass  # session memory must never break a Photoshop command


def _guard(exc: Exception) -> click.ClickException:
    if isinstance(exc, PhotoshopError):
        return click.ClickException(str(exc))
    return click.ClickException(f"{type(exc).__name__}: {exc}")


@click.group(invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True, help="JSON output for agents/scripts.")
@click.option("--doc", "doc_target", default=None,
              help="Target document by name or 1-based index (default: active document).")
@click.option("--timeout", default=120.0, type=float,
              help="Seconds to wait for Photoshop operations (default 120).")
@click.version_option(VERSION, prog_name="cli-anything-photoshop")
@click.pass_context
def cli(ctx: click.Context, as_json: bool, doc_target, timeout: float):
    """Command-line control of Adobe Photoshop 2026 (real app, via scripting)."""
    ctx.obj = Obj(json=as_json, doc=doc_target, timeout=timeout)
    if ctx.invoked_subcommand is None:
        ctx.invoke(repl)


# ── app ────────────────────────────────────────────────────────────────────
@cli.group()
def app():
    """Application-level info and control."""


@app.command("info")
@click.pass_context
def app_info(ctx: click.Context):
    """Running state + version (does not launch Photoshop)."""
    try:
        _emit(ctx, app_control.app_info())
    except Exception as exc:
        raise _guard(exc) from exc


@app.command("launch")
@click.option("--wait", default=90.0, type=float)
@click.pass_context
def app_launch(ctx: click.Context, wait: float):
    """Launch Photoshop if needed and wait until it is scriptable."""
    try:
        info = app_control.launch_app(wait=wait)
        _touch(ctx, "app launch")
        _emit(ctx, info)
    except Exception as exc:
        raise _guard(exc) from exc


@app.command("quit")
@click.pass_context
def app_quit(ctx: click.Context):
    """Ask Photoshop to quit (unsaved dialogs will time out — save first)."""
    try:
        _touch(ctx, "app quit")
        _emit(ctx, app_control.quit_app())
    except Exception as exc:
        raise _guard(exc) from exc


# ── open ───────────────────────────────────────────────────────────────────
@cli.command("open")
@click.argument("path", type=click.Path(exists=False))
@click.pass_context
def open_document(ctx: click.Context, path: str):
    """Open a file on disk as a new Photoshop document."""
    import os

    if not os.path.isabs(path):
        raise click.ClickException("path must be absolute")
    if not os.path.exists(path):
        raise click.ClickException(f"file not found: {path}")
    from cli_anything.photoshop.utils.photoshop_backend import qr, run_js, strict_js

    code = f"var d=app.open(new File({qr(path)}));out=[String(d.name)].join('|');"
    try:
        raw = run_js(strict_js("open", "var out;" + code + ";out;"),
                     timeout=ctx.obj["timeout"])
        name = raw.split("|")[0]
        _touch(ctx, "open", name)
        _emit(ctx, {"name": name})
    except Exception as exc:
        raise _guard(exc) from exc


# ── doc ────────────────────────────────────────────────────────────────────
@cli.group()
def doc():
    """Open documents: create, inspect, transform, close."""


@doc.command("new")
@click.option("--width", required=True, type=int)
@click.option("--height", required=True, type=int)
@click.option("--dpi", default=72.0, type=float)
@click.option("--name", default=None)
@click.option("--mode", type=click.Choice(list(documents.MODES)), default="rgb")
@click.option("--fill", type=click.Choice(list(documents.FILLS)), default="white")
@click.option("--bits", type=int, default=8)
@click.pass_context
def doc_new(ctx: click.Context, width, height, dpi, name, mode, fill, bits):
    """Create a real document."""
    try:
        data = documents.new_document(width, height, dpi, name, mode, fill, bits,
                                      timeout=ctx.obj["timeout"])
        _touch(ctx, "doc new", data.get("name"))
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@doc.command("list")
@click.pass_context
def doc_list(ctx: click.Context):
    """Open documents."""
    try:
        _emit_rows(ctx, documents.list_documents(timeout=ctx.obj["timeout"]),
                   ["index", "name", "width_px", "height_px", "mode"])
    except Exception as exc:
        raise _guard(exc) from exc


@doc.command("info")
@click.pass_context
def doc_info(ctx: click.Context):
    """Introspect the target document."""
    try:
        data = documents.doc_info(ctx.obj["doc"], timeout=ctx.obj["timeout"])
        _touch(ctx, "doc info", data.get("name"))
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@doc.command("flatten")
@click.pass_context
def doc_flatten(ctx: click.Context):
    """Flatten the document into one background layer."""
    try:
        data = documents.flatten_document(ctx.obj["doc"], timeout=ctx.obj["timeout"])
        _touch(ctx, "doc flatten", data.get("name"))
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@doc.command("resize-image")
@click.option("--width", type=float, default=None)
@click.option("--height", type=float, default=None)
@click.option("--resolution", type=float, default=72.0)
@click.option("--resample", type=click.Choice(list(documents.RESAMPLE)), default="bicubic")
@click.pass_context
def doc_resize_image(ctx: click.Context, width, height, resolution, resample):
    """Scale image; pass exactly one of --width/--height (keeps ratio)."""
    try:
        data = documents.resize_image(ctx.obj["doc"], width, height, resolution, resample,
                                      timeout=ctx.obj["timeout"])
        _touch(ctx, "doc resize-image", data.get("name"))
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@doc.command("resize-canvas")
@click.option("--width", required=True, type=int)
@click.option("--height", required=True, type=int)
@click.pass_context
def doc_resize_canvas(ctx: click.Context, width, height):
    """Change canvas size (content stays centered)."""
    try:
        data = documents.resize_canvas(ctx.obj["doc"], width, height,
                                       timeout=ctx.obj["timeout"])
        _touch(ctx, "doc resize-canvas", data.get("name"))
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@doc.command("rotate")
@click.option("--degrees", type=click.Choice(["90", "-90", "180"]), required=True)
@click.pass_context
def doc_rotate(ctx: click.Context, degrees: str):
    """Rotate the canvas (90 = clockwise in this engine)."""
    try:
        data = documents.rotate_canvas(ctx.obj["doc"], int(degrees),
                                       timeout=ctx.obj["timeout"])
        _touch(ctx, "doc rotate", data.get("name"))
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@doc.command("flip")
@click.option("--axis", type=click.Choice(["horizontal", "vertical"]), required=True)
@click.pass_context
def doc_flip(ctx: click.Context, axis: str):
    """Mirror the canvas."""
    try:
        data = documents.flip_canvas(ctx.obj["doc"], axis, timeout=ctx.obj["timeout"])
        _touch(ctx, "doc flip", data.get("name"))
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@doc.command("close")
@click.option("--save/--discard", default=False)
@click.pass_context
def doc_close(ctx: click.Context, save: bool):
    """Close the target document (default: discard changes)."""
    try:
        data = documents.close_document(ctx.obj["doc"], save, timeout=ctx.obj["timeout"])
        _touch(ctx, "doc close", data.get("name"))
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


# ── layer ──────────────────────────────────────────────────────────────────
@cli.group()
def layer():
    """Layers of the target document."""
    pass


_LAYER_OPT = click.option("--layer", "layer", default=None,
                          help="Layer name (default: active layer)")


@layer.command("list")
@click.pass_context
def layer_list(ctx: click.Context):
    """All layers, nested included."""
    try:
        rows = layers.list_layers(ctx.obj["doc"], timeout=ctx.obj["timeout"])
        _touch(ctx, "layer list", ctx.obj["doc"])
        _emit_rows(ctx, rows, ["depth", "name", "kind", "opacity", "visible", "parent"])
    except Exception as exc:
        raise _guard(exc) from exc


@layer.command("info")
@_LAYER_OPT
@click.pass_context
def layer_info(ctx: click.Context, layer):
    """Deep info for one layer (bounds + text content if text)."""
    try:
        data = layers.layer_info(ctx.obj["doc"], layer, timeout=ctx.obj["timeout"])
        _touch(ctx, "layer info", ctx.obj["doc"])
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@layer.command("new")
@click.option("--kind", type=click.Choice(["art", "text"]), default="art")
@click.option("--name", default=None)
@click.pass_context
def layer_new(ctx: click.Context, kind, name):
    """Add an art (pixel) or text layer; it becomes the active layer."""
    try:
        data = layers.new_layer(ctx.obj["doc"], kind, name, timeout=ctx.obj["timeout"])
        _touch(ctx, "layer new", ctx.obj["doc"])
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@layer.command("select")
@_LAYER_OPT
@click.pass_context
def layer_select(ctx: click.Context, layer):
    """Make the target layer active."""
    try:
        data = layers.select_layer(ctx.obj["doc"], layer, timeout=ctx.obj["timeout"])
        _touch(ctx, "layer select", ctx.obj["doc"])
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@layer.command("rename")
@_LAYER_OPT
@click.option("--new-name", required=True)
@click.pass_context
def layer_rename(ctx: click.Context, layer, new_name):
    """Rename the target layer."""
    try:
        data = layers.rename_layer(ctx.obj["doc"], layer, new_name,
                                   timeout=ctx.obj["timeout"])
        _touch(ctx, "layer rename", ctx.obj["doc"])
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@layer.command("delete")
@_LAYER_OPT
@click.pass_context
def layer_delete(ctx: click.Context, layer):
    """Delete the target layer."""
    try:
        data = layers.delete_layer(ctx.obj["doc"], layer, timeout=ctx.obj["timeout"])
        _touch(ctx, "layer delete", ctx.obj["doc"])
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@layer.command("visible")
@_LAYER_OPT
@click.option("--state", type=click.Choice(["show", "hide", "toggle"]), default="toggle")
@click.pass_context
def layer_visible(ctx: click.Context, layer, state):
    """Show/hide/toggle the target layer."""
    try:
        data = layers.set_visible(ctx.obj["doc"], layer, state, timeout=ctx.obj["timeout"])
        _touch(ctx, "layer visible", ctx.obj["doc"])
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@layer.command("opacity")
@_LAYER_OPT
@click.argument("value", type=float)
@click.pass_context
def layer_opacity(ctx: click.Context, layer, value):
    """Set layer opacity percent (0-100)."""
    try:
        data = layers.set_opacity(ctx.obj["doc"], layer, value, timeout=ctx.obj["timeout"])
        _touch(ctx, "layer opacity", ctx.obj["doc"])
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@layer.command("blend")
@_LAYER_OPT
@click.argument("mode", type=click.Choice(list(layers.BLEND_MODES)))
@click.pass_context
def layer_blend(ctx: click.Context, layer, mode):
    """Set the blend mode (engine enum subset)."""
    try:
        data = layers.set_blend_mode(ctx.obj["doc"], layer, mode, timeout=ctx.obj["timeout"])
        _touch(ctx, "layer blend", ctx.obj["doc"])
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@layer.command("text-get")
@_LAYER_OPT
@click.pass_context
def layer_text_get(ctx: click.Context, layer):
    """Read text content of a text layer."""
    try:
        data = layers.get_text(ctx.obj["doc"], layer, timeout=ctx.obj["timeout"])
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@layer.command("text-set")
@_LAYER_OPT
@click.argument("value")
@click.pass_context
def layer_text_set(ctx: click.Context, layer, value):
    """Write text content into a text layer."""
    try:
        data = layers.set_text(ctx.obj["doc"], layer, value, timeout=ctx.obj["timeout"])
        _touch(ctx, "layer text-set", ctx.obj["doc"])
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@layer.command("merge-down")
@_LAYER_OPT
@click.pass_context
def layer_merge_down(ctx: click.Context, layer):
    """Merge the target layer into the one below."""
    try:
        data = layers.merge_down(ctx.obj["doc"], layer, timeout=ctx.obj["timeout"])
        _touch(ctx, "layer merge-down", ctx.obj["doc"])
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


# ── adj ────────────────────────────────────────────────────────────────────
@cli.group()
def adj():
    """Adjustments applied to the target (pixel) layer."""


@adj.command("run")
@click.argument("adjustment", type=click.Choice(list(adjustments.ADJUSTMENTS)))
@_LAYER_OPT
@click.option("--amount", type=int, default=None)
@click.pass_context
def adj_run(ctx: click.Context, adjustment, layer, amount):
    """Apply one adjustment (invert|desaturate|auto-contrast|auto-levels|posterize|threshold)."""
    try:
        data = adjustments.apply_adjustment(ctx.obj["doc"], adjustment, layer, amount,
                                            timeout=ctx.obj["timeout"])
        _touch(ctx, "adj " + adjustment, ctx.obj["doc"])
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


# ── history ────────────────────────────────────────────────────────────────
@cli.group()
def history():
    """Document undo history (Photoshop's own)."""


@history.command("list")
@click.option("--limit", type=int, default=50)
@click.pass_context
def history_list(ctx: click.Context, limit: int):
    """List history states (current flagged)."""
    try:
        data = history_mod.list_history(ctx.obj["doc"], limit, timeout=ctx.obj["timeout"])
        _touch(ctx, "history list", data.get("document"))
        if ctx.obj["json"]:
            _emit(ctx, data)
            return
        _emit(ctx, {"document": data["document"], "current_state": data["current_index"]})
        click.secho("  i   name (y = current)", fg="cyan")
        for s in data["states"]:
            flag = "  <- current" if s["current"] else ""
            click.echo(f"  {s['index']:>3}  {s['name']}{flag}")
    except Exception as exc:
        raise _guard(exc) from exc


@history.command("undo")
@click.pass_context
def history_undo(ctx: click.Context):
    """Step one state back."""
    try:
        data = history_mod.undo_document(ctx.obj["doc"], timeout=ctx.obj["timeout"])
        _touch(ctx, "history undo", data.get("document"))
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@history.command("redo")
@click.pass_context
def history_redo(ctx: click.Context):
    """Step one state forward."""
    try:
        data = history_mod.redo_document(ctx.obj["doc"], timeout=ctx.obj["timeout"])
        _touch(ctx, "history redo", data.get("document"))
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@history.command("step")
@click.argument("offset", type=int)
@click.pass_context
def history_step(ctx: click.Context, offset: int):
    """Step the history cursor by N states (+forward / -back)."""
    try:
        data = history_mod.history_step(ctx.obj["doc"], offset, timeout=ctx.obj["timeout"])
        _touch(ctx, "history step", data.get("document"))
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


# ── export ─────────────────────────────────────────────────────────────────
@cli.group("export")
def export_grp():
    """Save/convert documents via real Photoshop rendering."""
    pass


@export_grp.command("document")
@click.argument("out", type=click.Path())
@click.option("--format", "fmt", type=click.Choice(["png", "jpg", "jpeg", "psd"]), default=None,
              help="Defaults from the file extension.")
@click.option("--quality", type=int, default=8, help="JPEG quality 0..12.")
@click.option("--overwrite", is_flag=True)
@click.pass_context
def export_document_cmd(ctx: click.Context, out, fmt, quality, overwrite):
    """Save the target document as PNG/JPG/PSD (magic bytes verified)."""
    import os

    if not os.path.isabs(out):
        raise click.ClickException("--out path must be absolute")
    try:
        data = export.export_document(ctx.obj["doc"], out, fmt, quality, overwrite,
                                      timeout=ctx.obj["timeout"])
        _touch(ctx, "export document", ctx.obj["doc"])
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


@export_grp.command("convert")
@click.argument("src", type=click.Path())
@click.argument("out", type=click.Path())
@click.option("--format", "fmt", type=click.Choice(["png", "jpg", "jpeg", "psd"]), default=None)
@click.option("--quality", type=int, default=8)
@click.option("--overwrite", is_flag=True)
@click.pass_context
def export_convert_cmd(ctx: click.Context, src, out, fmt, quality, overwrite):
    """Open SRC in Photoshop, save as OUT, close the temp document."""
    import os

    if not os.path.isabs(src):
        raise click.ClickException("src must be absolute")
    if not os.path.isabs(out):
        raise click.ClickException("out must be absolute")
    try:
        data = export.convert_file(src, out, fmt, quality, overwrite,
                                   timeout=ctx.obj["timeout"])
        _emit(ctx, data)
    except Exception as exc:
        raise _guard(exc) from exc


# ── session ────────────────────────────────────────────────────────────────
@cli.group()
def session():
    """Tiny agent workspace memory (last doc + command trail)."""


@session.command("status")
@click.pass_context
def session_status(ctx: click.Context):
    """Show the persisted session state."""
    data = session_mod.session_status()
    if ctx.obj["json"]:
        _emit(ctx, data)
        return
    _emit(ctx, {"last_doc": data.get("last_doc")})
    for entry in data.get("trail", [])[-10:]:
        click.echo(f"  {entry['ts']}  {entry['command']:20} doc={entry['doc']}")


@session.command("clear")
@click.pass_context
def session_clear(ctx: click.Context):
    """Forget the session state."""
    _emit(ctx, session_mod.clear_session())


# ── repl ───────────────────────────────────────────────────────────────────
REPL_HELP = dict(
    info="app info", launch="app launch", new="doc new --width 1080 --height 1080",
    list="doc list", layers="layer list", export="export document /tmp/x.png",
    help="this text", exit="leave the REPL",
)


@cli.command("repl")
@click.pass_context
def repl(ctx: click.Context):
    """Interactive REPL (also the no-argument default)."""
    skin = ReplSkin(SOFTWARE, version=VERSION)
    skin.print_banner()
    ptk_session = skin.create_prompt_session()
    skin.help(REPL_HELP)
    skin.info("Type commands like 'doc new --width 64 --height 64' (see help). exit quits.")
    while True:
        try:
            line = skin.get_input(ptk_session)
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in ("exit", "quit", "q"):
            break
        if line == "help":
            skin.help(REPL_HELP)
            continue
        try:
            args = shlex.split(line)
        except ValueError as exc:
            skin.error(f"bad command line: {exc}")
            continue
        try:
            cli.main(args=args, prog_name="cli-anything-photoshop", standalone_mode=False,
                     obj=ctx.obj)
        except click.exceptions.Abort:
            skin.warning("aborted")
        except click.ClickException as exc:
            skin.error(exc.format_message())
        except click.exceptions.UsageError as exc:
            skin.error(str(exc))
        except SystemExit:  # --json etc. unrelated; keep repl alive
            pass
        except Exception as exc:  # noqa: BLE001 — REPL must not die on command errors
            skin.error(str(exc))
    skin.print_goodbye()


def main() -> None:  # console_scripts entry point
    cli(prog_name="cli-anything-photoshop")


if __name__ == "__main__":
    main()
