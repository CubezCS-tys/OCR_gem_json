"""
Quality Assurance & Evaluation — multi-dimensional fidelity metrics.

From the reference document:
- Text accuracy: CER (Character Error Rate) and WER (Word Error Rate)
- Layout accuracy: IoU-based matching (AP/mAP)
- Reading order: Kendall's Tau distance
- Table structure: TEDS (Tree-Edit-Distance-based Similarity)
- Visual fidelity: SSIM (optional, render HTML → image → compare)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .reading_order import kendall_tau_distance
from .schema import CanonicalDocument, Page, Table

logger = logging.getLogger(__name__)


@dataclass
class TextMetrics:
    """Character-level and word-level error rates."""
    cer: float = 0.0  # Character Error Rate
    wer: float = 0.0  # Word Error Rate
    total_chars: int = 0
    total_words: int = 0
    substitutions: int = 0
    insertions: int = 0
    deletions: int = 0


@dataclass
class LayoutMetrics:
    """Region detection metrics."""
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    mean_iou: float = 0.0
    blocks_predicted: int = 0
    blocks_ground_truth: int = 0


@dataclass
class ReadingOrderMetrics:
    """Reading order evaluation."""
    kendall_tau: float = 0.0  # 0 = identical, 1 = reversed
    kendall_tau_similarity: float = 1.0  # 1 - tau
    blocks_evaluated: int = 0


@dataclass
class TableMetrics:
    """Table structure evaluation."""
    teds: float = 0.0  # Tree-Edit-Distance-based Similarity (0-1)
    tables_evaluated: int = 0


@dataclass
class VisualMetrics:
    """Visual fidelity metrics."""
    ssim: float = 0.0  # Structural Similarity Index (0-1)
    pages_evaluated: int = 0


@dataclass
class QAReport:
    """Complete QA report for a document."""
    document_id: str = ""
    filename: str = ""
    text: Optional[TextMetrics] = None
    layout: Optional[LayoutMetrics] = None
    reading_order: Optional[ReadingOrderMetrics] = None
    tables: Optional[TableMetrics] = None
    visual: Optional[VisualMetrics] = None
    low_confidence_blocks: list[dict] = field(default_factory=list)
    overall_score: float = 0.0

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"QA Report: {self.filename}",
            f"{'='*50}",
        ]
        if self.text:
            lines.append(f"Text:    CER={self.text.cer:.3f}  WER={self.text.wer:.3f}")
        if self.layout:
            lines.append(f"Layout:  F1={self.layout.f1:.3f}  mIoU={self.layout.mean_iou:.3f}")
        if self.reading_order:
            lines.append(f"Reading: Kendall τ={self.reading_order.kendall_tau:.3f} "
                         f"(sim={self.reading_order.kendall_tau_similarity:.3f})")
        if self.tables:
            lines.append(f"Tables:  TEDS={self.tables.teds:.3f} ({self.tables.tables_evaluated} tables)")
        if self.visual:
            lines.append(f"Visual:  SSIM={self.visual.ssim:.3f}")
        lines.append(f"Low confidence blocks: {len(self.low_confidence_blocks)}")
        lines.append(f"Overall score: {self.overall_score:.3f}")
        return "\n".join(lines)


# ─── Text Metrics ────────────────────────────────────────────────────────────

def compute_edit_distance(ref: str, hyp: str) -> tuple[int, int, int, int]:
    """
    Compute Levenshtein edit distance.

    Returns:
        (distance, substitutions, insertions, deletions)
    """
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]

    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(
                    dp[i - 1][j],      # deletion
                    dp[i][j - 1],      # insertion
                    dp[i - 1][j - 1],  # substitution
                )

    # Backtrace for sub/ins/del counts
    subs, ins, dels = 0, 0, 0
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref[i - 1] == hyp[j - 1]:
            i -= 1
            j -= 1
        elif i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
            subs += 1
            i -= 1
            j -= 1
        elif j > 0 and dp[i][j] == dp[i][j - 1] + 1:
            ins += 1
            j -= 1
        else:
            dels += 1
            i -= 1

    return dp[n][m], subs, ins, dels


def compute_cer(reference: str, hypothesis: str) -> TextMetrics:
    """Compute Character Error Rate."""
    if not reference:
        return TextMetrics()

    distance, subs, ins, dels = compute_edit_distance(reference, hypothesis)
    cer = distance / len(reference) if len(reference) > 0 else 0.0

    # WER
    ref_words = reference.split()
    hyp_words = hypothesis.split()
    wer_distance, _, _, _ = compute_edit_distance(
        " ".join(ref_words), " ".join(hyp_words)
    )
    wer = wer_distance / len(ref_words) if ref_words else 0.0

    return TextMetrics(
        cer=min(cer, 1.0),
        wer=min(wer, 1.0),
        total_chars=len(reference),
        total_words=len(ref_words),
        substitutions=subs,
        insertions=ins,
        deletions=dels,
    )


# ─── Layout Metrics ─────────────────────────────────────────────────────────

def compute_layout_metrics(
    predicted_page: Page,
    ground_truth_page: Page,
    iou_threshold: float = 0.5,
) -> LayoutMetrics:
    """Compute IoU-based layout detection metrics."""
    pred_blocks = predicted_page.blocks
    gt_blocks = ground_truth_page.blocks

    if not gt_blocks:
        return LayoutMetrics(blocks_predicted=len(pred_blocks))

    # Match predicted blocks to GT blocks by IoU
    matched_pred = set()
    matched_gt = set()
    total_iou = 0.0

    for gi, gt_block in enumerate(gt_blocks):
        best_iou = 0.0
        best_pi = -1
        for pi, pred_block in enumerate(pred_blocks):
            if pi in matched_pred:
                continue
            iou = gt_block.bbox.iou(pred_block.bbox)
            if iou > best_iou:
                best_iou = iou
                best_pi = pi

        if best_iou >= iou_threshold and best_pi >= 0:
            matched_pred.add(best_pi)
            matched_gt.add(gi)
            total_iou += best_iou

    tp = len(matched_gt)
    precision = tp / len(pred_blocks) if pred_blocks else 0.0
    recall = tp / len(gt_blocks) if gt_blocks else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    mean_iou = total_iou / tp if tp > 0 else 0.0

    return LayoutMetrics(
        precision=precision,
        recall=recall,
        f1=f1,
        mean_iou=mean_iou,
        blocks_predicted=len(pred_blocks),
        blocks_ground_truth=len(gt_blocks),
    )


# ─── Reading Order Metrics ───────────────────────────────────────────────────

def compute_reading_order_metrics(
    predicted_page: Page,
    ground_truth_order: list[str],
) -> ReadingOrderMetrics:
    """Compute reading order accuracy via Kendall Tau."""
    predicted_order = predicted_page.reading_order.sequence

    if not predicted_order or not ground_truth_order:
        return ReadingOrderMetrics()

    tau = kendall_tau_distance(predicted_order, ground_truth_order)

    return ReadingOrderMetrics(
        kendall_tau=tau,
        kendall_tau_similarity=1.0 - tau,
        blocks_evaluated=len(predicted_order),
    )


# ─── Table Metrics (TEDS) ───────────────────────────────────────────────────

def compute_teds(predicted_html: str, ground_truth_html: str) -> float:
    """
    Compute Tree-Edit-Distance-based Similarity (TEDS) for table HTML.

    TEDS measures structural + content similarity of HTML tables.
    Returns a score in [0, 1] where 1 = identical.

    For a full implementation, see: https://github.com/ibm-aur-nlp/PubTabNet
    Here we provide a simplified cosine-similarity-based approximation.
    """
    try:
        from html.parser import HTMLParser

        class TagExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tags = []
                self.data = []

            def handle_starttag(self, tag, attrs):
                self.tags.append(tag)

            def handle_data(self, data):
                self.data.append(data.strip())

        pred_parser = TagExtractor()
        pred_parser.feed(predicted_html)

        gt_parser = TagExtractor()
        gt_parser.feed(ground_truth_html)

        # Simple structural similarity: compare tag sequences
        pred_tags = pred_parser.tags
        gt_tags = gt_parser.tags

        if not gt_tags:
            return 1.0 if not pred_tags else 0.0

        # LCS-based similarity
        lcs_len = _lcs_length(pred_tags, gt_tags)
        structural_sim = 2 * lcs_len / (len(pred_tags) + len(gt_tags)) if (len(pred_tags) + len(gt_tags)) > 0 else 0.0

        # Content similarity
        pred_text = " ".join(pred_parser.data)
        gt_text = " ".join(gt_parser.data)
        if gt_text:
            content_dist, _, _, _ = compute_edit_distance(gt_text, pred_text)
            content_sim = 1.0 - min(content_dist / len(gt_text), 1.0)
        else:
            content_sim = 1.0

        # Combined TEDS approximation
        return 0.6 * structural_sim + 0.4 * content_sim

    except Exception as e:
        logger.warning(f"TEDS computation failed: {e}")
        return 0.0


def _lcs_length(a: list, b: list) -> int:
    """Longest common subsequence length."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[n][m]


