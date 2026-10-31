#!/usr/bin/env python3
"""Build the static library website from the entries under library/.

  python3 tools/build_site.py                      # build site/ (renders missing previews if TeX is installed)
  python3 tools/build_site.py --render all         # re-render every preview first
  python3 tools/build_site.py --serve              # build, then serve on http://localhost:8000

Output (all links are relative, so it works on GitHub Pages under a sub-path
and when opened straight from disk):

  site/
    index.html              home: hero carousel, how-to, why, CTA
    browse/index.html       searchable/filterable grid of every entry
    item/<id>.html          entry page: preview, copy snippet/preamble, notes
    previews/<id>.svg       rendered preview
    sty/<id>.sty            preamble entries packaged for \\usepackage{<id>}
    assets/style.css, assets/app.js

Stdlib only. Design and front-end adapted from OpenTikZ
(https://github.com/opentikz/opentikz, MIT licence).
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import html
import http.server
import json
import re
import shutil
from pathlib import Path

import build_catalog
import render_preview
from _common import (TYPE_TITLES, TYPES, extract_region, lib_root, load_config,
                     strip_markers, tex_sibling)

CFG: dict = {}
ASSET_V = ""   # content hash appended to CSS/JS URLs so browsers never use a stale copy
TYPE_ORDER = {t: i for i, t in enumerate(TYPES)}


def brand_text() -> str:
    return CFG["brand_prefix"] + CFG["brand_accent"]


def wordmark_html() -> str:
    return (f'{html.escape(CFG["brand_prefix"])}<span class="tik">'
            f'{html.escape(CFG["brand_accent"])}</span><span class="caret">&#9475;</span>')


def repo_tree_url(path: str = "") -> str:
    base = f'{CFG["repo_url"]}/tree/{CFG["repo_branch"]}'
    sub = "/".join(p for p in (CFG.get("repo_subdir", ""), path) if p)
    return f"{base}/{sub}" if sub else base


def repo_blob_url(path: str) -> str:
    sub = "/".join(p for p in (CFG.get("repo_subdir", ""), path) if p)
    return f'{CFG["repo_url"]}/blob/{CFG["repo_branch"]}/{sub}'


def json_for_script(obj) -> str:
    """JSON that is safe inside an inline <script> (no </script> breakout)."""
    return (json.dumps(obj, ensure_ascii=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def inline_md(text: str) -> str:
    """Tiny, safe inline formatter for notes: `code`, **bold**, *italic*, [label](https://url)."""
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![\w*])\*([^*\s][^*]*)\*(?![\w*])", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)\s\"]+)\)",
                 r'<a href="\2" target="_blank" rel="noopener">\1</a>', out)
    return out


# --------------------------------------------------------------------------- #
#  HTML fragments
# --------------------------------------------------------------------------- #
DL_ICON = ('<svg class="dl-ic" width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">'
           '<path d="M8 1.5v8m0 0L4.8 6.3M8 9.5l3.2-3.2M2.5 13.5h11" fill="none" '
           'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
           'stroke-linejoin="round"/></svg>')
COPY_ICON = ('<svg class="dl-ic" width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">'
             '<rect x="5" y="5" width="9" height="9" rx="1.6" fill="none" stroke="currentColor" '
             'stroke-width="1.6"/><path d="M11 5V3.2A1.2 1.2 0 0 0 9.8 2H3.2A1.2 1.2 0 0 0 2 3.2'
             'v6.6A1.2 1.2 0 0 0 3.2 11H5" fill="none" stroke="currentColor" stroke-width="1.6" '
             'stroke-linecap="round" stroke-linejoin="round"/></svg>')

PLACEHOLDER_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180" viewBox="0 0 320 180">
<rect x="1" y="1" width="318" height="178" rx="10" fill="none" stroke="#D6D2C4" stroke-dasharray="6 5"/>
<text x="160" y="96" text-anchor="middle" font-family="monospace" font-size="15" fill="#6F6C61">no preview yet</text>
</svg>
"""


def head(title: str, prefix: str, *, description: str = "", browse_href: str = "") -> str:
    """``prefix`` is the path back to the site root ('' or '../')."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description or CFG['tagline'])}">
<link rel="icon" href="{prefix}favicon.ico" sizes="any">
<link rel="icon" type="image/svg+xml" href="{prefix}favicon.svg">
<link rel="apple-touch-icon" href="{prefix}apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,900&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{prefix}assets/style.css?v={ASSET_V}">
</head>
<body data-browse="{browse_href}">
<div class="grid-bg" aria-hidden="true"></div>
"""


def navbar(surface: str, prefix: str) -> str:
    """Shared sticky header. surface in {home, browse, item}."""
    home = f"{prefix}index.html"
    browse = f"{prefix}browse/index.html"
    sec = "" if surface == "browse" else browse
    browse_active = " active" if surface in ("browse", "item") else ""
    return f"""<header class="navbar">
  <div class="nav-inner">
    <a class="wordmark" href="{home}">{wordmark_html()}</a>
    <input type="checkbox" id="nav-toggle" class="nav-toggle" hidden>
    <label class="nav-burger" for="nav-toggle" aria-label="Toggle navigation menu">
      <span></span><span></span><span></span>
    </label>
    <nav class="nav-links">
      <a class="nav-browse{browse_active}" href="{browse}" data-nav="browse">Browse</a>
      <a href="{sec}#snippets" data-nav="snippets">Snippets</a>
      <a href="{sec}#preambles" data-nav="preambles">Preambles</a>
      <a href="{sec}#templates" data-nav="templates">Templates</a>
      <a href="{sec}#icons" data-nav="icons">Icons</a>
      <a href="{repo_blob_url('README.md')}#adding-an-entry">Add entry</a>
      <a class="nav-gh" href="{repo_tree_url()}" target="_blank" rel="noopener">GitHub <span class="star">★</span></a>
    </nav>
  </div>
</header>
"""


def badge(t: str) -> str:
    return f'<span class="badge badge-{html.escape(t)}">{html.escape(t)}</span>'


def tag_list(tags: list[str]) -> str:
    return "".join(f'<span class="tag">{html.escape(x)}</span>' for x in tags)


def card(item: dict, prefix: str, idx: int) -> str:
    name = html.escape(item["name"])
    cats = item.get("category", [])
    page = {"template": " canvas-page", "icon": " canvas-icon"}.get(item["type"], "")
    return f"""  <a class="card" href="{prefix}item/{html.escape(item['id'])}.html" data-id="{html.escape(item['id'])}" data-type="{html.escape(item['type'])}" data-cats="{html.escape(' '.join(cats))}" style="--i:{idx}">
    <div class="canvas{page}"><img src="{prefix}previews/{html.escape(item['id'])}.svg" alt="{name} preview" loading="lazy"></div>
    <div class="card-meta">
      {badge(item['type'])}
      <h3>{name}</h3>
      <p class="domains">{" · ".join(html.escape(c) for c in cats)}</p>
    </div>
  </a>
"""


def metadata_table(item: dict) -> str:
    def row(k: str, v: str) -> str:
        return f"<tr><th>{html.escape(k)}</th><td>{v}</td></tr>"

    rows = [row("id", f"<code>{html.escape(item['id'])}</code>"),
            row("type", badge(item["type"])),
            row("category", ", ".join(html.escape(c) for c in item.get("category", [])))]
    if item.get("requires"):
        rows.append(row("requires", ", ".join(f"<code>{html.escape(r)}</code>"
                                              for r in item["requires"])))
    if item.get("added"):
        rows.append(row("added", html.escape(item["added"])))
    return '<table class="meta-table">' + "".join(rows) + "</table>"


def code_block(code_id: str, filename: str, hint: str, code: str, *, open_: bool) -> str:
    return f"""
  <details class="code-block"{' open' if open_ else ''}>
    <summary class="code-head">
      <span class="filename">{html.escape(filename)} <span class="code-hint">{html.escape(hint)}</span></span>
      <span class="code-toggle" aria-hidden="true"></span>
    </summary>
    <div class="code-body">
      <button class="copy code-copy" data-target="{code_id}">Copy</button>
      <pre><code id="{code_id}">{html.escape(code)}</code></pre>
    </div>
  </details>"""


def notes_section(item: dict) -> str:
    notes = item.get("notes") or []
    links = item.get("links") or []
    if not notes and not links:
        return ""
    body = ""
    if notes:
        body += "<ul>" + "".join(f"<li>{inline_md(n)}</li>" for n in notes) + "</ul>"
    if links:
        lis = "".join(
            f'<li><a href="{html.escape(l["url"])}" target="_blank" rel="noopener">'
            f'{html.escape(l.get("label") or l["url"])}</a></li>' for l in links)
        body += f"<h3>Sources</h3><ul>{lis}</ul>"
    return f"""
  <section class="skill">
    <div class="skill-head">
      <h2>Notes <span>— what I learned, gotchas &amp; tips</span></h2>
    </div>
    <details class="skill-body" open>
      <summary>My notes on this entry</summary>
      <div class="md">{body}</div>
    </details>
  </section>
