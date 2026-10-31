"""Shared helpers for the library tooling scripts.

Stdlib only, so every tool runs with a bare ``python3``.

Adapted from OpenTikZ (https://github.com/opentikz/opentikz, MIT).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator

# Entry types, in display order. The folder under library/ is the plural.
TYPES = ("snippet", "preamble", "template", "icon")
TYPE_DIRS = {"snippet": "snippets", "preamble": "preambles", "template": "templates",
             "icon": "icons"}
TYPE_TITLES = {"snippet": "Snippets", "preamble": "Preambles", "template": "Templates",
               "icon": "Icons"}

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Region markers inside an entry's .tex. Everything between a pair is what the
# site's "Copy preamble" / "Copy snippet" buttons copy.
#
#   %% >>> preamble          %% >>> snippet
#   \usepackage{booktabs}    \begin{table} ... \end{table}
#   %% <<< preamble          %% <<< snippet
REGION_RE = r"^[ \t]*%%[ \t]*>>>[ \t]*{name}[ \t]*\n(.*?)^[ \t]*%%[ \t]*<<<[ \t]*{name}[ \t]*$"


def lib_root() -> Path:
    """The library root folder (parent of tools/)."""
    return Path(__file__).resolve().parent.parent


def load_config(root: Path | None = None) -> dict:
    base = root or lib_root()
    return load_json(base / "site.config.json")


def iter_meta_files(root: Path | None = None) -> Iterator[Path]:
    """Yield every ``*.meta.json`` under library/<type-dir>/, sorted."""
    base = (root or lib_root()) / "library"
    for t in TYPES:
        d = base / TYPE_DIRS[t]
        if d.is_dir():
            yield from sorted(d.rglob("*.meta.json"))


def load_json(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON ({exc})") from exc


def tex_sibling(meta_path: Path) -> Path:
    """``foo/bar.meta.json`` -> ``foo/bar.tex``."""
    return meta_path.with_name(meta_path.name[: -len(".meta.json")] + ".tex")


def extract_region(tex_source: str, name: str) -> str | None:
    """Return the text between ``%% >>> name`` and ``%% <<< name`` (dedented
    of trailing blank lines), or None when the markers are absent."""
    m = re.search(REGION_RE.format(name=re.escape(name)), tex_source, re.S | re.M)
    if not m:
        return None
    return m.group(1).rstrip() + "\n"


def strip_markers(tex_source: str) -> str:
    """The full file without the ``%% >>>`` / ``%% <<<`` marker lines."""
    return re.sub(r"^[ \t]*%%[ \t]*(?:>>>|<<<)[ \t]*\w+[ \t]*\n", "", tex_source, flags=re.M)


def rel(path: Path, root: Path | None = None) -> str:
    base = root or lib_root()
    return path.resolve().relative_to(base).as_posix()
