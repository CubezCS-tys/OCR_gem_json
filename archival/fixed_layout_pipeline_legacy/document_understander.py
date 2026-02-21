"""
Document Understander — Gemini-powered structure analysis for the semantic renderer.

Analyses a CanonicalDocument to produce a DocumentUnderstanding: heading hierarchy,
document title, language, and optional block-type overrides (e.g. Quranic verses).

Falls back gracefully to heuristic analysis when:
  - GEMINI_API_KEY is not set
  - use_llm=False is passed
  - Gemini returns invalid JSON or raises any exception

Usage:
    from fixed_layout_pipeline.document_understander import DocumentUnderstander
    understander = DocumentUnderstander(model="gemini-2.0-flash-preview")
    understanding = understander.understand(doc)          # with Gemini
    understanding = understander.understand(doc, use_llm=False)  # heuristic only
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .schema import BlockType, CanonicalDocument, Direction

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3-flash-preview"

# ── Prompt ────────────────────────────────────────────────────────────────────

_PROMPT_TEMPLATE = """You are a document structure analyst for Arabic, French, and English documents.

Below is a list of short text blocks from an OCR-processed document (long body-text blocks are excluded).
Each line: ID | page | text

{outline_text}

Tasks:
1. Find the main document title (usually page 1, most prominent short block).
2. Identify structural section headings — at most 25 blocks.
   Many short blocks are NOT headings (author names, dates, footnote numbers, etc.) — exclude them.
3. Assign each heading a level: 1=main section, 2=subsection, 3=minor heading.

Return ONLY valid JSON, no explanation, no markdown fences:
{{"title_block_id":"<id or null>","primary_language":"<ar|en|fr>","headings":[{{"id":"<id>","level":<1|2|3>,"is_title":<true|false>}}],"overrides":[]}}

