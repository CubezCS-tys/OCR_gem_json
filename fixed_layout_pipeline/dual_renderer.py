"""
Dual-Output Renderer — generates both fidelity and semantic HTML from canonical JSON.

Output 1: Fidelity HTML  — per-page, absolutely-positioned LINES on a white canvas.
           Optional token overlay for word-level debugging/selection.
           No background image — the text itself IS the visual representation.

Output 2: Semantic HTML   — reflowed content using block_type → <h1>/<p>/<table>/<figure>.
           Good for reading, mobile, SEO, accessibility.

Output 3: Markdown        — plain semantic markdown (optional).

All outputs are deterministic: same canonical JSON → same output.
"""

from __future__ import annotations

import html as html_mod
import logging
import re
from pathlib import Path
from typing import Optional

from .schema import (
    Block,
    BlockType,
    CanonicalDocument,
    Direction,
    Line,
    Page,
    Table,
    Token,
)

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────

ARABIC_FONT_STACK = (
    "'Amiri', 'Noto Naskh Arabic', 'Traditional Arabic', "
    "'Simplified Arabic', 'Tahoma', serif"
)
LATIN_FONT_STACK = (
    "'Noto Serif', 'Times New Roman', 'Georgia', serif"
)


# ═══════════════════════════════════════════════════════════════════════════════
#  1. FIDELITY HTML — Line-level absolute positioning
# ═══════════════════════════════════════════════════════════════════════════════

