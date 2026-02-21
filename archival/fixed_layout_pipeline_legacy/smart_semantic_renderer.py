"""
Smart Semantic Renderer — clean, accessible HTML from CanonicalDocument.

Produces a properly structured HTML5 document with:
  - Real heading hierarchy (<h1>/<h2>/<h3>) informed by DocumentUnderstanding
  - Semantic elements: <article>, <section>, <figure>, <aside>, <table>
  - Actual <table> structure via Table.to_html_table()
  - Figures embedded as base64 data URIs
  - MathJax equations ($$...$$)
  - Full BiDi support (RTL Arabic / LTR Latin per block and token)
  - Accessible ARIA landmarks and lang attributes
  - Print-ready CSS, responsive layout

Contrast with html_renderer.py (pixel-positioned invisible text overlay):
  - This renderer sacrifices pixel-fidelity for usability, copy-paste, and accessibility.

Usage:
    from fixed_layout_pipeline.document_understander import DocumentUnderstander
    from fixed_layout_pipeline.smart_semantic_renderer import SmartSemanticRenderer
    from fixed_layout_pipeline.schema import CanonicalDocument

    doc = CanonicalDocument.load(Path("doc_canonical.json"))
    understanding = DocumentUnderstander().understand(doc)
    renderer = SmartSemanticRenderer()
    html = renderer.render(doc, understanding, canonical_json_path=Path("doc_canonical.json"))
    Path("doc_understood.html").write_text(html, encoding="utf-8")
"""

from __future__ import annotations

import base64
import html as _html
import logging
import re
import unicodedata
from pathlib import Path
from typing import Optional

from .document_understander import DocumentUnderstanding
from .schema import Block, BlockType, CanonicalDocument, Direction, Line, Page

logger = logging.getLogger(__name__)

# Bidirectional character categories considered "strong"
_STRONG_BIDI: frozenset[str] = frozenset({"L", "R", "AL"})

# Font stacks
_FONT_ARABIC = (
    "'Amiri', 'Noto Naskh Arabic', 'Traditional Arabic', "
    "'Simplified Arabic', 'Tahoma', serif"
)
_FONT_LATIN = (
    "'Noto Serif', 'Times New Roman', 'Georgia', "
    "'Amiri', 'Noto Naskh Arabic', serif"
)

# BlockTypes that are always skipped in semantic output
_SKIP_TYPES: frozenset[BlockType] = frozenset(
    {
        BlockType.PAGE_NUMBER,
        BlockType.FOOTER,
        BlockType.STAMP,
        BlockType.SIGNATURE,
        BlockType.BARCODE,
        BlockType.SELECTION_MARK,
        BlockType.UNKNOWN,
    }
)

# BlockTypes that prevent merging of adjacent TEXT blocks
_NO_MERGE_TYPES: frozenset[BlockType] = frozenset(
    {
        BlockType.HEADER,
        BlockType.TABLE,
        BlockType.FIGURE,
        BlockType.FOOTNOTE,
        BlockType.EQUATION,
        BlockType.KEY_VALUE,
    }
)


# ── Main renderer class ───────────────────────────────────────────────────────

