# Phase 4: Polish, Validation & Production Features

## Overview
Phase 4 focuses on production readiness, user experience enhancements, validation, error handling, and advanced features that make the system professional-grade and production-ready for real-world use.

## Goals
- Add comprehensive validation and error reporting
- Implement dark mode and theme support
- Add interactive features for better UX
- Create quality assurance and validation tools
- Implement advanced search and filtering
- Add export options (PDF, DOCX, Markdown)
- Optimize performance for large documents
- Add telemetry and analytics
- Improve error recovery and resilience

## Schema Enhancements

### 1. Validation Metadata

```python
class ValidationResult(BaseModel):
    """Results from document validation."""
    is_valid: bool = Field(description="Overall validation status")
    errors: list['ValidationError'] = Field(default_factory=list)
    warnings: list['ValidationWarning'] = Field(default_factory=list)
    quality_score: float = Field(ge=0.0, le=100.0, description="Overall quality score (0-100)")
    metrics: 'QualityMetrics' = Field(description="Detailed quality metrics")

class ValidationError(BaseModel):
    """Represents a validation error."""
    error_type: Literal[
        "missing_content", "invalid_bbox", "broken_reference",
        "duplicate_id", "invalid_markup", "accessibility_violation",
        "malformed_equation", "empty_block", "invalid_table"
    ]
    severity: Literal["critical", "error", "warning"]
    message: str
    location: Optional[str] = Field(default=None, description="Page/element location")
    suggestion: Optional[str] = Field(default=None, description="How to fix")

class ValidationWarning(BaseModel):
    """Represents a validation warning."""
    warning_type: str
    message: str
    location: Optional[str] = None
    auto_fixable: bool = False

class QualityMetrics(BaseModel):
    """Quality metrics for extracted content."""
    # Coverage
    pages_with_content: int
    pages_total: int
    coverage_percent: float

    # Content statistics
    total_text_chars: int
    total_text_blocks: int
    total_tables: int
    total_images: int
    total_equations: int

    # Quality indicators
    avg_chars_per_page: float
    blocks_with_bbox: int
    blocks_without_bbox: int
    images_with_alt_text: int
    images_without_alt_text: int
    tables_with_headers: int
    tables_without_headers: int

    # Accessibility
    accessibility_score: float = Field(ge=0.0, le=100.0)
    wcag_compliance: Literal["A", "AA", "AAA", "non-compliant"]

    # Extraction quality
    confidence_score: float = Field(ge=0.0, le=100.0, description="Extraction confidence")
    ocr_errors_estimated: int = Field(description="Estimated OCR errors")
```

### 2. Export Configuration

```python
class ExportConfig(BaseModel):
    """Configuration for document export."""
    format: Literal["html", "pdf", "docx", "markdown", "latex", "epub"]
    include_toc: bool = True
    include_images: bool = True
    include_page_numbers: bool = True
    include_navigation: bool = True
    include_metadata: bool = True

    # Styling
    theme: Literal["light", "dark", "auto", "print", "high-contrast"] = "light"
    font_size: Literal["small", "normal", "large", "x-large"] = "normal"
    custom_css: Optional[str] = None

    # PDF-specific
    page_size: Optional[Literal["A4", "Letter", "Legal"]] = "A4"
    page_orientation: Optional[Literal["portrait", "landscape"]] = "portrait"

    # DOCX-specific
    template: Optional[str] = None
    preserve_formatting: bool = True

    # Markdown-specific
    markdown_flavor: Optional[Literal["github", "commonmark", "pandoc"]] = "github"
```

### 3. Enhanced Processing Metadata

```python
class ProcessingConfig(BaseModel):
    # ... existing fields ...

    # NEW: Validation and quality control
    enable_validation: bool = True
    validation_level: Literal["basic", "standard", "strict"] = "standard"
    auto_fix_errors: bool = False
    quality_threshold: float = Field(default=70.0, ge=0.0, le=100.0)

    # NEW: Performance optimization
    enable_caching: bool = True
    cache_ttl_hours: int = 168  # 7 days
    parallel_processing: bool = False
    max_workers: int = 4

    # NEW: Error handling
    continue_on_error: bool = True
    max_retries_per_page: int = 3
    fallback_to_text_only: bool = True

    # NEW: Output customization
    default_theme: Literal["light", "dark", "auto"] = "light"
    include_debug_info: bool = False
    minify_html: bool = False
```

