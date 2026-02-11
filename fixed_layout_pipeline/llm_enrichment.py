"""
Optional LLM Enrichment — use LLMs for reading order repair,
not as the source of geometric truth.

From the reference document:
  "Use LLM/VLM outputs as semantic enrichment or fallback, not as
   the canonical geometric truth."

  "A practical 'LLM assist' pattern is: take deterministic OCR + layout
   outputs (tokens/boxes/tables), then ask an LLM to propose reading order
   or structured grouping—but force it to reference element IDs only,
   not generate new text."
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from .config import LLMEnrichmentConfig
from .schema import (
    Direction,
    Page,
    ReadingOrder,
    ReadingOrderMethod,
    ReadingOrderUnit,
)

logger = logging.getLogger(__name__)


# ─── Reading Order Repair Prompt ─────────────────────────────────────────────

READING_ORDER_PROMPT = """You are given OCR blocks with IDs, bounding boxes, direction, and text.
Task: output a JSON object with a single field "sequence" listing the block IDs
in the correct human reading order for this page.

Rules:
- Do not change any text.
- Do not invent new IDs.
- Respect Arabic RTL reading conventions.
- For multi-column layouts, read right column first in RTL documents.
- Prefer column-wise reading consistent with the layout.
- Headers before body content, footnotes/footers at end.
- Tables are read as a single unit at their position.

Provide only valid JSON.

Page direction: {page_direction}
Page dimensions: {page_width}px × {page_height}px

Blocks:
{blocks_json}

Output format:
{{"sequence": ["block_id_1", "block_id_2", ...]}}
"""


def enrich_reading_order(
    page: Page,
    config: LLMEnrichmentConfig,
) -> Optional[ReadingOrder]:
    """
    Use an LLM to repair/improve reading order.

    Sends block IDs, bboxes, and text previews to the LLM.
    The LLM returns only a sequence of IDs — no new text.

    Args:
        page: Page with blocks to reorder.
        config: LLM enrichment settings.

    Returns:
        ReadingOrder if successful, None otherwise.
    """
    if not page.blocks:
        return None

    # Build blocks description for the prompt
    blocks_desc = []
    for block in page.blocks:
        text_preview = block.full_text()[:100]
        blocks_desc.append({
            "block_id": block.block_id,
            "type": block.block_type.value,
            "bbox": {
                "x0": round(block.bbox.x0),
                "y0": round(block.bbox.y0),
                "x1": round(block.bbox.x1),
                "y1": round(block.bbox.y1),
            },
            "direction": block.direction.value,
            "language": block.language or "ar",
            "text_preview": text_preview,
        })

    prompt = READING_ORDER_PROMPT.format(
        page_direction=page.principal_direction.value,
        page_width=page.image.width_px,
        page_height=page.image.height_px,
        blocks_json=json.dumps(blocks_desc, ensure_ascii=False, indent=2),
    )

    # Call LLM
    try:
        if config.provider == "gemini":
            response_text = _call_gemini(prompt, config)
        elif config.provider == "mistral":
            response_text = _call_mistral(prompt, config)
        else:
            logger.warning(f"Unknown LLM provider: {config.provider}")
            return None

        if not response_text:
            return None

        # Parse response
        return _parse_reading_order_response(response_text, page)

    except Exception as e:
        logger.error(f"LLM enrichment failed: {e}")
        return None


def _parse_reading_order_response(
    response_text: str,
    page: Page,
) -> Optional[ReadingOrder]:
    """Parse the LLM's reading order response and validate it."""
    try:
        # Clean up response (remove markdown code fences if present)
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        data = json.loads(text)
        sequence = data.get("sequence", [])

        if not sequence:
            logger.warning("LLM returned empty sequence")
            return None

        # Validate: all IDs must exist in the page's blocks
        block_ids = {b.block_id for b in page.blocks}
        invalid_ids = [sid for sid in sequence if sid not in block_ids]
        if invalid_ids:
            logger.warning(f"LLM returned invalid block IDs: {invalid_ids}")
            # Filter out invalid IDs
            sequence = [sid for sid in sequence if sid in block_ids]

        # Check all blocks are included
        missing_ids = block_ids - set(sequence)
        if missing_ids:
            logger.warning(f"LLM missed {len(missing_ids)} blocks, appending")
            sequence.extend(sorted(missing_ids))

        # Check for duplicates
        seen = set()
        deduped = []
        for sid in sequence:
            if sid not in seen:
                deduped.append(sid)
                seen.add(sid)
        sequence = deduped

        # Build ReadingOrder
        units = []
        for block_id in sequence:
            block = next((b for b in page.blocks if b.block_id == block_id), None)
            units.append(ReadingOrderUnit(
                unit_id=block_id,
                ref_block_id=block_id,
                ref_table_id=block.table.table_id if block and block.table else None,
            ))

        return ReadingOrder(
            units=units,
            sequence=sequence,
            confidence=0.75,
            method=ReadingOrderMethod.MODEL,
        )

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        return None


# ─── LLM Provider Calls ─────────────────────────────────────────────────────

def _call_gemini(prompt: str, config: LLMEnrichmentConfig) -> Optional[str]:
    """Call Google Gemini API."""
    try:
        import google.generativeai as genai

        genai.configure(api_key=config.gemini_api_key)
        model = genai.GenerativeModel(config.gemini_model)

        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                max_output_tokens=4096,
            ),
        )

        return response.text

    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        return None


def _call_mistral(prompt: str, config: LLMEnrichmentConfig) -> Optional[str]:
    """Call Mistral API."""
    try:
        from mistralai import Mistral

        client = Mistral(api_key=config.mistral_api_key)

        response = client.chat.complete(
            model=config.mistral_model,
            messages=[
                {"role": "system", "content": "You are a document layout analysis expert. Output only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=4096,
        )

        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"Mistral API call failed: {e}")
        return None
