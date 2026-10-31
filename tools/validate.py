#!/usr/bin/env python3
"""Validate every library entry.

Static checks (always run, no TeX needed):
  - meta.json has the required fields with the right types;
  - ``type`` matches the folder (snippets/ preambles/ templates/), ids are
    unique kebab-case and match the folder + file names;
  - the .tex exists and has a ``%% >>> snippet`` region (and a ``preamble``
    region for snippets/preambles);
  - every package \\usepackage'd in the preamble region is listed in
    ``requires`` (warning), so the site shows what you need to load.

Compile check: each .tex must build with latexmk. Skipped (non-fatal) when no
TeX is installed, unless ``--strict`` (used in CI) is given.

Exit code is non-zero if any entry FAILs.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

from _common import (ID_RE, TYPE_DIRS, TYPES, extract_region, iter_meta_files, lib_root,
                     load_json, rel, tex_sibling)
from render_preview import compile_pdf, have_toolchain

REQUIRED = {"id": str, "name": str, "type": str, "category": list, "tags": list,
            "requires": list, "description": str, "preview": str}
OPTIONAL = {"notes": list, "added": str, "featured": bool, "links": list}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
USEPKG_RE = re.compile(r"\\usepackage\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")


def strip_comments(text: str) -> str:
    return "\n".join(re.sub(r"(?<!\\)%.*$", "", line) for line in text.splitlines())


def check_entry(meta_path: Path, root: Path, seen: dict[str, str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []
    try:
        meta = load_json(meta_path)
    except ValueError as exc:
        return [str(exc)], warns

    for key, typ in REQUIRED.items():
        if key not in meta:
            errors.append(f"missing required field '{key}'")
        elif not isinstance(meta[key], typ):
            errors.append(f"'{key}' must be a {typ.__name__}")
    for key, typ in OPTIONAL.items():
        if key in meta and not isinstance(meta[key], typ):
            errors.append(f"'{key}' must be a {typ.__name__}")
    for key in meta:
        if key not in REQUIRED and key not in OPTIONAL:
            warns.append(f"unknown field '{key}' (ignored by the site)")
    if errors:
        return errors, warns

    entry_id, entry_type = meta["id"], meta["type"]
    if not ID_RE.match(entry_id):
        errors.append(f"id {entry_id!r} must be kebab-case")
    if entry_type not in TYPES:
        errors.append(f"type must be one of {', '.join(TYPES)}")
    elif meta_path.parent.parent.name != TYPE_DIRS[entry_type]:
        errors.append(f"type '{entry_type}' should live under library/{TYPE_DIRS[entry_type]}/")
    if meta_path.parent.name != entry_id or meta_path.name != f"{entry_id}.meta.json":
        errors.append(f"folder and files must be named after the id: {entry_id}/{entry_id}.meta.json")
    if entry_id in seen:
        errors.append(f"duplicate id (also used by {seen[entry_id]})")
    seen[entry_id] = rel(meta_path.parent, root)
    if not meta["category"]:
        errors.append("'category' needs at least one value")
    if "added" in meta and not DATE_RE.match(meta["added"]):
        errors.append("'added' must be YYYY-MM-DD")
    for link in meta.get("links", []):
        if not (isinstance(link, dict) and isinstance(link.get("url"), str)):
            errors.append("each 'links' item must be {\"label\": ..., \"url\": ...}")

    tex = tex_sibling(meta_path)
    if not tex.exists():
        errors.append(f"missing {tex.name}")
        return errors, warns
    source = tex.read_text(encoding="utf-8")
    if extract_region(source, "snippet") is None:
        errors.append("no '%% >>> snippet' ... '%% <<< snippet' region in the .tex")
    preamble = extract_region(source, "preamble")
    if preamble is None and entry_type in ("snippet", "preamble"):
        errors.append("no '%% >>> preamble' ... '%% <<< preamble' region in the .tex")
    if preamble:
        used = {p.strip() for grp in USEPKG_RE.findall(strip_comments(preamble))
                for p in grp.split(",") if p.strip()}
        missing = sorted(used - set(meta["requires"]))
        if missing:
            warns.append("packages loaded but not in 'requires': " + ", ".join(missing))
    return errors, warns


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--strict", action="store_true",
                        help="require the compile check (fail if TeX is missing)")
    parser.add_argument("--no-compile", action="store_true", help="static checks only")
    args = parser.parse_args(argv)

    root = lib_root()
    can_compile = have_toolchain() and not args.no_compile
    if args.strict and not can_compile:
        print("error: --strict needs latexmk + pdftocairo on PATH")
        return 1

    seen: dict[str, str] = {}
    n_fail = n_warn = n = 0
    for meta_path in iter_meta_files(root):
        n += 1
        name = rel(meta_path.parent, root)
        errors, warns = check_entry(meta_path, root, seen)
        if not errors and can_compile:
            with tempfile.TemporaryDirectory(prefix="latexlib-validate-") as tmp:
                pdf, log = compile_pdf(tex_sibling(meta_path), Path(tmp))
                if pdf is None:
                    errors.append("does not compile:\n" + log)
        status = "FAIL" if errors else ("WARN" if warns else "ok")
        print(f"  {status:<4}  {name}")
        for e in errors:
            print(f"        x {e}")
        for w in warns:
            print(f"        ! {w}")
        n_fail += bool(errors)
        n_warn += bool(warns)

    compiled = "compiled" if can_compile else "compile SKIPPED (no TeX)"
    print(f"\n{n} entries, {n_fail} failed, {n_warn} with warnings — {compiled}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