class FidelityRenderer:
    """
    Render a CanonicalDocument as fixed-layout HTML using LINE-level positioning.

    Each page is a white canvas of exact page dimensions.
    Each line is absolutely positioned at its bounding box.
    English tokens inside RTL lines get <span dir="ltr"> wrappers.
    Optional token overlay for debugging.
    """

    def __init__(self, scale: float = 1.0, show_tokens: bool = False):
        self.scale = scale
        self.show_tokens = show_tokens  # toggle token-level boxes

    def render(self, doc: CanonicalDocument) -> str:
        """Render full multi-page fidelity HTML."""
        pages = []
        for page in doc.pages:
            pages.append(self._render_page(page))

        title = html_mod.escape(doc.title or doc.source.filename or "Document")
        lang = doc.languages[0] if doc.languages else "ar"
        direction = "rtl" if doc.principal_direction == Direction.RTL else "ltr"

        return self._wrap(title, lang, direction, "\n".join(pages), doc)

    # ── Per-page ──────────────────────────────────────────────────────────

    def _render_page(self, page: Page) -> str:
        w = page.image.width_px
        h = page.image.height_px
        if w == 0 or h == 0:
            return ""

        s = self.scale
        sw, sh = int(w * s), int(h * s)
        page_dir = "rtl" if page.principal_direction == Direction.RTL else "ltr"

        # Lines layer
        lines_html = self._render_lines(page, s)
        # Token overlay layer (optional)
        tokens_html = self._render_tokens(page, s) if self.show_tokens else ""
        # Tables
        tables_html = self._render_tables(page, s)

        return f'''
    <div class="page" id="page-{page.page_index}"
         dir="{page_dir}" lang="ar"
         style="width:{sw}px; height:{sh}px;">

      <!-- Lines layer (primary) -->
      <div class="line-layer">
{lines_html}
      </div>

      <!-- Token overlay (debug, toggled via JS) -->
      <div class="token-layer" style="display:none;">
{tokens_html}
      </div>

      <!-- Tables -->
{tables_html}

      <div class="page-num">{page.page_index + 1}</div>
    </div>'''

    # ── Lines ─────────────────────────────────────────────────────────────

    def _render_lines(self, page: Page, s: float) -> str:
        parts = []
        for block in page.blocks_in_reading_order():
            if block.block_type == BlockType.TABLE:
                continue
            for line in block.lines:
                parts.append(self._line_span(line, block, s))
        return "\n".join(parts)

    def _line_span(self, line: Line, block: Block, s: float) -> str:
        bbox = line.bbox
        x, y = bbox.x0 * s, bbox.y0 * s
        w, h = bbox.width * s, bbox.height * s
        fs = max(8, h * 0.82)

        line_dir = line.direction or block.direction or Direction.RTL
        dir_attr = "rtl" if line_dir == Direction.RTL else "ltr"

        # Pick font
        font = ARABIC_FONT_STACK if line_dir == Direction.RTL else LATIN_FONT_STACK

        # Build inner HTML with BiDi handling
        inner = self._bidi_line_html(line, block)

        # Block type → CSS class for semantic styling
        btype = block.block_type.value

        return (
            f'        <div class="line {btype}" dir="{dir_attr}" '
            f'data-line-id="{line.line_id}" '
            f'data-conf="{line.confidence:.2f}" '
            f'style="left:{x:.1f}px; top:{y:.1f}px; '
            f'width:{w:.1f}px; height:{h:.1f}px; '
            f'font-size:{fs:.1f}px; line-height:{h:.1f}px; '
            f'font-family:{font};">'
            f'{inner}</div>'
        )

    def _bidi_line_html(self, line: Line, block: Block) -> str:
        """
        Build inner HTML for a line, wrapping LTR tokens in <span dir="ltr">
        when the line is RTL, and vice versa.
        """
        line_dir = line.direction or block.direction or Direction.RTL

        if not line.tokens:
            return html_mod.escape(line.text)

        parts = []
        for tok in line.tokens:
            t = html_mod.escape(tok.text)
            tok_dir = tok.direction or line_dir
            if tok_dir != line_dir:
                # Opposite direction → wrap
                d = "ltr" if tok_dir == Direction.LTR else "rtl"
                parts.append(f'<span dir="{d}">{t}</span>')
            else:
                parts.append(t)

        return " ".join(parts)

    # ── Tokens (overlay) ─────────────────────────────────────────────────

    def _render_tokens(self, page: Page, s: float) -> str:
        parts = []
        for block in page.blocks_in_reading_order():
            if block.block_type == BlockType.TABLE:
                continue
            for line in block.lines:
                for tok in line.tokens:
                    parts.append(self._token_span(tok, block, s))
        return "\n".join(parts)

    def _token_span(self, tok: Token, block: Block, s: float) -> str:
        bbox = tok.bbox
        x, y = bbox.x0 * s, bbox.y0 * s
        w, h = bbox.width * s, bbox.height * s
        fs = max(8, h * 0.82)
        direction = tok.direction or block.direction or Direction.RTL
        dir_attr = "rtl" if direction == Direction.RTL else "ltr"
        font = ARABIC_FONT_STACK if direction == Direction.RTL else LATIN_FONT_STACK
        t = html_mod.escape(tok.text)

        # Color-coded confidence border
        c = tok.confidence
        if c >= 0.9:
            border = "1px solid rgba(0,180,0,0.5)"
        elif c >= 0.7:
            border = "1px solid rgba(255,165,0,0.5)"
        else:
            border = "1px solid rgba(255,0,0,0.6)"

        return (
            f'        <span class="tok" dir="{dir_attr}" '
            f'data-tok="{tok.token_id}" data-conf="{tok.confidence:.2f}" '
            f'style="position:absolute; '
            f'left:{x:.1f}px; top:{y:.1f}px; '
            f'width:{w:.1f}px; height:{h:.1f}px; '
            f'font-size:{fs:.1f}px; line-height:{h:.1f}px; '
            f'font-family:{font}; '
            f'border:{border}; '
            f'white-space:nowrap; color:transparent;">'
            f'{t}</span>'
        )

    # ── Tables ───────────────────────────────────────────────────────────

    def _render_tables(self, page: Page, s: float) -> str:
        parts = []
        for table in page.tables:
            bbox = table.bbox
            x, y = bbox.x0 * s, bbox.y0 * s
            w, h = bbox.width * s, bbox.height * s
            inner = table.to_html_table()
            parts.append(
                f'      <div class="tbl-overlay" data-table="{table.table_id}" '
                f'style="position:absolute; left:{x:.1f}px; top:{y:.1f}px; '
                f'width:{w:.1f}px; height:{h:.1f}px; z-index:2;">\n'
                f'        {inner}\n'
                f'      </div>'
            )
        return "\n".join(parts)

    # ── Full document wrapper ────────────────────────────────────────────

    def _wrap(self, title: str, lang: str, direction: str,
              pages_html: str, doc: CanonicalDocument) -> str:
        n_pages = doc.page_count()
        return f'''<!DOCTYPE html>
<html lang="{lang}" dir="{direction}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — Fidelity</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Amiri&family=Noto+Naskh+Arabic&family=Noto+Serif&display=swap" rel="stylesheet">
  <style>
    /* ─── Reset ──────────────────────────────────────────── */
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0; padding: 20px;
      background: #525659;
      display: flex; flex-direction: column; align-items: center;
      font-family: {ARABIC_FONT_STACK};
    }}

    /* ─── Page canvas ────────────────────────────────────── */
    .page {{
      position: relative;
      background: white;
      margin: 20px auto;
      box-shadow: 0 2px 10px rgba(0,0,0,0.35);
      overflow: hidden;
    }}

    /* ─── Line layer ─────────────────────────────────────── */
    .line-layer {{
      position: absolute; inset: 0; z-index: 1;
    }}
    .line-layer .line {{
      position: absolute;
      white-space: pre;
      unicode-bidi: plaintext;
      cursor: text;
    }}
    .line-layer .line::selection {{
      background: rgba(0, 120, 215, 0.35);
    }}
    .line-layer .line::-moz-selection {{
      background: rgba(0, 120, 215, 0.35);
    }}

    /* Semantic hints from block type */
    .line.header {{ font-weight: bold; }}
    .line.footnote {{ font-style: italic; opacity: 0.8; }}
    .line.page_number {{ font-size: 0.85em; opacity: 0.6; }}

    /* ─── Token overlay ──────────────────────────────────── */
    .token-layer {{
      position: absolute; inset: 0; z-index: 3;
    }}
    .token-layer .tok {{
      cursor: text;
    }}
    .token-layer .tok::selection {{
      background: rgba(0, 120, 215, 0.35);
      color: transparent;
    }}

    /* ─── Table overlay ──────────────────────────────────── */
    .tbl-overlay table {{
      width: 100%; height: 100%;
      border-collapse: collapse; table-layout: fixed;
    }}
    .tbl-overlay td, .tbl-overlay th {{
      border: 1px solid #999; padding: 2px 4px;
      font-size: 14px; vertical-align: top;
    }}
    .tbl-overlay th {{ font-weight: bold; background: #f0f0f0; }}

    /* ─── Page number badge ──────────────────────────────── */
    .page-num {{
      position: absolute; bottom: 4px; left: 50%;
      transform: translateX(-50%);
      font-size: 11px; color: #aaa;
      pointer-events: none; user-select: none; z-index: 5;
    }}

    /* ─── Toolbar ────────────────────────────────────────── */
    .toolbar {{
      position: fixed; top: 10px; left: 50%; transform: translateX(-50%);
      background: rgba(0,0,0,0.88); color: white;
      padding: 8px 18px; border-radius: 8px; z-index: 1000;
      display: flex; gap: 14px; align-items: center;
      font-family: sans-serif; font-size: 13px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.4);
    }}
    .toolbar button {{
      background: #444; color: white; border: none;
      padding: 5px 12px; border-radius: 4px; cursor: pointer; font-size: 12px;
    }}
    .toolbar button:hover {{ background: #666; }}
    .toolbar button.active {{ background: #0078d7; }}

    /* ─── Print ──────────────────────────────────────────── */
    @media print {{
      body {{ background: white; padding: 0; }}
      .page {{ box-shadow: none; margin: 0; page-break-after: always; }}
      .toolbar, .page-num {{ display: none; }}
    }}
  </style>
</head>
<body>

  <div class="toolbar">
    <span>{title}</span>
    <span style="opacity:.4">|</span>
    <span>{n_pages} pages</span>
    <button onclick="toggleTokens()" id="btn-tok">Tokens</button>
    <button onclick="toggleDebug()" id="btn-dbg">Debug</button>
    <button onclick="fitAll()" id="btn-fit">Fit Text</button>
  </div>

{pages_html}

  <script>
    /* ── Toggle token overlay ─────────────────────────── */
    let tokensOn = false;
    function toggleTokens() {{
      tokensOn = !tokensOn;
      document.querySelectorAll('.token-layer').forEach(el => {{
        el.style.display = tokensOn ? 'block' : 'none';
      }});
      document.getElementById('btn-tok').classList.toggle('active', tokensOn);
    }}

    /* ── Toggle debug borders on lines ────────────────── */
    let debugOn = false;
    function toggleDebug() {{
      debugOn = !debugOn;
      document.querySelectorAll('.line-layer .line').forEach(el => {{
        el.style.outline = debugOn ? '1px solid rgba(255,0,0,0.35)' : 'none';
        el.style.background = debugOn ? 'rgba(255,255,200,0.15)' : 'none';
      }});
      document.getElementById('btn-dbg').classList.toggle('active', debugOn);
    }}

    /* ── Fit text to bbox via scaleX ──────────────────── */
    function fitAll() {{
      const m = document.createElement('span');
      m.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap;left:-9999px;top:-9999px;';
      document.body.appendChild(m);
      document.querySelectorAll('.line-layer .line').forEach(el => {{
        const boxW = parseFloat(el.style.width);
        if (!boxW || boxW <= 0) return;
        m.style.fontFamily = el.style.fontFamily;
        m.style.fontSize = el.style.fontSize;
        m.style.fontWeight = getComputedStyle(el).fontWeight;
        m.style.lineHeight = el.style.lineHeight;
        m.textContent = el.textContent;
        const natW = m.offsetWidth;
        if (natW > 0 && Math.abs(natW - boxW) > 2) {{
          const s = boxW / natW;
          const dir = el.getAttribute('dir');
          el.style.transformOrigin = (dir === 'rtl') ? 'right center' : 'left center';
          el.style.transform = 'scaleX(' + s.toFixed(4) + ')';
        }} else {{
          el.style.transform = '';
        }}
      }});
      document.body.removeChild(m);
      document.getElementById('btn-fit').classList.toggle('active');
    }}

    /* ── Confidence tooltips ──────────────────────────── */
    document.querySelectorAll('[data-conf]').forEach(el => {{
      el.title = 'Confidence: ' + el.dataset.conf;
    }});

    /* Auto-fit on load */
    window.addEventListener('load', fitAll);
  </script>
</body>
</html>'''