class SmartSemanticRenderer:
    """
    Renders a CanonicalDocument as clean, accessible semantic HTML.

    Args:
        embed_figures: If True, load figure image files and embed them as
                       base64 data URIs.  If False, use figure_uri as-is.
    """

    def __init__(self, embed_figures: bool = True) -> None:
        self.embed_figures = embed_figures

    # ── Public API ────────────────────────────────────────────────────────────

    def render(
        self,
        doc: CanonicalDocument,
        understanding: DocumentUnderstanding,
        canonical_json_path: Optional[Path] = None,
    ) -> str:
        """
        Render the full document to an HTML5 string.

        Args:
            doc: The canonical document to render.
            understanding: From DocumentUnderstander.understand(doc).
            canonical_json_path: Used to resolve relative figure_uri paths.
                                 Pass None to use uris as-is.

        Returns:
            Complete, self-contained HTML5 string.
        """
        self._understanding = understanding
        self._doc_dir: Optional[Path] = (
            canonical_json_path.parent if canonical_json_path else None
        )

        body_sections: list[str] = []
        for page in doc.pages:
            rendered = self._render_page(page)
            if rendered:
                body_sections.append(rendered)

        body = "\n\n".join(body_sections)

        title = _html.escape(understanding.document_title or "Document")
        lang = understanding.primary_language or "ar"
        doc_dir = "rtl" if doc.principal_direction == Direction.RTL else "ltr"
        primary_font = _FONT_ARABIC if doc_dir == "rtl" else _FONT_LATIN

        return _build_html_shell(title, lang, doc_dir, primary_font, body)

    # ── Page rendering ────────────────────────────────────────────────────────

    def _render_page(self, page: Page) -> str:
        """Each page becomes a <section> with a subtle separator between pages."""
        page_dir = "rtl" if page.principal_direction == Direction.RTL else "ltr"
        page_num = page.page_index + 1

        # Page label and break (not before the first page)
        separator = ""
        if page.page_index > 0:
            if page_dir == "rtl":
                label_text = f"صفحة {_arabic_numeral(page_num)}"
            else:
                label_text = f"Page {page_num}"
            separator = (
                f'  <hr class="page-break" aria-hidden="true">\n'
                f'  <p class="page-label" aria-hidden="true">{label_text}</p>\n'
            )

        blocks = page.blocks_in_reading_order()
        merged = _merge_consecutive_text(blocks)

        inner_parts: list[str] = []
        for block in merged:
            rendered = self._render_block(block)
            if rendered:
                inner_parts.append(rendered)

        if not inner_parts:
            return ""

        inner = "\n".join(inner_parts)
        aria_label = f"Page {page_num}"

        return (
            f'{separator}'
            f'  <section aria-label="{aria_label}" dir="{page_dir}">\n'
            f'{inner}\n'
            f'  </section>'
        )

    # ── Block dispatch ────────────────────────────────────────────────────────

    def _render_block(self, block: Block) -> str:
        """Dispatch to per-type renderer. Returns empty string to skip."""
        # Check for Gemini override first
        override = self._understanding.block_type_overrides.get(block.block_id)
        if override == "decorative":
            return ""
        if override == "quran":
            return self._render_quran(block)

        bt = block.block_type

        if bt in _SKIP_TYPES:
            return ""
        if bt == BlockType.HEADER:
            return self._render_header(block)
        if bt == BlockType.TEXT:
            return self._render_text(block)
        if bt == BlockType.TABLE:
            return self._render_table(block)
        if bt == BlockType.FIGURE:
            return self._render_figure(block)
        if bt == BlockType.EQUATION:
            return self._render_equation(block)
        if bt == BlockType.FOOTNOTE:
            return self._render_footnote(block)
        if bt == BlockType.CAPTION:
            return self._render_caption(block)
        if bt == BlockType.HANDWRITING:
            return self._render_handwriting(block)
        if bt == BlockType.KEY_VALUE:
            return self._render_key_value(block)
        # Default: render as paragraph
        return self._render_text(block)

    # ── Per-type renderers ────────────────────────────────────────────────────

    def _render_header(self, block: Block) -> str:
        info = self._understanding.sections.get(block.block_id)
        level = info.heading_level if info else 2
        tag = f"h{level}"
        dir_attr = _dir(block.direction)
        lang = block.language or "ar"
        text = _block_text_bidi(block)
        if not text.strip():
            return ""
        anchor_id = f"sec-{block.block_id}"
        return f'    <{tag} id="{anchor_id}" dir="{dir_attr}" lang="{lang}">{text}</{tag}>'

    def _render_text(self, block: Block) -> str:
        dir_attr = _dir(block.direction)
        lang = block.language or "ar"
        text = _block_text_bidi(block)
        if not text.strip():
            return ""
        return f'    <p dir="{dir_attr}" lang="{lang}">{text}</p>'

    def _render_table(self, block: Block) -> str:
        if not block.table:
            return ""
        table_html = block.table.to_html_table()
        if not table_html:
            return ""
        # Inject caption if available
        if block.figure_caption:
            caption_text = _html.escape(block.figure_caption)
            table_html = re.sub(
                r"(<table[^>]*>)",
                rf"\1\n    <caption>{caption_text}</caption>",
                table_html,
                count=1,
            )
        return (
            f'    <div class="table-wrapper" role="region" aria-label="Table">\n'
            f"      {table_html}\n"
            f"    </div>"
        )

    def _render_figure(self, block: Block) -> str:
        caption = _html.escape(block.figure_caption or "")
        uri = block.figure_uri or ""

        if self.embed_figures and uri and not uri.startswith("data:"):
            uri = self._embed_image(uri)

        if uri:
            img_html = f'<img src="{uri}" alt="{caption}" loading="lazy">'
        else:
            img_html = '<span class="figure-missing">[Figure not available]</span>'

        cap_html = f"\n      <figcaption>{caption}</figcaption>" if caption else ""
        return f"    <figure>\n      {img_html}{cap_html}\n    </figure>"

    def _render_equation(self, block: Block) -> str:
        if block.equation_latex:
            # MathJax display math — use $$ delimiters
            latex = block.equation_latex
            return (
                f'    <div class="equation" role="math" aria-label="Equation">'
                f"$${latex}$$"
                f"</div>"
            )
        # Fallback: render raw text in a monospace block
        text = _html.escape(block.full_text())
        if not text.strip():
            return ""
        return f'    <pre class="equation-raw" role="math">{text}</pre>'

    def _render_footnote(self, block: Block) -> str:
        dir_attr = _dir(block.direction)
        lang = block.language or "ar"
        text = _block_text_bidi(block)
        if not text.strip():
            return ""
        return f'    <aside class="footnote" dir="{dir_attr}" lang="{lang}">{text}</aside>'

    def _render_caption(self, block: Block) -> str:
        dir_attr = _dir(block.direction)
        text = _block_text_bidi(block)
        if not text.strip():
            return ""
        return f'    <p class="caption" dir="{dir_attr}">{text}</p>'

    def _render_handwriting(self, block: Block) -> str:
        dir_attr = _dir(block.direction)
        lang = block.language or "ar"
        text = _block_text_bidi(block)
        if not text.strip():
            return ""
        return f'    <p class="handwriting" dir="{dir_attr}" lang="{lang}">{text}</p>'

    def _render_key_value(self, block: Block) -> str:
        dir_attr = _dir(block.direction)
        lines = block.lines
        if not lines:
            return ""
        items: list[str] = []
        # Even line count: alternate key/value
        if len(lines) >= 2 and len(lines) % 2 == 0:
            for i in range(0, len(lines), 2):
                key = _html.escape(lines[i].compute_text() if lines[i].tokens else lines[i].text)
                val = _html.escape(lines[i + 1].compute_text() if lines[i + 1].tokens else lines[i + 1].text)
                items.append(f"      <dt>{key}</dt>\n      <dd>{val}</dd>")
        else:
            for ln in lines:
                key = _html.escape(ln.compute_text() if ln.tokens else ln.text)
                items.append(f"      <dt>{key}</dt>")
        inner = "\n".join(items)
        return f'    <dl dir="{dir_attr}">\n{inner}\n    </dl>'

    def _render_quran(self, block: Block) -> str:
        text = _block_text_bidi(block)
        if not text.strip():
            return ""
        return f'    <blockquote class="quran" dir="rtl" lang="ar">{text}</blockquote>'

    # ── Figure embedding ──────────────────────────────────────────────────────

    def _embed_image(self, uri: str) -> str:
        """Load an image file and return a base64 data URI."""
        fig_path = Path(uri)
        if self._doc_dir and not fig_path.is_absolute():
            fig_path = self._doc_dir / uri
        if not fig_path.exists():
            logger.warning("Figure file not found: %s", fig_path)
            return uri  # return as-is (will show as broken image)
        try:
            suffix = fig_path.suffix.lower()
            mime = {
                ".webp": "image/webp",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
            }.get(suffix, "image/png")
            data = base64.b64encode(fig_path.read_bytes()).decode("ascii")
            return f"data:{mime};base64,{data}"
        except Exception as exc:
            logger.warning("Failed to embed figure %s: %s", fig_path, exc)
            return uri


