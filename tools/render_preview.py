#!/usr/bin/env python3
"""Render an entry's .tex to an .svg preview (page 1).

Pipeline:  latexmk -pdf  ->  pdftocairo -svg (first page only)

PDF output (not DVI) is used so entries can \\includegraphics PNG/PDF/JPG files.
Snippets and preambles are cropped to their ink (Ghostscript bbox), so they can
use an ordinary ``article`` test file with floats and captions; templates keep
the full first page.

Usage:
  python3 tools/render_preview.py library/snippets/booktabs-table
  python3 tools/render_preview.py --missing     # every entry without a preview
  python3 tools/render_preview.py --all         # re-render everything

Needs a TeX distribution (latexmk + pdflatex) and poppler's pdftocairo.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from _common import iter_meta_files, lib_root, load_json, tex_sibling


def have_toolchain() -> bool:
    return all(shutil.which(t) for t in ("latexmk", "pdftocairo"))


def require_toolchain() -> None:
    missing = [t for t in ("latexmk", "pdftocairo") if shutil.which(t) is None]
    if missing:
        sys.exit("error: required tool(s) not found on PATH: " + ", ".join(missing)
                 + "\n       install a TeX distribution (latexmk) and poppler-utils (pdftocairo).")


def compile_pdf(tex: Path, out_dir: Path) -> tuple[Path | None, str]:
    """Compile ``tex`` to PDF in ``out_dir``. Returns (pdf or None, log tail).

    Runs from the entry's own folder so relative \\includegraphics / \\input
    paths (e.g. an image saved next to the .tex) resolve."""
    proc = subprocess.run(
        ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error",
         f"-output-directory={out_dir}", tex.name],
        cwd=tex.parent, capture_output=True, text=True,
    )
    pdf = out_dir / (tex.stem + ".pdf")
    if proc.returncode != 0 or not pdf.exists():
        return None, _error_excerpt(out_dir / (tex.stem + ".log"), proc.stdout + proc.stderr)
    return pdf, ""


def _error_excerpt(log: Path, fallback: str) -> str:
    """The TeX error lines ('! ...' plus the 'l.<n>' context) from the .log,
    which is far more useful than latexmk's own chatter."""
    if log.exists():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        out: list[str] = []
        for i, line in enumerate(lines):
            if line.startswith("!"):
                out.extend(lines[i:i + 4])
                if len(out) > 30:
                    break
        if out:
            return "\n".join("        " + l for l in out)
    return "\n".join("        " + l for l in fallback.strip().splitlines()[-20:])


CROP_MARGIN_PT = 8.0
_BBOX_RE = re.compile(r"%%HiResBoundingBox:\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)")
_SVG_SIZE_RE = re.compile(r'<svg([^>]*?)\swidth="([\d.]+)"\s+height="([\d.]+)"\s+viewBox="[^"]*"')


def ink_bbox(pdf: Path) -> tuple[float, float, float, float] | None:
    """Bounding box of everything drawn on page 1 (PDF coords, origin bottom-left)."""
    if shutil.which("gs") is None:
        return None
    proc = subprocess.run(
        ["gs", "-q", "-dBATCH", "-dNOPAUSE", "-dSAFER", "-sDEVICE=bbox",
         "-dFirstPage=1", "-dLastPage=1", str(pdf)],
        capture_output=True, text=True)
    m = _BBOX_RE.search(proc.stdout + proc.stderr)
    if not m:
        return None
    x0, y0, x1, y1 = map(float, m.groups())
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def crop_svg(svg: Path, bbox: tuple[float, float, float, float]) -> None:
    """Crop a pdftocairo SVG (units = pt, origin top-left) to ``bbox`` by
    rewriting its width/height/viewBox — the drawing itself is untouched."""
    text = svg.read_text(encoding="utf-8")
    m = _SVG_SIZE_RE.search(text)
    if not m:
        return
    page_h = float(m.group(3))
    x0, y0, x1, y1 = bbox
    pad = CROP_MARGIN_PT
    vx, vy = x0 - pad, page_h - y1 - pad
    w, h = (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad
    new = f'<svg{m.group(1)} width="{w:.2f}" height="{h:.2f}" viewBox="{vx:.2f} {vy:.2f} {w:.2f} {h:.2f}"'
    svg.write_text(text[:m.start()] + new + text[m.end():], encoding="utf-8")


def render(tex: Path, svg: Path, *, crop: bool = True) -> None:
    """Compile and convert page 1 to SVG. With ``crop`` (snippets/preambles),
    trim the page to the ink, so entries can use a normal class like
    ``article`` — with floats, captions and numbering — and still get a tight
    preview. Templates keep the whole page."""
    with tempfile.TemporaryDirectory(prefix="latexlib-render-") as tmp:
        pdf, log = compile_pdf(tex, Path(tmp))
        if pdf is None:
            raise RuntimeError(f"latexmk failed for {tex.name}\n{log}")
        subprocess.run(["pdftocairo", "-svg", "-f", "1", "-l", "1", str(pdf), str(svg)],
                       check=True, capture_output=True, text=True)
        if crop:
            bbox = ink_bbox(pdf)
            if bbox:
                crop_svg(svg, bbox)


def entry_targets(root: Path) -> list[tuple[Path, Path, bool]]:
    """(tex, svg, crop) for every entry in the library."""
    out = []
    for meta_path in iter_meta_files(root):
        meta = load_json(meta_path)
        out.append((tex_sibling(meta_path), meta_path.parent / meta.get("preview", "preview.svg"),
                    meta.get("type") != "template"))
    return out


def resolve_one(target: Path) -> tuple[Path, Path, bool]:
    """Accept an entry folder, its .tex, or its .meta.json."""
    if target.is_dir():
        metas = sorted(target.glob("*.meta.json"))
        if len(metas) != 1:
            sys.exit(f"error: expected exactly one *.meta.json in {target}")
        meta_path = metas[0]
    elif target.name.endswith(".meta.json"):
        meta_path = target
    elif target.suffix == ".tex":
        meta_path = target.with_name(target.stem + ".meta.json")
    else:
        sys.exit(f"error: not an entry folder or .tex: {target}")
    if not meta_path.exists():
        sys.exit(f"error: {meta_path} not found")
    meta = load_json(meta_path)
    return (tex_sibling(meta_path), meta_path.parent / meta.get("preview", "preview.svg"),
            meta.get("type") != "template")


def render_many(pairs: list[tuple[Path, Path, bool]], root: Path) -> int:
    """Render each entry; report failures without stopping. Returns #failures."""
    failures = 0
    for tex, svg, crop in pairs:
        name = tex.relative_to(root).as_posix()
        try:
            render(tex, svg, crop=crop)
            print(f"  ok    {name}")
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            failures += 1
            print(f"  FAIL  {name}\n{exc}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", nargs="?", type=Path, help="entry folder or .tex")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="re-render every entry")
    group.add_argument("--missing", action="store_true", help="render entries with no preview yet")
    args = parser.parse_args(argv)

    require_toolchain()
    root = lib_root()
    if args.all or args.missing:
        pairs = entry_targets(root)
        if args.missing:
            pairs = [p for p in pairs if not p[1].exists()]
    elif args.target:
        pairs = [resolve_one(args.target.resolve())]
    else:
        parser.error("give an entry folder, or --all / --missing")

    if not pairs:
        print("nothing to render")
        return 0
    print(f"rendering {len(pairs)} preview(s)")
    return 1 if render_many(pairs, root) else 0


if __name__ == "__main__":
    raise SystemExit(main())
