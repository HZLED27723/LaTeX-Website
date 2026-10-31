<div align="center">

# My<span>LaTeX</span>┃

### Write it once. Reuse it forever.

My personal library of LaTeX snippets, preambles, templates and icons.
Every entry compiles, has a rendered preview, and is one click from my clipboard.

**[Live site](https://hzled27723.github.io/LaTeX-Website/)** · [Adding an entry](#adding-an-entry) · [Building the site](#building-the-site) · [How it's organised](#how-its-organised) · [Publishing](#publishing-on-github-pages)

</div>

---

Every time I work out how to do something in LaTeX (a table layout, an equation
style, a preamble that just works), I log it here. When I start a new document
I search the site, copy the **preamble** lines and the **snippet**, and I'm done.

Four kinds of entry:

| Type | What it is | Example |
| --- | --- | --- |
| **Snippet** | A piece of document body + the packages it needs | booktabs table, aligned equations, side-by-side figures |
| **Preamble** | A reusable setup block. Also downloadable as a `.sty` | everyday packages, maths macros, heading styles |
| **Template** | A complete starting document | article, lab report, Beamer slides, homework |
| **Icon** | A TikZ icon for a tool or skill. Also downloadable as SVG/PNG | Claude, LaTeX, Python, SolidWorks, MATLAB, Excel |

## Adding an entry

From the repo root:

```bash
python3 tools/new_entry.py snippet "Booktabs table" --category tables --tags table,booktabs
```

This creates `library/snippets/booktabs-table/` with two files:

**`booktabs-table.tex`** is a complete, compilable test file. Put your code between the markers:

```tex
\documentclass{article}
\pagestyle{empty}

%% >>> preamble
\usepackage{booktabs}          % what goes in YOUR document's preamble
%% <<< preamble

\begin{document}
%% >>> snippet
\begin{table}[htbp]            % what goes in YOUR document's body
  ...
\end{table}
%% <<< snippet
\end{document}
```

The site's **Copy preamble** and **Copy snippet** buttons copy exactly what's
between each pair of markers. Templates only need the `snippet` markers. Their
main button copies the whole file.

**`booktabs-table.meta.json`** holds what the site shows:

```json
{
  "id": "booktabs-table",
  "name": "Booktabs table",
  "type": "snippet",
  "category": ["tables"],
  "tags": ["table", "booktabs"],
  "requires": ["booktabs"],
  "description": "A clean, publication-style table.",
  "notes": ["No vertical lines. They clash with booktabs rules.",
            "`\\label` must come after `\\caption`."],
  "links": [{"label": "booktabs on CTAN", "url": "https://ctan.org/pkg/booktabs"}],
  "added": "2026-10-31",
  "featured": false,
  "preview": "preview.svg"
}
```

- `category` drives the filter chips on the Browse page; `tags` only feed search.
- `notes` support `` `code` ``, `**bold**`, `*italic*` and `[links](https://…)`.
- `featured: true` puts the entry in the home-page carousel.
- `requires` lists the packages. `validate.py` warns if the preamble loads one you didn't list.

Then build (next section). Or skip the local build and just commit the `.tex` + `.meta.json`.
GitHub renders the preview and redeploys the site for you.

**Adding an icon** for a new skill or tool works the same way:

```bash
python3 tools/new_entry.py icon "Arduino" --category brands,electronics
```

It starts as a coloured "skill badge" tile. Change the colour and text, or paste
in a real logo as a TikZ path.

> **About the brand icons:** Anthropic, Claude, LaTeX, Overleaf, Python, NumPy,
> Jupyter, Git and GitHub are the real marks, imported from
> [OpenTikZ](https://github.com/opentikz/opentikz) (CC0, shapes from simple-icons).
> OpenAI, SolidWorks, Fusion 360, Onshape, MATLAB, Excel and Typst are simple
> skill badges in each brand's colour, drawn from scratch, not the official logos.
> All logos stay trademarks of their owners and are here only to identify the tool.

> Need an image in a snippet? Save it next to the `.tex` and `\includegraphics` it
> by relative path. Previews compile from the entry's own folder.

## Building the site

Needs Python 3 (stdlib only) and, for previews, a TeX distribution with
`latexmk`, plus `pdftocairo` (poppler) and Ghostscript.

```bash
python3 tools/build_site.py --serve
```

That renders any missing previews, rebuilds `site/` and serves it at
<http://localhost:8000>. Other useful commands:

```bash
python3 tools/validate.py
```

```bash
python3 tools/render_preview.py library/snippets/booktabs-table
```

```bash
python3 tools/build_site.py --render all
```

`validate.py` checks every entry's metadata and that it compiles.
`render_preview.py` re-renders one preview after you edit its `.tex`
(`--all` / `--missing` also work). `build_site.py --render all` re-renders
everything and rebuilds.

<details>
<summary>Installing the toolchain</summary>

- **macOS:** MacTeX (includes latexmk), then `brew install poppler ghostscript`
- **Ubuntu/Debian:** `sudo apt install texlive-latex-extra texlive-pictures texlive-science cm-super latexmk poppler-utils ghostscript`
- **Windows:** MiKTeX or TeX Live, plus poppler for `pdftocairo`

Without TeX the site still builds, and entries without a preview show a placeholder.
</details>

## How it's organised

```
LaTeX-Website/
  site.config.json          name, tagline, GitHub link: change the branding here
  library/
    snippets/<id>/          <id>.tex + <id>.meta.json + preview.svg
    preambles/<id>/
    templates/<id>/
    icons/<id>/
  tools/
    new_entry.py            scaffold a new entry
    validate.py             check metadata + compile every entry
    render_preview.py       .tex -> PDF -> cropped SVG preview
    build_catalog.py        library -> catalog.json (auto-generated, don't edit)
    build_site.py           catalog + previews -> static site/
  assets/                   favicons
  catalog.json              generated index of every entry
```

Snippet and preamble previews are cropped to the ink, so test files can use a
normal `article` class with floats, captions and numbering. Templates preview
their full first page.

**Renaming the site:** edit `brand_prefix` / `brand_accent` (the blue part of the
wordmark), `headline` and `tagline` in `site.config.json`.

## Publishing on GitHub Pages

Live at **https://hzled27723.github.io/LaTeX-Website/**

`.github/workflows/deploy.yml` validates the entries, renders every preview,
builds the site and deploys it on each push to `main`. (Pages is set to
**Settings → Pages → Source: GitHub Actions**.) All links are relative, so the
site also works opened straight from disk.

## Credits

The look, layout, front-end and site generator are adapted from
[OpenTikZ](https://github.com/opentikz/opentikz) (code MIT, content CC0). See
[`LICENSE`](LICENSE).
