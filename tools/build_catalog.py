#!/usr/bin/env python3
"""Build catalog.json from every entry's metadata.

Walks library/{snippets,preambles,templates}/, reads each ``*.meta.json`` and
writes a stable, sorted ``catalog.json``. AUTO-GENERATED — never hand-edit it.
(build_site.py also regenerates it, so you rarely need to run this directly.)

``--check`` verifies catalog.json is current without writing (exit 1 if stale).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _common import iter_meta_files, lib_root, load_json, rel

CATALOG_NAME = "catalog.json"


def build(root: Path) -> list[dict]:
    entries: list[dict] = []
    for meta_path in iter_meta_files(root):
        entry = dict(load_json(meta_path))
        entry["path"] = rel(meta_path.parent, root)
        entries.append(entry)
    entries.sort(key=lambda e: (e.get("type", ""), e.get("id", "")))
    return entries


def serialize(entries: list[dict]) -> str:
    return json.dumps(entries, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write(root: Path) -> list[dict]:
    entries = build(root)
    (root / CATALOG_NAME).write_text(serialize(entries), encoding="utf-8")
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify catalog.json is current; exit 1 if stale")
    args = parser.parse_args(argv)

    root = lib_root()
    entries = build(root)
    text = serialize(entries)
    path = root / CATALOG_NAME
    if args.check:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != text:
            print(f"error: {CATALOG_NAME} is out of date; run tools/build_catalog.py")
            return 1
        print(f"{CATALOG_NAME} is up to date")
        return 0
    path.write_text(text, encoding="utf-8")
    print(f"wrote {CATALOG_NAME} ({len(entries)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
