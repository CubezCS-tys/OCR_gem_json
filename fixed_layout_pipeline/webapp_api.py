"""
Stable API surface used by webapp.

Webapp should import from this module instead of reaching into internal
pipeline modules. This allows internal cleanup/refactors without breaking
webapp behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def process_one_with_azure_env(
    pdf_path: Path,
    output_dir: Path,
    *,
    dpi: int = 300,
    render_mode: str = "replace-text",
) -> dict:
    """Run unified Azure batch processing for a single document."""
    from .batch_pipeline import process_one
    from .config import AzureConfig

    cfg = AzureConfig()
    cfg.validate()
    return process_one(
        pdf_path=pdf_path,
        output_dir=output_dir,
        endpoint=cfg.endpoint,
        api_key=cfg.api_key,
        dpi=dpi,
        render_mode=render_mode,
    )


def generate_searchable_pdf_with_azure_env(
    pdf_path: Path,
    output_path: Path,
    *,
    pages: Optional[str] = None,
    output_json_path: Optional[Path] = None,
) -> Path:
    """Generate searchable PDF from a PDF path using Azure env credentials."""
    from .config import AzureConfig
    from .searchable_pdf import generate_searchable_pdf

    cfg = AzureConfig()
    cfg.validate()
    return generate_searchable_pdf(
        pdf_path=pdf_path,
        output_path=output_path,
        config=cfg,
        pages=pages,
        output_json_path=output_json_path,
    )


def generate_searchable_pdf_from_bytes_with_azure_env(
    pdf_bytes: bytes,
    output_path: Path,
    *,
    pages: Optional[str] = None,
    output_json_path: Optional[Path] = None,
) -> Path:
    """Generate searchable PDF from in-memory bytes using Azure env credentials."""
    from .config import AzureConfig
    from .searchable_pdf import generate_searchable_pdf_from_bytes

    cfg = AzureConfig()
    cfg.validate()
    return generate_searchable_pdf_from_bytes(
        pdf_bytes=pdf_bytes,
        output_path=output_path,
        config=cfg,
        pages=pages,
        output_json_path=output_json_path,
    )
