"""
Core fixed-layout OCR package exports.

This package is intentionally minimal:
- searchable PDF generation
- OCR JSON export
- pixel-perfect overlay HTML rendering
- async/parallel batch processing
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

__version__ = "1.3.0"

__all__ = [
    "AzureConfig",
    "GeminiConfig",
    "process_one",
    "run_pipeline",
    "generate_searchable_pdf",
    "generate_searchable_pdf_from_bytes",
    "process_one_with_azure_env",
    "generate_searchable_pdf_with_azure_env",
    "generate_searchable_pdf_from_bytes_with_azure_env",
    "render_document_hybrid",
    "render_document_hybrid_v2",
    "render_document_with_formulas",
]

if TYPE_CHECKING:
    from .batch_pipeline import process_one, run_pipeline
    from .config import AzureConfig, GeminiConfig
    from .overlay_renderer import render_document_hybrid, render_document_hybrid_v2, render_document_with_formulas
    from .searchable_pdf import (
        generate_searchable_pdf,
        generate_searchable_pdf_from_bytes,
    )
    from .webapp_api import (
        generate_searchable_pdf_from_bytes_with_azure_env,
        generate_searchable_pdf_with_azure_env,
        process_one_with_azure_env,
    )


def __getattr__(name: str) -> Any:
    if name == "AzureConfig":
        from .config import AzureConfig
        return AzureConfig
    if name == "GeminiConfig":
        from .config import GeminiConfig
        return GeminiConfig
    if name in {"render_document_hybrid", "render_document_hybrid_v2", "render_document_with_formulas"}:
        from .overlay_renderer import render_document_hybrid, render_document_hybrid_v2, render_document_with_formulas
        return {
            "render_document_hybrid": render_document_hybrid,
            "render_document_hybrid_v2": render_document_hybrid_v2,
            "render_document_with_formulas": render_document_with_formulas,
        }[name]
    if name in {"process_one", "run_pipeline"}:
        batch_pipeline = importlib.import_module(".batch_pipeline", __name__)
        return getattr(batch_pipeline, name)
    if name in {"generate_searchable_pdf", "generate_searchable_pdf_from_bytes"}:
        searchable_pdf = importlib.import_module(".searchable_pdf", __name__)
        return getattr(searchable_pdf, name)
    if name in {
        "process_one_with_azure_env",
        "generate_searchable_pdf_with_azure_env",
        "generate_searchable_pdf_from_bytes_with_azure_env",
    }:
        webapp_api = importlib.import_module(".webapp_api", __name__)
        return getattr(webapp_api, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