"""


USAGE = {
    "snippet": ("Copy the <strong>preamble</strong> lines into your document's preamble "
                "(skip any packages you already load), then paste the <strong>snippet</strong> "
                "where you want it in the body."),
    "preamble": ("Paste the <strong>preamble</strong> block between <code>\\documentclass</code> "
                 "and <code>\\begin{document}</code> — or download it as a <code>.sty</code>, "
                 "drop it next to your <code>main.tex</code> and load it with "
                 "<code>\\usepackage{{{id}}}</code>."),
    "template": ("Download the full <code>.tex</code> (or copy it) and save it as your "
                 "<code>main.tex</code> — it compiles as-is. Then replace the placeholder text."),
    "icon": ("Copy the <strong>preamble</strong> lines (TikZ + the brand colour) into your preamble "
             "and paste the <strong>snippet</strong> where you want the icon. Resize it with "
             "<code>\\begin{tikzpicture}[scale=0.5]</code> or wrap it in "
             "<code>\\resizebox{1cm}{!}{...}</code>. Or just grab the SVG/PNG for slides and CVs."),
}

TRADEMARK_NOTE = ('<p class="license-note">The TikZ <strong>code</strong> is free to reuse; the '
                  '<strong>brand</strong> it represents is a trademark of its owner. Use it to '
                  'identify the tool (e.g. on a CV or skills slide), not to imply endorsement.</p>')


def sty_text(item: dict, preamble: str) -> str:
    body = re.sub(r"\\usepackage(?=\s*[\[{])", r"\\RequirePackage", preamble)
    return (f"% {item['id']}.sty — generated from the {brand_text()} entry \"{item['name']}\"\n"
            "\\NeedsTeXFormat{LaTeX2e}\n"
            f"\\ProvidesPackage{{{item['id']}}}\n\n{body}\n\\endinput\n")


def item_page(item: dict, source: str, tex_name: str) -> str:
    prefix = "../"
    name = html.escape(item["name"])
    desc = item.get("description", "")
    preview = f"../previews/{item['id']}.svg"
    snippet = extract_region(source, "snippet")
    preamble = extract_region(source, "preamble")
    full = strip_markers(source)
    is_template = item["type"] == "template"

    buttons = []
    if is_template:
        buttons.append(f'<button class="dl-btn dl-primary dl-copy" data-target="full">{COPY_ICON}Copy full .tex</button>')
    elif snippet:
        buttons.append(f'<button class="dl-btn dl-primary dl-copy" data-target="snip">{COPY_ICON}Copy snippet</button>')
    if preamble and not is_template:
        buttons.append(f'<button class="dl-btn dl-copy" data-target="pre">{COPY_ICON}Copy preamble</button>')
    buttons.append(f'<button class="dl-btn" data-tex="full" data-name="{html.escape(tex_name)}">{DL_ICON}.tex</button>')
    if item["type"] == "preamble" and preamble:
        buttons.append(f'<a class="dl-btn" href="../sty/{item["id"]}.sty" download>{DL_ICON}.sty</a>')
    buttons.append(f'<a class="dl-btn" href="{preview}" download="{item["id"]}.svg">{DL_ICON}SVG</a>')
    buttons.append(f'<button class="dl-btn" data-png="{preview}" data-name="{item["id"]}.png">{DL_ICON}PNG</button>')

    blocks = ""
    if is_template:
        blocks += code_block("full", tex_name, "— the whole document", full, open_=True)
    else:
        if preamble:
            blocks += code_block("pre", "preamble", "— before \\begin{document}", preamble, open_=True)
        if snippet:
            blocks += code_block("snip", "snippet", "— in the document body", snippet, open_=True)
        blocks += code_block("full", tex_name, "— complete, compilable test file", full, open_=False)

    usage = USAGE[item["type"]].replace("{{{id}}}", "{" + html.escape(item["id"]) + "}")
    return (
        head(f"{item['name']} — {brand_text()}", prefix, description=desc,
             browse_href="../browse/index.html")
        + navbar("item", prefix)
        + f"""<main class="item">
  <a class="back" href="../browse/index.html">← browse the library</a>
  <div class="item-top">
    <div class="item-canvas{' canvas-page' if is_template else ''}{' canvas-icon' if item['type'] == 'icon' else ''}"><img src="{preview}" alt="{name} preview"></div>
    <div class="item-head">
      {badge(item['type'])}
      <h1>{name}</h1>
      <p class="lede">{inline_md(desc)}</p>
      {metadata_table(item)}
      <p class="tags">{tag_list(item.get('tags', []))}</p>
      <div class="downloads">
        {chr(10).join('        ' + b for b in buttons).strip()}
      </div>
    </div>
  </div>
{blocks}
{notes_section(item)}
  <section class="usage">
    <h2>Use it</h2>
    <p>{usage}</p>
    {TRADEMARK_NOTE if "brands" in item.get("category", []) else ""}
    <p class="license-note">Source: <a href="{repo_tree_url(item['path'])}" target="_blank" rel="noopener"><code>{html.escape(item['path'])}/</code></a></p>
  </section>
</main>
"""
        + footer(prefix)
        + f'<script src="../assets/app.js?v={ASSET_V}"></script>\n</body>\n</html>\n'
    )


def footer(prefix: str) -> str:
    return f"""<footer class="site-footer">
  <div>
    <span class="fw">{html.escape(brand_text())}</span> — {html.escape(CFG['tagline'])}
  </div>
  <div class="licenses">
    Design adapted from <a href="https://opentikz.org" target="_blank" rel="noopener">OpenTikZ</a> (<code>MIT</code>)
  </div>
</footer>
"""


HOWTO = [
    {"tab_label": "Grab a snippet",
     "caption": "Need that table layout again? Search, copy, paste.",
     "steps": [
         {"code": "/ · booktabs", "text": "Press / and search by name, tag or category."},
         {"code": "Copy preamble · Copy snippet",
          "text": "Packages go in your preamble, the snippet goes in the body."},
         {"code": "pdflatex main.tex", "text": "Compile. Every entry is tested to build."}]},
    {"tab_label": "Start a document",
     "caption": "Start every new document from your own tested setup.",
     "steps": [
         {"code": "Templates", "text": "Pick a template: article, report, slides…"},
         {"code": ".tex · Copy full .tex", "text": "Save it as your main.tex. It compiles as-is."},
         {"code": "\\usepackage{my-macros}",
          "text": "Pull in your own preambles as .sty packages."}]},
    {"tab_label": "Log something new",
     "caption": "Figured something out? Log it once and you'll never Google it again.",
     "steps": [
         {"code": 'new_entry.py snippet "Name"', "text": "Scaffold an entry: a .tex plus its metadata."},
         {"code": "%% >>> snippet · %% <<< snippet",
          "text": "Paste your working code between the markers and jot down notes."},
         {"code": "build_site.py --render missing",
          "text": "Render the preview and rebuild, or just push and let GitHub do it."}]},
]


def howto_carousel() -> str:
    slides, dots = "", ""
    for i, s in enumerate(HOWTO):
        label = html.escape(s["tab_label"])
        active = " active" if i == 0 else ""
        cells = ""
        for n, st in enumerate(s["steps"], start=1):
            chips = "".join(f"<code>{html.escape(p.strip())}</code>" for p in st["code"].split(" · "))
            cells += (f'<div class="howto-step"><span class="howto-step-n">{n}</span>'
                      f'<div class="howto-step-vis"><div class="howto-codes">{chips}</div></div>'
                      f'<p class="howto-step-cap">{html.escape(st["text"])}</p></div>')
        slides += f"""      <div class="demo-slide{active}" data-slide="{i}">
        <p class="howto-cap">{html.escape(s["caption"])}</p>
        <div class="howto-steps">{cells}</div>
      </div>
"""
        dots += (f'<button class="demo-dot{active}" data-dot="{i}" aria-label="{label}">'
                 f"<span>{label}</span></button>")
    return f"""
  <section class="howto">
    <h2>3 ways to use the library</h2>
    <div class="car-dots howto-tabs">{dots}</div>
    <div class="carousel howto-carousel" id="howto-carousel" tabindex="0" data-autoplay data-interval="6000" aria-roledescription="carousel" aria-label="How to use the library">
      <div class="car-track">
{slides}      </div>
    </div>
  </section>
"""


def hero_carousel(items: list[dict]) -> str:
    slides, dots = "", ""
    for i, it in enumerate(items):
        name = html.escape(it["name"])
        active = " active" if i == 0 else ""
        page = " hero-page" if it["type"] == "template" else ""
        slides += f"""        <div class="hero-slide{active}" data-slide="{i}">
          <figure class="hero-fig{page}">
            <img src="previews/{html.escape(it['id'])}.svg" alt="{name}" loading="lazy">
            <figcaption class="hero-cap">{badge(it['type'])}<a href="item/{html.escape(it['id'])}.html">{name}</a></figcaption>
          </figure>
        </div>
"""
        dots += f'<button class="hero-dot{active}" data-dot="{i}" aria-label="Show {name}"></button>'
    return f"""    <div class="carousel hero-carousel" id="hero-carousel" tabindex="0" data-autoplay data-interval="5000" aria-roledescription="carousel" aria-label="Featured entries">
      <button class="car-nav car-prev" aria-label="Previous">&lsaquo;</button>
      <div class="car-track">
{slides}      </div>
      <button class="car-nav car-next" aria-label="Next">&rsaquo;</button>
    </div>
    <div class="car-dots">{dots}</div>
