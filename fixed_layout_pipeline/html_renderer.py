"""
Fixed-Layout HTML Renderer — pixel-accurate HTML overlay.

This is the core of the "custom fixed-layout HTML overlay" architecture:
- Page scan image as the background (all visual fidelity comes from this)
- Invisible absolutely-positioned text spans as an overlay
  (enabling text selection, search, copy-paste, and accessibility)

From the reference document:
  "A minimal but production-friendly approach uses:
   an <img> (or CSS background) for the raster page, and
   an overlay <div> containing absolutely positioned spans."

The rendered HTML is deterministic — regenerating from the same
canonical JSON always produces the same HTML.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Optional

from .config import RendererConfig
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


class FixedLayoutRenderer:
    """
    Render a CanonicalDocument as fixed-layout HTML.

    Each page is rendered as:
    ┌──────────────────────────────┐
    │  <div class="page">         │
    │    <img src="page.webp"/>   │  ← visual fidelity
    │    <div class="text-layer"> │
    │      <span>النص هنا</span>  │  ← invisible, selectable text
    │      <span>العربي</span>    │
    │    </div>                   │
    │  </div>                     │
    └──────────────────────────────┘
    """

    def __init__(self, config: Optional[RendererConfig] = None):
        self.config = config or RendererConfig()

    def render_document(self, doc: CanonicalDocument) -> str:
        """Render the full document to HTML."""
        pages_html = []
        for page in doc.pages:
            pages_html.append(self.render_page(page))

        return self._wrap_document(
            pages_html="\n".join(pages_html),
            doc=doc,
        )

    def render_page(self, page: Page) -> str:
        """Render a single page as a fixed-layout overlay."""
        w = page.image.width_px
        h = page.image.height_px

        if w == 0 or h == 0:
            logger.warning(f"Page {page.page_index}: no dimensions, skipping")
            return ""

        scale = self.config.scale
        scaled_w = int(w * scale)
        scaled_h = int(h * scale)

        # Page direction
        page_dir = "rtl" if page.principal_direction == Direction.RTL else "ltr"

        # Build overlay spans
        overlay_html = self._render_overlay(page, scale)

        # Build table overlays (rendered as HTML tables at exact positions)
        table_html = self._render_table_overlays(page, scale)

        return f'''
    <div class="page" id="page-{page.page_index}"
         style="position:relative; width:{scaled_w}px; height:{scaled_h}px; margin:20px auto; box-shadow:0 2px 8px rgba(0,0,0,0.3);"
         dir="{page_dir}">
      <!-- Page image: all visual fidelity comes from this -->
      <img src="{page.image.uri}"
           alt="Page {page.page_index + 1}"
           style="position:absolute; inset:0; width:100%; height:100%;"
           loading="lazy" />

      <!-- Text overlay: invisible but selectable -->
      <div class="text-layer" style="position:absolute; inset:0; z-index:1;">
{overlay_html}
      </div>

      <!-- Table overlays -->
{table_html}

      <!-- Page number indicator -->
      <div class="page-number" style="position:absolute; bottom:4px; left:50%; transform:translateX(-50%); font-size:11px; color:#888; z-index:2;">
        {page.page_index + 1}
      </div>
    </div>'''

    def _render_overlay(self, page: Page, scale: float) -> str:
        """Render text overlay spans for all blocks/lines/tokens."""
        spans = []

        # Get blocks in reading order
        ordered_blocks = page.blocks_in_reading_order()

        for block in ordered_blocks:
            if block.block_type == BlockType.TABLE:
                # Tables are rendered separately
                continue

            if block.lines:
                for line in block.lines:
                    if line.tokens:
                        # Word-level overlay
                        for token in line.tokens:
                            spans.append(self._render_token_span(token, block, scale))
                    else:
                        # Line-level overlay (fallback)
                        spans.append(self._render_line_span(line, block, scale))
            else:
                # Block-level overlay (when no lines are available)
                spans.append(self._render_block_span(block, scale))

        return "\n".join(spans)

    def _render_token_span(self, token: Token, block: Block, scale: float) -> str:
        """Render a single word/token as an absolutely positioned span."""
        bbox = token.bbox
        text = html.escape(token.text)
        direction = token.direction or block.direction or Direction.RTL
        dir_attr = "rtl" if direction == Direction.RTL else "ltr"

        x = bbox.x0 * scale
        y = bbox.y0 * scale
        w = bbox.width * scale
        h = bbox.height * scale

        # Font size: approximate from bbox height
        font_size = max(8, h * 0.85)

        # Opacity: 0 = invisible (production), >0 = debug
        opacity = self.config.text_opacity

        # Debug: show bounding boxes
        debug_border = ""
        if self.config.debug_boxes:
            confidence = token.confidence
            if confidence >= 0.9:
                border_color = "rgba(0,200,0,0.4)"
            elif confidence >= 0.7:
                border_color = "rgba(255,165,0,0.4)"
            else:
                border_color = "rgba(255,0,0,0.4)"
            debug_border = f"border:1px solid {border_color}; background:{border_color.replace('0.4', '0.1')};"
            opacity = max(opacity, 0.6)  # Make text visible in debug

        # Font stack based on detected language
        if direction == Direction.RTL:
            font_family = self.config.arabic_font_stack
        else:
            font_family = self.config.latin_font_stack

        return (
            f'        <span class="tok" dir="{dir_attr}" '
            f'data-confidence="{token.confidence:.2f}" '
            f'data-token-id="{token.token_id}" '
            f'style="position:absolute; '
            f'left:{x:.1f}px; top:{y:.1f}px; '
            f'width:{w:.1f}px; height:{h:.1f}px; '
            f'font-size:{font_size:.1f}px; line-height:{h:.1f}px; '
            f'font-family:{font_family}; '
            f'color:transparent; '
            f'{debug_border}'
            f'white-space:nowrap;">'
            f'{text}</span>'
        )

    def _render_line_span(self, line: Line, block: Block, scale: float) -> str:
        """Render a full line as an overlay span (fallback when no tokens)."""
        bbox = line.bbox
        text = html.escape(line.text)
        direction = line.direction or block.direction or Direction.RTL
        dir_attr = "rtl" if direction == Direction.RTL else "ltr"

        x = bbox.x0 * scale
        y = bbox.y0 * scale
        w = bbox.width * scale
        h = bbox.height * scale
        font_size = max(8, h * 0.85)
        opacity = self.config.text_opacity

        font_family = (
            self.config.arabic_font_stack
            if direction == Direction.RTL
            else self.config.latin_font_stack
        )

        debug_border = ""
        if self.config.debug_boxes:
            debug_border = "border:1px solid rgba(0,0,255,0.3);"
            opacity = max(opacity, 0.6)

        return (
            f'        <span class="line" dir="{dir_attr}" '
            f'data-line-id="{line.line_id}" '
            f'data-confidence="{line.confidence:.2f}" '
            f'style="position:absolute; '
            f'left:{x:.1f}px; top:{y:.1f}px; '
            f'width:{w:.1f}px; height:{h:.1f}px; '
            f'font-size:{font_size:.1f}px; line-height:{h:.1f}px; '
            f'font-family:{font_family}; '
            f'color:transparent; '
            f'{debug_border}'
            f'white-space:nowrap;">'
            f'{text}</span>'
        )

    def _render_block_span(self, block: Block, scale: float) -> str:
        """Render an entire block as one overlay span."""
        bbox = block.bbox
        text = html.escape(block.full_text())
        direction = block.direction or Direction.RTL
        dir_attr = "rtl" if direction == Direction.RTL else "ltr"

        x = bbox.x0 * scale
        y = bbox.y0 * scale
        w = bbox.width * scale
        h = bbox.height * scale
        font_size = max(8, min(h * 0.3, 24))
        opacity = self.config.text_opacity

        debug_border = ""
        if self.config.debug_boxes:
            debug_border = "border:2px solid rgba(128,0,128,0.4);"
            opacity = max(opacity, 0.6)

        return (
            f'        <span class="block" dir="{dir_attr}" '
            f'data-block-id="{block.block_id}" '
            f'style="position:absolute; '
            f'left:{x:.1f}px; top:{y:.1f}px; '
            f'width:{w:.1f}px; height:{h:.1f}px; '
            f'font-size:{font_size:.1f}px; '
            f'color:transparent; '
            f'{debug_border}'
            f'">'
            f'{text}</span>'
        )

    def _render_table_overlays(self, page: Page, scale: float) -> str:
        """Render tables as positioned HTML <table> elements over the page image."""
        tables_html = []

        for table in page.tables:
            bbox = table.bbox
            x = bbox.x0 * scale
            y = bbox.y0 * scale
            w = bbox.width * scale
            h = bbox.height * scale

            # Render the table HTML
            table_inner = table.to_html_table()

            opacity = self.config.text_opacity
            debug_border = ""
            if self.config.debug_boxes:
                debug_border = "border:2px solid rgba(0,128,255,0.5);"
                opacity = max(opacity, 0.7)

            tables_html.append(
                f'      <div class="table-overlay" '
                f'data-table-id="{table.table_id}" '
                f'style="position:absolute; '
                f'left:{x:.1f}px; top:{y:.1f}px; '
                f'width:{w:.1f}px; height:{h:.1f}px; '
                f'z-index:2; opacity:{opacity}; '
                f'{debug_border}'
                f'">\n'
                f'        {table_inner}\n'
                f'      </div>'
            )

        return "\n".join(tables_html)

    def _wrap_document(self, pages_html: str, doc: CanonicalDocument) -> str:
        """Wrap all pages in a complete HTML document."""
        title = html.escape(doc.title or doc.source.filename or "Document")
        lang = doc.languages[0] if doc.languages else "ar"
        direction = "rtl" if doc.principal_direction == Direction.RTL else "ltr"

        mathjax_script = ""
        if self.config.enable_mathjax:
            mathjax_script = '''
    <script>
      MathJax = {
        tex: { inlineMath: [['\\\\(', '\\\\)'], ['$', '$']] },
        startup: { typeset: false }
      };
    </script>
    <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" async></script>'''

        return f'''<!DOCTYPE html>
<html lang="{lang}" dir="{direction}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  {mathjax_script}
  <style>
    /* ─── Reset & Base ─────────────────────────────────────── */
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 20px;
      background: #525659;
      font-family: {self.config.arabic_font_stack};
      display: flex;
      flex-direction: column;
      align-items: center;
    }}

    /* ─── Page Container ──────────────────────────────────── */
    .page {{
      background: white;
      overflow: hidden;
      position: relative;
    }}
    .page img {{
      display: block;
      user-select: none;
      pointer-events: none;
    }}

    /* ─── Text Layer ──────────────────────────────────────── */
    .text-layer {{
      position: absolute;
      inset: 0;
      /* Text is invisible but selectable */
    }}
    .text-layer span {{
      cursor: text;
      color: transparent;
    }}
    /* Selection highlight */
    .text-layer span::selection {{
      background: rgba(0, 120, 215, 0.35);
      color: transparent;
    }}
    .text-layer span::-moz-selection {{
      background: rgba(0, 120, 215, 0.35);
      color: transparent;
    }}

    /* ─── Table Overlay ───────────────────────────────────── */
    .table-overlay table {{
      width: 100%;
      height: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }}
    .table-overlay td,
    .table-overlay th {{
      color: transparent;
      overflow: hidden;
      padding: 1px;
      cursor: text;
    }}
    .table-overlay td::selection,
    .table-overlay th::selection {{
      background: rgba(0, 120, 215, 0.35);
    }}

    /* ─── Debug Mode ──────────────────────────────────────── */
    .debug-info {{
      position: fixed;
      top: 10px;
      right: 10px;
      background: rgba(0,0,0,0.8);
      color: #0f0;
      padding: 10px;
      border-radius: 5px;
      font-family: monospace;
      font-size: 12px;
      z-index: 1000;
      max-width: 350px;
    }}

    /* ─── Page number ─────────────────────────────────────── */
    .page-number {{
      pointer-events: none;
      user-select: none;
    }}

    /* ─── Toolbar ─────────────────────────────────────────── */
    .toolbar {{
      position: fixed;
      top: 10px;
      left: 50%;
      transform: translateX(-50%);
      background: rgba(0,0,0,0.85);
      color: white;
      padding: 8px 16px;
      border-radius: 8px;
      z-index: 1000;
      display: flex;
      gap: 12px;
      align-items: center;
      font-family: sans-serif;
      font-size: 13px;
    }}
    .toolbar button {{
      background: #444;
      color: white;
      border: none;
      padding: 4px 10px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 12px;
    }}
    .toolbar button:hover {{ background: #666; }}
    .toolbar button.active {{ background: #0078d7; }}

    /* ─── Print ───────────────────────────────────────────── */
    @media print {{
      body {{ background: white; padding: 0; }}
      .page {{ box-shadow: none; margin: 0; page-break-after: always; }}
      .toolbar, .debug-info, .page-number {{ display: none; }}
    }}
  </style>
</head>
<body>
  <!-- Toolbar -->
  <div class="toolbar">
    <span>{title}</span>
    <span>|</span>
    <span>{doc.page_count()} pages</span>
    <button onclick="toggleDebug()" id="btn-debug">Debug</button>
    <button onclick="toggleTextVis()" id="btn-text">Show Text</button>
  </div>

  <!-- Pages -->
{pages_html}

  <script>
    // ─── Toggle debug bounding boxes ─────────────────────
    let debugMode = {'true' if self.config.debug_boxes else 'false'};
    function toggleDebug() {{
      debugMode = !debugMode;
      document.querySelectorAll('.tok, .line, .block').forEach(el => {{
        if (debugMode) {{
          el.style.border = '1px solid rgba(255,0,0,0.4)';
          el.style.color = 'red';
        }} else {{
          el.style.border = 'none';
          el.style.color = 'transparent';
        }}
      }});
      document.getElementById('btn-debug').classList.toggle('active', debugMode);
      if (debugMode) fitVisibleSpans();
    }}

    // ─── Toggle text visibility ──────────────────────────
    let textVisible = false;
    function toggleTextVis() {{
      textVisible = !textVisible;
      document.querySelectorAll('.text-layer span').forEach(el => {{
        el.style.color = textVisible ? '#333' : 'transparent';
        el.style.background = textVisible ? 'rgba(255,255,200,0.7)' : 'none';
      }});
      document.getElementById('btn-text').classList.toggle('active', textVisible);
      if (textVisible) fitVisibleSpans();
    }}

    // ─── Confidence tooltip on hover ─────────────────────
    document.querySelectorAll('[data-confidence]').forEach(el => {{
      el.title = `Confidence: ${{el.dataset.confidence}}`;
    }});

    // ─── Text fitting (only when text is made visible) ───
    // Uses an off-screen measurement span for accurate Arabic text width.
    // Called when Show Text or Debug is toggled on.
    function fitVisibleSpans() {{
      const m = document.createElement('span');
      m.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap;left:-9999px;top:-9999px;';
      document.body.appendChild(m);
      document.querySelectorAll('.tok, .line').forEach(el => {{
        const boxW = parseFloat(el.style.width);
        if (!boxW || boxW <= 0) return;
        m.style.fontFamily = el.style.fontFamily;
        m.style.fontSize = el.style.fontSize;
        m.style.fontWeight = getComputedStyle(el).fontWeight;
        m.style.lineHeight = el.style.lineHeight;
        m.textContent = el.textContent;
        const naturalW = m.offsetWidth;
        if (naturalW > boxW * 1.02) {{
          const s = boxW / naturalW;
          const dir = el.getAttribute('dir');
          el.style.transformOrigin = (dir === 'rtl') ? 'right center' : 'left center';
          el.style.transform = `scaleX(${{s.toFixed(4)}})`;
        }} else {{
          el.style.transform = '';
        }}
      }});
      document.body.removeChild(m);
    }}
  </script>
</body>
</html>'''

    def render_to_file(
        self,
        doc: CanonicalDocument,
        output_path: Path,
    ) -> Path:
        """Render document and write to file."""
        html_content = self.render_document(doc)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        logger.info(f"Written HTML to {output_path}")
        return output_path
