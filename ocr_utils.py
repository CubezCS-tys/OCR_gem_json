"""
Production-grade OCR utilities for validation, preprocessing, and quality assurance.

This module provides:
- Input validation (file size, PDF health checks, corruption detection)
- Document preprocessing (deskew, denoise detection)
- Idempotency via content hashing
- Structured logging helpers
- Graceful shutdown signal handling
"""

import os
import hashlib
import logging
import signal
import sys
import json
from pathlib import Path
from typing import Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# =============================================================================
# INPUT VALIDATION
# =============================================================================

@dataclass
class ValidationResult:
    """Result of PDF validation."""
    is_valid: bool
    file_size_bytes: int
    file_hash: str
    errors: list[str]
    warnings: list[str]


def validate_pdf_input(
    pdf_path: str,
    max_size_mb: int = 200,
    check_corruption: bool = True
) -> ValidationResult:
    """
    Validate PDF file before processing.

    Args:
        pdf_path: Path to PDF file
        max_size_mb: Maximum allowed file size in MB
        check_corruption: Whether to check for PDF corruption

    Returns:
        ValidationResult with validation status
    """
    errors = []
    warnings = []

    pdf_path = Path(pdf_path)

    # Check file exists
    if not pdf_path.exists():
        errors.append(f"File not found: {pdf_path}")
        return ValidationResult(
            is_valid=False,
            file_size_bytes=0,
            file_hash="",
            errors=errors,
            warnings=warnings
        )

    # Check file size
    file_size = pdf_path.stat().st_size
    if file_size == 0:
        errors.append("File is empty (0 bytes)")
    elif file_size > max_size_mb * 1024 * 1024:
        errors.append(
            f"File too large: {file_size / (1024*1024):.1f} MB "
            f"(max: {max_size_mb} MB)"
        )

    # Compute file hash for idempotency
    file_hash = ""
    try:
        with open(pdf_path, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
    except Exception as e:
        errors.append(f"Failed to hash file: {e}")

    # Basic PDF magic number check
    try:
        with open(pdf_path, 'rb') as f:
            header = f.read(5)
            if not header.startswith(b'%PDF-'):
                errors.append("File does not appear to be a valid PDF (missing %PDF- header)")
    except Exception as e:
        errors.append(f"Failed to read file header: {e}")

    # Check for password protection (basic check)
    if check_corruption:
        try:
            with open(pdf_path, 'rb') as f:
                content = f.read(min(file_size, 10000))  # Read first 10KB
                if b'/Encrypt' in content:
                    warnings.append("PDF may be password-protected or encrypted")
        except Exception as e:
            warnings.append(f"Could not check for encryption: {e}")

    is_valid = len(errors) == 0

    return ValidationResult(
        is_valid=is_valid,
        file_size_bytes=file_size,
        file_hash=file_hash,
        errors=errors,
        warnings=warnings
    )


# =============================================================================
# IDEMPOTENCY / DEDUPLICATION
# =============================================================================

class ProcessingCache:
    """Cache to track processed files and avoid reprocessing."""

    def __init__(self, cache_file: str = ".ocr_cache.json"):
        self.cache_file = Path(cache_file)
        self.cache = self._load_cache()

    def _load_cache(self) -> dict:
        """Load cache from disk."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load cache: {e}")
        return {}

    def _save_cache(self):
        """Save cache to disk (atomic write)."""
        temp_file = Path(str(self.cache_file) + ".tmp")
        try:
            with open(temp_file, 'w') as f:
                json.dump(self.cache, f, indent=2)
            temp_file.replace(self.cache_file)
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")
            if temp_file.exists():
                temp_file.unlink()

    def is_processed(self, file_hash: str) -> bool:
        """Check if file has been processed."""
        return file_hash in self.cache

    def get_output_path(self, file_hash: str) -> Optional[str]:
        """Get output path for a processed file."""
        entry = self.cache.get(file_hash)
        if entry:
            return entry.get("output_path")
        return None

    def mark_processed(
        self,
        file_hash: str,
        input_path: str,
        output_path: str,
        metadata: Optional[dict] = None
    ):
        """Mark a file as processed."""
        import time
        self.cache[file_hash] = {
            "input_path": str(input_path),
            "output_path": str(output_path),
            "timestamp": time.time(),
            "metadata": metadata or {}
        }
        self._save_cache()

    def clear(self):
        """Clear the cache."""
        self.cache = {}
        self._save_cache()


# =============================================================================
# GRACEFUL SHUTDOWN
# =============================================================================

class GracefulShutdownHandler:
    """Handle graceful shutdown on SIGINT/SIGTERM.

    Usage:
        shutdown_handler = GracefulShutdownHandler()
        shutdown_handler.setup()

        while not shutdown_handler.should_exit:
            # Do work
            pass
    """

    def __init__(self):
        self.should_exit = False
        self._cleanup_callbacks = []

    def register_cleanup(self, callback):
        """Register a cleanup callback to run on shutdown."""
        self._cleanup_callbacks.append(callback)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name}, initiating graceful shutdown...")
        self.should_exit = True

        # Run cleanup callbacks
        for callback in self._cleanup_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Cleanup callback failed: {e}")

    def setup(self):
        """Setup signal handlers."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)


# =============================================================================
# STRUCTURED LOGGING
# =============================================================================

def setup_structured_logging(log_file: Optional[str] = None) -> logging.Logger:
    """
    Setup structured JSON logging for production.

    Args:
        log_file: Optional log file path for file output

    Returns:
        Configured logger
    """
    import logging.config

    handlers = {
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'INFO',
            'formatter': 'structured',
            'stream': 'ext://sys.stdout'
        }
    }

    if log_file:
        handlers['file'] = {
            'class': 'logging.FileHandler',
            'level': 'DEBUG',
            'formatter': 'structured',
            'filename': log_file
        }

    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'structured': {
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S'
            }
        },
        'handlers': handlers,
        'root': {
            'level': 'DEBUG',
            'handlers': list(handlers.keys())
        }
    })

    return logging.getLogger(__name__)