"""


def why_band() -> str:
    return r"""
  <section class="why-tikz-slim">
    <h2>Why keep your own library</h2>
    <div class="wts-strip">
      <div class="wts-item"><span class="wts-num">01</span><b>Never re-Google it</b><span class="wts-desc">Solve a layout once, log it, and it's one search away next time.</span></div>
      <div class="wts-item"><span class="wts-num">02</span><b>Known to compile</b><span class="wts-desc">Every entry is a complete test file with a rendered preview, so you know it works.</span></div>
      <div class="wts-item"><span class="wts-num">03</span><b>Paste-ready</b><span class="wts-desc">Preamble and body are split, packages are listed, and preambles ship as <code>.sty</code>.</span></div>
    </div>
  </section>
"""


def compare_band() -> str:
    return """
  <section class="why-ot">
    <h2>Why not just search StackExchange again?</h2>
    <div class="cmp-rows">
      <div class="cmp-row cmp-head"><span class="cmp-h-x">Searching from scratch</span><span class="cmp-h-v">Your own library</span></div>
      <div class="cmp-row"><span class="cmp-x">Dig through threads and old projects</span><span class="cmp-v">Your tested version, one search away</span></div>
      <div class="cmp-row"><span class="cmp-x">Copied code misses a package</span><span class="cmp-v">Preamble split out, <code>requires</code> listed</span></div>
      <div class="cmp-row"><span class="cmp-x">Hit the same gotcha twice</span><span class="cmp-v">Your notes saved next to the code</span></div>
      <div class="cmp-row"><span class="cmp-x">Every document set up differently</span><span class="cmp-v">Same setup every time via your own <code>.sty</code></span></div>
    </div>
  </section>
"""


def getstarted_band() -> str:
    sub = CFG.get("repo_subdir", "")
    where = f"Run from the <code>{html.escape(sub)}/</code> folder. " if sub else "Run from the repo root. "
    return f"""
  <section class="getstarted" id="get-started">
    <h2>Log a new entry in two lines</h2>
    <p class="gs-lede">Scaffold it, paste your code between the markers, rebuild.</p>
    <div class="gs-cmds">
      <pre><code>python3 tools/new_entry.py snippet "Booktabs table" --category tables</code></pre>
      <pre><code>python3 tools/build_site.py --serve</code></pre>
    </div>
    <p class="gs-note">{where}Or just commit the <code>.tex</code> and
      <code>.meta.json</code>, and GitHub renders the previews and redeploys.
      <a href="{repo_blob_url('README.md')}#adding-an-entry">Full guide &rarr;</a></p>
  </section>
"""


def skills_band(icons: list[dict]) -> str:
    """Home-page strip of every icon, so skills are visible without going to Browse."""
    if not icons:
        return ""
    tiles = "".join(
        f'<a class="skill-tile" href="item/{html.escape(it["id"])}.html">'
        f'<img src="previews/{html.escape(it["id"])}.svg" alt="" loading="lazy">'
        f'<span>{html.escape(it["name"])}</span></a>'
        for it in icons)
    return f"""
  <section class="skills-band" id="skills">
    <h2>Skills &amp; tools</h2>
    <p class="gs-lede">Icons I can drop into any document, CV or slide, as TikZ, SVG or PNG.</p>
    <div class="skill-grid">{tiles}</div>
    <a class="btn btn-ghost" href="browse/index.html#icons">All icons &rarr;</a>
  </section>
"""


def home_page(showcase: list[dict], counts: dict, icons: list[dict] | None = None) -> str:
    stats = " · ".join(f"{counts[t]} {TYPE_TITLES[t].lower()}" for t in TYPES if counts.get(t))
    return (
        head(f"{brand_text()} — {CFG['tagline']}", "", browse_href="browse/index.html")
        + navbar("home", "")
        + f"""<main class="home">
  <section class="showcase">
    <a class="hero-logo" href="index.html" aria-label="{html.escape(brand_text())} home">{wordmark_html()}</a>
    <h1>{html.escape(CFG['headline'])}</h1>
    <p class="show-lede">{html.escape(CFG['tagline'])}</p>
{hero_carousel(showcase) if showcase else ''}    <div class="cta-row">
      <a class="btn btn-primary" href="browse/index.html">Browse the library &rarr;</a>
    </div>
    <p class="cta-sub">{html.escape(stats)}</p>
  </section>
{skills_band(icons or [])}
{getstarted_band()}
{howto_carousel()}
{why_band()}
{compare_band()}
  <section class="cta-band">
    <h2>Start your next document faster.</h2>
    <a class="btn btn-primary" href="browse/index.html">Browse the library →</a>
  </section>
</main>
"""
        + footer("")
        + f'<script src="assets/app.js?v={ASSET_V}"></script>\n</body>\n</html>\n'
    )


def browse_page(items: list[dict]) -> str:
    prefix = "../"
    counts = {t: sum(1 for it in items if it["type"] == t) for t in TYPES}
    groups_html, idx = "", 0
    for t in TYPES:
        members = [it for it in items if it["type"] == t]
        if not members:
            continue
        cards = ""
        for it in members:
            cards += card(it, prefix, idx)
            idx += 1
        groups_html += f"""  <section class="group" id="{t}s" data-group="{t}">
    <div class="group-head">
      <h2>{TYPE_TITLES[t]}</h2>
      <span class="group-count" data-count>{len(members)}</span>
    </div>
    <div class="grid">
{cards}    </div>
  </section>
"""

    chips = ['<button class="chip active" data-type="all">all</button>']
    chips += [f'<button class="chip" data-type="{t}">{TYPE_TITLES[t].lower()} · {counts[t]}</button>'
              for t in TYPES if counts[t]]
    cats: dict[str, int] = {}
    for it in items:
        for c in it.get("category", []):
            cats[c] = cats.get(c, 0) + 1
    cat_chips = ['<button class="chip chip-cat active" data-cat="all">any category</button>']
    cat_chips += [f'<button class="chip chip-cat" data-cat="{html.escape(c)}">{html.escape(c)}</button>'
                  for c in sorted(cats)]

    search_index = json_for_script([
        {"id": it["id"], "name": it["name"], "type": it["type"],
         "category": it.get("category", []), "tags": it.get("tags", []),
         "requires": it.get("requires", []), "description": it.get("description", "")}
        for it in items])

    return (
        head(f"Browse — {brand_text()}", prefix)
        + navbar("browse", prefix)
        + f"""<section class="hero hero-browse">
  <h1 class="browse-title">Browse the library</h1>
  <div class="hero-search">
    <input id="search" type="search" placeholder="Search snippets, icons, packages, tags…    ( / )" autocomplete="off" aria-label="Search the library">
  </div>
  <div class="chips" id="chips">
      {chr(10).join('      ' + c for c in chips).strip()}
  </div>
  <div class="chips chips-cat" id="cat-chips">
      {chr(10).join('      ' + c for c in cat_chips).strip()}
  </div>
  <p class="result-count" id="count"></p>
</section>