# ═══════════════════════════════════════════════════════════════════════════════
#  2. SEMANTIC HTML — Reflowable, structured output
# ═══════════════════════════════════════════════════════════════════════════════

# Map block types to semantic HTML tags
BLOCK_TAG_MAP = {
    BlockType.HEADER:      "h2",
    BlockType.TEXT:         "p",
    BlockType.FOOTNOTE:    "aside",
    BlockType.FOOTER:      "footer",
    BlockType.PAGE_NUMBER: None,       # skip
    BlockType.CAPTION:     "figcaption",
    BlockType.EQUATION:    "div",
    BlockType.FIGURE:      "figure",
    BlockType.TABLE:       "div",
    BlockType.HANDWRITING: "p",
    BlockType.KEY_VALUE:   "dl",
    BlockType.UNKNOWN:     "p",
}


class SemanticRenderer:
    """
    Render a CanonicalDocument as reflowed semantic HTML.

    Converts blocks to semantic tags based on block_type.
    Reading order determines element sequence.
    No absolute positioning — standard flow layout.
    """

    def render(self, doc: CanonicalDocument) -> str:
        title = html_mod.escape(doc.title or doc.source.filename or "Document")
        lang = doc.languages[0] if doc.languages else "ar"
        direction = "rtl" if doc.principal_direction == Direction.RTL else "ltr"

        body_parts = []
        for page in doc.pages:
            body_parts.append(self._render_page(page))

        body = "\n\n".join(body_parts)

        return f'''<!DOCTYPE html>
<html lang="{lang}" dir="{direction}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — Semantic</title>
  <link href="https://fonts.googleapis.com/css2?family=Amiri&family=Noto+Naskh+Arabic&family=Noto+Serif&display=swap" rel="stylesheet">
  <style>
    body {{
      max-width: 800px; margin: 2em auto; padding: 0 1.5em;
      font-family: {ARABIC_FONT_STACK};
      font-size: 18px; line-height: 1.8;
      color: #1a1a1a; background: #fdfdfd;
      direction: {direction};
    }}
    h1, h2, h3 {{ color: #333; margin-top: 1.5em; }}
    h1 {{ font-size: 1.6em; border-bottom: 2px solid #ccc; padding-bottom: 0.3em; }}
    h2 {{ font-size: 1.35em; }}
    p {{ text-align: justify; margin: 0.8em 0; }}
    aside {{ font-size: 0.9em; color: #555; border-right: 3px solid #ddd; padding-right: 1em; margin: 1em 0; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
    th, td {{ border: 1px solid #bbb; padding: 6px 10px; text-align: right; }}
    th {{ background: #f0f0f0; font-weight: bold; }}
    figure {{ margin: 1.5em 0; text-align: center; }}
    figcaption {{ font-size: 0.9em; color: #666; margin-top: 0.5em; }}
    .page-break {{ border-top: 1px dashed #ccc; margin: 2em 0; padding-top: 0.5em;
                   font-size: 0.8em; color: #999; text-align: center; }}
    footer {{ font-size: 0.85em; color: #777; margin-top: 1em; }}
    @media print {{
      .page-break {{ page-break-before: always; border: none; }}
    }}
  </style>
</head>
<body>
  <h1>{title}</h1>
{body}
</body>
</html>'''

    def _render_page(self, page: Page) -> str:
        parts = []
        if page.page_index > 0:
            parts.append(f'  <div class="page-break">— {page.page_index + 1} —</div>')

        for block in page.blocks_in_reading_order():
            rendered = self._render_block(block)
            if rendered:
                parts.append(rendered)

        return "\n".join(parts)

    def _render_block(self, block: Block) -> str:
        btype = block.block_type

        # Skip page numbers in semantic output
        if btype == BlockType.PAGE_NUMBER:
            return ""

        # Tables
        if btype == BlockType.TABLE and block.table:
            return f"  {block.table.to_html_table()}"

        # Figures
        if btype == BlockType.FIGURE:
            cap = html_mod.escape(block.figure_caption or "")
            uri = block.figure_uri or ""
            inner = f'<img src="{uri}" alt="{cap}" />' if uri else ""
            cap_html = f"\n    <figcaption>{cap}</figcaption>" if cap else ""
            return f"  <figure>\n    {inner}{cap_html}\n  </figure>"

        # Equations
        if btype == BlockType.EQUATION and block.equation_latex:
            return f'  <div class="equation">$${block.equation_latex}$$</div>'

        # Text/header/footnote/etc.
        tag = BLOCK_TAG_MAP.get(btype, "p")
        if tag is None:
            return ""

        text = self._block_text_with_bidi(block)
        direction = "rtl" if block.direction == Direction.RTL else "ltr"
        lang = block.language or "ar"

        return f'  <{tag} dir="{direction}" lang="{lang}">{text}</{tag}>'

    def _block_text_with_bidi(self, block: Block) -> str:
        """Join lines with <br>, wrapping opposite-direction tokens."""
        line_parts = []
        block_dir = block.direction or Direction.RTL
        for line in block.lines:
            if line.tokens:
                toks = []
                for tok in line.tokens:
                    t = html_mod.escape(tok.text)
                    tok_dir = tok.direction or block_dir
                    if tok_dir != block_dir:
                        d = "ltr" if tok_dir == Direction.LTR else "rtl"
                        toks.append(f'<span dir="{d}">{t}</span>')
                    else:
                        toks.append(t)
                line_parts.append(" ".join(toks))
            else:
                line_parts.append(html_mod.escape(line.text))
        return "\n    ".join(line_parts)


