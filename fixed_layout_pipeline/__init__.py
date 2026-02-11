"""
Fixed-Layout OCR Pipeline
=========================

Canonical JSON + Fixed-Layout HTML Overlay architecture for
pixel-accurate reproduction of scanned Arabic/English/French documents.

Primary OCR engine: Azure Document Intelligence (prebuilt-layout)
Architecture: PDF → Rasterise → Preprocess → OCR → Canonical JSON → HTML overlay

Usage:
    from fixed_layout_pipeline import Pipeline, PipelineConfig

    config = PipelineConfig.from_env()
    pipeline = Pipeline(config)
    doc, html_path = pipeline.process("document.pdf")

    # QA loop: edit JSON, regenerate HTML
    pipeline.regenerate_html("output/doc_canonical.json")
"""

from .config import PipelineConfig
from .pipeline import Pipeline, process_pdf
from .schema import CanonicalDocument
from .html_renderer import FixedLayoutRenderer

__version__ = "1.0.0"
__all__ = [
    "Pipeline",
    "PipelineConfig",
    "CanonicalDocument",
    "FixedLayoutRenderer",
    "process_pdf",
]