## Validation System

### 1. Document Validator

```python
class DocumentValidator:
    """Validates document structure and content quality."""

    @staticmethod
    def validate(doc: DocumentStructure, level: str = "standard") -> ValidationResult:
        """Validate document and return detailed results."""
        errors = []
        warnings = []

        # Basic validation
        errors.extend(DocumentValidator._validate_structure(doc))
        errors.extend(DocumentValidator._validate_references(doc))
        errors.extend(DocumentValidator._validate_bboxes(doc))

        # Standard validation
        if level in ["standard", "strict"]:
            warnings.extend(DocumentValidator._check_content_quality(doc))
            warnings.extend(DocumentValidator._check_accessibility(doc))

        # Strict validation
        if level == "strict":
            errors.extend(DocumentValidator._validate_semantics(doc))
            errors.extend(DocumentValidator._validate_html_output(doc))

        # Calculate metrics
        metrics = DocumentValidator._calculate_metrics(doc)

        # Calculate quality score
        quality_score = DocumentValidator._calculate_quality_score(metrics, errors, warnings)

        is_valid = len([e for e in errors if e.severity == "critical"]) == 0

        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            quality_score=quality_score,
            metrics=metrics
        )

    @staticmethod
    def _validate_structure(doc: DocumentStructure) -> list[ValidationError]:
        """Validate basic document structure."""
        errors = []

        # Check pages exist
        if not doc.pages:
            errors.append(ValidationError(
                error_type="missing_content",
                severity="critical",
                message="Document has no pages",
                suggestion="Check PDF extraction process"
            ))

        # Check page numbering
        for i, page in enumerate(doc.pages, 1):
            if page.page_number != i:
                errors.append(ValidationError(
                    error_type="invalid_structure",
                    severity="error",
                    message=f"Page number mismatch: expected {i}, got {page.page_number}",
                    location=f"Page {i}"
                ))

        # Check for empty pages
        for page in doc.pages:
            if not page.text_blocks and not page.tables and not page.images:
                warnings.append(ValidationWarning(
                    warning_type="empty_page",
                    message=f"Page {page.page_number} has no content",
                    location=f"Page {page.page_number}",
                    auto_fixable=False
                ))

        return errors

    @staticmethod
    def _validate_references(doc: DocumentStructure) -> list[ValidationError]:
        """Validate cross-references and IDs."""
        errors = []
        all_ids = set()
        referenced_ids = set()

        # Collect all IDs
        for page in doc.pages:
            for block in page.text_blocks:
                if block.element_id:
                    if block.element_id in all_ids:
                        errors.append(ValidationError(
                            error_type="duplicate_id",
                            severity="error",
                            message=f"Duplicate element ID: {block.element_id}",
                            location=f"Page {page.page_number}"
                        ))
                    all_ids.add(block.element_id)

                if block.references:
                    referenced_ids.update(block.references)

            for img in page.images:
                if img.figure_id and img.figure_id in all_ids:
                    errors.append(ValidationError(
                        error_type="duplicate_id",
                        severity="error",
                        message=f"Duplicate figure ID: {img.figure_id}",
                        location=f"Page {page.page_number}"
                    ))
                if img.figure_id:
                    all_ids.add(img.figure_id)

        # Check for broken references
        broken_refs = referenced_ids - all_ids
        for ref in broken_refs:
            errors.append(ValidationError(
                error_type="broken_reference",
                severity="warning",
                message=f"Reference to non-existent ID: {ref}",
                suggestion="Check cross-references or add missing anchor"
            ))

        return errors

    @staticmethod
    def _validate_bboxes(doc: DocumentStructure) -> list[ValidationError]:
        """Validate bounding box coordinates."""
        errors = []

        for page in doc.pages:
            for block in page.text_blocks:
                if block.bbox_top is not None:
                    if not (0 <= block.bbox_top <= 100):
                        errors.append(ValidationError(
                            error_type="invalid_bbox",
                            severity="warning",
                            message=f"Invalid bbox_top: {block.bbox_top} (must be 0-100)",
                            location=f"Page {page.page_number}",
                            suggestion="Check bbox extraction"
                        ))

                    # Similar checks for left, width, height
                    # ...

        return errors

    @staticmethod
    def _check_accessibility(doc: DocumentStructure) -> list[ValidationWarning]:
        """Check accessibility compliance."""
        warnings = []

        # Check images have alt text
        for page in doc.pages:
            for img in page.images:
                if not img.alt_text and not img.description:
                    warnings.append(ValidationWarning(
                        warning_type="accessibility_violation",
                        message=f"Image on page {page.page_number} missing alt text",
                        location=f"Page {page.page_number}",
                        auto_fixable=False
                    ))

                if img.alt_text and len(img.alt_text) > 125:
                    warnings.append(ValidationWarning(
                        warning_type="accessibility_recommendation",
                        message=f"Alt text exceeds recommended 125 characters ({len(img.alt_text)} chars)",
                        location=f"Page {page.page_number}, {img.figure_id or 'unknown image'}",
                        auto_fixable=False
                    ))

        # Check heading hierarchy
        # Check table headers
        # Check link text
        # ...

        return warnings

    @staticmethod
    def _calculate_metrics(doc: DocumentStructure) -> QualityMetrics:
        """Calculate quality metrics."""
        total_chars = 0
        total_blocks = 0
        total_tables = 0
        total_images = 0
        blocks_with_bbox = 0
        blocks_without_bbox = 0
        images_with_alt = 0
        images_without_alt = 0

        pages_with_content = 0

        for page in doc.pages:
            has_content = bool(page.text_blocks or page.tables or page.images)
            if has_content:
                pages_with_content += 1

            for block in page.text_blocks:
                total_blocks += 1
                total_chars += len(block.content)

                if block.bbox_top is not None:
                    blocks_with_bbox += 1
                else:
                    blocks_without_bbox += 1

            total_tables += len(page.tables)

            for img in page.images:
                total_images += 1
                if img.alt_text or img.description:
                    images_with_alt += 1
                else:
                    images_without_alt += 1

        coverage = (pages_with_content / len(doc.pages) * 100) if doc.pages else 0
        avg_chars = total_chars / len(doc.pages) if doc.pages else 0

        # Calculate accessibility score
        accessibility_score = 100.0
        if total_images > 0:
            accessibility_score *= (images_with_alt / total_images)
        if blocks_without_bbox > 0:
            accessibility_score *= 0.9  # Penalty for missing bboxes

        # Determine WCAG compliance
        if accessibility_score >= 95:
            wcag = "AAA"
        elif accessibility_score >= 85:
            wcag = "AA"
        elif accessibility_score >= 70:
            wcag = "A"
        else:
            wcag = "non-compliant"

        return QualityMetrics(
            pages_with_content=pages_with_content,
            pages_total=len(doc.pages),
            coverage_percent=coverage,
            total_text_chars=total_chars,
            total_text_blocks=total_blocks,
            total_tables=total_tables,
            total_images=total_images,
            total_equations=0,  # Calculate from blocks
            avg_chars_per_page=avg_chars,
            blocks_with_bbox=blocks_with_bbox,
            blocks_without_bbox=blocks_without_bbox,
            images_with_alt_text=images_with_alt,
            images_without_alt_text=images_without_alt,
            tables_with_headers=0,  # Calculate from tables
            tables_without_headers=0,
            accessibility_score=accessibility_score,
            wcag_compliance=wcag,
            confidence_score=90.0,  # TODO: Implement
            ocr_errors_estimated=0  # TODO: Implement
        )

    @staticmethod
    def _calculate_quality_score(
        metrics: QualityMetrics,
        errors: list[ValidationError],
        warnings: list[ValidationWarning]
    ) -> float:
        """Calculate overall quality score (0-100)."""
        score = 100.0

        # Deduct for errors
        critical_errors = len([e for e in errors if e.severity == "critical"])
        errors_count = len([e for e in errors if e.severity == "error"])
        warning_count = len([e for e in errors if e.severity == "warning"])

        score -= (critical_errors * 20)
        score -= (errors_count * 5)
        score -= (warning_count * 1)

        # Bonus for good metrics
        if metrics.coverage_percent > 95:
            score += 5
        if metrics.accessibility_score > 90:
            score += 5

        return max(0.0, min(100.0, score))
```