# ── BiDi helpers ─────────────────────────────────────────────────────────────

def _dir(direction: Direction) -> str:
    return "rtl" if direction == Direction.RTL else "ltr"


def _has_strong_bidi(text: str) -> bool:
    """Return True if text contains at least one strongly directional character."""
    return any(unicodedata.bidirectional(ch) in _STRONG_BIDI for ch in text)


def _block_text_bidi(block: Block) -> str:
    """
    Join block lines into HTML text with per-token BiDi span wrapping.

    - TEXT/HANDWRITING blocks: lines joined with spaces (flowing paragraph).
    - All others: lines joined with <br>.
    - Tokens whose direction differs from the block direction are wrapped in
      <span dir="..."> to let the browser apply the correct BiDi algorithm.
    - Arabic negative numbers: the leading '-' is moved to the end so it
      appears correctly on the right side in RTL context.
    """
    block_dir = block.direction or Direction.RTL
    line_parts: list[str] = []

    for line in block.lines:
        if line.tokens:
            tok_parts: list[str] = []
            for tok in line.tokens:
                t = tok.text
                tok_dir = tok.direction or block_dir

                # Fix Arabic negative numbers: '-5' → '5-'
                if tok_dir == Direction.RTL and t.startswith("-") and len(t) > 1:
                    t = t[1:] + "-"

                t_escaped = _html.escape(t)

                if tok_dir != block_dir:
                    d = "ltr" if tok_dir == Direction.LTR else "rtl"
                    tok_parts.append(f'<span dir="{d}">{t_escaped}</span>')
                else:
                    tok_parts.append(t_escaped)

            line_parts.append(" ".join(tok_parts))
        else:
            line_parts.append(_html.escape(line.text))

    flow_types = {BlockType.TEXT, BlockType.HANDWRITING}
    if block.block_type in flow_types:
        return " ".join(line_parts)
    return "<br>\n      ".join(line_parts)


