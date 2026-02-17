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
import unicodedata
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
    "'faces_Regular', 'Amiri', 'Noto Naskh Arabic', 'Traditional Arabic', "
    "'Simplified Arabic', 'Tahoma', serif"
)
LATIN_FONT_STACK = (
    "'Noto Serif', 'Times New Roman', 'Georgia', serif"
)
# Combined stacks ensure per-glyph font selection works for mixed-script lines
FONT_STACK_RTL = (
    "'faces_Regular', 'Amiri', 'Noto Naskh Arabic', 'Traditional Arabic', "
    "'Simplified Arabic', 'Noto Serif', 'Times New Roman', 'Georgia', "
    "'Tahoma', serif"
)
FONT_STACK_LTR = (
    "'Noto Serif', 'Times New Roman', 'Georgia', "
    "'faces_Regular', 'Amiri', 'Noto Naskh Arabic', 'Traditional Arabic', "
    "'Simplified Arabic', 'Tahoma', serif"
)

# Unicode BiDi types that count as "strong" directional characters.
# Arabic-Indic digits (AN), punctuation (CS/ON), and whitespace (WS) do NOT
# qualify and cannot anchor dir="auto".
_STRONG_BIDI = frozenset({'L', 'R', 'AL'})


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
    Optional semantic layer for reading mode toggle.
    """

    def __init__(self, scale: float = 1.0, show_tokens: bool = False, include_semantic: bool = False):
        self.scale = scale
        self.show_tokens = show_tokens  # toggle token-level boxes
        self.include_semantic = include_semantic  # embed semantic layer for reading mode

    def render(self, doc: CanonicalDocument) -> str:
        """Render full multi-page fidelity HTML."""
        pages = []
        for page in doc.pages:
            pages.append(self._render_page(page))

        title = html_mod.escape(doc.title or doc.source.filename or "Document")
        lang = doc.languages[0] if doc.languages else "ar"
        direction = "rtl" if doc.principal_direction == Direction.RTL else "ltr"

        # Optionally generate semantic layer content
        semantic_html = ""
        if self.include_semantic:
            semantic_html = self._generate_semantic_content(doc)

        return self._wrap(title, lang, direction, "\n".join(pages), semantic_html, doc)

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
        # Figures
        figures_html = self._render_figures(page, s)

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

      <!-- Figures -->
{figures_html}

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

    @staticmethod
    def _has_strong_dir_char(text: str) -> bool:
        """Return True if *text* contains at least one Unicode strong
        directional character (L, R, or AL).  Arabic-Indic digits (AN),
        punctuation (CS/ON), and whitespace (WS) are *not* strong and
        cannot anchor ``dir="auto"``."""
        return any(unicodedata.bidirectional(ch) in _STRONG_BIDI for ch in text)

    def _line_span(self, line: Line, block: Block, s: float) -> str:
        bbox = line.bbox
        x, y = bbox.x0 * s, bbox.y0 * s
        w, h = bbox.width * s, bbox.height * s
        fs = max(8, h * 0.82)

        line_dir = line.direction or block.direction or Direction.RTL
        # Use dir="auto" when the text has strong directional characters
        # (L / R / AL) so the browser can infer direction from content.
        # Fall back to the block/line direction when text contains only
        # numbers, punctuation, or other weak/neutral chars — dir="auto"
        # cannot determine the correct direction for those and defaults
        # to LTR, which breaks RTL table cells with numeric content.
        if self._has_strong_dir_char(line.text):
            dir_attr = "auto"
        else:
            dir_attr = "rtl" if line_dir == Direction.RTL else "ltr"

        # Pick font — combined stack so Arabic glyphs always use Arabic fonts
        # even in LTR-detected lines, and vice versa
        font = FONT_STACK_RTL if line_dir == Direction.RTL else FONT_STACK_LTR

        # Build inner HTML with BiDi handling
        inner = self._bidi_line_html(line, block)

        # Block type → CSS class for semantic styling
        btype = block.block_type.value

        # Apply detected styles from vision model
        style_parts = [
            f'left:{x:.1f}px; top:{y:.1f}px;',
            f'width:{w:.1f}px; height:{h:.1f}px;',
            f'font-size:{fs:.1f}px; line-height:{h:.1f}px;',
            f'font-family:{font};'
        ]
        
        if line.font_weight:
            style_parts.append(f'font-weight:{line.font_weight};')
        if line.font_style:
            style_parts.append(f'font-style:{line.font_style};')
        if line.text_decoration:
            style_parts.append(f'text-decoration:{line.text_decoration};')
        if line.background_color:
            style_parts.append(f'background-color:{line.background_color};')
        
        style_str = ' '.join(style_parts)

        return (
            f'        <div class="line {btype}" dir="{dir_attr}" '
            f'data-line-id="{line.line_id}" '
            f'data-conf="{line.confidence:.2f}" '
            f'style="{style_str}">'
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
            t = tok.text
            tok_dir = tok.direction or line_dir
            
            # Fix Arabic negative numbers: move minus from start to end
            if tok_dir == Direction.RTL and t.startswith('-'):
                t = t[1:] + '-'
            elif tok_dir == Direction.RTL and t.startswith('−'):
                t = t[1:] + '−'
            
            t = html_mod.escape(t)
            
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
        font = FONT_STACK_RTL if direction == Direction.RTL else FONT_STACK_LTR
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
        # Tables are rendered as positioned text blocks
        return ""

    # ── Figures ──────────────────────────────────────────────────────────

    def _render_figures(self, page: Page, s: float) -> str:
        """Render figures at their exact bounding box positions."""
        parts = []
        for block in page.blocks:
            if block.block_type != BlockType.FIGURE:
                continue
            if not block.figure_uri:
                continue
                
            bbox = block.bbox
            x, y = bbox.x0 * s, bbox.y0 * s
            w, h = bbox.width * s, bbox.height * s
            
            caption = html_mod.escape(block.figure_caption or "")
            
            parts.append(
                f'      <div class="fig-overlay" data-block="{block.block_id}" '
                f'style="position:absolute; left:{x:.1f}px; top:{y:.1f}px; '
                f'width:{w:.1f}px; height:{h:.1f}px; z-index:2;">\n'
                f'        <img src="{block.figure_uri}" alt="{caption}" '
                f'style="width:100%; height:100%; object-fit:contain;" />\n'
                f'      </div>'
            )
        return "\n".join(parts)

    # ── Semantic layer generation ────────────────────────────────────────

    def _generate_semantic_content(self, doc: CanonicalDocument) -> str:
        """Generate semantic/reading mode content from document blocks."""
        # Use SemanticRenderer logic but return just the content, not full HTML
        renderer = SemanticRenderer()
        parts = []
        
        for page in doc.pages:
            blocks = page.blocks_in_reading_order()
            merged = renderer._merge_paragraphs(blocks)
            
            for block in merged:
                rendered = renderer._render_block(block)
                if rendered:
                    parts.append(rendered)
        
        return "\n".join(parts)

    # ── Full document wrapper ────────────────────────────────────────────

    def _wrap(self, title: str, lang: str, direction: str,
              pages_html: str, semantic_html: str, doc: CanonicalDocument) -> str:
        n_pages = doc.page_count()
        
        # Build toolbar buttons based on whether semantic layer is included
        if semantic_html:
            toolbar_buttons = f'''
    <button onclick="toggleReading()" id="btn-reading">📖 Reading</button>
    <span style="opacity:.4">|</span>
    <button onclick="toggleTokens()" id="btn-tok">Tokens</button>
    <button onclick="toggleDebug()" id="btn-dbg">Debug</button>
    <button onclick="toggleConfidence()" id="btn-conf">Confidence</button>
    <button onclick="fitAll()" id="btn-fit">Fit Text</button>'''
        else:
            toolbar_buttons = f'''
    <button onclick="toggleTokens()" id="btn-tok">Tokens</button>
    <button onclick="toggleDebug()" id="btn-dbg">Debug</button>
    <button onclick="toggleConfidence()" id="btn-conf">Confidence</button>
    <button onclick="fitAll()" id="btn-fit">Fit Text</button>'''
        
        # Build semantic layer section if included
        if semantic_html:
            semantic_section = f'''

  <!-- Semantic/Reading layer -->
  <div class="semantic-layer" id="reading-view">
    <div class="content">
      <h1>{title}</h1>
{semantic_html}
    </div>
  </div>'''
        else:
            semantic_section = ""
        
        return f'''<!DOCTYPE html>
<html lang="{lang}" dir="{direction}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — Fidelity</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Amiri&family=Noto+Naskh+Arabic&family=Noto+Serif&display=swap" rel="stylesheet">
  <style>
    /* ─── CSS Variables ──────────────────────────────────── */
    :root {{
      --arabic-font: {ARABIC_FONT_STACK};
      --text-color: #111;
      --muted: #666;
      --lowconf-bg: rgba(220, 80, 60, 0.20);
      --lowconf-highlight: rgba(255, 200, 0, 0.25);
    }}

    /* ─── Reset ──────────────────────────────────────────── */
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0; padding: 20px;
      background: #525659;
      display: flex; flex-direction: column; align-items: center;
      font-family: var(--arabic-font);
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
      white-space: nowrap;
      cursor: text;
      color: var(--text-color);
      font-family: var(--arabic-font);
      font-variant-ligatures: contextual;
      text-rendering: geometricPrecision;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
      transition: background 0.2s ease;
      overflow: hidden;
    }}
    .line-layer .line[dir="rtl"],
    .line-layer .line[dir="ltr"] {{
      /* When direction is explicitly set (e.g. number-only cells
         that lack strong BiDi characters), use 'isolate' so the
         dir attribute is honoured by the BiDi algorithm.
         'plaintext' would ignore dir and fall back to heuristic
         first-strong-char detection, defaulting to LTR for
         number-only content. */
      unicode-bidi: isolate;
    }}
    .line-layer .line[dir="rtl"] {{
      text-align: right;
    }}
    .line-layer .line[dir="ltr"] {{
      text-align: left;
    }}
    .line-layer .line[dir="auto"] {{
      /* For lines with strong directional characters, let the
         browser determine direction from the text content.
         'plaintext' inspects actual characters rather than
         inheriting from the parent element. */
      unicode-bidi: plaintext;
      text-align: start;
    }}
    .line-layer .line::selection {{
      background: rgba(0, 120, 215, 0.35);
    }}
    .line-layer .line::-moz-selection {{
      background: rgba(0, 120, 215, 0.35);
    }}

    /* Journal-grade semantic styling by block type */
    .line.header {{
      font-weight: 700;
      letter-spacing: 0.3px;
    }}
    .line.footnote {{
      color: var(--muted);
      font-style: normal;
      font-size: 0.92em;
    }}
    .line.page_number {{
      color: #999;
      font-size: 0.85em;
    }}

    /* Confidence-based highlighting (toggled via JS) */
    .line[data-conf] {{
      outline: 0 solid transparent;
    }}
    .confidence-mode .line[data-conf^="0.7"],
    .confidence-mode .line[data-conf^="0.6"],
    .confidence-mode .line[data-conf^="0.5"],
    .confidence-mode .line[data-conf^="0.4"],
    .confidence-mode .line[data-conf^="0.3"] {{
      background: var(--lowconf-bg);
      border-radius: 3px;
      padding: 0 2px;
    }}
    .confidence-mode .line[data-conf^="0.5"],
    .confidence-mode .line[data-conf^="0.4"],
    .confidence-mode .line[data-conf^="0.3"] {{
      background: var(--lowconf-highlight);
    }}

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
    .tbl-overlay {{
      background: white;
      overflow: auto;
    }}
    .tbl-overlay table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: auto;
      font-family: {ARABIC_FONT_STACK};
    }}
    .tbl-overlay td, .tbl-overlay th {{
      border: 1px solid #666;
      padding: 3px 5px;
      font-size: 13px;
      vertical-align: middle;
      text-align: center;
      direction: rtl;
      line-height: 1.2;
    }}
    .tbl-overlay th {{
      font-weight: bold;
      background: #e8e8e8;
      border: 1px solid #555;
    }}
    .tbl-overlay td {{
      background: white;
    }}

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

    /* ─── Semantic/Reading Layer ─────────────────────────── */
    .semantic-layer {{
      display: none;
      max-width: 800px;
      margin: 80px auto 40px auto;
      padding: 0 2.5em;
      background: white;
      box-shadow: 0 2px 20px rgba(0,0,0,0.15);
      border-radius: 6px;
    }}
    .semantic-layer.active {{
      display: block;
    }}
    .semantic-layer .content {{
      padding: 3em 2em;
      font-family: var(--arabic-font);
      font-size: 19px;
      line-height: 1.9;
      color: #1a1a1a;
      direction: {direction};
      font-variant-ligatures: contextual;
      text-rendering: optimizeLegibility;
    }}
    .semantic-layer h1 {{
      font-size: 1.75em;
      color: #222;
      margin: 0 0 1em 0;
      border-bottom: 2px solid #ddd;
      padding-bottom: 0.4em;
    }}
    .semantic-layer h2 {{
      font-size: 1.4em;
      color: #222;
      font-weight: 700;
      margin: 1.8em 0 0.6em 0;
      letter-spacing: 0.3px;
    }}
    .semantic-layer h3 {{
      font-size: 1.15em;
      color: #444;
      margin: 1.5em 0 0.5em 0;
    }}
    .semantic-layer p {{
      margin: 0 0 1.2em 0;
      text-align: justify;
      text-justify: inter-word;
      orphans: 3;
      widows: 3;
    }}
    .semantic-layer aside {{
      font-size: 0.92em;
      color: #666;
      background: #f8f8f8;
      border-right: 3px solid #ddd;
      padding: 0.8em 1.2em;
      margin: 1.5em 0;
    }}
    .semantic-layer table {{
      width: 100%;
      border-collapse: collapse;
      margin: 1.5em 0;
      font-size: 0.95em;
    }}
    .semantic-layer th, .semantic-layer td {{
      border: 1px solid #999;
      padding: 8px 12px;
      text-align: right;
    }}
    .semantic-layer th {{
      background: #e8e8e8;
      font-weight: 700;
    }}
    .semantic-layer figure {{
      margin: 2em 0;
      text-align: center;
      background: #f8f8f8;
      padding: 1em;
      border-radius: 4px;
    }}
    .semantic-layer figcaption {{
      font-size: 0.92em;
      color: #666;
      margin-top: 0.8em;
      font-style: italic;
    }}
    .semantic-layer .page-break {{
      border-top: 1px dashed #ccc;
      margin: 3em 0 2em 0;
      padding-top: 0.8em;
      font-size: 0.8em;
      color: #aaa;
      text-align: center;
    }}
  </style>
</head>
<body>

  <div class="toolbar">
    <span>{title}</span>
    <span style="opacity:.4">|</span>
    <span>{n_pages} pages</span>
{toolbar_buttons}
  </div>

  <!-- Fidelity layer (pages) -->
  <div class="pages-container" id="fidelity-view">
{pages_html}
  </div>
{semantic_section}

  <script>
    /* ── Toggle Reading mode (fidelity ↔ semantic) ─────── */
    let readingMode = false;
    function toggleReading() {{
      readingMode = !readingMode;
      const fidelityView = document.getElementById('fidelity-view');
      const readingView = document.getElementById('reading-view');
      const body = document.body;
      
      if (readingMode) {{
        fidelityView.style.display = 'none';
        readingView.classList.add('active');
        body.style.background = 'white';
      }} else {{
        fidelityView.style.display = 'block';
        readingView.classList.remove('active');
        body.style.background = '#525659';
      }}
      
      const btn = document.getElementById('btn-reading');
      if (btn) btn.classList.toggle('active', readingMode);
    }}

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

    /* ── Toggle confidence highlighting ───────────────── */
    let confidenceOn = false;
    function toggleConfidence() {{
      confidenceOn = !confidenceOn;
      document.body.classList.toggle('confidence-mode', confidenceOn);
      document.getElementById('btn-conf').classList.toggle('active', confidenceOn);
    }}

    /* ── Fit text to bbox via font-size (proportional) ── */
    function fitAll() {{
      const m = document.createElement('span');
      m.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap;left:-9999px;top:-9999px;';
      document.body.appendChild(m);
      document.querySelectorAll('.line-layer .line').forEach(el => {{
        const boxW = parseFloat(el.style.width);
        const boxH = parseFloat(el.style.height);
        if (!boxW || boxW <= 0) return;
        // Reset any previous fit adjustments
        el.style.transform = '';
        const origFs = parseFloat(el.dataset.origFs || el.style.fontSize);
        if (!el.dataset.origFs) el.dataset.origFs = origFs;
        // Measure natural width at original font-size
        m.style.fontFamily = el.style.fontFamily;
        m.style.fontSize = origFs + 'px';
        m.style.fontWeight = getComputedStyle(el).fontWeight;
        m.style.lineHeight = el.style.lineHeight;
        m.setAttribute('dir', el.getAttribute('dir') || 'rtl');
        m.innerHTML = el.innerHTML;
        const natW = m.offsetWidth;
        if (natW <= 0) return;
        let newFs = origFs;
        if (natW > boxW * 1.02) {{
          // Text overflows — shrink font-size proportionally
          newFs = origFs * (boxW / natW);
        }}
        // Clamp: don't go below 6px, don't exceed box height
        newFs = Math.max(6, Math.min(newFs, boxH * 0.95));
        el.style.fontSize = newFs.toFixed(1) + 'px';
        el.style.lineHeight = boxH + 'px';

        // Justify: distribute remaining space as word-spacing
        el.style.wordSpacing = 'normal';
        m.style.fontSize = newFs + 'px';
        m.innerHTML = el.innerHTML;
        const fittedW = m.offsetWidth;
        const textContent = el.textContent || '';
        const words = textContent.trim().split(/ +/);
        const nGaps = words.length - 1;
        // Only justify if line fills >60% of box and has multiple words
        if (nGaps > 0 && fittedW > boxW * 0.6) {{
          const extraSpace = boxW - fittedW;
          if (extraSpace > 0) {{
            const ws = extraSpace / nGaps;
            // Cap word-spacing to avoid absurd gaps (max 2em)
            if (ws < newFs * 2) {{
              el.style.wordSpacing = ws.toFixed(1) + 'px';
            }}
          }}
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
    :root {{
      --arabic-font: {ARABIC_FONT_STACK};
      --text-color: #1a1a1a;
      --heading-color: #222;
      --muted-color: #666;
      --border-color: #ddd;
      --bg-subtle: #f8f8f8;
    }}
    
    body {{
      max-width: 800px; margin: 2em auto; padding: 0 2em;
      font-family: var(--arabic-font);
      font-size: 19px; 
      line-height: 1.9;
      color: var(--text-color); 
      background: white;
      direction: {direction};
      font-variant-ligatures: contextual;
      text-rendering: optimizeLegibility;
      -webkit-font-smoothing: antialiased;
    }}
    
    /* Typography hierarchy */
    h1, h2, h3 {{ 
      color: var(--heading-color); 
      font-weight: 700;
      line-height: 1.3;
      margin-top: 1.8em; 
      margin-bottom: 0.6em;
    }}
    h1 {{ 
      font-size: 1.75em; 
      border-bottom: 2px solid var(--border-color); 
      padding-bottom: 0.4em;
      margin-top: 0;
    }}
    h2 {{ 
      font-size: 1.4em;
      letter-spacing: 0.3px;
    }}
    h3 {{
      font-size: 1.15em;
      color: #444;
    }}
    
    /* Paragraphs with journal-style typography */
    p {{ 
      text-align: justify; 
      text-justify: inter-word;
      margin: 0 0 1.2em 0;
      orphans: 3;
      widows: 3;
    }}
    p:first-of-type {{
      margin-top: 0;
    }}
    
    /* Lists */
    ul, ol {{
      margin: 1em 0;
      padding-right: 2em;
      padding-left: 0;
    }}
    li {{
      margin: 0.4em 0;
      text-align: justify;
    }}
    
    /* Footnotes */
    aside {{ 
      font-size: 0.92em; 
      color: var(--muted-color); 
      border-right: 3px solid var(--border-color); 
      padding-right: 1.2em; 
      margin: 1.5em 0;
      background: var(--bg-subtle);
      padding-top: 0.5em;
      padding-bottom: 0.5em;
    }}
    
    /* Tables */
    table {{ 
      border-collapse: collapse; 
      width: 100%; 
      margin: 1.5em 0;
      font-size: 0.95em;
    }}
    th, td {{ 
      border: 1px solid #999; 
      padding: 8px 12px; 
      text-align: right;
      vertical-align: top;
    }}
    th {{ 
      background: #e8e8e8; 
      font-weight: 700;
    }}
    
    /* Figures */
    figure {{ 
      margin: 2em 0; 
      text-align: center;
      background: var(--bg-subtle);
      padding: 1em;
      border-radius: 4px;
    }}
    figcaption {{ 
      font-size: 0.92em; 
      color: var(--muted-color); 
      margin-top: 0.8em;
      font-style: italic;
    }}
    
    /* Page breaks */
    .page-break {{ 
      border-top: 1px dashed #ccc; 
      margin: 3em 0 2em 0; 
      padding-top: 0.8em;
      font-size: 0.8em; 
      color: #aaa; 
      text-align: center;
      letter-spacing: 2px;
    }}
    
    /* Footer metadata */
    footer {{ 
      font-size: 0.88em; 
      color: #888; 
      margin-top: 1.5em;
      padding-top: 0.5em;
      border-top: 1px solid #eee;
    }}
    
    /* Blockquotes for citations */
    blockquote {{
      margin: 1.5em 2em;
      padding: 0.5em 1.5em;
      border-right: 4px solid var(--border-color);
      background: var(--bg-subtle);
      font-style: italic;
    }}
    
    @media print {{
      body {{ max-width: 100%; margin: 0; padding: 1cm; }}
      .page-break {{ page-break-before: always; border: none; }}
    }}
    @media (max-width: 600px) {{
      body {{ font-size: 17px; padding: 0 1em; }}
      h1 {{ font-size: 1.5em; }}
      h2 {{ font-size: 1.25em; }}
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
            parts.append(f'  <div class="page-break">— صفحة {page.page_index + 1} —</div>')

        blocks = page.blocks_in_reading_order()
        merged = self._merge_paragraphs(blocks)
        
        for block in merged:
            rendered = self._render_block(block)
            if rendered:
                parts.append(rendered)

        return "\n".join(parts)
    
    def _merge_paragraphs(self, blocks: list[Block]) -> list[Block]:
        """
        Merge consecutive TEXT blocks into single paragraphs.
        Keeps headers, tables, figures separate.
        """
        if not blocks:
            return blocks
        
        merged = []
        current_para_lines = []
        current_para_block = None
        
        for block in blocks:
            # Don't merge special blocks
            if block.block_type in (BlockType.HEADER, BlockType.TABLE, BlockType.FIGURE, 
                                   BlockType.FOOTNOTE, BlockType.FOOTER, BlockType.EQUATION):
                # Flush accumulated paragraph
                if current_para_lines and current_para_block:
                    para_block = Block(
                        block_id=current_para_block.block_id,
                        bbox=current_para_block.bbox,
                        block_type=BlockType.TEXT,
                        lines=current_para_lines,
                        direction=current_para_block.direction,
                        language=current_para_block.language,
                    )
                    merged.append(para_block)
                    current_para_lines = []
                    current_para_block = None
                
                merged.append(block)
                continue
            
            # TEXT blocks - accumulate for merging
            if block.block_type == BlockType.TEXT:
                if not current_para_block:
                    current_para_block = block
                current_para_lines.extend(block.lines)
            else:
                # Other block types, flush and add separately
                if current_para_lines and current_para_block:
                    para_block = Block(
                        block_id=current_para_block.block_id,
                        bbox=current_para_block.bbox,
                        block_type=BlockType.TEXT,
                        lines=current_para_lines,
                        direction=current_para_block.direction,
                        language=current_para_block.language,
                    )
                    merged.append(para_block)
                    current_para_lines = []
                    current_para_block = None
                merged.append(block)
        
        # Flush remaining
        if current_para_lines and current_para_block:
            para_block = Block(
                block_id=current_para_block.block_id,
                bbox=current_para_block.bbox,
                block_type=BlockType.TEXT,
                lines=current_para_lines,
                direction=current_para_block.direction,
                language=current_para_block.language,
            )
            merged.append(para_block)
        
        return merged

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
        """
        Join lines intelligently with proper spacing and bidi wrapping.
        For TEXT blocks, merge lines into flowing paragraphs.
        For other blocks, preserve line breaks.
        """
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
        
        # For TEXT blocks, join with spaces (flowing paragraph)
        # For others (headers, footnotes), keep line breaks
        if block.block_type == BlockType.TEXT:
            return " ".join(line_parts)
        else:
            return "<br>\n    ".join(line_parts)


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

        # Detect table direction from cell bounding boxes.
        # For RTL tables, reverse column order so the visual layout
        # matches the original document when rendered in markdown.
        table_dir = table._detect_table_direction()
        col_order = list(range(max_col))
        if table_dir == "rtl":
            col_order = list(reversed(col_order))

        lines = []
        for r in range(max_row):
            cols = [grid.get((r, c), "") for c in col_order]
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