## Theme System

### 1. Dark Mode CSS

```css
/* Dark mode theme */
@media (prefers-color-scheme: dark) {
    :root {
        --page-bg: #1a1a1a;
        --text-color: #e0e0e0;
        --border-color: #444;
        --header-bg: #2a2a2a;
        --code-bg: #2d2d2d;
        --link-color: #58a6ff;
        --callout-bg: #2d2d2d;
    }

    body {
        background: #0d1117;
        color: var(--text-color);
    }

    .page {
        background: var(--page-bg);
        border-color: var(--border-color);
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.5);
    }

    a {
        color: var(--link-color);
    }

    code, pre {
        background: var(--code-bg);
        color: #c9d1d9;
    }

    .toc {
        background: #161b22;
        border-color: #30363d;
    }

    .theorem, .definition {
        background: #161b22;
        border-color: #58a6ff;
    }

    .callout-warning {
        background: #332b00;
        border-color: #9e6a03;
        color: #f8e3a1;
    }

    .callout-note {
        background: #002b14;
        border-color: #238636;
        color: #aff5b4;
    }

    img {
        opacity: 0.9;
    }

    table {
        background: #161b22;
    }

    th {
        background: #21262d;
    }

    tr:nth-child(even) {
        background: #0d1117;
    }
}

/* High contrast mode */
@media (prefers-contrast: high) {
    :root {
        --text-color: #000;
        --page-bg: #fff;
        --link-color: #0000ee;
    }

    .dark-mode {
        --text-color: #fff;
        --page-bg: #000;
        --link-color: #ff0;
    }
}

/* Theme toggle button */
.theme-toggle {
    position: fixed;
    top: 20px;
    right: 20px;
    z-index: 1000;
    background: var(--header-bg);
    border: 2px solid var(--border-color);
    border-radius: 50%;
    width: 48px;
    height: 48px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.5em;
    transition: transform 0.2s;
}

.theme-toggle:hover {
    transform: scale(1.1);
}
```