# ── Paragraph merging ─────────────────────────────────────────────────────────

def _merge_consecutive_text(blocks: list[Block]) -> list[Block]:
    """
    Merge consecutive TEXT blocks into a single Block so they render as
    one <p> element rather than dozens of single-sentence paragraphs.

    Non-text blocks (headers, tables, figures, etc.) are kept as-is and
    interrupt any active accumulation.
    """
    if not blocks:
        return []

    merged: list[Block] = []
    accum_lines: list = []
    accum_block: Optional[Block] = None

    def flush() -> None:
        nonlocal accum_lines, accum_block
        if accum_lines and accum_block:
            # Create a synthetic merged block (shallow copy with combined lines)
            new_block = accum_block.model_copy(update={"lines": list(accum_lines)})
            merged.append(new_block)
        accum_lines = []
        accum_block = None

    for block in blocks:
        if block.block_type in _SKIP_TYPES:
            flush()
            continue  # skip entirely
        if block.block_type in _NO_MERGE_TYPES:
            flush()
            merged.append(block)
        elif block.block_type == BlockType.TEXT:
            if accum_block is None:
                accum_block = block
            accum_lines.extend(block.lines)
        else:
            # Other types (CAPTION, etc.) — flush then add
            flush()
            merged.append(block)

    flush()
    return merged


# ── Arabic numeral helper ─────────────────────────────────────────────────────

_AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"


def _arabic_numeral(n: int) -> str:
    """Convert an integer to Eastern Arabic numerals."""
    return "".join(_AR_DIGITS[int(d)] for d in str(n))


# ── HTML shell ────────────────────────────────────────────────────────────────