# ═══════════════════════════════════════════════════════════════════════════════
#  3. MARKDOWN — Plain semantic markdown
# ═══════════════════════════════════════════════════════════════════════════════

class MarkdownRenderer:
    """Render a CanonicalDocument as Markdown."""

    def render(self, doc: CanonicalDocument) -> str:
        title = doc.title or doc.source.filename or "Document"
        parts = [f"# {title}\n"]

        for page in doc.pages:
            if page.page_index > 0:
                parts.append(f"\n---\n<!-- Page {page.page_index + 1} -->\n")
            parts.append(self._render_page(page))

        return "\n".join(parts)

    def _render_page(self, page: Page) -> str:
        parts = []
        for block in page.blocks_in_reading_order():
            rendered = self._render_block(block)
            if rendered:
                parts.append(rendered)
        return "\n\n".join(parts)

    def _render_block(self, block: Block) -> str:
        btype = block.block_type

        if btype == BlockType.PAGE_NUMBER:
            return ""

        if btype == BlockType.HEADER:
            text = block.full_text().strip()
            return f"## {text}"

        if btype == BlockType.TABLE and block.table:
            return self._table_to_md(block.table)

        if btype == BlockType.FIGURE:
            cap = block.figure_caption or ""
            uri = block.figure_uri or ""
            return f"![{cap}]({uri})" if uri else f"*[Figure: {cap}]*"

        if btype == BlockType.EQUATION and block.equation_latex:
            return f"$$\n{block.equation_latex}\n$$"

        if btype == BlockType.FOOTNOTE:
            text = block.full_text().strip()
            return f"> {text}"

        # Default: paragraph
        text = block.full_text().strip()
        return text if text else ""

    def _table_to_md(self, table: Table) -> str:
        if not table.cells:
            return ""

        max_row = max(c.row + c.row_span for c in table.cells)
        max_col = max(c.col + c.col_span for c in table.cells)
        grid: dict[tuple[int, int], str] = {}
        for cell in table.cells:
            grid[(cell.row, cell.col)] = cell.text.replace("|", "\\|").strip()

        lines = []
        for r in range(max_row):
            cols = [grid.get((r, c), "") for c in range(max_col)]
            lines.append("| " + " | ".join(cols) + " |")
            if r == 0:
                lines.append("| " + " | ".join(["---"] * max_col) + " |")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
