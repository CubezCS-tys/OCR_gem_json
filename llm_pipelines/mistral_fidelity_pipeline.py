#!/usr/bin/env python3
"""
Mistral OCR fidelity-first pipeline.

Design goal:
- Keep OCR text/layout fidelity high by avoiding a second LLM transformation pass.
- Store canonical OCR JSON that mirrors Mistral OCR output plus light normalization.
- Render deterministic HTML from OCR markdown with MathJax support for equations.

Usage:
    python3 -m llm_pipelines.mistral_fidelity_pipeline input.pdf --output-dir outputs
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import json
import logging
import os
import pathlib
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

from dotenv import load_dotenv
from mistralai import Mistral

load_dotenv()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class MistralFidelityConfig:
    """Config for the fidelity-first OCR pipeline."""

    model: str = "mistral-ocr-latest"
    output_dir: str = "outputs"
    include_image_base64: bool = True
    inline_images_in_json: bool = False
    table_format: str = "html"  # "html" gives best table fidelity.
    bbox_annotation_format: Optional[str] = None
    document_annotation_format: Optional[str] = None
    save_json: bool = True
    save_markdown: bool = True
    save_html: bool = True
    save_images: bool = True
    max_retries: int = 3
    retry_delay: float = 2.0


class MistralFidelityPipeline:
    """
    OCR-only pipeline:
      PDF -> Mistral OCR -> canonical JSON + markdown + deterministic HTML
    """

    def __init__(self, config: Optional[MistralFidelityConfig] = None):
        self.config = config or MistralFidelityConfig()
        api_key = os.environ.get("MISTRAL_API_KEY")
        if not api_key:
            raise ValueError(
                "MISTRAL_API_KEY environment variable not set. "
                "Get your key at https://console.mistral.ai/"
            )
        self.client = Mistral(api_key=api_key)

    @staticmethod
    def _to_plain(value: Any) -> Any:
        """Recursively convert SDK objects into plain Python structures."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [MistralFidelityPipeline._to_plain(v) for v in value]
        if isinstance(value, dict):
            return {k: MistralFidelityPipeline._to_plain(v) for k, v in value.items()}

        for attr in ("model_dump", "dict"):
            fn = getattr(value, attr, None)
            if callable(fn):
                try:
                    dumped = fn()
                    if isinstance(dumped, dict):
                        return {
                            k: MistralFidelityPipeline._to_plain(v)
                            for k, v in dumped.items()
                        }
                except Exception:
                    pass

        if hasattr(value, "__dict__"):
            data = {}
            for k, v in vars(value).items():
                if k.startswith("_"):
                    continue
                data[k] = MistralFidelityPipeline._to_plain(v)
            return data
        return value

    @staticmethod
    def _extract_text_from_annotation(item: Any) -> str:
        """Best-effort extraction of visible text from header/footer/link objects."""
        if item is None:
            return ""
        if isinstance(item, str):
            return item
        if not isinstance(item, dict):
            item = MistralFidelityPipeline._to_plain(item)
            if not isinstance(item, dict):
                return str(item)
        for key in ("text", "content", "value", "label", "markdown"):
            if key in item and item[key]:
                return str(item[key])
        return ""

    @staticmethod
    def _contains_rtl(text: str, threshold: float = 0.30) -> bool:
        """Heuristic detection for RTL-heavy text (Arabic/Hebrew scripts)."""
        if not text:
            return False
        rtl = 0
        ltr = 0
        for ch in text:
            code = ord(ch)
            if (
                0x0590 <= code <= 0x05FF
                or 0x0600 <= code <= 0x06FF
                or 0x0750 <= code <= 0x077F
                or 0x08A0 <= code <= 0x08FF
                or 0xFB1D <= code <= 0xFDFF
                or 0xFE70 <= code <= 0xFEFF
            ):
                rtl += 1
            elif 0x0041 <= code <= 0x005A or 0x0061 <= code <= 0x007A:
                ltr += 1
        denom = rtl + ltr
        if denom == 0:
            return False
        return (rtl / denom) >= threshold

    @staticmethod
    def _direction_counts(text: str) -> tuple[int, int]:
        """Return (rtl_count, ltr_count) directional character counts."""
        rtl = 0
        ltr = 0
        for ch in text or "":
            code = ord(ch)
            if (
                0x0590 <= code <= 0x05FF
                or 0x0600 <= code <= 0x06FF
                or 0x0750 <= code <= 0x077F
                or 0x08A0 <= code <= 0x08FF
                or 0xFB1D <= code <= 0xFDFF
                or 0xFE70 <= code <= 0xFEFF
            ):
                rtl += 1
            elif 0x0041 <= code <= 0x005A or 0x0061 <= code <= 0x007A:
                ltr += 1
        return rtl, ltr

    def _detect_text_direction(self, text: str) -> str:
        """Detect dominant direction for a sentence/text span."""
        raw = text or ""
        # Ignore math payload when deciding prose direction.
        clean = re.sub(r"\$\$.*?\$\$", " ", raw, flags=re.DOTALL)
        clean = re.sub(r"(?<!\$)\$[^$\n]+\$(?!\$)", " ", clean)
        clean = re.sub(r"\\\((.+?)\\\)", " ", clean, flags=re.DOTALL)
        clean = re.sub(r"\\\[(.+?)\\\]", " ", clean, flags=re.DOTALL)
        clean = re.sub(r"\\[A-Za-z]+", " ", clean)

        rtl, ltr = self._direction_counts(clean)
        if rtl == 0 and ltr == 0:
            rtl, ltr = self._direction_counts(raw)
        if rtl == 0 and ltr == 0:
            return "auto"
        return "rtl" if rtl >= ltr else "ltr"

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into sentence-like units (Arabic + Latin punctuation)."""
        normalized = re.sub(r"\s+", " ", (text or "")).strip()
        if not normalized:
            return []
        parts = re.split(r"(?<=[\.\!\?؟؛:])\s+", normalized)
        return [p.strip() for p in parts if p and p.strip()]

    def _upload_pdf(self, pdf_path: pathlib.Path) -> str:
        """Upload PDF and return Mistral file_id."""
        for attempt in range(1, self.config.max_retries + 1):
            try:
                with open(pdf_path, "rb") as fh:
                    uploaded = self.client.files.upload(
                        file={"file_name": pdf_path.name, "content": fh},
                        purpose="ocr",
                    )
                logger.info("Uploaded PDF -> file_id=%s", uploaded.id)
                return uploaded.id
            except Exception as exc:
                logger.warning("Upload attempt %d failed: %s", attempt, exc)
                if attempt >= self.config.max_retries:
                    raise
                time.sleep(self.config.retry_delay * attempt)
        raise RuntimeError("Upload failed unexpectedly")

    def _run_ocr(self, file_id: str):
        """Call Mistral OCR with high-fidelity defaults."""
        req: dict[str, Any] = {
            "model": self.config.model,
            "document": {"file_id": file_id},
            "include_image_base64": self.config.include_image_base64,
        }
        if self.config.table_format:
            req["table_format"] = self.config.table_format
        if self.config.bbox_annotation_format:
            req["bbox_annotation_format"] = self.config.bbox_annotation_format
        if self.config.document_annotation_format:
            req["document_annotation_format"] = self.config.document_annotation_format

        for attempt in range(1, self.config.max_retries + 1):
            try:
                logger.info("Running OCR with model=%s (attempt %d)", self.config.model, attempt)
                return self.client.ocr.process(**req)
            except TypeError as exc:
                # Backward compatibility for older SDKs that don't expose new params.
                if any(k in req for k in ("table_format", "bbox_annotation_format", "document_annotation_format")):
                    logger.warning(
                        "SDK does not accept one or more advanced OCR params (%s). "
                        "Retrying with base arguments only.",
                        exc,
                    )
                    req.pop("table_format", None)
                    req.pop("bbox_annotation_format", None)
                    req.pop("document_annotation_format", None)
                    continue
                raise
            except Exception as exc:
                logger.warning("OCR attempt %d failed: %s", attempt, exc)
                if attempt >= self.config.max_retries:
                    raise
                time.sleep(self.config.retry_delay * attempt)
        raise RuntimeError("OCR failed unexpectedly")

    def _normalise(self, ocr_response: Any, source_name: str) -> dict[str, Any]:
        """Convert OCR response to stable canonical JSON."""
        pages = []
        rtl_pages = 0

        raw_pages = getattr(ocr_response, "pages", []) or []
        for idx, page in enumerate(raw_pages):
            page_index = int(getattr(page, "index", idx))
            markdown = getattr(page, "markdown", "") or ""
            direction = "rtl" if self._contains_rtl(markdown) else "ltr"
            if direction == "rtl":
                rtl_pages += 1

            dimensions = self._to_plain(getattr(page, "dimensions", None))
            headers = self._to_plain(getattr(page, "headers", [])) or []
            footers = self._to_plain(getattr(page, "footers", [])) or []
            links = self._to_plain(getattr(page, "hyperlinks", [])) or []
            tables = self._to_plain(getattr(page, "tables", [])) or []
            images = self._to_plain(getattr(page, "images", [])) or []

            if not self.config.inline_images_in_json:
                for img in images:
                    if isinstance(img, dict):
                        img.pop("image_base64", None)

            pages.append(
                {
                    "page_number": page_index + 1,
                    "direction": direction,
                    "text_align_hint": "right" if direction == "rtl" else "left",
                    "markdown": markdown,
                    "dimensions": dimensions,
                    "headers": headers,
                    "footers": footers,
                    "hyperlinks": links,
                    "tables": tables,
                    "images": images,
                }
            )

        total_pages = len(pages)
        primary_direction = "rtl" if rtl_pages > (total_pages / 2.0) else "ltr"

        return {
            "schema_version": "mistral_ocr_fidelity_v1",
            "created_at_utc": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "model": self.config.model,
            "document": {
                "source_file": source_name,
                "total_pages": total_pages,
                "primary_direction": primary_direction,
            },
            "pages": pages,
            "usage_info": self._to_plain(getattr(ocr_response, "usage_info", None)),
        }

    @staticmethod
    def _split_table_row(line: str) -> list[str]:
        row = line.strip()
        if row.startswith("|"):
            row = row[1:]
        if row.endswith("|"):
            row = row[:-1]
        return [cell.strip() for cell in row.split("|")]

    @staticmethod
    def _is_table_separator(line: str) -> bool:
        row = line.strip()
        if row.startswith("|"):
            row = row[1:]
        if row.endswith("|"):
            row = row[:-1]
        cells = [c.strip() for c in row.split("|")]
        if not cells:
            return False
        return all(re.fullmatch(r":?-{3,}:?", c) for c in cells)

    @staticmethod
    def _normalise_image_key(value: str) -> str:
        """Normalise image IDs/paths for matching markdown references."""
        v = (value or "").strip().strip("'").strip('"')
        if not v:
            return ""
        # Match by basename so `images/img-0.jpeg` and `img-0.jpeg` both resolve.
        return pathlib.Path(v).name.lower()

    def _resolve_image_src(
        self,
        src_ref: str,
        image_lookup: dict[str, dict[str, str]],
    ) -> Optional[dict[str, str]]:
        """Resolve markdown image source to a real src/alt entry."""
        if not src_ref:
            return None
        key = self._normalise_image_key(src_ref)
        if key and key in image_lookup:
            return image_lookup[key]
        raw = src_ref.strip().lower()
        if raw in image_lookup:
            return image_lookup[raw]
        return None

    @staticmethod
    def _normalise_table_key(value: str) -> str:
        """Normalise table IDs/paths for matching markdown references."""
        v = (value or "").strip().strip("'").strip('"')
        if not v:
            return ""
        return pathlib.Path(v).name.lower()

    def _resolve_table_html(self, ref: str, table_lookup: dict[str, str]) -> Optional[str]:
        """Resolve markdown table reference to OCR-provided HTML."""
        if not ref:
            return None
        key = self._normalise_table_key(ref)
        if key and key in table_lookup:
            return table_lookup[key]
        raw = ref.strip().lower()
        if raw in table_lookup:
            return table_lookup[raw]
        return None

    @staticmethod
    def _upsert_attr(attrs: str, name: str, value: str) -> str:
        """Upsert a simple HTML attribute in a tag attribute string."""
        pattern = re.compile(rf"\s{name}\s*=\s*(['\"]).*?\1", flags=re.IGNORECASE)
        rendered = f' {name}="{html.escape(value, quote=True)}"'
        if pattern.search(attrs):
            return pattern.sub(rendered, attrs, count=1)
        return f"{attrs}{rendered}"

    @staticmethod
    def _append_class(attrs: str, class_name: str) -> str:
        """Append class token to class=... attribute if missing."""
        match = re.search(r"\sclass\s*=\s*(['\"])(.*?)\1", attrs, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return f'{attrs} class="{class_name}"'
        existing = match.group(2).split()
        if class_name not in existing:
            existing.append(class_name)
        replacement = f' class="{" ".join(existing)}"'
        return f"{attrs[:match.start()]}{replacement}{attrs[match.end():]}"

    @staticmethod
    def _to_arabic_indic_digits(text: str) -> str:
        """Convert Western digits in text to Arabic-Indic digits."""
        if not text:
            return text
        # Decimal point in numeric tokens -> Arabic decimal separator.
        out = re.sub(r"(?<=\d)\.(?=\d)", "٫", text)
        trans = str.maketrans("0123456789%", "٠١٢٣٤٥٦٧٨٩٪")
        return out.translate(trans)

    def _normalise_table_html(self, table_html: str, table_dir: str) -> str:
        """
        Normalize OCR table HTML for stable rendering:
        - One consistent table direction per page (`table_dir`).
        - Per-cell direction for mixed Arabic/Latin content.
        - Arabic-Indic digit localization for RTL Arabic cells.
        """
        src = (table_html or "").strip()
        if not src:
            return src

        def _table_repl(match: re.Match[str]) -> str:
            attrs = match.group(1) or ""
            attrs = self._append_class(attrs, "ocr-html-table")
            attrs = self._upsert_attr(attrs, "dir", table_dir)
            return f"<table{attrs}>"

        src = re.sub(r"<table([^>]*)>", _table_repl, src, count=1, flags=re.IGNORECASE)

        def _cell_repl(match: re.Match[str]) -> str:
            tag = match.group(1)
            attrs = match.group(2) or ""
            inner = match.group(3) or ""

            plain = html.unescape(re.sub(r"<[^>]+>", " ", inner))
            cell_dir = self._detect_text_direction(plain)
            if cell_dir == "auto":
                cell_dir = table_dir

            # Convert Western digits to Arabic-Indic in Arabic RTL cells.
            if cell_dir == "rtl" and not re.search(r"[A-Za-z]", plain):
                inner = self._to_arabic_indic_digits(inner)

            attrs = self._upsert_attr(attrs, "dir", cell_dir)
            return f"<{tag}{attrs}>{inner}</{tag}>"

        src = re.sub(r"<(th|td)([^>]*)>(.*?)</\1>", _cell_repl, src, flags=re.IGNORECASE | re.DOTALL)
        return src

    def _inline_markdown(
        self,
        text: str,
        image_lookup: Optional[dict[str, dict[str, str]]] = None,
        used_image_keys: Optional[set[str]] = None,
    ) -> str:
        """
        Minimal inline markdown:
        - links [text](url)
        - code `...`
        - bold/italic markers
        Keeps LaTeX delimiters unchanged for MathJax.
        """
        # Decode OCR-provided entities first so `&lt;` and `&gt;` render as symbols.
        raw = html.unescape(text)

        # Protect image spans first so escaping/markdown transforms do not corrupt them.
        image_placeholders: dict[str, str] = {}

        def _stash_image(match: re.Match[str]) -> str:
            key = f"@@IMG{len(image_placeholders)}@@"
            alt = (match.group(1) or "").strip() or "OCR image"
            src_ref = (match.group(2) or "").strip()
            resolved = self._resolve_image_src(src_ref, image_lookup or {})
            if resolved:
                src = resolved.get("src", "")
                if used_image_keys is not None and src_ref:
                    used_image_keys.add(self._normalise_image_key(src_ref))
                image_placeholders[key] = (
                    f'<img class="inline-ocr-image" src="{html.escape(src, quote=True)}" '
                    f'alt="{html.escape(alt, quote=True)}"/>'
                )
            else:
                # Fallback if mapping is missing: show the alt label only.
                image_placeholders[key] = html.escape(alt)
            return key

        raw = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _stash_image, raw)

        # Protect math spans so escaping/markdown transforms do not corrupt them.
        placeholders: dict[str, str] = {}

        def _stash(match: re.Match[str]) -> str:
            key = f"@@MATH{len(placeholders)}@@"
            # Decode pre-escaped entities from OCR (`&lt;`) before output.
            placeholders[key] = html.unescape(match.group(0))
            return key

        # Inline display `$$...$$` on one line.
        raw = re.sub(r"\$\$([^\n$]|\\\$)+\$\$", _stash, raw)
        # Inline math `$...$` (single-line).
        raw = re.sub(r"(?<!\$)\$([^\n$]|\\\$)+\$(?!\$)", _stash, raw)
        # TeX delimiters.
        raw = re.sub(r"\\\((.+?)\\\)", _stash, raw)
        raw = re.sub(r"\\\[(.+?)\\\]", _stash, raw)

        out = html.escape(raw)
        out = re.sub(
            r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
            r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
            out,
        )
        out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
        out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
        out = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", out)
        out = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", out)
        out = re.sub(r"_([^_]+)_", r"<em>\1</em>", out)

        for key, snippet in image_placeholders.items():
            out = out.replace(key, snippet)
        for key, math_src in placeholders.items():
            out = out.replace(key, html.escape(math_src))
        return out

    def _render_sentence_level_text(
        self,
        text: str,
        image_lookup: Optional[dict[str, dict[str, str]]] = None,
        used_image_keys: Optional[set[str]] = None,
    ) -> str:
        """
        Render text with sentence-level direction spans.
        This avoids forcing one direction for a full page/paragraph.
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return ""

        parts: list[str] = []
        for sent in sentences:
            rendered = self._inline_markdown(sent, image_lookup, used_image_keys)
            direction = self._detect_text_direction(sent)
            if direction == "auto":
                parts.append(f'<span class="dir-sentence">{rendered}</span>')
            else:
                parts.append(
                    f'<span class="dir-sentence dir-{direction}" dir="{direction}">{rendered}</span>'
                )
        return " ".join(parts)

    def _block_dir_attrs(self, text: str, extra_class: str = "") -> str:
        """Return HTML attributes for block-level direction/alignment."""
        direction = self._detect_text_direction(text)
        cls = f"block block-{direction}"
        if extra_class:
            cls = f"{cls} {extra_class}"
        return f'class="{cls}" dir="{direction}"'

    @staticmethod
    def _render_math_display(content: str) -> str:
        """Render a display-math block robustly for MathJax."""
        # Convert OCR-escaped entities so `&lt;` does not become `&amp;lt;`.
        decoded = html.unescape(content.strip())
        return f'<div class="math-display">$$\n{html.escape(decoded)}\n$$</div>'

    def _markdown_to_html(
        self,
        markdown_text: str,
        image_lookup: Optional[dict[str, dict[str, str]]] = None,
        used_image_keys: Optional[set[str]] = None,
        table_lookup: Optional[dict[str, str]] = None,
        used_table_keys: Optional[set[str]] = None,
    ) -> str:
        """Simple deterministic markdown renderer for OCR output."""
        lines = markdown_text.splitlines()
        i = 0
        out: list[str] = []
        in_ul = False
        in_ol = False

        def close_lists() -> None:
            nonlocal in_ul, in_ol
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if in_ol:
                out.append("</ol>")
                in_ol = False

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if not stripped:
                close_lists()
                i += 1
                continue

            # Standalone markdown table reference line(s) -> inline table placement.
            table_matches = list(re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", stripped))
            if table_matches:
                residue = re.sub(r"\[[^\]]+\]\([^)]+\)", "", stripped).strip()
                table_blocks: list[str] = []
                for m in table_matches:
                    label = (m.group(1) or "").strip()
                    src_ref = (m.group(2) or "").strip()
                    table_html = (
                        self._resolve_table_html(src_ref, table_lookup or {})
                        or self._resolve_table_html(label, table_lookup or {})
                    )
                    if not table_html:
                        continue
                    norm_key = self._normalise_table_key(src_ref or label)
                    if used_table_keys is not None and norm_key:
                        used_table_keys.add(norm_key)
                    table_blocks.append(
                        f'<div class="ocr-table-wrap inline-ocr-table" dir="auto">{table_html}</div>'
                    )

                if table_blocks and not residue:
                    close_lists()
                    out.extend(table_blocks)
                    i += 1
                    continue

            # Standalone markdown image line(s) -> inline figure placement.
            image_matches = list(re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", stripped))
            if image_matches:
                residue = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", "", stripped).strip()
                if not residue:
                    close_lists()
                    for m in image_matches:
                        alt = (m.group(1) or "").strip() or "OCR image"
                        src_ref = (m.group(2) or "").strip()
                        resolved = self._resolve_image_src(src_ref, image_lookup or {})
                        if resolved:
                            if used_image_keys is not None and src_ref:
                                used_image_keys.add(self._normalise_image_key(src_ref))
                            src = resolved.get("src", "")
                            out.append(
                                f'<figure class="ocr-image inline-ocr-image-block">'
                                f'<img src="{html.escape(src, quote=True)}" alt="{html.escape(alt, quote=True)}"/>'
                                f"</figure>"
                            )
                        else:
                            out.append(f"<p>{html.escape(m.group(0))}</p>")
                    i += 1
                    continue

            # Display math block with explicit delimiters on separate lines.
            if stripped == "$$":
                close_lists()
                i += 1
                math_lines = []
                while i < len(lines) and lines[i].strip() != "$$":
                    math_lines.append(lines[i])
                    i += 1
                if i < len(lines) and lines[i].strip() == "$$":
                    i += 1
                out.append(self._render_math_display("\n".join(math_lines)))
                continue

            # Single-line display math block.
            if stripped.startswith("$$") and stripped.endswith("$$") and len(stripped) > 4:
                close_lists()
                inner = stripped[2:-2]
                out.append(self._render_math_display(inner))
                i += 1
                continue

            # \[ ... \] display block (single-line or multi-line).
            if stripped.startswith(r"\["):
                close_lists()
                if stripped.endswith(r"\]") and len(stripped) > 4:
                    inner = stripped[2:-2]
                    out.append(self._render_math_display(inner))
                    i += 1
                    continue
                i += 1
                math_lines = []
                while i < len(lines) and lines[i].strip() != r"\]":
                    math_lines.append(lines[i])
                    i += 1
                if i < len(lines) and lines[i].strip() == r"\]":
                    i += 1
                out.append(self._render_math_display("\n".join(math_lines)))
                continue

            if stripped.startswith("```"):
                close_lists()
                fence = stripped[:3]
                i += 1
                code_buf = []
                while i < len(lines) and not lines[i].strip().startswith(fence):
                    code_buf.append(lines[i])
                    i += 1
                if i < len(lines):
                    i += 1
                out.append("<pre><code>")
                out.append(html.escape("\n".join(code_buf)))
                out.append("</code></pre>")
                continue

            head = re.match(r"^(#{1,6})\s+(.*)$", stripped)
            if head:
                close_lists()
                level = len(head.group(1))
                out.append(
                    f"<h{level} {self._block_dir_attrs(head.group(2).strip())}>"
                    f"{self._render_sentence_level_text(head.group(2).strip(), image_lookup, used_image_keys)}"
                    f"</h{level}>"
                )
                i += 1
                continue

            if stripped in {"---", "***", "___"}:
                close_lists()
                out.append("<hr/>")
                i += 1
                continue

            if (
                "|" in stripped
                and (i + 1) < len(lines)
                and self._is_table_separator(lines[i + 1])
            ):
                close_lists()
                header_cells = self._split_table_row(lines[i])
                align_cells = self._split_table_row(lines[i + 1])
                i += 2
                rows = []
                while i < len(lines) and "|" in lines[i]:
                    if not lines[i].strip():
                        break
                    rows.append(self._split_table_row(lines[i]))
                    i += 1

                out.append('<table class="md-table">')
                out.append("<thead><tr>")
                for col, cell in enumerate(header_cells):
                    align = ""
                    if col < len(align_cells):
                        token = align_cells[col]
                        if token.startswith(":") and token.endswith(":"):
                            align = ' style="text-align:center"'
                        elif token.endswith(":"):
                            align = ' style="text-align:right"'
                        elif token.startswith(":"):
                            align = ' style="text-align:left"'
                    out.append(f"<th{align}>{self._inline_markdown(cell)}</th>")
                out.append("</tr></thead>")

                if rows:
                    out.append("<tbody>")
                    for row in rows:
                        out.append("<tr>")
                        for cell in row:
                            out.append(f"<td>{self._inline_markdown(cell)}</td>")
                        out.append("</tr>")
                    out.append("</tbody>")
                out.append("</table>")
                continue

            ul = re.match(r"^\s*[-*+]\s+(.*)$", line)
            if ul:
                if in_ol:
                    out.append("</ol>")
                    in_ol = False
                if not in_ul:
                    out.append("<ul>")
                    in_ul = True
                out.append(
                    f"<li {self._block_dir_attrs(ul.group(1).strip())}>"
                    f"{self._render_sentence_level_text(ul.group(1).strip(), image_lookup, used_image_keys)}"
                    f"</li>"
                )
                i += 1
                continue

            ol = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
            if ol:
                if in_ul:
                    out.append("</ul>")
                    in_ul = False
                if not in_ol:
                    out.append("<ol>")
                    in_ol = True
                out.append(
                    f"<li {self._block_dir_attrs(ol.group(1).strip())}>"
                    f"{self._render_sentence_level_text(ol.group(1).strip(), image_lookup, used_image_keys)}"
                    f"</li>"
                )
                i += 1
                continue

            close_lists()
            para = [stripped]
            i += 1
            while i < len(lines):
                nxt = lines[i].strip()
                if not nxt:
                    break
                if re.match(r"^(#{1,6})\s+", nxt):
                    break
                if re.match(r"^\s*[-*+]\s+", lines[i]):
                    break
                if re.match(r"^\s*\d+[.)]\s+", lines[i]):
                    break
                if nxt in {"---", "***", "___"}:
                    break
                para.append(nxt)
                i += 1
            out.append(
                f"<p {self._block_dir_attrs(' '.join(para))}>"
                f"{self._render_sentence_level_text(' '.join(para), image_lookup, used_image_keys)}"
                f"</p>"
            )

        close_lists()
        return "\n".join(out)

    @staticmethod
    def _build_image_data_uri(image_base64: str) -> str:
        if not image_base64:
            return ""
        if image_base64.startswith("data:image/"):
            return image_base64
        return f"data:image/png;base64,{image_base64}"

    def _save_images(self, pages: list[dict[str, Any]], image_dir: pathlib.Path) -> int:
        """Decode OCR image blobs into files for sidecar export."""
        image_dir.mkdir(parents=True, exist_ok=True)
        written = 0
        for page in pages:
            pnum = page.get("page_number", 0)
            for i, img in enumerate(page.get("images", [])):
                if not isinstance(img, dict):
                    continue
                b64 = img.get("image_base64")
                if not b64:
                    continue
                raw = b64.split(",", 1)[-1] if "," in b64 else b64
                image_id = img.get("id") or f"img{i + 1}"
                image_path = image_dir / f"page_{pnum:04d}_{image_id}.png"
                try:
                    image_path.write_bytes(base64.b64decode(raw))
                    img["saved_path"] = str(image_path.name)
                    if not self.config.inline_images_in_json:
                        img.pop("image_base64", None)
                    written += 1
                except Exception as exc:
                    logger.warning("Could not save image page=%s id=%s: %s", pnum, image_id, exc)
        return written

    def _render_page(self, page: dict[str, Any]) -> str:
        pnum = page.get("page_number")
        direction = page.get("direction", "ltr")
        headers = page.get("headers", [])
        footers = page.get("footers", [])
        markdown_text = page.get("markdown", "")
        tables = page.get("tables", [])
        images = page.get("images", [])
        used_image_keys: set[str] = set()
        used_table_keys: set[str] = set()
        page_table_dir = "rtl" if direction == "rtl" else "ltr"

        # Build page-scoped image lookup so markdown refs like `img-0.jpeg` resolve.
        image_lookup: dict[str, dict[str, str]] = {}
        for img in images:
            if not isinstance(img, dict):
                continue
            data_uri = self._build_image_data_uri(str(img.get("image_base64") or ""))
            if not data_uri:
                saved = img.get("saved_path")
                if saved:
                    data_uri = f"images/{saved}"
            if not data_uri:
                continue
            alt = str(img.get("id") or "OCR image")
            keys: set[str] = set()
            for key_field in ("id", "saved_path"):
                raw = img.get(key_field)
                if isinstance(raw, str) and raw.strip():
                    keys.add(raw.strip().lower())
                    norm = self._normalise_image_key(raw)
                    if norm:
                        keys.add(norm)
            for key in keys:
                image_lookup[key] = {"src": data_uri, "alt": alt}

        # Build page-scoped table lookup so markdown refs like `tbl-0.html` resolve.
        table_lookup: dict[str, str] = {}
        table_entries: list[tuple[str, str]] = []
        for idx, tbl in enumerate(tables):
            if not isinstance(tbl, dict):
                continue
            table_html = ""
            for key in ("html", "content"):
                raw_html = tbl.get(key)
                if isinstance(raw_html, str) and raw_html.strip():
                    table_html = raw_html.strip()
                    break
            if not table_html:
                continue
            table_html = self._normalise_table_html(table_html, table_dir=page_table_dir)
            raw_id = str(tbl.get("id") or tbl.get("name") or f"tbl-{idx}.html")
            norm_id = self._normalise_table_key(raw_id) or f"tbl-{idx}.html"
            table_lookup[norm_id] = table_html
            table_entries.append((norm_id, table_html))

        parts = [f'<section class="page" data-page="{pnum}" data-page-direction="{direction}" dir="auto">']
        parts.append(f'<div class="page-label">Page {pnum}</div>')

        header_text = " ".join(
            txt for txt in (self._extract_text_from_annotation(h) for h in headers) if txt
        ).strip()
        if header_text:
            header_dir = self._detect_text_direction(header_text)
            parts.append(
                f'<header class="page-header block block-{header_dir}" dir="{header_dir}">'
                f'{self._render_sentence_level_text(header_text)}'
                f"</header>"
            )

        parts.append('<article class="page-content">')
        parts.append(
            self._markdown_to_html(
                markdown_text,
                image_lookup=image_lookup,
                used_image_keys=used_image_keys,
                table_lookup=table_lookup,
                used_table_keys=used_table_keys,
            )
        )
        parts.append("</article>")

        # Keep any OCR tables that were not referenced in markdown as fallback.
        unplaced_tables = [table_html for key, table_html in table_entries if key not in used_table_keys]
        if unplaced_tables:
            parts.append('<section class="page-tables">')
            parts.append("<h3>Unplaced Tables</h3>")
            for t in unplaced_tables:
                parts.append(f'<div class="ocr-table-wrap" dir="auto">{t}</div>')
            parts.append("</section>")

        if images:
            image_items = []
            for img in images:
                if not isinstance(img, dict):
                    continue
                image_keys = set()
                for key_field in ("id", "saved_path"):
                    raw = img.get(key_field)
                    if isinstance(raw, str) and raw.strip():
                        image_keys.add(raw.strip().lower())
                        norm = self._normalise_image_key(raw)
                        if norm:
                            image_keys.add(norm)
                if image_keys and any(k in used_image_keys for k in image_keys):
                    # Already placed inline by markdown reference.
                    continue
                data_uri = self._build_image_data_uri(str(img.get("image_base64") or ""))
                if not data_uri:
                    saved = img.get("saved_path")
                    if saved:
                        # Sidecar image relative to HTML file.
                        data_uri = f"images/{saved}"
                if not data_uri:
                    continue
                alt = str(img.get("id") or "OCR image")
                image_items.append(
                    f'<figure class="ocr-image"><img src="{data_uri}" alt="{html.escape(alt)}"/></figure>'
                )
            if image_items:
                parts.append('<section class="page-images">')
                parts.append("<h3>Unplaced Images</h3>")
                parts.extend(image_items)
                parts.append("</section>")

        footer_text = " ".join(
            txt for txt in (self._extract_text_from_annotation(f) for f in footers) if txt
        ).strip()
        if footer_text:
            footer_dir = self._detect_text_direction(footer_text)
            parts.append(
                f'<footer class="page-footer block block-{footer_dir}" dir="{footer_dir}">'
                f'{self._render_sentence_level_text(footer_text)}'
                f"</footer>"
            )

        parts.append("</section>")
        return "\n".join(parts)

    def _render_html(self, canonical: dict[str, Any]) -> str:
        doc = canonical.get("document", {})
        direction = doc.get("primary_direction", "ltr")
        lang = "ar" if direction == "rtl" else "en"
        pages = canonical.get("pages", [])
        body = "\n".join(self._render_page(p) for p in pages)
        title = html.escape(str(doc.get("source_file") or "OCR Document"))

        return f"""<!DOCTYPE html>
<html lang="{lang}" dir="auto" data-primary-direction="{direction}">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{title}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: #f2f3f7;
      color: #151515;
      font-family: "Noto Naskh Arabic", "Amiri", "Segoe UI", Tahoma, sans-serif;
      line-height: 1.6;
      overflow-x: hidden;
    }}
    .doc {{
      max-width: 980px;
      margin: 0 auto;
      padding: 20px 10px 32px;
    }}
    .doc-meta {{
      margin: 0 0 14px;
      color: #555;
      font-size: 0.95rem;
    }}
    .page {{
      background: #fff;
      border: 1px solid #d7dbe5;
      margin: 0 0 14px;
      padding: 14px 16px;
      border-radius: 6px;
      box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
    }}
    .page-label {{
      font-size: 0.8rem;
      color: #6c6f79;
      margin-bottom: 8px;
    }}
    .page-header, .page-footer {{
      color: #666;
      font-size: 0.85rem;
      padding: 4px 0;
      border-color: #e5e7ef;
      border-style: solid;
      border-width: 0;
    }}
    .page-header {{ border-bottom-width: 1px; margin-bottom: 12px; }}
    .page-footer {{ border-top-width: 1px; margin-top: 12px; }}
    .page-content h1, .page-content h2, .page-content h3, .page-content h4 {{
      margin: 0.7em 0 0.35em;
    }}
    .page-content p {{ margin: 0.45em 0; }}
    .page-content ul, .page-content ol {{ margin: 0.4em 1.2em; padding: 0; }}
    .page-content pre {{
      overflow: visible;
      background: #f8f9fc;
      border: 1px solid #e6e9f0;
      border-radius: 4px;
      padding: 10px;
    }}
    .page-content code {{
      font-family: "JetBrains Mono", "Fira Code", ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.95em;
    }}
    .block {{
      unicode-bidi: plaintext;
    }}
    .block-rtl {{
      direction: rtl;
      text-align: right;
    }}
    .block-ltr {{
      direction: ltr;
      text-align: left;
    }}
    .block-auto {{
      direction: auto;
      text-align: start;
    }}
    .dir-sentence {{
      unicode-bidi: plaintext;
    }}
    .dir-sentence.dir-rtl {{
      direction: rtl;
      unicode-bidi: isolate;
    }}
    .dir-sentence.dir-ltr {{
      direction: ltr;
      unicode-bidi: isolate;
    }}
    .math-display {{
      direction: ltr;
      text-align: center;
      unicode-bidi: embed;
      margin: 0.6em 0;
      overflow: visible !important;
      max-width: 100%;
    }}
    mjx-container[display="true"] {{
      overflow: visible !important;
      max-width: 100% !important;
      width: 100% !important;
    }}
    mjx-assistive-mml {{
      overflow: hidden !important;
    }}
    .md-table, .ocr-table-wrap table {{
      width: 100%;
      border-collapse: collapse;
      margin: 0.7em 0;
    }}
    .md-table th, .md-table td, .ocr-table-wrap th, .ocr-table-wrap td {{
      border: 1px solid #ccd2df;
      padding: 6px 8px;
      vertical-align: top;
    }}
    .ocr-html-table {{
      unicode-bidi: isolate;
    }}
    .ocr-html-table th[dir="rtl"], .ocr-html-table td[dir="rtl"] {{
      text-align: right;
    }}
    .ocr-html-table th[dir="ltr"], .ocr-html-table td[dir="ltr"] {{
      text-align: left;
    }}
    .page-tables h3, .page-images h3 {{
      margin: 1em 0 0.45em;
      color: #404451;
      font-size: 0.95rem;
      font-weight: 600;
    }}
    .ocr-image {{
      margin: 0.7em 0;
      padding: 0;
    }}
    .ocr-image img {{
      max-width: 100%;
      height: auto;
      border: 1px solid #d8dce7;
      border-radius: 4px;
      background: #fff;
    }}
  </style>
  <script>
    function __removeMathScrollbars() {{
      document.querySelectorAll('mjx-container[display=\"true\"]').forEach((el) => {{
        el.style.overflow = 'visible';
        el.style.maxWidth = '100%';
        el.style.width = '100%';
      }});
    }}
    window.MathJax = {{
      tex: {{
        inlineMath: [['\\\\(', '\\\\)'], ['$', '$']],
        displayMath: [['\\\\[', '\\\\]'], ['$$', '$$']],
        processEscapes: true
      }},
      chtml: {{
        displayAlign: 'center',
        displayIndent: '0',
        linebreaks: {{ automatic: true, width: 'container' }}
      }},
      options: {{
        skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre']
      }},
      startup: {{
        pageReady: () => MathJax.startup.defaultPageReady().then(() => {{
          __removeMathScrollbars();
        }})
      }}
    }};
    window.addEventListener('load', () => {{
      setTimeout(__removeMathScrollbars, 200);
    }});
  </script>
  <script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
</head>
<body>
  <main class="doc">
    <div class="doc-meta">Model: {html.escape(str(canonical.get("model") or ""))} | Pages: {len(pages)}</div>
    {body}
  </main>
</body>
</html>
"""

    def process(self, pdf_path: str) -> dict[str, pathlib.Path]:
        """Run OCR and write configured outputs."""
        pdf = pathlib.Path(pdf_path).expanduser().resolve()
        if not pdf.exists():
            raise FileNotFoundError(f"PDF not found: {pdf}")

        out_dir = pathlib.Path(self.config.output_dir).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = pdf.stem

        file_id = self._upload_pdf(pdf)
        ocr_response = self._run_ocr(file_id)
        canonical = self._normalise(ocr_response, source_name=pdf.name)

        result: dict[str, pathlib.Path] = {}

        if self.config.save_images and self.config.include_image_base64:
            image_dir = out_dir / "images"
            # Need raw images from SDK response, not stripped canonical copy.
            raw_pages = getattr(ocr_response, "pages", []) or []
            for p in canonical.get("pages", []):
                pg = p["page_number"] - 1
                if 0 <= pg < len(raw_pages):
                    p["images"] = self._to_plain(getattr(raw_pages[pg], "images", [])) or []
            saved_count = self._save_images(canonical.get("pages", []), image_dir)
            if saved_count > 0:
                result["images_dir"] = image_dir
                logger.info("Saved %d OCR images -> %s", saved_count, image_dir)

        if self.config.save_json:
            json_path = out_dir / f"{stem}_mistral_fidelity.json"
            json_path.write_text(
                json.dumps(canonical, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            result["json_path"] = json_path
            logger.info("Wrote canonical JSON -> %s", json_path)

        if self.config.save_markdown:
            md_path = out_dir / f"{stem}_mistral_fidelity.md"
            with open(md_path, "w", encoding="utf-8") as fh:
                for page in canonical.get("pages", []):
                    pnum = page.get("page_number", "?")
                    fh.write(f"\n\n---\n## PAGE {pnum}\n\n")
                    fh.write(page.get("markdown", ""))
            result["markdown_path"] = md_path
            logger.info("Wrote markdown -> %s", md_path)

        if self.config.save_html:
            html_path = out_dir / f"{stem}_mistral_fidelity.html"
            html_path.write_text(self._render_html(canonical), encoding="utf-8")
            result["html_path"] = html_path
            logger.info("Wrote deterministic HTML -> %s", html_path)

        return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mistral OCR fidelity pipeline (OCR -> canonical JSON + markdown + HTML)"
    )
    parser.add_argument("pdf", help="Path to PDF file")
    parser.add_argument("--output-dir", "-o", default="outputs", help="Output directory")
    parser.add_argument(
        "--table-format",
        default="html",
        choices=["html", "markdown"],
        help="Preferred table format from OCR API (default: html)",
    )
    parser.add_argument(
        "--bbox-annotation-format",
        default=None,
        help="Optional bbox annotation format passed to OCR API",
    )
    parser.add_argument(
        "--document-annotation-format",
        default=None,
        help="Optional document annotation format passed to OCR API",
    )
    parser.add_argument("--no-images", action="store_true", help="Do not request image base64")
    parser.add_argument("--inline-images-json", action="store_true", help="Keep image base64 in JSON")
    parser.add_argument("--no-json", action="store_true", help="Skip JSON output")
    parser.add_argument("--no-markdown", action="store_true", help="Skip markdown output")
    parser.add_argument("--no-html", action="store_true", help="Skip HTML output")

    args = parser.parse_args()

    cfg = MistralFidelityConfig(
        output_dir=args.output_dir,
        table_format=args.table_format,
        bbox_annotation_format=args.bbox_annotation_format,
        document_annotation_format=args.document_annotation_format,
        include_image_base64=not args.no_images,
        inline_images_in_json=args.inline_images_json,
        save_json=not args.no_json,
        save_markdown=not args.no_markdown,
        save_html=not args.no_html,
        save_images=not args.no_images,
    )

    pipeline = MistralFidelityPipeline(cfg)
    result = pipeline.process(args.pdf)
    print("Outputs:")
    for key, path in result.items():
        print(f"  {key}: {path}")


if __name__ == "__main__":
    main()