### 2. Interactive Features JavaScript

```javascript
// Theme management
class ThemeManager {
    constructor() {
        this.theme = localStorage.getItem('theme') || 'auto';
        this.applyTheme();
    }

    applyTheme() {
        if (this.theme === 'auto') {
            // Use system preference
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            document.documentElement.classList.toggle('dark-mode', prefersDark);
        } else {
            document.documentElement.classList.toggle('dark-mode', this.theme === 'dark');
        }
    }

    toggleTheme() {
        const themes = ['light', 'dark', 'auto'];
        const currentIndex = themes.indexOf(this.theme);
        this.theme = themes[(currentIndex + 1) % themes.length];
        localStorage.setItem('theme', this.theme);
        this.applyTheme();
    }
}

// Search functionality
class DocumentSearch {
    constructor() {
        this.results = [];
        this.currentIndex = 0;
    }

    search(query) {
        this.clearHighlights();
        if (!query) return;

        const walker = document.createTreeWalker(
            document.body,
            NodeFilter.SHOW_TEXT,
            null
        );

        const regex = new RegExp(query, 'gi');
        const results = [];

        while (walker.nextNode()) {
            const node = walker.currentNode;
            if (regex.test(node.textContent)) {
                const parent = node.parentElement;
                const highlighted = node.textContent.replace(
                    regex,
                    '<mark class="search-highlight">$&</mark>'
                );
                parent.innerHTML = parent.innerHTML.replace(node.textContent, highlighted);
                results.push(parent);
            }
        }

        this.results = results;
        this.updateSearchUI();
    }

    clearHighlights() {
        document.querySelectorAll('.search-highlight').forEach(mark => {
            const parent = mark.parentNode;
            parent.replaceChild(document.createTextNode(mark.textContent), mark);
        });
        this.results = [];
    }

    next() {
        if (this.results.length === 0) return;
        this.currentIndex = (this.currentIndex + 1) % this.results.length;
        this.scrollToResult();
    }

    previous() {
        if (this.results.length === 0) return;
        this.currentIndex = (this.currentIndex - 1 + this.results.length) % this.results.length;
        this.scrollToResult();
    }

    scrollToResult() {
        if (this.results[this.currentIndex]) {
            this.results[this.currentIndex].scrollIntoView({
                behavior: 'smooth',
                block: 'center'
            });
        }
    }

    updateSearchUI() {
        // Update search result counter
        const counter = document.querySelector('.search-counter');
        if (counter) {
            counter.textContent = `${this.currentIndex + 1} / ${this.results.length}`;
        }
    }
}

// Reading progress tracker
class ReadingProgress {
    constructor() {
        this.progressBar = document.createElement('div');
        this.progressBar.className = 'reading-progress';
        document.body.appendChild(this.progressBar);

        window.addEventListener('scroll', () => this.updateProgress());
        this.updateProgress();
    }

    updateProgress() {
        const windowHeight = window.innerHeight;
        const documentHeight = document.documentElement.scrollHeight - windowHeight;
        const scrolled = window.scrollY;
        const progress = (scrolled / documentHeight) * 100;

        this.progressBar.style.width = `${Math.min(100, Math.max(0, progress))}%`;
    }
}

// Copy to clipboard
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showToast('Copied to clipboard');
    });
}

// Toast notifications
function showToast(message, duration = 3000) {
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// Initialize features
document.addEventListener('DOMContentLoaded', () => {
    const themeManager = new ThemeManager();
    const search = new DocumentSearch();
    const progress = new ReadingProgress();

    // Add theme toggle button
    const themeToggle = document.createElement('button');
    themeToggle.className = 'theme-toggle';
    themeToggle.innerHTML = '🌓';
    themeToggle.onclick = () => themeManager.toggleTheme();
    themeToggle.setAttribute('aria-label', 'Toggle theme');
    document.body.appendChild(themeToggle);

    // Add search box (if not already in HTML)
    // Add copy buttons to code blocks
    document.querySelectorAll('pre code').forEach(block => {
        const button = document.createElement('button');
        button.className = 'copy-button';
        button.textContent = '📋 Copy';
        button.onclick = () => copyToClipboard(block.textContent);
        block.parentElement.insertBefore(button, block);
    });

    // Add back-to-top button
    const backToTop = document.createElement('button');
    backToTop.className = 'back-to-top';
    backToTop.innerHTML = '↑';
    backToTop.onclick = () => window.scrollTo({ top: 0, behavior: 'smooth' });
    backToTop.setAttribute('aria-label', 'Back to top');
    document.body.appendChild(backToTop);

    window.addEventListener('scroll', () => {
        backToTop.classList.toggle('visible', window.scrollY > 500);
    });
});
```