Rules:
- Use block IDs exactly as shown (ASCII only).
- "is_title": true for exactly ONE block.
- headings list: maximum 25 items.
- overrides: always [].
"""


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class SectionInfo:
    """Describes one heading block with its inferred level."""
    block_id: str
    heading_level: int          # 1, 2, or 3
    section_title: str
    is_document_title: bool = False


@dataclass
class DocumentUnderstanding:
    """
    Result of the document understanding pass.

    Always constructed successfully — falls back to heuristic defaults
    when Gemini is unavailable or fails.
    """
    document_title: Optional[str] = None
    # block_id → SectionInfo (only for HEADER blocks)
    sections: dict[str, SectionInfo] = field(default_factory=dict)
    # block_id → override type string ("quran", "decorative")
    block_type_overrides: dict[str, str] = field(default_factory=dict)
    primary_language: str = "ar"
    used_llm: bool = False
    cost_usd: float = 0.0
    elapsed_seconds: float = 0.0


# ── Core class ────────────────────────────────────────────────────────────────

class DocumentUnderstander:
    """
    Analyses a CanonicalDocument and returns a DocumentUnderstanding.

    Never raises — all Gemini failures produce a heuristic fallback result.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        use_llm: bool = True,
    ) -> None:
        self.model = model
        self.use_llm = use_llm

    # ── Public API ────────────────────────────────────────────────────────────

    def understand(self, doc: CanonicalDocument) -> DocumentUnderstanding:
        """
        Analyse doc and return a DocumentUnderstanding.

        If use_llm is True and GEMINI_API_KEY is set, calls Gemini.
        Otherwise (or on any failure) returns a heuristic result.
        """
        if not self.use_llm:
            logger.info("LLM disabled — using heuristic understanding")
            return self._fallback(doc)

        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            logger.warning(
                "GEMINI_API_KEY not set — falling back to heuristic understanding"
            )
            return self._fallback(doc)

        try:
            return self._understand_with_gemini(doc, api_key)
        except Exception as exc:
            logger.warning(
                "Gemini understanding failed (%s) — falling back to heuristic", exc
            )
            return self._fallback(doc)

    # ── Gemini path ───────────────────────────────────────────────────────────

    def _understand_with_gemini(
        self, doc: CanonicalDocument, api_key: str
    ) -> DocumentUnderstanding:
        from google import genai  # noqa: PLC0415
        from google.genai import types  # noqa: PLC0415

        client = genai.Client(api_key=api_key)
        outline = _build_outline(doc)
        outline_text = _outline_to_text(outline)
        prompt = _PROMPT_TEMPLATE.format(outline_text=outline_text)

        t0 = time.time()
        # Note: we do NOT use response_mime_type="application/json" here because some
        # Gemini model versions impose a very low effective output-token limit in JSON mode,
        # causing the response to be truncated mid-JSON. Plain text mode + regex extraction
        # is more reliable across model versions.
        # Note: do NOT set max_output_tokens — on some model versions it counter-productively
        # limits output to ~325 tokens (less than the model's natural stopping point).
        # Without it, the model uses its default context window and stops naturally.
        response = client.models.generate_content(
            model=self.model,
            contents=[prompt],
            config=types.GenerateContentConfig(temperature=0.0),
        )
        elapsed = time.time() - t0

        # Cost (matches gemini_html.py formula: Flash input $0.50/M, output $3.00/M)
        meta = response.usage_metadata
        inp = meta.prompt_token_count if meta else 0
        out = meta.candidates_token_count if meta else 0
        cost = (inp / 1_000_000) * 0.50 + (out / 1_000_000) * 3.00

        logger.info(
            "Gemini understanding: %.1fs | %d in / %d out tokens | $%.4f",
            elapsed, inp, out, cost,
        )

        # Extract JSON: strip markdown fences, then find the outermost {...} object
        raw_text = (response.text or "").strip()
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.IGNORECASE)
        raw_text = re.sub(r"\s*```\s*$", "", raw_text)
        # Find outermost JSON object (handles any preamble text)
        m = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if m:
            raw_text = m.group(0)

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            logger.warning("Gemini returned invalid JSON (%s) — falling back", exc)
            return self._fallback(doc)

        return self._parse_response(doc, data, cost, elapsed)

    def _parse_response(
        self,
        doc: CanonicalDocument,
        data: dict,
        cost: float,
        elapsed: float,
    ) -> DocumentUnderstanding:
        """Convert Gemini's JSON response into a DocumentUnderstanding."""
        # Build a quick text lookup: block_id → full_text
        block_text: dict[str, str] = {}
        for page in doc.pages:
            for block in page.blocks:
                block_text[block.block_id] = block.full_text().strip()

        # Parse headings — support both old schema (block_id/heading_level) and new (id/level)
        sections: dict[str, SectionInfo] = {}
        for h in data.get("headings", []):
            block_id = str(h.get("id") or h.get("block_id", ""))
            if not block_id:
                continue
            level = int(h.get("level") or h.get("heading_level") or 2)
            level = max(1, min(3, level))  # clamp to 1–3
            is_title = bool(h.get("is_title") or h.get("is_document_title", False))
            title_text = block_text.get(block_id, "")
            sections[block_id] = SectionInfo(
                block_id=block_id,
                heading_level=level,
                section_title=title_text,
                is_document_title=is_title,
            )

        # Parse overrides — support both old and new schema
        overrides: dict[str, str] = {}
        for o in data.get("overrides", []) + data.get("block_type_overrides", []):
            bid = str(o.get("id") or o.get("block_id", ""))
            otype = str(o.get("type") or o.get("override_type", ""))
            if bid and otype:
                overrides[bid] = otype

        # Document title: look up from title_block_id, then first is_title section
        title_block_id = data.get("title_block_id") or data.get("document_title")
        doc_title: Optional[str] = None
        if title_block_id and title_block_id in block_text:
            doc_title = block_text[title_block_id]
        if not doc_title:
            for info in sections.values():
                if info.is_document_title:
                    doc_title = info.section_title
                    break
        if not doc_title:
            doc_title = _derive_fallback_title(doc)

        lang = data.get("primary_language", "ar") or "ar"

        return DocumentUnderstanding(
            document_title=doc_title,
            sections=sections,
            block_type_overrides=overrides,
            primary_language=lang,
            used_llm=True,
            cost_usd=cost,
            elapsed_seconds=elapsed,
        )

    # ── Heuristic fallback ────────────────────────────────────────────────────

    def _fallback(self, doc: CanonicalDocument) -> DocumentUnderstanding:
        """
        Heuristic understanding without Gemini.

        Strategy (in priority order):
        1. If any HEADER blocks exist: first on page 0 → h1, all others → h2.
        2. If NO HEADER blocks (e.g. searchable-PDF extraction): identify short
           TEXT blocks (≤80 chars) as heading candidates, classify by length.
        """
        sections: dict[str, SectionInfo] = {}
        title_assigned = False

        has_headers = any(
            b.block_type == BlockType.HEADER
            for p in doc.pages for b in p.blocks
        )

        for page in doc.pages:
            for block in page.blocks_in_reading_order():
                text = block.full_text().strip()
                if not text:
                    continue

                if has_headers:
                    if block.block_type != BlockType.HEADER:
                        continue
                    if not title_assigned and page.page_index == 0:
                        level, is_title = 1, True
                        title_assigned = True
                    else:
                        level, is_title = 2, False
                else:
                    # No structural markup — use text length as proxy for headings
                    # Short blocks (≤80 chars) on the first page → title/h1
                    # Short blocks elsewhere → h2 (section headings)
                    if len(text) > 80:
                        continue  # skip long body text
                    if not title_assigned and page.page_index == 0:
                        level, is_title = 1, True
                        title_assigned = True
                    else:
                        level, is_title = 2, False

                sections[block.block_id] = SectionInfo(
                    block_id=block.block_id,
                    heading_level=level,
                    section_title=text,
                    is_document_title=is_title,
                )

        doc_title = (
            doc.title
            or next(
                (s.section_title for s in sections.values() if s.is_document_title),
                None,
            )
            or _derive_fallback_title(doc)
        )
        lang = doc.languages[0] if doc.languages else "ar"

        return DocumentUnderstanding(
            document_title=doc_title,
            sections=sections,
            block_type_overrides={},
            primary_language=lang,
            used_llm=False,
            cost_usd=0.0,
            elapsed_seconds=0.0,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_outline(doc: CanonicalDocument) -> list[dict]:
    """
    Build a compact block outline for Gemini classification.

    Design goals:
    - Keep total outline under ~15K chars (~4K tokens) so the response fits in budget.
    - Include enough signal to identify headings even when block_type is all "text"
      (which happens with searchable-PDF extraction via spdf_to_canonical).

    Strategy:
    - Short blocks (≤80 chars) are always included verbatim — they're heading candidates.
    - Long blocks (body text) are represented as a single summary entry "[body, N words]"
      so Gemini knows they exist without bloating the prompt.
    - HEADER/FOOTER typed blocks always included.
    - Figures and tables without captions skipped.
    - Capped at MAX_BLOCKS total entries.
    """
    MAX_ENTRIES = 300
    # Blocks this short or shorter are heading candidates (filters out body paragraphs)
    SHORT_THRESHOLD = 40
    TEXT_PREVIEW = 55

    outline: list[dict] = []

    for page in doc.pages:
        for block in page.blocks_in_reading_order():
            if len(outline) >= MAX_ENTRIES:
                break
            raw_text = block.full_text().replace("\n", " ").strip()
            if not raw_text:
                continue

            is_heading_type = block.block_type == BlockType.HEADER
            is_short = len(raw_text) <= SHORT_THRESHOLD

            # Only include heading-typed blocks and genuinely short text blocks.
            # Body paragraphs (long text) are excluded — they can't be headings.
            if is_short or is_heading_type:
                outline.append(
                    {
                        "id": block.block_id,
                        "page": page.page_index + 1,
                        "type": block.block_type.value,
                        "short": is_short,
                        "text": raw_text[:TEXT_PREVIEW],
                    }
                )

        if len(outline) >= MAX_ENTRIES:
            break

    return outline


def _outline_to_text(outline: list[dict]) -> str:
    """Convert the outline list to a plain text table for the prompt.

    Format: ID | page | text
    Avoids embedding JSON-with-Arabic inside the prompt, which can confuse models.
    """
    lines = []
    for entry in outline:
        lines.append(f"{entry['id']} | p{entry['page']} | {entry['text']}")
    return "\n".join(lines)


def _derive_fallback_title(doc: CanonicalDocument) -> str:
    """Derive a title from the source filename when no heading is found."""
    name = doc.source.filename or "Document"
    # Strip common suffixes
    for suffix in ("_canonical.json", "_canonical", ".json", "_ocr"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.replace("_", " ").replace("-", " ").strip()
