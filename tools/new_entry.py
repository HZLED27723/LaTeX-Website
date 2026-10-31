#!/usr/bin/env python3
"""Scaffold a new library entry (the "log something new" command).

  python3 tools/new_entry.py snippet "Booktabs table" --category tables --tags table,booktabs
  python3 tools/new_entry.py preamble "Thesis preamble" --category setup
  python3 tools/new_entry.py template "Lab report" --category documents
  python3 tools/new_entry.py icon "Arduino" --category brands,electronics

Creates library/<type>s/<id>/ with:
  <id>.tex        a compilable starting point with %% >>> preamble / snippet markers
  <id>.meta.json  name, category, tags, description, notes, date added

Then: edit the .tex, run  python3 tools/build_site.py --render missing --serve
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys

from _common import ID_RE, TYPE_DIRS, TYPES, lib_root

# Snippets/preambles use a normal article test file (floats, captions and
# numbering all work); the preview is cropped to the ink automatically.
SNIPPET_TEX = r"""\documentclass{article}
\pagestyle{empty}

%% >>> preamble
% packages / settings this snippet needs in YOUR document's preamble
\usepackage{amsmath}
%% <<< preamble

\begin{document}
%% >>> snippet
% the code you paste into the body of your document
Hello, \LaTeX{} library! $E = mc^2$
%% <<< snippet
\end{document}
"""

PREAMBLE_TEX = r"""\documentclass{article}
\pagestyle{empty}

%% >>> preamble
% the reusable setup block — paste between \documentclass and \begin{document}
\usepackage{amsmath}
%% <<< preamble

\begin{document}
%% >>> snippet
% a short demo of what the preamble gives you (used for the preview)
Demo of the setup: $\sum_{i=1}^n i = \frac{n(n+1)}{2}$
%% <<< snippet
\end{document}
"""

TEMPLATE_TEX = r"""\documentclass[11pt, a4paper]{article}

%% >>> preamble
\usepackage[margin=2.5cm]{geometry}
\usepackage{amsmath}
%% <<< preamble

\title{Title}
\author{Author}
\date{\today}

\begin{document}
%% >>> snippet
\maketitle

\section{Introduction}
Start writing here.
%% <<< snippet
\end{document}
"""

ICON_TEX = r"""\documentclass[border=4pt]{standalone}

%% >>> preamble
\usepackage{tikz}
\definecolor{brandcolor}{HTML}{0072B2}
%% <<< preamble

\begin{document}
%% >>> snippet
\begin{tikzpicture}
  \fill[brandcolor, rounded corners=0.45cm] (0,0) rectangle (2.5,2.5);
  \node[white, font=\fontfamily{phv}\fontseries{b}\fontsize{26}{26}\selectfont]
    at (1.25,1.25) {Ab};
\end{tikzpicture}
%% <<< snippet
\end{document}
"""

STARTERS = {"snippet": SNIPPET_TEX, "preamble": PREAMBLE_TEX, "template": TEMPLATE_TEX,
            "icon": ICON_TEX}


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)


def split_list(value: str) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("type", choices=TYPES)
    parser.add_argument("name", help='display name, e.g. "Booktabs table"')
    parser.add_argument("--id", help="kebab-case id (default: derived from the name)")
    parser.add_argument("--category", default="general",
                        help="comma-separated browse categories (e.g. tables,math)")
    parser.add_argument("--tags", default="", help="comma-separated search keywords")
    parser.add_argument("--description", default="", help="one-line description")
    args = parser.parse_args(argv)

    entry_id = args.id or slugify(args.name)
    if not ID_RE.match(entry_id):
        sys.exit(f"error: id {entry_id!r} must be kebab-case (a-z, 0-9, dashes)")

    root = lib_root()
    clash = list((root / "library").glob(f"*/{entry_id}"))
    if clash:
        sys.exit(f"error: an entry with id {entry_id!r} already exists: {clash[0]}")

    folder = root / "library" / TYPE_DIRS[args.type] / entry_id
    folder.mkdir(parents=True)
    (folder / f"{entry_id}.tex").write_text(STARTERS[args.type], encoding="utf-8")
    meta = {
        "id": entry_id,
        "name": args.name,
        "type": args.type,
        "category": split_list(args.category) or ["general"],
        "tags": split_list(args.tags),
        "requires": {"template": ["geometry", "amsmath"], "icon": ["tikz"]}.get(args.type, ["amsmath"]),
        "description": args.description or f"TODO: what does {args.name} do?",
        "notes": ["TODO: gotchas, tips, or where you found this."],
        "added": dt.date.today().isoformat(),
        "featured": False,
        "preview": "preview.svg",
    }
    (folder / f"{entry_id}.meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rel = folder.relative_to(root).as_posix()
    print(f"created {rel}/")
    print(f"  1. edit   {rel}/{entry_id}.tex   (keep the %% >>> / <<< markers)")
    print(f"  2. fill   {rel}/{entry_id}.meta.json  (description, notes, tags, requires)")
    print("  3. build  python3 tools/build_site.py --render missing --serve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