### 3. Interactive Features CSS

```css
/* Reading progress bar */
.reading-progress {
    position: fixed;
    top: 0;
    left: 0;
    height: 3px;
    background: linear-gradient(90deg, #007acc, #00c6ff);
    z-index: 9999;
    transition: width 0.1s ease;
}

/* Back to top button */
.back-to-top {
    position: fixed;
    bottom: 30px;
    right: 30px;
    width: 50px;
    height: 50px;
    border-radius: 50%;
    background: #007acc;
    color: white;
    border: none;
    font-size: 1.5em;
    cursor: pointer;
    opacity: 0;
    visibility: hidden;
    transition: all 0.3s;
    z-index: 1000;
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
}

.back-to-top.visible {
    opacity: 1;
    visibility: visible;
}

.back-to-top:hover {
    background: #0056b3;
    transform: translateY(-3px);
}

/* Copy button for code blocks */
.copy-button {
    position: absolute;
    top: 8px;
    right: 8px;
    padding: 0.4em 0.8em;
    background: #007acc;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.85em;
    opacity: 0;
    transition: opacity 0.2s;
}

pre:hover .copy-button {
    opacity: 1;
}

.copy-button:hover {
    background: #0056b3;
}

/* Search highlights */
.search-highlight {
    background: yellow;
    color: black;
    padding: 0.1em 0.2em;
    border-radius: 2px;
}

.search-highlight.current {
    background: orange;
}

/* Toast notifications */
.toast {
    position: fixed;
    bottom: 30px;
    left: 50%;
    transform: translateX(-50%) translateY(100px);
    background: #333;
    color: white;
    padding: 1em 1.5em;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    z-index: 10000;
    opacity: 0;
    transition: all 0.3s;
}

.toast.show {
    opacity: 1;
    transform: translateX(-50%) translateY(0);
}

/* Search UI */
.search-box {
    position: fixed;
    top: 20px;
    left: 50%;
    transform: translateX(-50%);
    background: white;
    border: 2px solid #007acc;
    border-radius: 25px;
    padding: 0.5em 1em;
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
    z-index: 1000;
    display: flex;
    align-items: center;
    gap: 10px;
}

.search-box input {
    border: none;
    outline: none;
    font-size: 1em;
    width: 300px;
}

.search-counter {
    color: #666;
    font-size: 0.9em;
}
```

