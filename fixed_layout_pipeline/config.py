"""
Configuration for the Fixed-Layout OCR Pipeline.

Azure Document Intelligence is the primary geometry OCR engine,
chosen for best-in-class Arabic + English + French support with
word-level bounding boxes, reading order, and table structure.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Auto-load .env from workspace root
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@dataclass
class AzureConfig:
    """Azure Document Intelligence configuration."""
    endpoint: str = field(
        default_factory=lambda: os.environ.get("AZURE_DI_ENDPOINT", "")
    )
    api_key: str = field(
        default_factory=lambda: os.environ.get("AZURE_DI_API_KEY", "")
    )
    # prebuilt-layout: best for structure + geometry + reading order
    # prebuilt-read: best for high-res OCR + optional searchable PDF
    model_id: str = "prebuilt-layout"

    def validate(self) -> None:
        if not self.endpoint:
            raise ValueError(
                "AZURE_DI_ENDPOINT not set. "
                "Export it or pass endpoint= to AzureConfig."
            )
        if not self.api_key:
            raise ValueError(
                "AZURE_DI_API_KEY not set. "
                "Export it or pass api_key= to AzureConfig."
            )


@dataclass
class RasterConfig:
    """Page rasterisation settings."""
    # 300 DPI is standard; 400+ for small Arabic fonts
    dpi: int = 300
    # Output format for page images
    image_format: str = "webp"
    # WebP quality (0-100)
    image_quality: int = 90


@dataclass
class PreprocessConfig:
    """Preprocessing pipeline toggles."""
    deskew: bool = True
    denoise: bool = True
    binarise: bool = False  # Only for very degraded scans
    dewarp: bool = False    # Enable for book scans with curved baselines
    auto_orient: bool = True  # Detect and fix 0/90/180/270 rotation


@dataclass
class RendererConfig:
    """Fixed-layout HTML renderer settings."""
    # Text overlay opacity (0 = invisible/selectable, >0 for debugging)
    text_opacity: float = 1.0
    # Debug mode: show text bboxes with colored borders
    debug_boxes: bool = False
    # Font stack for Arabic text
    arabic_font_stack: str = (
        "'Amiri', 'Noto Naskh Arabic', 'Traditional Arabic', "
        "'Simplified Arabic', 'Tahoma', serif"
    )
    # Font stack for Latin text (English/French)
    latin_font_stack: str = (
        "'Noto Serif', 'Times New Roman', 'Georgia', serif"
    )
    # Include MathJax for equation rendering
    enable_mathjax: bool = True
    # Embed page images as base64 (True) or reference external files (False)
    embed_images: bool = True
    # Scale factor for rendering (1.0 = actual pixel size)
    scale: float = 1.0


@dataclass
class LLMEnrichmentConfig:
    """Optional LLM-based enrichment settings."""
    enabled: bool = False
    # Provider: "gemini" or "mistral"
    provider: str = "gemini"
    gemini_api_key: str = field(
        default_factory=lambda: os.environ.get("GEMINI_API_KEY", "")
    )
    gemini_model: str = field(
        default_factory=lambda: os.environ.get("MODEL_NAME", "gemini-2.0-flash")
    )
    mistral_api_key: str = field(
        default_factory=lambda: os.environ.get("MISTRAL_API_KEY", "")
    )
    mistral_model: str = "mistral-large-latest"
    # What the LLM should help with
    repair_reading_order: bool = True
    enrich_table_structure: bool = False
    semantic_classification: bool = False


@dataclass
class QAConfig:
    """Quality assurance and evaluation settings."""
    # Compute CER/WER when ground truth is available
    compute_text_metrics: bool = True
    # Compute SSIM visual fidelity (render HTML → image → compare)
    compute_visual_fidelity: bool = False
    # Reading order evaluation via Kendall Tau
    compute_reading_order_metrics: bool = True
    # Table structure evaluation via TEDS
    compute_table_metrics: bool = True
    # Confidence threshold below which to flag for review
    confidence_threshold: float = 0.80


@dataclass
class PipelineConfig:
    """Top-level pipeline configuration."""
    azure: AzureConfig = field(default_factory=AzureConfig)
    raster: RasterConfig = field(default_factory=RasterConfig)
    preprocess: PreprocessConfig = field(default_factory=PreprocessConfig)
    renderer: RendererConfig = field(default_factory=RendererConfig)
    llm: LLMEnrichmentConfig = field(default_factory=LLMEnrichmentConfig)
    qa: QAConfig = field(default_factory=QAConfig)

    # I/O paths
    output_dir: Path = Path("output")
    # Keep intermediate files (page images, raw Azure response)
    keep_intermediates: bool = True
    # Extract figures as separate images
    extract_figures: bool = True
    # Max concurrent pages to process
    max_workers: int = 4
    # Logging level
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "PipelineConfig":
        """Create config from environment variables with sensible defaults."""
        return cls(
            azure=AzureConfig(),
            raster=RasterConfig(
                dpi=int(os.environ.get("OCR_DPI", "300")),
            ),
            renderer=RendererConfig(
                debug_boxes=os.environ.get("OCR_DEBUG", "").lower() == "true",
            ),
            llm=LLMEnrichmentConfig(
                enabled=os.environ.get("LLM_ENRICH", "").lower() == "true",
            ),
        )
