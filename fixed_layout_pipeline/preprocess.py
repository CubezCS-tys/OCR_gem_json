"""
Image Preprocessing — deskew, denoise, dewarp, binarise, orientation detection.

The reference document emphasises:
- "A robust workflow separates preprocessing into explicit stages
  (crop → binarise → deskew → dewarp → segment → recognise)"
- "Dewarping is not optional for many book scans"
- "Do not trust PDF metadata alone for orientation"

Uses OpenCV (cv2) and scikit-image for image processing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from .config import PreprocessConfig

logger = logging.getLogger(__name__)


@dataclass
class PreprocessResult:
    """Result of preprocessing a page image."""
    image: np.ndarray
    rotation_applied: int = 0  # degrees (0, 90, 180, 270)
    was_deskewed: bool = False
    deskew_angle: float = 0.0
    was_denoised: bool = False
    was_binarised: bool = False
    was_dewarped: bool = False
    steps_applied: list[str] = None

    def __post_init__(self):
        if self.steps_applied is None:
            self.steps_applied = []


def load_image_from_bytes(img_bytes: bytes) -> np.ndarray:
    """Load an image from bytes into an OpenCV array."""
    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode image from bytes")
    return img


def to_grayscale(image: np.ndarray) -> np.ndarray:
    """Convert to grayscale if needed."""
    if len(image.shape) == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


# ─── Orientation Detection ───────────────────────────────────────────────────

def detect_orientation(image: np.ndarray) -> int:
    """
    Detect page orientation (0, 90, 180, 270 degrees).

    Uses Tesseract OSD (Orientation and Script Detection) if available,
    otherwise falls back to a simple text-line angle heuristic.

    Returns rotation in degrees to apply to normalize to 0°.
    """
    try:
        import pytesseract
        gray = to_grayscale(image)
        osd = pytesseract.image_to_osd(gray, output_type=pytesseract.Output.DICT)
        rotation = osd.get("rotate", 0)
        confidence = osd.get("orientation_conf", 0)
        logger.info(
            f"OSD detected rotation={rotation}° (confidence={confidence})"
        )
        if confidence > 1.0:  # Tesseract OSD confidence threshold
            return rotation
    except Exception as e:
        logger.debug(f"Tesseract OSD not available: {e}")

    # Fallback: use line angle heuristic
    return _detect_orientation_heuristic(image)


def _detect_orientation_heuristic(image: np.ndarray) -> int:
    """
    Simple heuristic: detect dominant text line angle.
    If lines are mostly vertical, page is likely rotated 90° or 270°.
    """
    gray = to_grayscale(image)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180, threshold=100,
        minLineLength=100, maxLineGap=10
    )

    if lines is None:
        return 0

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi
        angles.append(angle)

    if not angles:
        return 0

    median_angle = np.median(angles)

    # Classify into 0/90/180/270
    if -15 < median_angle < 15:
        return 0
    elif 75 < median_angle < 105:
        return 90
    elif median_angle > 165 or median_angle < -165:
        return 180
    elif -105 < median_angle < -75:
        return 270
    return 0


def apply_rotation(image: np.ndarray, degrees: int) -> np.ndarray:
    """Rotate image by 0/90/180/270 degrees."""
    if degrees == 0:
        return image
    elif degrees == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    elif degrees == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    elif degrees == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image


# ─── Deskew ──────────────────────────────────────────────────────────────────

def detect_skew_angle(image: np.ndarray) -> float:
    """Detect the skew angle of the page (in degrees)."""
    gray = to_grayscale(image)
    # Threshold
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Find coordinates of all text pixels
    coords = np.column_stack(np.where(binary > 0))
    if len(coords) < 100:
        return 0.0

    # Minimum area rectangle
    angle = cv2.minAreaRect(coords)[-1]

    # Normalize angle
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle

    # Clamp to reasonable range
    if abs(angle) > 10:
        logger.warning(f"Skew angle {angle}° exceeds 10°, likely misdetection")
        return 0.0

    return angle


def deskew(image: np.ndarray) -> tuple[np.ndarray, float]:
    """
    Deskew an image by detecting and correcting small rotation.

    Returns:
        (deskewed_image, angle_corrected)
    """
    angle = detect_skew_angle(image)

    if abs(angle) < 0.1:
        return image, 0.0

    logger.info(f"Deskewing by {angle:.2f}°")
    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        image, matrix, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return rotated, angle


# ─── Denoise ─────────────────────────────────────────────────────────────────

def denoise(image: np.ndarray) -> np.ndarray:
    """
    Apply non-local means denoising.
    Effective for scanned document noise without destroying text edges.
    """
    if len(image.shape) == 3:
        return cv2.fastNlMeansDenoisingColored(image, None, 10, 10, 7, 21)
    return cv2.fastNlMeansDenoising(image, None, 10, 7, 21)


# ─── Binarise ────────────────────────────────────────────────────────────────

def binarise(image: np.ndarray) -> np.ndarray:
    """
    Adaptive binarisation for degraded scans.
    Uses Sauvola's method for better handling of uneven lighting.
    """
    gray = to_grayscale(image)
    try:
        from skimage.filters import threshold_sauvola
        thresh = threshold_sauvola(gray, window_size=25)
        binary = (gray > thresh).astype(np.uint8) * 255
        return binary
    except ImportError:
        # Fallback to OpenCV adaptive threshold
        return cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 25, 10
        )


# ─── Dewarp ──────────────────────────────────────────────────────────────────

def dewarp(image: np.ndarray) -> np.ndarray:
    """
    Basic dewarping for book scans with curved baselines.

    Note: Full dewarping is complex. This provides a basic correction
    using text line detection and perspective transform. For production,
    consider using dedicated dewarping libraries (e.g., page_dewarp).
    """
    # This is a simplified placeholder — production dewarping typically
    # uses deep learning models or more sophisticated geometric transforms.
    # For now, we detect dominant curved lines and attempt basic straightening.
    gray = to_grayscale(image)

    # Detect edges
    edges = cv2.Canny(gray, 50, 150)

    # Find contours that might be text lines
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Filter for horizontal-ish contours (potential text lines)
    line_contours = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w > image.shape[1] * 0.3 and h < image.shape[0] * 0.05:
            line_contours.append(cnt)

    if len(line_contours) < 3:
        logger.debug("Not enough text lines detected for dewarping")
        return image

    logger.info(f"Dewarping: detected {len(line_contours)} text line contours")
    # For now, return the original — placeholder for production dewarping
    # TODO: Integrate page_dewarp or a CNN-based dewarper
    return image


# ─── Main Preprocessing Pipeline ─────────────────────────────────────────────

def preprocess_page(
    image: np.ndarray,
    config: PreprocessConfig,
) -> PreprocessResult:
    """
    Run the full preprocessing pipeline on a page image.

    Pipeline order (from the reference document):
    1. Orientation detection & correction
    2. Deskew
    3. Denoise
    4. Dewarp
    5. Binarise (optional, for very degraded scans)

    Args:
        image: Page image as numpy array (BGR or grayscale).
        config: Preprocessing toggles.

    Returns:
        PreprocessResult with processed image and metadata.
    """
    result = PreprocessResult(image=image.copy())

    # 1. Orientation detection
    if config.auto_orient:
        rotation = detect_orientation(image)
        if rotation != 0:
            result.image = apply_rotation(result.image, rotation)
            result.rotation_applied = rotation
            result.steps_applied.append(f"rotate_{rotation}")
            logger.info(f"Applied rotation correction: {rotation}°")

    # 2. Deskew
    if config.deskew:
        result.image, angle = deskew(result.image)
        if abs(angle) > 0.1:
            result.was_deskewed = True
            result.deskew_angle = angle
            result.steps_applied.append("deskew")

    # 3. Denoise
    if config.denoise:
        result.image = denoise(result.image)
        result.was_denoised = True
        result.steps_applied.append("denoise")

    # 4. Dewarp
    if config.dewarp:
        original_shape = result.image.shape
        result.image = dewarp(result.image)
        if result.image.shape != original_shape:
            result.was_dewarped = True
            result.steps_applied.append("dewarp")

    # 5. Binarise
    if config.binarise:
        result.image = binarise(result.image)
        result.was_binarised = True
        result.steps_applied.append("binarise")

    logger.info(f"Preprocessing complete: {result.steps_applied}")
    return result