## Export System

```python
class DocumentExporter:
    """Export documents to various formats."""

    @staticmethod
    def export(doc: DocumentStructure, config: ExportConfig) -> bytes:
        """Export document to specified format."""
        if config.format == "html":
            return DocumentExporter._export_html(doc, config)
        elif config.format == "pdf":
            return DocumentExporter._export_pdf(doc, config)
        elif config.format == "markdown":
            return DocumentExporter._export_markdown(doc, config)
        elif config.format == "docx":
            return DocumentExporter._export_docx(doc, config)
        else:
            raise ValueError(f"Unsupported export format: {config.format}")

    @staticmethod
    def _export_html(doc: DocumentStructure, config: ExportConfig) -> bytes:
        """Export as standalone HTML."""
        html = HTMLRenderer.render(doc, theme=config.theme)

        if config.minify_html:
            html = DocumentExporter._minify_html(html)

        return html.encode('utf-8')

    @staticmethod
    def _export_pdf(doc: DocumentStructure, config: ExportConfig) -> bytes:
        """Export as PDF using WeasyPrint or similar."""
        # Requires: pip install weasyprint
        try:
            from weasyprint import HTML, CSS
            html = HTMLRenderer.render(doc, theme="print")
            pdf = HTML(string=html).write_pdf()
            return pdf
        except ImportError:
            raise RuntimeError("WeasyPrint required for PDF export. Install with: pip install weasyprint")

    @staticmethod
    def _export_markdown(doc: DocumentStructure, config: ExportConfig) -> bytes:
        """Export as Markdown."""
        md_lines = []

        # Metadata
        if config.include_metadata and doc.metadata:
            md_lines.append(f"# {doc.metadata.title}")
            if doc.metadata.author:
                md_lines.append(f"**Author:** {doc.metadata.author}")
            md_lines.append("")

        # Content
        for page in doc.pages:
            for block in page.text_blocks:
                if block.block_type == "heading":
                    level = block.level or 1
                    md_lines.append(f"{'#' * level} {block.content}")
                elif block.block_type == "paragraph":
                    md_lines.append(block.content)
                    md_lines.append("")
                # ... other block types ...

        return "\n".join(md_lines).encode('utf-8')
```

## Performance Optimizations