# ─── Visual Fidelity (SSIM) ─────────────────────────────────────────────────

def compute_ssim(image_a_path: str, image_b_path: str) -> float:
    """
    Compute Structural Similarity Index between two images.

    Used to detect "layout drift" between the original scan and
    the rendered HTML (captured as a screenshot).
    """
    try:
        import cv2
        import numpy as np
        from skimage.metrics import structural_similarity

        img_a = cv2.imread(image_a_path, cv2.IMREAD_GRAYSCALE)
        img_b = cv2.imread(image_b_path, cv2.IMREAD_GRAYSCALE)

        if img_a is None or img_b is None:
            return 0.0

        # Resize to same dimensions
        h = min(img_a.shape[0], img_b.shape[0])
        w = min(img_a.shape[1], img_b.shape[1])
        img_a = cv2.resize(img_a, (w, h))
        img_b = cv2.resize(img_b, (w, h))

        score, _ = structural_similarity(img_a, img_b, full=True)
        return float(score)

    except ImportError:
        logger.warning("scikit-image not installed, SSIM unavailable")
        return 0.0
    except Exception as e:
        logger.warning(f"SSIM computation failed: {e}")
        return 0.0


# ─── Confidence Flagging ─────────────────────────────────────────────────────

def flag_low_confidence(
    doc: CanonicalDocument,
    threshold: float = 0.80,
) -> list[dict]:
    """
    Flag blocks/tokens with confidence below threshold for manual review.
    """
    flagged = []

    for page in doc.pages:
        for block in page.blocks:
            if block.confidence > 0 and block.confidence < threshold:
                flagged.append({
                    "page": page.page_index,
                    "block_id": block.block_id,
                    "block_type": block.block_type.value,
                    "confidence": block.confidence,
                    "text_preview": block.full_text()[:80],
                })

            for line in block.lines:
                for token in line.tokens:
                    if 0 < token.confidence < threshold:
                        flagged.append({
                            "page": page.page_index,
                            "block_id": block.block_id,
                            "token_id": token.token_id,
                            "confidence": token.confidence,
                            "text": token.text,
                        })

    return flagged