def _build_html_shell(
    title: str,
    lang: str,
    direction: str,
    primary_font: str,
    body: str,
) -> str:
    """Build the complete HTML5 document string."""

    return f"""<!DOCTYPE html>
<html lang="{lang}" dir="{direction}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>

  <!-- Fonts: Amiri for Arabic, Noto Serif for Latin -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Amiri:ital,wght@0,400;0,700;1,400;1,700&family=Noto+Naskh+Arabic:wght@400;700&family=Noto+Serif:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">

  <!-- MathJax for equation rendering -->
  <script>
    MathJax = {{
      tex: {{
        inlineMath: [['\\\\(', '\\\\)']],
        displayMath: [['$$', '$$']],
        processEscapes: true
      }},
      options: {{ skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre'] }}
    }};
  </script>
  <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" async></script>

  <style>
    /* ── Variables ─────────────────────────────────────────── */
    :root {{
      --font-arabic:  {_FONT_ARABIC};
      --font-latin:   {_FONT_LATIN};
      --font-primary: {primary_font};
      --color-text:       #1a1a1a;
      --color-heading:    #111111;
      --color-muted:      #555555;
      --color-border:     #dddddd;
      --color-bg-alt:     #f7f7f5;
      --color-bg-table-h: #e8e8e6;
      --max-width: 820px;
      --line-height: 1.95;
    }}

    /* ── Reset ─────────────────────────────────────────────── */
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    /* ── Base ──────────────────────────────────────────────── */
    html {{ font-size: 18px; scroll-behavior: smooth; }}
    body {{
      font-family: var(--font-primary);
      line-height: var(--line-height);
      color: var(--color-text);
      background: #faf9f7;
      padding: 0 1.25rem 5rem;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
      font-variant-ligatures: contextual;
    }}

    /* ── Content width ─────────────────────────────────────── */
    header[role="banner"],
    main[role="main"],
    footer[role="contentinfo"] {{
      max-width: var(--max-width);
      margin-inline: auto;
    }}

    /* ── Document header ───────────────────────────────────── */
    header[role="banner"] {{
      padding-block: 3rem 2rem;
      border-bottom: 2px solid var(--color-border);
      margin-bottom: 2.5rem;
    }}
    header[role="banner"] h1 {{
      font-size: 2rem;
      font-weight: 700;
      color: var(--color-heading);
      line-height: 1.25;
    }}

    /* ── Sections (one per page) ───────────────────────────── */
    section {{
      margin-bottom: 0.25rem;
    }}

    /* ── Heading hierarchy ─────────────────────────────────── */
    h1, h2, h3 {{
      font-weight: 700;
      color: var(--color-heading);
      line-height: 1.3;
      margin-top: 2rem;
      margin-bottom: 0.75rem;
    }}
    h1 {{ font-size: 1.75rem; }}
    h2 {{
      font-size: 1.35rem;
      border-bottom: 1px solid var(--color-border);
      padding-bottom: 0.3rem;
    }}
    h3 {{ font-size: 1.1rem; color: #333; }}

    /* ── Paragraphs ────────────────────────────────────────── */
    p {{
      margin-bottom: 1rem;
      text-align: justify;
      text-justify: inter-word;
      orphans: 3;
      widows: 3;
    }}
    p[dir="rtl"]  {{ text-align: right; }}
    p[dir="ltr"]  {{ text-align: left; }}

    /* ── Tables ────────────────────────────────────────────── */
    .table-wrapper {{
      overflow-x: auto;
      margin-block: 1.5rem;
      border-radius: 4px;
      box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      font-size: 0.93rem;
      background: #fff;
    }}
    th, td {{
      border: 1px solid #bbb;
      padding: 7px 12px;
      vertical-align: top;
    }}
    th {{
      background: var(--color-bg-table-h);
      font-weight: 700;
    }}
    caption {{
      font-size: 0.9rem;
      color: var(--color-muted);
      caption-side: bottom;
      padding-block: 0.4rem;
      font-style: italic;
    }}

    /* ── Figures ───────────────────────────────────────────── */
    figure {{
      margin-block: 2rem;
      text-align: center;
      background: var(--color-bg-alt);
      padding: 1.25rem;
      border-radius: 6px;
      border: 1px solid var(--color-border);
    }}
    figure img {{
      max-width: 100%;
      height: auto;
      display: block;
      margin-inline: auto;
      border-radius: 3px;
    }}
    figcaption {{
      font-size: 0.9rem;
      color: var(--color-muted);
      margin-top: 0.8rem;
      font-style: italic;
    }}
    .figure-missing {{
      font-size: 0.9rem;
      color: var(--color-muted);
      font-style: italic;
    }}

    /* ── Equations ─────────────────────────────────────────── */
    .equation {{
      margin-block: 1.5rem;
      padding: 1rem;
      background: var(--color-bg-alt);
      border-radius: 4px;
      text-align: center;
      overflow-x: auto;
    }}
    .equation-raw {{
      font-size: 0.9rem;
      background: var(--color-bg-alt);
      padding: 1rem;
      border-radius: 4px;
      overflow-x: auto;
      direction: ltr;
      text-align: left;
    }}

    /* ── Quran verses ──────────────────────────────────────── */
    .quran {{
      margin-block: 1.5rem;
      margin-inline: 1.5rem;
      padding: 0.8rem 1.5rem;
      background: #fffef8;
      border-inline-end: 4px solid #c5a500;
      border-radius: 6px 0 0 6px;
      font-size: 1.08rem;
      color: #1a1a00;
      line-height: 2.2;
    }}

    /* ── Footnotes ─────────────────────────────────────────── */
    .footnote {{
      font-size: 0.88rem;
      color: var(--color-muted);
      background: var(--color-bg-alt);
      border-inline-start: 3px solid var(--color-border);
      padding: 0.6rem 1rem;
      margin-block: 1.25rem;
      border-radius: 0 4px 4px 0;
    }}

    /* ── Captions (standalone) ─────────────────────────────── */
    .caption {{
      font-size: 0.9rem;
      color: var(--color-muted);
      font-style: italic;
      text-align: center;
    }}

    /* ── Handwriting ───────────────────────────────────────── */
    .handwriting {{
      font-style: italic;
      color: #333;
      background: var(--color-bg-alt);
      padding: 0.5rem 1rem;
      border-radius: 4px;
    }}

    /* ── Key-value lists ───────────────────────────────────── */
    dl {{ margin-block: 1rem; }}
    dt {{ font-weight: 700; color: var(--color-heading); margin-top: 0.5rem; }}
    dd {{ margin-inline-start: 2rem; color: var(--color-muted); }}

    /* ── Page separators ───────────────────────────────────── */
    .page-break {{
      border: none;
      border-top: 1px dashed #ccc;
      margin-block: 2.5rem 1rem;
    }}
    .page-label {{
      font-size: 0.72rem;
      color: #aaa;
      text-align: center;
      letter-spacing: 2px;
      text-transform: uppercase;
      margin-bottom: 1.5rem;
    }}

    /* ── Print ─────────────────────────────────────────────── */
    @media print {{
      body {{ background: #fff; padding: 0; font-size: 11pt; }}
      .page-break {{ page-break-before: always; border: none; }}
      .no-print {{ display: none; }}
    }}

    /* ── Responsive ────────────────────────────────────────── */
    @media (max-width: 640px) {{
      html {{ font-size: 16px; }}
      h1   {{ font-size: 1.5rem; }}
      h2   {{ font-size: 1.2rem; }}
      body {{ padding: 0 0.75rem 3rem; }}
    }}
  </style>
</head>
<body>

  <header role="banner">
    <h1>{title}</h1>
  </header>

  <main role="main">
{body}
  </main>

  <footer role="contentinfo" class="no-print">
    <p style="font-size:0.78rem;color:#aaa;text-align:center;padding:2rem 0;">
      Generated by OCR Pipeline · Smart Semantic Renderer
    </p>
  </footer>

</body>
</html>"""