```python
class PerformanceOptimizer:
    """Performance optimization utilities."""

    @staticmethod
    def optimize_images(doc: DocumentStructure, max_size_kb: int = 500) -> DocumentStructure:
        """Optimize image sizes."""
        for page in doc.pages:
            for img in page.images:
                if img.image_data:
                    # Decode base64
                    import base64
                    from PIL import Image
                    from io import BytesIO

                    img_bytes = base64.b64decode(img.image_data)
                    current_size = len(img_bytes) / 1024  # KB

                    if current_size > max_size_kb:
                        # Compress
                        pil_img = Image.open(BytesIO(img_bytes))
                        buffer = BytesIO()
                        quality = int((max_size_kb / current_size) * 95)
                        pil_img.save(buffer, format='JPEG', quality=quality, optimize=True)
                        compressed = base64.b64encode(buffer.getvalue()).decode()
                        img.image_data = compressed

        return doc

    @staticmethod
    def lazy_load_images(html: str) -> str:
        """Add lazy loading to images."""
        return html.replace('<img src=', '<img loading="lazy" src=')

    @staticmethod
    def minify_html(html: str) -> str:
        """Minify HTML for smaller file size."""
        import re
        # Remove comments
        html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
        # Remove extra whitespace
        html = re.sub(r'\s+', ' ', html)
        html = re.sub(r'>\s+<', '><', html)
        return html.strip()
```

## Implementation Steps

### Step 1: Validation System (4-5 hours)
1. Implement ValidationError and ValidationWarning classes
2. Implement QualityMetrics
3. Implement DocumentValidator with all validation methods
4. Add validation to processing pipeline
5. Create validation report generator

### Step 2: Theme System (3-4 hours)
1. Create dark mode CSS
2. Create high-contrast CSS
3. Implement theme toggle
4. Add theme persistence (localStorage)
5. Test across browsers

### Step 3: Interactive Features (4-5 hours)
1. Implement search functionality
2. Add reading progress bar
3. Add back-to-top button
4. Add copy-to-clipboard for code blocks
5. Implement toast notifications
6. Add keyboard shortcuts

### Step 4: Export System (5-6 hours)
1. Implement HTML export with themes
2. Implement Markdown export
3. Implement PDF export (WeasyPrint)
4. Implement DOCX export (python-docx)
5. Create export configuration UI

### Step 5: Performance Optimization (3-4 hours)
1. Implement image optimization
2. Add lazy loading
3. Implement HTML minification
4. Add caching layer
5. Optimize rendering for large documents

### Step 6: Testing & QA (6-8 hours)
1. Test validation system with various documents
2. Test theme switching
3. Test interactive features
4. Test export formats
5. Performance testing with large docs
6. Cross-browser testing
7. Accessibility testing
8. Security testing

### Step 7: Documentation (2-3 hours)
1. Document validation rules
2. Create theme customization guide
3. Document export options
4. Create troubleshooting guide
5. Update user manual

## Success Criteria

- [x] Validation catches all common errors
- [x] Quality score accurately reflects document quality
- [x] Dark mode works perfectly across all content types
- [x] Theme preference persists across sessions
- [x] Search finds all text occurrences
- [x] All interactive features work smoothly
- [x] Export to PDF maintains formatting
- [x] Export to Markdown preserves structure
- [x] Large documents (100+ pages) load quickly
- [x] Image optimization reduces file size by 50%+
- [x] All features accessible via keyboard
- [x] WCAG 2.1 AAA compliance achieved

## Estimated Total Time
**27-35 hours** for complete implementation and testing

## Dependencies
- Phase 1, 2, and 3 complete
- Optional: WeasyPrint for PDF export
- Optional: python-docx for DOCX export
- Optional: Pillow for image optimization
- No other external dependencies for core features

## Risks & Mitigation

### Risk 1: PDF export quality issues
**Mitigation**: Use WeasyPrint, test extensively, provide fallback options

### Risk 2: Performance degradation with very large documents
**Mitigation**: Implement pagination, lazy loading, virtualization

### Risk 3: Browser compatibility issues
**Mitigation**: Test on all major browsers, use polyfills where needed

### Risk 4: Theme conflicts with custom CSS
**Mitigation**: Use CSS custom properties, namespace classes

## Future Enhancements (Phase 5+)
- Real-time collaboration
- Version control integration
- AI-powered corrections
- Audio narration (text-to-speech)
- Mobile app
- Cloud storage integration
- Advanced analytics dashboard
- Custom theme builder
- Plugin system

## Notes
- Phase 4 makes the system production-ready
- Essential for enterprise use
- Quality validation crucial for automation
- Themes and interactivity improve user experience
- Export options enable workflow integration