# ─── Full QA Report ──────────────────────────────────────────────────────────

def generate_qa_report(
    doc: CanonicalDocument,
    ground_truth: Optional[CanonicalDocument] = None,
    confidence_threshold: float = 0.80,
) -> QAReport:
    """
    Generate a comprehensive QA report for a processed document.

    Args:
        doc: The processed canonical document.
        ground_truth: Optional ground truth for comparison.
        confidence_threshold: Flag blocks below this confidence.

    Returns:
        QAReport with all available metrics.
    """
    report = QAReport(
        document_id=doc.document_id,
        filename=doc.source.filename,
    )

    # Flag low confidence
    report.low_confidence_blocks = flag_low_confidence(doc, confidence_threshold)

    if ground_truth:
        # Text metrics (page-level, then aggregate)
        all_ref, all_hyp = "", ""
        for pred_page, gt_page in zip(doc.pages, ground_truth.pages):
            all_ref += gt_page.content_text + "\n"
            all_hyp += pred_page.content_text + "\n"

        if all_ref.strip():
            report.text = compute_cer(all_ref.strip(), all_hyp.strip())

        # Reading order metrics
        if ground_truth.pages:
            tau_scores = []
            for pred_page, gt_page in zip(doc.pages, ground_truth.pages):
                if gt_page.reading_order.sequence:
                    rom = compute_reading_order_metrics(
                        pred_page, gt_page.reading_order.sequence
                    )
                    tau_scores.append(rom.kendall_tau)

            if tau_scores:
                avg_tau = sum(tau_scores) / len(tau_scores)
                report.reading_order = ReadingOrderMetrics(
                    kendall_tau=avg_tau,
                    kendall_tau_similarity=1.0 - avg_tau,
                    blocks_evaluated=sum(
                        len(p.blocks) for p in doc.pages
                    ),
                )

    # Overall score: weighted combination of available metrics
    scores = []
    if report.text:
        scores.append(1.0 - report.text.cer)
    if report.reading_order:
        scores.append(report.reading_order.kendall_tau_similarity)
    if report.tables:
        scores.append(report.tables.teds)

    # Confidence-based score (always available)
    conf_score = doc.avg_confidence()
    if conf_score > 0:
        scores.append(conf_score)

    report.overall_score = sum(scores) / len(scores) if scores else 0.0

    return report