<main id="gallery">
{groups_html}</main>
<p class="empty" id="empty" hidden>Nothing matches — try a different term, or log it as a new entry.</p>
"""
        + footer(prefix)
        + f'<script id="catalog" type="application/json">{search_index}</script>\n'
        + ('<script src="https://cdn.jsdelivr.net/npm/fuse.js@7.0.0/dist/fuse.min.js" '
           'integrity="sha384-PCSoOZTpbkikBEtd/+uV3WNdc676i9KUf01KOA8CnJotvlx8rRrETbDuwdjqTYvt" '
           'crossorigin="anonymous" referrerpolicy="no-referrer"></script>\n')
        + f'<script src="../assets/app.js?v={ASSET_V}"></script>\n'
        + "</body>\n</html>\n"
    )


def build(root: Path, render: str) -> int:
    global CFG, ASSET_V
    CFG = load_config(root)
    ASSET_V = hashlib.sha1((STYLE_CSS + APP_JS).encode()).hexdigest()[:10]

    if render != "none":
        if render_preview.have_toolchain():
            pairs = render_preview.entry_targets(root)
            if render == "missing":
                pairs = [p for p in pairs if not p[1].exists()]
            if pairs:
                print(f"rendering {len(pairs)} preview(s)")
                render_preview.render_many(pairs, root)
        else:
            print("note: latexmk/pdftocairo not found — skipping preview rendering")

    catalog = build_catalog.write(root)
    catalog = [it for it in catalog if it.get("type") in TYPES]
    catalog.sort(key=lambda it: (TYPE_ORDER[it["type"]], it["name"].lower()))

    site = root / "site"
    if site.exists():
        shutil.rmtree(site)
    for d in ("item", "browse", "previews", "assets", "sty"):
        (site / d).mkdir(parents=True)
    (site / "assets" / "style.css").write_text(STYLE_CSS, encoding="utf-8")
    (site / "assets" / "app.js").write_text(APP_JS, encoding="utf-8")
    (site / ".nojekyll").write_text("", encoding="utf-8")
    if CFG.get("cname"):
        (site / "CNAME").write_text(CFG["cname"] + "\n", encoding="utf-8")
    for fav in ("favicon.ico", "favicon.svg", "apple-touch-icon.png"):
        src = root / "assets" / fav
        if src.exists():
            shutil.copyfile(src, site / fav)

    n_prev = 0
    for it in catalog:
        item_dir = root / it["path"]
        svg = item_dir / it.get("preview", "preview.svg")
        if svg.exists():
            shutil.copyfile(svg, site / "previews" / f"{it['id']}.svg")
            n_prev += 1
        else:
            (site / "previews" / f"{it['id']}.svg").write_text(PLACEHOLDER_SVG, encoding="utf-8")
        tex = tex_sibling(item_dir / f"{it['id']}.meta.json")
        source = tex.read_text(encoding="utf-8") if tex.exists() else "% (source not found)\n"
        if it["type"] == "preamble":
            pre = extract_region(source, "preamble")
            if pre:
                (site / "sty" / f"{it['id']}.sty").write_text(sty_text(it, pre), encoding="utf-8")
        (site / "item" / f"{it['id']}.html").write_text(
            item_page(it, source, tex.name), encoding="utf-8")

    (site / "browse" / "index.html").write_text(browse_page(catalog), encoding="utf-8")

    counts = {t: sum(1 for it in catalog if it["type"] == t) for t in TYPES}
    showcase = [it for it in catalog if it.get("featured")] or catalog[:8]
    icons = [it for it in catalog if it["type"] == "icon"]
    (site / "index.html").write_text(home_page(showcase, counts, icons), encoding="utf-8")

    if CFG.get("site_url"):
        base = CFG["site_url"].rstrip("/")
        urls = [f"{base}/", f"{base}/browse/"] + [f"{base}/item/{it['id']}.html" for it in catalog]
        body = "\n".join(f"  <url><loc>{u}</loc></url>" for u in urls)
        (site / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{body}\n</urlset>\n", encoding="utf-8")

    missing = len(catalog) - n_prev
    print(f"built site/ — {len(catalog)} entries, {n_prev} previews"
          + (f" ({missing} without a preview yet)" if missing else "")
          + f", featured={len(showcase)}")
    return 0


def serve(site: Path, port: int) -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"serving on http://localhost:{port}  (Ctrl+C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--render", choices=("none", "missing", "all"), default="missing",
                        help="render previews before building (default: missing)")
    parser.add_argument("--serve", action="store_true", help="serve site/ after building")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    root = lib_root()
    rc = build(root, args.render)
    if rc == 0 and args.serve:
        serve(root / "site", args.port)
    return rc


# --------------------------------------------------------------------------- #
#  Assets (kept here so the script is the single source of truth)
#  Stylesheet + script adapted from OpenTikZ (MIT).
# --------------------------------------------------------------------------- #
STYLE_CSS = r""":root{
  --paper:#FBFAF6; --ink:#1B1A16; --muted:#6F6C61; --line:#E6E3D8; --line-strong:#D6D2C4;
  --otblue:#0072B2; --otorange:#E69F00; --otteal:#009E73; --otpurple:#A85C86; --otgray:#5A5A5A;
  --grid:rgba(0,114,178,.05);
  --shadow:0 1px 0 var(--line-strong), 0 18px 40px -28px rgba(27,26,22,.45);
  --maxw:1180px; --gutter:28px;   /* single source of truth for the layout container */
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:"IBM Plex Sans",system-ui,sans-serif; font-size:16px; line-height:1.6;
  -webkit-font-smoothing:antialiased; position:relative; min-height:100vh;
}
/* TikZ-style coordinate grid background */
.grid-bg{
  position:fixed; inset:0; z-index:-1; pointer-events:none;
  background-image:
    linear-gradient(var(--grid) 1px,transparent 1px),
    linear-gradient(90deg,var(--grid) 1px,transparent 1px);
  background-size:26px 26px;
  mask-image:radial-gradient(ellipse 120% 90% at 50% 0,#000 40%,transparent 100%);
}
a{color:inherit}
code{font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:.86em;
  background:#F1EFE6; padding:.08em .35em; border-radius:3px; border:1px solid var(--line)}

/* ---------- sticky nav bar ---------- */
.navbar{position:sticky; top:0; z-index:50; background:rgba(251,250,246,.86);
  backdrop-filter:blur(8px); border-bottom:1px solid var(--line)}
.nav-inner{max-width:var(--maxw); margin:0 auto; padding:11px var(--gutter);
  display:flex; align-items:center; gap:16px; flex-wrap:wrap}
.wordmark{display:inline-block; text-decoration:none; font-family:"Fraunces",serif;
  font-weight:900; font-size:26px; letter-spacing:-.02em; line-height:1}
.wordmark .tik{color:var(--otblue)}
.wordmark .caret{color:var(--otorange); animation:blink 1.2s steps(1) infinite; margin-left:.04em}
@keyframes blink{50%{opacity:0}}
.nav-links{display:flex; align-items:center; gap:4px; margin-left:auto; flex-wrap:wrap}
.nav-links a{font-family:"IBM Plex Sans",sans-serif; font-size:.92rem; color:var(--muted);
  text-decoration:none; padding:7px 11px; border-radius:7px; white-space:nowrap;
  transition:color .15s, background .15s}
.nav-links a:hover{color:var(--ink); background:#F1EFE6}
.nav-links a.active{color:var(--otblue)}
.nav-gh{color:var(--ink); font-weight:500}
.nav-gh .star{color:var(--otorange)}
/* hamburger toggle — hidden on desktop, shown at the mobile breakpoint */
.nav-toggle{display:none}
.nav-burger{display:none; width:42px; height:38px; flex:none; cursor:pointer; padding:0;
  border:1px solid var(--line); border-radius:9px; background:transparent;
  align-items:center; justify-content:center; flex-direction:column; gap:4px}
.nav-burger span{display:block; width:18px; height:2px; border-radius:2px; background:var(--ink);
  transition:transform .2s ease, opacity .2s ease}

/* ---------- hero (elevated, centred search) ---------- */
.hero{max-width:760px; margin:0 auto; padding:54px 28px 12px; text-align:center}
.hero .eyebrow{margin:0 0 .4em; font-family:"IBM Plex Mono",monospace; font-size:.8rem;
  letter-spacing:.03em; color:var(--muted)}
.hero .lede{font-size:clamp(1.15rem,2.6vw,1.6rem); margin:0 auto .95em; max-width:30ch;
  font-family:"Fraunces",serif; font-weight:400; color:#34322b}
.hero-search{position:relative; max-width:640px; margin:0 auto}
#search{width:100%; padding:16px 18px 16px 48px; font:inherit; font-size:1.05rem; color:var(--ink);
  background:#fff; border:1.5px solid var(--line-strong); border-radius:13px; box-shadow:var(--shadow);
  transition:border-color .15s, box-shadow .15s}
#search::placeholder{color:#A6A294}
#search:focus{outline:none; border-color:var(--otblue); box-shadow:0 0 0 4px rgba(0,114,178,.14)}
.hero-search::before{content:"\2315"; position:absolute; left:17px; top:50%;
  transform:translateY(-50%) rotate(-12deg); color:#A6A294; font-size:1.3rem; pointer-events:none}
.chips{display:flex; flex-wrap:wrap; gap:8px; margin:14px 0 0; justify-content:center}
.chip{font:500 .85rem/1 "IBM Plex Mono",monospace; padding:7px 13px; cursor:pointer;
  background:#fff; color:var(--muted); border:1.5px solid var(--line-strong);
  border-radius:999px; transition:.15s}
.chip:hover{border-color:var(--otblue); color:var(--ink)}
.chip.active{background:var(--ink); color:var(--paper); border-color:var(--ink)}
.result-count{color:var(--muted); font-size:.82rem; margin:12px 0 0; text-align:center;
  font-family:"IBM Plex Mono",monospace}

/* ---------- gallery ---------- */
.grid{
  max-width:var(--maxw); margin:6px auto 0; padding:14px var(--gutter) 60px;
  display:grid; grid-template-columns:repeat(auto-fill,minmax(232px,1fr)); gap:20px;
}
.card{
  display:flex; flex-direction:column; text-decoration:none; background:#fff;
  border:1px solid var(--line); border-radius:12px; overflow:hidden;
  box-shadow:var(--shadow); transition:transform .18s cubic-bezier(.2,.7,.2,1), box-shadow .18s, border-color .18s;
  animation:rise .5s both; animation-delay:calc(var(--i,0) * 32ms);
}
@keyframes rise{from{opacity:0; transform:translateY(12px)}to{opacity:1; transform:none}}
.card:hover{transform:translateY(-4px); border-color:var(--line-strong);
  box-shadow:0 1px 0 var(--line-strong),0 26px 50px -26px rgba(27,26,22,.55)}
.canvas{
  aspect-ratio:4/3; display:grid; place-items:center; place-content:center; padding:20px;
  background:
    linear-gradient(rgba(0,0,0,.028) 1px,transparent 1px),
    linear-gradient(90deg,rgba(0,0,0,.028) 1px,transparent 1px) #fcfcfa;
  background-size:18px 18px; border-bottom:1px solid var(--line);
}
.canvas img{max-width:100%; max-height:150px; width:auto; height:auto; display:block}
.card-meta{padding:13px 15px 16px}
.card-meta h3{margin:.35em 0 .15em; font-family:"Fraunces",serif; font-weight:600;
  font-size:1.12rem; letter-spacing:-.01em}
.domains{margin:0; color:var(--muted); font-size:.8rem;
  font-family:"IBM Plex Mono",monospace}
.empty{max-width:1180px; margin:0 auto; padding:0 28px 80px; color:var(--muted)}

/* ---------- badges ---------- */
.badge{display:inline-block; font:500 .68rem/1 "IBM Plex Mono",monospace;
  text-transform:uppercase; letter-spacing:.06em; padding:5px 8px; border-radius:5px;
  border:1px solid currentColor}
.badge-icon{color:var(--otteal)}
.badge-template{color:var(--otblue)}
.badge-example{color:var(--otpurple)}
.badge-skill{color:var(--otorange)}
.badge-snippet{color:var(--otpurple)}
.badge-icon{color:var(--otteal)}
.badge-preamble{color:var(--otorange)}

/* ---------- item page ---------- */
.item{max-width:var(--maxw); margin:0 auto; padding:8px var(--gutter) 70px}
.back{display:inline-block; margin:6px 0 22px; color:var(--muted);
  font-family:"IBM Plex Mono",monospace; font-size:.85rem; text-decoration:none}
.back:hover{color:var(--otblue)}
.item-top{display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.1fr); gap:34px; align-items:start}
.item-canvas{
  background:
    linear-gradient(rgba(0,0,0,.03) 1px,transparent 1px),
    linear-gradient(90deg,rgba(0,0,0,.03) 1px,transparent 1px) #fff;
  background-size:22px 22px; border:1px solid var(--line); border-radius:12px;
  padding:30px; display:grid; place-items:center; place-content:center; box-shadow:var(--shadow); min-height:240px;
}
.item-canvas img{max-width:100%; max-height:360px; display:block}
.item-head h1{font-family:"Fraunces",serif; font-weight:900; letter-spacing:-.02em;
  font-size:clamp(1.8rem,4vw,2.6rem); margin:.3em 0 .15em; line-height:1.05}
.item-head .lede{font-family:"Fraunces",serif; color:#34322b; margin:.2em 0 1em}
.skill-note{background:#FFF8EC; border:1px solid #F0DDB6; border-left:3px solid var(--otorange);
  padding:11px 14px; border-radius:7px; font-size:.9rem; color:#5b5341}
.meta-table{width:100%; border-collapse:collapse; margin:14px 0 4px; font-size:.9rem}
.meta-table th{text-align:left; width:96px; padding:7px 10px 7px 0; color:var(--muted);
  font-weight:500; vertical-align:top; font-family:"IBM Plex Mono",monospace; font-size:.82rem}
.meta-table td{padding:7px 0; border-bottom:1px solid var(--line)}
.tags{display:flex; flex-wrap:wrap; gap:6px; margin:14px 0 0}
.tag{font:.74rem/1 "IBM Plex Mono",monospace; color:var(--muted);
  background:#F1EFE6; border:1px solid var(--line); border-radius:999px; padding:5px 9px}

/* ---------- downloads (bold action bar) ---------- */
.downloads{display:flex; flex-wrap:wrap; align-items:center; gap:10px; margin:22px 0 0}
.dl-btn{display:inline-flex; align-items:center; gap:7px; cursor:pointer; text-decoration:none;
  font:600 .9rem "IBM Plex Sans",sans-serif; color:var(--ink); background:#fff;
  border:1.5px solid var(--line-strong); border-radius:10px; padding:10px 16px;
  transition:transform .15s, box-shadow .15s, border-color .15s, color .15s}
.dl-btn .dl-ic{flex:none}
.dl-btn:hover{border-color:var(--otblue); color:var(--otblue); transform:translateY(-1px);
  box-shadow:0 8px 18px -12px rgba(0,114,178,.6)}
.dl-primary{background:var(--otblue); color:#fff; border-color:var(--otblue);
  box-shadow:0 10px 24px -12px rgba(0,114,178,.7)}
.dl-primary:hover{background:var(--otblue); color:#fff; filter:brightness(1.07)}
.dl-primary.done{background:var(--otteal); border-color:var(--otteal); color:#fff; filter:none}

/* ---------- code block (collapsed by default) ---------- */
.code-block{margin:34px 0 0; border:1px solid var(--line-strong); border-radius:12px;
  overflow:hidden; box-shadow:var(--shadow); background:#1c1b1f}
.code-head{display:flex; align-items:center; justify-content:space-between; cursor:pointer;
  padding:12px 16px; background:#26242b; list-style:none; user-select:none}
.code-head::-webkit-details-marker{display:none}
.code-block[open] .code-head{border-bottom:1px solid #34313b}
.filename{font-family:"IBM Plex Mono",monospace; font-size:.82rem; color:#cfc9d6}
.code-toggle{display:inline-flex; align-items:center; font:500 .8rem "IBM Plex Mono",monospace;
  color:var(--otorange)}
.code-toggle::before{content:"\25B8"; margin-right:7px}
.code-toggle::after{content:"View source"}
.code-block[open] .code-toggle{color:#cfc9d6}
.code-block[open] .code-toggle::before{content:"\25BE"}
.code-block[open] .code-toggle::after{content:"Hide source"}
.code-body{position:relative}
.code-copy{position:absolute; top:12px; right:14px; z-index:2}
.copy{font:500 .8rem "IBM Plex Mono",monospace; cursor:pointer; color:#1c1b1f;
  background:var(--otorange); border:none; padding:7px 13px; border-radius:6px; transition:.15s}
.copy:hover{filter:brightness(1.08)}
.copy.done{background:var(--otteal); color:#fff}
.code-block pre{margin:0; padding:18px 16px; overflow:auto; max-height:560px}
.code-block code{background:none; border:none; padding:0; color:#e9e6f0;
  font-family:"IBM Plex Mono",monospace; font-size:.82rem; line-height:1.65; white-space:pre}
.usage{margin:34px 0 0; max-width:70ch}
.usage h2{font-family:"Fraunces",serif; font-weight:600; font-size:1.4rem; margin:0 0 .4em}
.license-note{color:var(--muted); font-size:.92rem}

/* ---------- footer ---------- */
.site-footer{max-width:1180px; margin:40px auto 0; padding:24px 28px 50px;
  border-top:1px solid var(--line); display:flex; flex-wrap:wrap; gap:14px;
  justify-content:space-between; color:var(--muted); font-size:.86rem}
.site-footer .fw{font-family:"Fraunces",serif; font-weight:600; color:var(--ink)}

/* ---------- homepage sections (Icons / Templates / Examples) ---------- */
.group{max-width:var(--maxw); margin:10px auto 0; padding:0 var(--gutter); scroll-margin-top:74px}
.group[hidden]{display:none}
.group-head{display:flex; align-items:baseline; gap:12px; padding:20px 0 10px;
  border-bottom:1px solid var(--line-strong)}
.group-head h2{margin:0; font-family:"Fraunces",serif; font-weight:600;
  font-size:1.55rem; letter-spacing:-.01em}
.group-count{font-family:"IBM Plex Mono",monospace; font-size:.82rem; color:var(--muted);
  background:#F1EFE6; border:1px solid var(--line); border-radius:999px; padding:3px 9px}
.group .grid{max-width:none; margin:0; padding:18px 0 6px}

/* ---------- edit contract (template pages) ---------- */
.skill{margin:36px 0 0}
.skill-head{display:flex; align-items:center; justify-content:space-between; gap:14px; margin-bottom:12px}
.skill-head h2{margin:0; font-family:"Fraunces",serif; font-weight:600; font-size:1.4rem}
.skill-head h2 span{font-family:"IBM Plex Sans",sans-serif; font-weight:400;
  font-size:.82rem; color:var(--muted)}
.skill-link-inline{font:500 .82rem "IBM Plex Mono",monospace; color:var(--otblue);
  text-decoration:none; white-space:nowrap}
.skill-link-inline:hover{text-decoration:underline}
.contract-params{width:100%; border-collapse:collapse; margin:.4em 0 .2em; font-size:.9rem}
.contract-params td{padding:6px 10px 6px 0; border-bottom:1px solid var(--line); vertical-align:top}
.contract-params td:first-child{width:34%; white-space:nowrap}
.param-def{color:var(--muted); font-size:.86em}
.skill-body{background:#fff; border:1px solid var(--line-strong); border-radius:12px;
  box-shadow:var(--shadow)}
.skill-body>summary{cursor:pointer; padding:14px 16px; list-style:none;
  font-family:"IBM Plex Mono",monospace; font-size:.86rem; color:var(--otblue)}
.skill-body>summary::-webkit-details-marker{display:none}
.skill-body>summary::before{content:"▸ "; color:var(--otorange)}
.skill-body[open]>summary{border-bottom:1px solid var(--line)}
.skill-body[open]>summary::before{content:"▾ "}
.md{padding:8px 22px 22px; max-width:74ch}
.md h2,.md h3,.md h4{font-family:"Fraunces",serif; font-weight:600; letter-spacing:-.01em;
  margin:1.1em 0 .35em}
.md h2{font-size:1.25rem} .md h3{font-size:1.08rem} .md h4{font-size:.98rem}
.md p{margin:.5em 0}
.md ul,.md ol{padding-left:1.3em; margin:.5em 0}
.md li{margin:.2em 0}
.md a{color:var(--otblue)}
.md blockquote{border-left:3px solid var(--otorange); background:#FFF8EC;
  margin:.8em 0; padding:9px 13px; border-radius:6px; color:#5b5341; font-size:.92rem}
.md pre.md-code{background:#1c1b1f; border-radius:8px; padding:13px 14px; overflow:auto; margin:.7em 0}
.md pre.md-code code{background:none; border:none; padding:0; color:#e9e6f0;
  font-family:"IBM Plex Mono",monospace; font-size:.8rem; line-height:1.6; white-space:pre}

/* ---------- Home / marketing surface ---------- */
.home{max-width:var(--maxw); margin:0 auto; padding:0 var(--gutter)}

/* figure-led, centred hero — the figure is the largest element */
.showcase{max-width:880px; margin:0 auto; padding:50px 0 42px; text-align:center}
/* large brand lockup, centred above the headline (mirrors the navbar wordmark) */
.hero-logo{display:inline-block; text-decoration:none; font-family:"Fraunces",serif;
  font-weight:900; letter-spacing:-.025em; line-height:1; margin:0 0 .5em;
  font-size:clamp(2.6rem,7vw,4.6rem)}
.hero-logo .tik{color:var(--otblue)}
.hero-logo .caret{color:var(--otorange); animation:blink 1.2s steps(1) infinite; margin-left:.03em}
.showcase h1{font-family:"Fraunces",serif; font-weight:900; letter-spacing:-.025em;
  font-size:clamp(1.55rem,3.6vw,2.3rem); line-height:1.08; margin:0 0 .25em; color:#34322b}
.show-lede{font-family:"Fraunces",serif; font-weight:400; color:#34322b;
  font-size:clamp(1.05rem,2vw,1.3rem); max-width:48ch; margin:0 auto 1.5em}
.show-lede em{font-style:italic; color:var(--otblue)}
.cta-row{display:flex; flex-wrap:wrap; gap:12px; justify-content:center; margin-top:1.4em}
.btn{display:inline-block; text-decoration:none; font-weight:600; font-size:.98rem;
  padding:12px 20px; border-radius:10px; transition:.15s; border:1.5px solid transparent}
.btn-primary{background:var(--otblue); color:#fff; box-shadow:0 10px 24px -12px rgba(0,114,178,.7)}
.btn-primary:hover{filter:brightness(1.06); transform:translateY(-1px)}
.btn-ghost{border-color:var(--line-strong); color:var(--ink)}
.btn-ghost:hover{border-color:var(--otblue); color:var(--otblue)}

.cta-band{padding:42px 0; border-top:1px solid var(--line)}

/* ---------- get started (on-page install) ---------- */
.getstarted{padding:42px 0; border-top:1px solid var(--line); text-align:center}
.getstarted h2{font-family:"Fraunces",serif; font-weight:600; font-size:1.7rem; margin:0 0 .25em; letter-spacing:-.01em}
.gs-lede{color:var(--muted); margin:0 0 18px; font-size:1rem}
.gs-cmds{display:grid; gap:10px; max-width:560px; margin:0 auto}
.gs-cmds pre{margin:0}
.gs-cmds code{display:block; text-align:left; padding:10px 14px; border:1px solid var(--line-strong); border-radius:6px; background:var(--paper); color:var(--ink); font:.9rem "IBM Plex Mono",monospace}
.gs-note{color:var(--muted); margin:16px auto 0; max-width:54ch; font-size:.9rem; line-height:1.5}
.gs-note a{color:var(--otblue); text-decoration:none; border-bottom:1px solid var(--otblue)}

/* ---------- why-tikz (slim) ---------- */
.why-tikz-slim{padding:42px 28px 42px; border-top:1px solid var(--line); text-align:center}
.why-tikz-slim h2{font-family:"Fraunces",serif; font-weight:600; font-size:1.7rem; margin:0 0 .25em; letter-spacing:-.01em}
.wts-strip{display:grid; grid-template-columns:repeat(3,1fr); gap:18px; max-width:980px; margin:22px auto 0; text-align:left}
.wts-item{display:flex; flex-direction:column; gap:7px; padding:18px 18px 20px; border:1px solid var(--line-strong); border-radius:10px; background:var(--paper)}
.wts-num{font:600 .8rem "IBM Plex Mono",monospace; color:var(--otorange); letter-spacing:.04em}
.wts-item b{font:600 1rem "Fraunces",serif; color:var(--ink)}
.wts-desc{font:.9rem/1.5 "IBM Plex Sans",sans-serif; color:var(--muted)}
@media(max-width:680px){.wts-strip{grid-template-columns:1fr}}

/* why-opentikz verdict cards */
.why-ot{padding:42px 0; border-top:1px solid var(--line); text-align:center}
.why-ot h2{font-family:"Fraunces",serif; font-weight:600; font-size:1.7rem; margin:0 0 .25em; letter-spacing:-.01em}

.cmp-rows{display:grid; gap:11px; max-width:780px; margin:6px auto 0; text-align:left}
.cmp-row{display:grid; grid-template-columns:1fr 1fr; gap:20px; align-items:start}
.cmp-head{padding-bottom:5px; border-bottom:1px solid var(--line)}
.cmp-head span{font-family:"IBM Plex Mono",monospace; font-size:.7rem; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); padding-left:1.6em}
.cmp-x,.cmp-v{position:relative; padding-left:1.6em; font-size:.95rem; line-height:1.45}
.cmp-x{color:var(--muted)}
.cmp-x::before{content:"\2717"; position:absolute; left:0; top:0; color:var(--muted)}
.cmp-v{color:var(--ink); font-weight:500}
.cmp-v::before{content:"\2713"; position:absolute; left:0; top:0; color:var(--otteal); font-weight:700}
.cmp-v code{font-size:.85em}

/* stack the two-column sections on narrow screens */
@media (max-width:720px){
  .cmp-row{grid-template-columns:1fr; gap:5px}
  .cmp-head{display:none}
}
.cta-band{text-align:center; border-bottom:none}
.cta-band h2{font-family:"Fraunces",serif; font-weight:900; letter-spacing:-.02em;
  font-size:clamp(1.6rem,3.4vw,2.4rem); margin:0 0 .6em}
.cta-sub{color:var(--muted); font-size:.85rem; margin:1.1em 0 0; font-family:"IBM Plex Mono",monospace}

/* shared carousel (hero + how-to-use) */
.carousel{display:flex; align-items:center; gap:10px}
.car-track{flex:1; min-width:0}
.demo-slide{display:none}
.demo-slide.active{display:block; animation:fade .25s both}
@keyframes fade{from{opacity:0}to{opacity:1}}
.car-nav{flex:none; width:40px; height:40px; border-radius:50%; cursor:pointer; font-size:1.05rem;
  background:#fff; border:1.5px solid var(--line-strong); color:var(--ink); transition:.15s}
.car-nav:hover{border-color:var(--otblue); color:var(--otblue)}
.hero-carousel .car-nav{width:34px; height:34px; padding:0; border:none; background:none;
  font-size:1.9rem; line-height:1; color:var(--muted); box-shadow:none}
.hero-carousel .car-nav:hover{color:var(--otblue); border:none; transform:none}
.car-dots{display:flex; flex-wrap:wrap; justify-content:center; gap:8px; margin-top:20px}
.demo-dot{cursor:pointer; font:500 .76rem "IBM Plex Mono",monospace; color:var(--muted);
  background:#fff; border:1.5px solid var(--line-strong); border-radius:999px; padding:5px 11px; transition:.15s}
.demo-dot:hover{border-color:var(--otblue)}
.demo-dot.active{background:var(--ink); color:var(--paper); border-color:var(--ink)}

/* how-to-use section */
.howto{margin:36px 0 0; padding-top:36px; border-top:1px solid var(--line); text-align:center}
.howto h2{font-family:"Fraunces",serif; font-weight:600; font-size:1.7rem; margin:0 0 .2em; letter-spacing:-.01em}
.howto-tabs{margin:6px 0 18px}
.howto-carousel .demo-slide{min-height:420px}            /* fixed height: no section jump */
/* steps layout */
.howto-steps{display:grid; grid-template-columns:repeat(3,1fr); gap:16px; align-items:start}
.howto-step{border:1px solid var(--line); border-radius:8px; padding:14px}
.howto-step-n{display:inline-grid; place-items:center; width:24px; height:24px; border-radius:999px;
  background:var(--otblue); color:#fff; font:600 .8rem/1 "IBM Plex Mono",monospace}
.howto-step-vis{min-height:104px; display:grid; place-items:center; margin:10px 0}
.howto-step-vis img{max-height:104px; max-width:100%; width:auto; height:auto}
.howto-step-cap{margin:0; color:var(--muted); font-size:.85rem}
/* inout layout */
.howto-flow{display:grid; grid-template-columns:1fr auto 1fr; gap:14px; align-items:center}
.howto-cell{margin:0; border:1px solid var(--line); border-radius:8px; padding:12px;
  display:grid; place-items:center; min-height:280px}
.howto-cell img{max-height:260px; max-width:100%; width:auto; height:auto}
.howto-cell figcaption,.howto-arrow figcaption{font-family:"IBM Plex Mono",monospace; font-size:.7rem; color:var(--muted); margin-top:6px}
.howto-codes{display:grid; gap:7px; justify-items:center}
.howto-codes code{display:block; padding:3px 10px; border:1px solid var(--line-strong); border-radius:5px}
/* describe cell as a mini terminal showing the skill command */
.howto-term{border:none}
.howto-term-box{width:100%; max-width:30ch; background:var(--paper); border:1px solid var(--line-strong); box-shadow:0 1px 0 var(--line-strong); border-radius:8px; padding:11px 13px; text-align:left; font-family:"IBM Plex Mono",monospace}
.howto-term-bar{display:flex; gap:6px; margin-bottom:9px}
.howto-term-bar span{width:9px; height:9px; border-radius:999px}
.howto-term-bar span:nth-child(1){background:var(--otorange)}
.howto-term-bar span:nth-child(2){background:var(--otblue)}
.howto-term-bar span:nth-child(3){background:var(--otteal)}
.howto-term-cmd{display:block; background:none; border:none; padding:0; color:var(--otteal); font-size:.78rem; margin-bottom:7px}
.howto-term-text{display:block; background:none; border:none; padding:0; color:var(--ink); font-size:.86rem; line-height:1.55; white-space:normal; overflow-wrap:anywhere}
.howto-ph{color:var(--muted); font-family:"IBM Plex Mono",monospace; font-size:.8rem;
  border-style:dashed}
.howto-arrow{display:grid; gap:6px; justify-items:center; color:var(--muted)}
.howto-arrow-glyph{display:inline-block; font-size:1.5rem; line-height:1; color:var(--muted)}
.howto-cap{margin:0 auto 18px; max-width:60ch; color:var(--muted); font-size:.9rem}

/* hero figure carousel */
.hero-carousel{margin:26px auto 0; max-width:760px}
.hero-slide{display:none}
.hero-slide.active{display:block; animation:fade .25s both}
.hero-fig{margin:0; display:flex; flex-direction:column; align-items:center; gap:14px}
.hero-fig img{width:100%; height:300px; object-fit:contain}
.hero-cap{display:flex; align-items:center; gap:10px; font:.95rem "IBM Plex Sans",sans-serif}
.hero-cap a{color:var(--ink); text-decoration:none; border-bottom:1px solid var(--line-strong)}
.hero-cap a:hover{color:var(--otblue); border-color:var(--otblue)}
.hero-dot{width:9px; height:9px; padding:0; border-radius:50%; cursor:pointer;
  background:transparent; border:1.5px solid var(--line-strong)}
.hero-dot:hover{border-color:var(--otblue)}
.hero-dot.active{background:var(--ink); border-color:var(--ink)}

/* Browse tool-surface header */
.hero-browse{padding-top:40px}
.browse-title{font-family:"Fraunces",serif; font-weight:900; letter-spacing:-.02em;
  font-size:clamp(1.7rem,4vw,2.4rem); margin:0 0 .5em}

@media(max-width:720px){
  :root{--gutter:18px}            /* one place sets the mobile gutter for every container */
  .item-top{grid-template-columns:1fr; gap:22px}
  /* navbar collapses to a hamburger; links become an overlay dropdown */
  .nav-inner{padding:10px var(--gutter); gap:10px; flex-wrap:nowrap; position:relative}
  .nav-burger{display:flex; position:absolute; right:var(--gutter); top:50%;
    transform:translateY(-50%)}
  .nav-links{position:absolute; top:calc(100% + 1px); left:0; right:0; margin:0;
    flex-direction:column; flex-wrap:nowrap; align-items:stretch; gap:0;
    background:rgba(251,250,246,.98); backdrop-filter:blur(8px);
    border-bottom:1px solid var(--line); box-shadow:0 14px 30px rgba(27,26,22,.09);
    max-height:0; overflow-y:hidden; transition:max-height .26s ease; padding:0 var(--gutter)}
  .nav-toggle:checked ~ .nav-links{max-height:80vh; overflow-y:auto; padding:4px var(--gutter) 10px}
  .nav-links a{padding:13px 6px; font-size:1rem; border-radius:0;
    border-bottom:1px solid var(--line)}
  .nav-links a:last-child{border-bottom:0}
  /* burger → X when open */
  .nav-toggle:checked ~ .nav-burger span:nth-child(1){transform:translateY(6px) rotate(45deg)}
  .nav-toggle:checked ~ .nav-burger span:nth-child(2){opacity:0}
  .nav-toggle:checked ~ .nav-burger span:nth-child(3){transform:translateY(-6px) rotate(-45deg)}
  .hero{padding:34px 20px 8px}
  .showcase{padding:32px 0 26px}
  .howto-steps,.howto-flow{grid-template-columns:1fr}
  .howto-arrow-glyph{transform:rotate(90deg)}
  .carousel{gap:6px}
  .car-nav{width:34px; height:34px}
}

/* ---------- LaTeX library additions ---------- */
/* full-page template previews read as a sheet of paper */
.canvas-page img, .item-canvas.canvas-page img{background:#fff; box-shadow:0 1px 0 var(--line-strong), 0 10px 24px -14px rgba(27,26,22,.55); border:1px solid var(--line)}
.canvas.canvas-page{padding:14px}
.canvas.canvas-icon img{height:118px; max-height:118px; width:auto}
.item-canvas.canvas-icon img{height:230px; width:auto}
.canvas.canvas-page img{max-height:168px}
.item-canvas.canvas-page img{max-height:520px}
.hero-page img{filter:drop-shadow(0 10px 18px rgba(27,26,22,.22))}
.code-hint{color:#8f8a99; margin-left:.4em}
.code-block + .code-block{margin-top:16px}
.chips-cat{margin-top:10px}
.chip-cat{font-size:.76rem; padding:5px 11px}
.chip-cat.active{background:var(--otblue); border-color:var(--otblue); color:#fff}
.howto-carousel .demo-slide{min-height:250px}
.howto-codes code{white-space:nowrap; max-width:100%; overflow:hidden; text-overflow:ellipsis}
.site-footer a{color:var(--otblue); text-decoration:none}
/* home: skills & tools strip */
.skills-band{padding:42px 0; border-top:1px solid var(--line); text-align:center}
.skills-band h2{font-family:"Fraunces",serif; font-weight:600; font-size:1.7rem; margin:0 0 .25em; letter-spacing:-.01em}
.skill-grid{display:grid; grid-template-columns:repeat(auto-fill,minmax(104px,1fr)); gap:12px;
  max-width:960px; margin:18px auto 22px}
.skill-tile{display:flex; flex-direction:column; align-items:center; gap:8px; padding:14px 8px 11px;
  background:#fff; border:1px solid var(--line); border-radius:10px; text-decoration:none;
  box-shadow:var(--shadow); transition:transform .15s, border-color .15s}
.skill-tile:hover{transform:translateY(-3px); border-color:var(--line-strong)}
.skill-tile img{height:52px; width:auto; max-width:100%}
.skill-tile span{font:500 .78rem "IBM Plex Sans",sans-serif; color:var(--ink)}
.site-footer a:hover{text-decoration:underline}
.cta-sub{margin-top:1.2em}
"""

APP_JS = r"""(function () {
  // ---- search + filter (index page) ----
  var catalogEl = document.getElementById('catalog');
  var gallery = document.getElementById('gallery');
  if (catalogEl && gallery) {
    var data = JSON.parse(catalogEl.textContent);
    var cards = Array.prototype.slice.call(gallery.querySelectorAll('.card'));
    var groups = Array.prototype.slice.call(gallery.querySelectorAll('.group'));
    var byId = {};
    cards.forEach(function (c) { byId[c.getAttribute('data-id')] = c; });
    var searchEl = document.getElementById('search');
    var countEl = document.getElementById('count');
    var emptyEl = document.getElementById('empty');
    var chips = Array.prototype.slice.call(document.querySelectorAll('#chips .chip'));
    var catChips = Array.prototype.slice.call(document.querySelectorAll('#cat-chips .chip'));
    var activeType = 'all', activeCat = 'all';

    // support ?q= (prefill+run) and ?focus= from the Home search hand-off
    var params = new URLSearchParams(location.search);
    var q0 = params.get('q');
    if (q0 && searchEl) searchEl.value = q0;

    var fuse = window.Fuse ? new window.Fuse(data, {
      includeScore: true, threshold: 0.38, ignoreLocation: true,
      keys: [
        { name: 'name', weight: 3 }, { name: 'tags', weight: 2 },
        { name: 'category', weight: 1.5 }, { name: 'requires', weight: 1.5 },
        { name: 'id', weight: 1 }, { name: 'description', weight: 1 }
      ]
    }) : null;

    function apply() {
      var q = (searchEl.value || '').trim();
      var rank = {};
      var matched = null;          // null = no query (show all)
      if (q && fuse) {
        matched = {};
        fuse.search(q).forEach(function (r, i) { matched[r.item.id] = true; rank[r.item.id] = i; });
      } else if (q) {              // offline / CDN blocked: plain substring match
        matched = {};
        var words = q.toLowerCase().split(/\s+/);
        data.forEach(function (it) {
          var hay = [it.id, it.name, it.description].concat(it.tags, it.category, it.requires)
            .join(' ').toLowerCase();
          if (words.every(function (w) { return hay.indexOf(w) !== -1; })) matched[it.id] = true;
        });
      }
      var shown = 0;
      cards.forEach(function (c) {
        var id = c.getAttribute('data-id');
        var typeOk = activeType === 'all' || c.getAttribute('data-type') === activeType;
        var catOk = activeCat === 'all' ||
          (' ' + c.getAttribute('data-cats') + ' ').indexOf(' ' + activeCat + ' ') !== -1;
        var searchOk = !matched || matched[id];
        if (typeOk && catOk && searchOk) {
          c.style.display = '';
          c.style.order = (id in rank) ? rank[id] : 0;
          shown++;
        } else {
          c.style.display = 'none';
        }
      });
      // hide a section when it has no visible cards (or is filtered out by type)
      groups.forEach(function (g) {
        var vis = g.querySelectorAll('.card:not([style*="display: none"])').length;
        g.hidden = vis === 0;
        var cnt = g.querySelector('[data-count]');
        if (cnt) cnt.textContent = vis;
      });
      if (countEl) countEl.textContent = shown + (shown === 1 ? ' entry' : ' entries');
      if (emptyEl) emptyEl.hidden = shown !== 0;
    }

    if (searchEl) searchEl.addEventListener('input', apply);
    chips.forEach(function (chip) {
      chip.addEventListener('click', function () {
        chips.forEach(function (x) { x.classList.remove('active'); });
        chip.classList.add('active');
        activeType = chip.getAttribute('data-type');
        apply();
      });
    });
    catChips.forEach(function (chip) {
      chip.addEventListener('click', function () {
        catChips.forEach(function (x) { x.classList.remove('active'); });
        chip.classList.add('active');
        activeCat = chip.getAttribute('data-cat');
        apply();
      });
    });
    apply();
    if (searchEl && (q0 || params.get('focus'))) searchEl.focus();

    // ---- active-section highlight (only the section links; Browse stays active) ----
    var sectionLinks = {};
    ['snippets', 'preambles', 'templates', 'icons'].forEach(function (k) {
      var a = document.querySelector('.nav-links a[data-nav="' + k + '"]');
      if (a) sectionLinks[k] = a;
    });
    if (Object.keys(sectionLinks).length && 'IntersectionObserver' in window) {
      var obs = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          if (en.isIntersecting && sectionLinks[en.target.id]) {
            Object.keys(sectionLinks).forEach(function (k) { sectionLinks[k].classList.remove('active'); });
            sectionLinks[en.target.id].classList.add('active');
          }
        });
      }, { rootMargin: '-45% 0px -50% 0px' });
      groups.forEach(function (g) { obs.observe(g); });
    }
  }

  // ---- keyboard: '/' focuses search (or jumps to Browse); Esc clears + blurs ----
  document.addEventListener('keydown', function (e) {
    var s = document.getElementById('search');
    var t = e.target || {};
    var typing = /^(input|textarea|select)$/i.test(t.tagName || '') || t.isContentEditable;
    if (e.key === '/' && !typing && s) {
      e.preventDefault();
      s.focus();
    } else if (e.key === '/' && !typing && document.body.getAttribute('data-browse')) {
      e.preventDefault();
      location.href = document.body.getAttribute('data-browse') + '?focus=1';
    } else if (e.key === 'Escape' && s && document.activeElement === s) {
      s.value = '';
      s.dispatchEvent(new Event('input'));
      s.blur();
    }
  });

  // ---- mobile nav: close the hamburger menu on link tap / Esc ----
  var navToggle = document.getElementById('nav-toggle');
  if (navToggle) {
    document.querySelectorAll('.nav-links a').forEach(function (a) {
      a.addEventListener('click', function () { navToggle.checked = false; });
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && navToggle.checked) navToggle.checked = false;
    });
  }

  // ---- copy-to-clipboard (item page) ----
  document.querySelectorAll('.copy, .dl-copy').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.preventDefault();          // primary copy lives outside <summary>, but be safe
      var el = document.getElementById(btn.getAttribute('data-target'));
      if (!el) return;
      navigator.clipboard.writeText(el.textContent).then(function () {
        var old = btn.innerHTML;   // innerHTML preserves any inline icon on restore
        btn.innerHTML = 'Copied ✓';
        btn.classList.add('done');
        setTimeout(function () { btn.innerHTML = old; btn.classList.remove('done'); }, 1600);
      });
    });
  });

  // ---- downloads (item page): .tex from inlined source, PNG via canvas ----
  function triggerDownload(href, name) {
    var a = document.createElement('a');
    a.href = href; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
  }
  document.querySelectorAll('[data-tex]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var el = document.getElementById(btn.getAttribute('data-tex'));
      if (!el) return;
      var url = URL.createObjectURL(new Blob([el.textContent], { type: 'application/x-tex' }));
      triggerDownload(url, btn.getAttribute('data-name') || 'figure.tex');
      setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
    });
  });
  document.querySelectorAll('[data-png]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var img = new Image();
      img.onload = function () {
        var scale = 3;
        var w = img.naturalWidth || 600, h = img.naturalHeight || 400;
        var c = document.createElement('canvas');
        c.width = w * scale; c.height = h * scale;
        var ctx = c.getContext('2d');
        ctx.fillStyle = '#ffffff';                 // figures assume a white background
        ctx.fillRect(0, 0, c.width, c.height);
        ctx.drawImage(img, 0, 0, c.width, c.height);
        c.toBlob(function (blob) {
          var url = URL.createObjectURL(blob);
          triggerDownload(url, btn.getAttribute('data-name') || 'figure.png');
          setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
        }, 'image/png');
      };
      img.src = btn.getAttribute('data-png');
    });
  });

  // ---- per-instance carousels (supports multiple on one page) ----
  // Each .carousel keeps its OWN active index; all inner queries are scoped to the
  // element so the skills demo (#skills-carousel/.demo-slide/.demo-dot) never shares
  // state across multiple carousels on the same page.
  var carousels = Array.prototype.slice.call(document.querySelectorAll('.carousel'));
  carousels.forEach(function (car) {
    var slides = Array.prototype.slice.call(
      car.querySelectorAll('.demo-slide, .hero-slide'));
    if (!slides.length) return;
    // dots live in a sibling .car-dots (or any node with [data-dots-for=id])
    var dotWrap = car.parentNode
      ? car.parentNode.querySelector('.car-dots')
      : null;
    var dots = dotWrap
      ? Array.prototype.slice.call(dotWrap.querySelectorAll('.demo-dot, .hero-dot'))
      : [];
    var idx = 0;
    function show(n) {
      idx = (n + slides.length) % slides.length;
      slides.forEach(function (s, i) { s.classList.toggle('active', i === idx); });
      dots.forEach(function (d, i) { d.classList.toggle('active', i === idx); });
    }
    var prev = car.querySelector('.car-prev'), next = car.querySelector('.car-next');
    if (prev) prev.addEventListener('click', function () { show(idx - 1); });
    if (next) next.addEventListener('click', function () { show(idx + 1); });
    dots.forEach(function (d, i) { d.addEventListener('click', function () { show(i); }); });
    // keyboard only when THIS carousel (or something inside it) has focus
    car.addEventListener('keydown', function (e) {
      var t = e.target || {};
      if (/^(input|textarea|select)$/i.test(t.tagName || '')) return;
      if (e.key === 'ArrowLeft') { e.preventDefault(); show(idx - 1); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); show(idx + 1); }
    });
    show(0);

    // ---- autoplay (opt-in via data-autoplay; honors reduced motion) ----
    // Pauses on hover, keyboard focus, or a hidden tab.
    // Manual navigation restarts the countdown so the slide never advances
    // the instant after you click.
    var prefersReduced = window.matchMedia
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (car.hasAttribute('data-autoplay') && slides.length > 1 && !prefersReduced) {
      var autoMs = parseInt(car.getAttribute('data-interval'), 10) || 5000;
      var hover = false, focused = false, timer = null;
      function autoActive() { return !(hover || focused || document.hidden); }
      function start() {
        if (timer) clearInterval(timer);
        timer = setInterval(function () { if (autoActive()) show(idx + 1); }, autoMs);
      }
      car.addEventListener('mouseenter', function () { hover = true; });
      car.addEventListener('mouseleave', function () { hover = false; });
      car.addEventListener('focusin', function () { focused = true; });
      car.addEventListener('focusout', function () { focused = false; });
      car.addEventListener('click', start);    // manual nav resets the cadence
      car.addEventListener('keydown', start);
      if (dotWrap) {                            // tabs/dots live outside .carousel
        dotWrap.addEventListener('click', start);
        dotWrap.addEventListener('keydown', start);
      }
      document.addEventListener('visibilitychange', function () {
        if (!document.hidden) start();         // realign cadence when the tab returns
      });
      start();
    }
  });

})();
"""


if __name__ == "__main__":
    raise SystemExit(main())