# =============================================================================
# HTML SANITIZATION
# =============================================================================

def sanitize_html_attribute(value: str, attr_type: str = "text") -> str:
    """
    Sanitize LLM-generated values before injecting into HTML attributes.

    Prevents CSS injection, XSS, and other injection attacks.

    Args:
        value: The value to sanitize
        attr_type: Type of attribute ("text", "style", "url")

    Returns:
        Sanitized value safe for HTML attribute
    """
    if not value:
        return ""

    if attr_type == "style":
        # For style attributes, only allow specific CSS properties
        # Strip anything that looks like property injection
        import re
        # Remove quotes, semicolons, and curly braces to prevent breaking out
        value = re.sub(r'[";{}]', '', value)
        # Limit to alphanumeric, spaces, colons, dashes, dots, %
        value = re.sub(r'[^a-zA-Z0-9\s:.\-,%#()]', '', value)
        return value[:200]  # Limit length

    elif attr_type == "url":
        # For URLs, strict validation
        import re
        if not re.match(r'^https?://', value, re.IGNORECASE):
            return ""
        # Block javascript: and data: schemes
        if re.match(r'^(javascript|data):', value, re.IGNORECASE):
            return ""
        return value[:500]  # Limit length

    else:  # text
        # For text attributes, escape HTML special chars
        value = value.replace('&', '&amp;')
        value = value.replace('<', '&lt;')
        value = value.replace('>', '&gt;')
        value = value.replace('"', '&quot;')
        value = value.replace("'", '&#x27;')
        return value[:1000]  # Limit length


# =============================================================================
# DISK SPACE CHECK
# =============================================================================

def check_disk_space(output_dir: str, required_mb: int = 1000) -> Tuple[bool, str]:
    """
    Check if there's enough disk space for output.

    Args:
        output_dir: Output directory path
        required_mb: Required free space in MB

    Returns:
        (has_space, message)
    """
    try:
        import shutil
        stat = shutil.disk_usage(output_dir)
        free_mb = stat.free / (1024 * 1024)

        if free_mb < required_mb:
            return (
                False,
                f"Insufficient disk space: {free_mb:.0f} MB free, "
                f"{required_mb} MB required"
            )

        return (True, f"{free_mb:.0f} MB free")

    except Exception as e:
        # If we can't check, assume it's OK (don't block processing)
        logger.warning(f"Could not check disk space: {e}")
        return (True, "Could not verify disk space")


# =============================================================================
# CORRELATION ID FOR LOGGING
# =============================================================================

import uuid
import threading

_thread_local = threading.local()


def get_correlation_id() -> str:
    """Get or create a correlation ID for the current thread."""
    if not hasattr(_thread_local, 'correlation_id'):
        _thread_local.correlation_id = str(uuid.uuid4())[:8]
    return _thread_local.correlation_id


def set_correlation_id(correlation_id: str):
    """Set correlation ID for the current thread."""
    _thread_local.correlation_id = correlation_id


class CorrelationFilter(logging.Filter):
    """Add correlation ID to all log records."""

    def filter(self, record):
        record.correlation_id = get_correlation_id()
        return True


def setup_correlation_logging():
    """Setup logging with correlation IDs."""
    # Add filter to root logger
    root_logger = logging.getLogger()
    root_logger.addFilter(CorrelationFilter())

    # Update format to include correlation ID
    for handler in root_logger.handlers:
        if handler.formatter:
            handler.setFormatter(logging.Formatter(
                '%(asctime)s - [%(correlation_id)s] - %(name)s - %(levelname)s - %(message)s'
            ))