#  4. Convenience: generate all outputs at once
# ═══════════════════════════════════════════════════════════════════════════════

def render_all(
    json_path: Path,
    output_dir: Optional[Path] = None,
    scale: float = 1.0,
    show_tokens: bool = False,
) -> dict[str, Path]:
    """
    Load canonical JSON and produce all three outputs.

    Returns dict with keys: 'fidelity', 'semantic', 'markdown'
    mapped to their output file paths.
    """
    doc = CanonicalDocument.load(json_path)
    stem = json_path.stem.replace("_canonical", "")
    out = output_dir or json_path.parent
    out.mkdir(parents=True, exist_ok=True)

    results = {}

    # 1. Fidelity HTML
    fid_path = out / f"{stem}_fidelity.html"
    fid_html = FidelityRenderer(scale=scale, show_tokens=show_tokens).render(doc)
    fid_path.write_text(fid_html, encoding="utf-8")
    logger.info(f"Fidelity HTML → {fid_path}")
    results["fidelity"] = fid_path

    # 2. Semantic HTML
    sem_path = out / f"{stem}_semantic.html"
    sem_html = SemanticRenderer().render(doc)
    sem_path.write_text(sem_html, encoding="utf-8")
    logger.info(f"Semantic HTML → {sem_path}")
    results["semantic"] = sem_path

    # 3. Markdown
    md_path = out / f"{stem}.md"
    md_text = MarkdownRenderer().render(doc)
    md_path.write_text(md_text, encoding="utf-8")
    logger.info(f"Markdown      → {md_path}")
    results["markdown"] = md_path

    return results
