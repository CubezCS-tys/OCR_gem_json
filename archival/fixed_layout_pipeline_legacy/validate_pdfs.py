"""
PDF Validator — checks searchable PDFs for corruption.

Uses dual validation (pikepdf + PyPDF2) and can optionally attempt
repair via pikepdf re-linearisation.

Usage (standalone):
    python -m fixed_layout_pipeline validate --input output_searchable
    python -m fixed_layout_pipeline validate --fix

Usage (library):
    from fixed_layout_pipeline.validate_pdfs import validate_directory
    results = validate_directory(Path("output_searchable"))
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def validate_with_pikepdf(pdf_path: Path) -> dict:
    """Validate using pikepdf (structural check)."""
    import pikepdf

    result = {"file": str(pdf_path), "valid": False, "pages": 0, "errors": []}
    try:
        with pikepdf.open(pdf_path) as pdf:
            n = len(pdf.pages)
            result["pages"] = n
            if n == 0:
                result["errors"].append("0 pages")
                return result
            for i, page in enumerate(pdf.pages):
                try:
                    _ = page.obj
                except Exception as e:
                    result["errors"].append(f"Page {i+1}: {e}")
            if not result["errors"]:
                result["valid"] = True
    except Exception as e:
        result["errors"].append(f"{type(e).__name__}: {e}")
    return result


def validate_with_pypdf(pdf_path: Path) -> dict:
    """Validate using PyPDF2 (text extraction check)."""
    from PyPDF2 import PdfReader
    from PyPDF2.errors import PdfReadError

    result = {"file": str(pdf_path), "valid": False, "pages": 0, "errors": []}
    try:
        reader = PdfReader(pdf_path, strict=True)
        n = len(reader.pages)
        result["pages"] = n
        if n == 0:
            result["errors"].append("0 pages")
            return result
        for i, page in enumerate(reader.pages):
            try:
                _ = page.extract_text()
            except Exception as e:
                result["errors"].append(f"Page {i+1}: {e}")
        if not result["errors"]:
            result["valid"] = True
    except PdfReadError as e:
        result["errors"].append(f"PdfReadError: {e}")
    except Exception as e:
        result["errors"].append(f"{type(e).__name__}: {e}")
    return result


def attempt_repair(pdf_path: Path) -> bool:
    """Attempt pikepdf re-linearisation repair."""
    import pikepdf

    backup = pdf_path.with_suffix(".pdf.bak")
    try:
        with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
            shutil.copy2(pdf_path, backup)
            pdf.save(pdf_path, linearize=True)
        logger.info("🔧 Repaired: %s", pdf_path.name)
        return True
    except Exception as e:
        logger.error("🔧 Repair failed %s: %s", pdf_path.name, e)
        if backup.exists():
            shutil.move(str(backup), str(pdf_path))
        return False


def validate_one(pdf_path: Path) -> dict:
    """Validate a single PDF with dual-engine check."""
    if pdf_path.stat().st_size == 0:
        return {"file": str(pdf_path), "valid": False, "pages": 0,
                "errors": ["Empty file (0 bytes)"]}

    r1 = validate_with_pikepdf(pdf_path)
    if r1["valid"]:
        return r1

    r2 = validate_with_pypdf(pdf_path)
    if r2["valid"]:
        r1["errors"].append("(PyPDF2 says OK — minor issue)")
        r1["valid"] = True
        return r1

    r1["errors"] = list(set(r1["errors"] + r2["errors"]))
    return r1


def validate_directory(
    input_dir: Path,
    fix: bool = False,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Validate all PDFs under *input_dir* (recursive).

    Returns (valid, corrupted, empty) lists.
    """
    pdfs = sorted(p for p in input_dir.rglob("*.pdf") if not p.name.endswith(".bak"))
    if not pdfs:
        logger.warning("No PDFs in %s", input_dir)
        return [], [], []

    logger.info("Validating %d PDFs in %s…", len(pdfs), input_dir)
    valid, corrupted, empty = [], [], []

    for pdf in pdfs:
        if pdf.stat().st_size == 0:
            empty.append({"file": str(pdf), "errors": ["Empty file"]})
            logger.warning("⚠️  %s — empty", pdf.name)
            continue

        r = validate_one(pdf)
        if r["valid"]:
            valid.append(r)
            logger.info("✅ %s — %d pages", pdf.name, r["pages"])
        else:
            corrupted.append(r)
            logger.error("❌ %s — %s", pdf.name, "; ".join(r["errors"]))

    # Repair pass
    if fix and corrupted:
        repaired = sum(1 for r in corrupted if attempt_repair(Path(r["file"])))
        logger.info("Repaired %d/%d", repaired, len(corrupted))

    return valid, corrupted, empty


def print_summary(
    valid: list[dict], corrupted: list[dict], empty: list[dict],
) -> None:
    total = len(valid) + len(corrupted) + len(empty)
    print("\n" + "=" * 55)
    print("           PDF VALIDATION SUMMARY")
    print("=" * 55)
    print(f"  Total:      {total}")
    print(f"  ✅ Valid:     {len(valid)}")
    print(f"  ❌ Corrupt:   {len(corrupted)}")
    print(f"  ⚠️  Empty:    {len(empty)}")
    if corrupted:
        print("\n  Corrupted:")
        for r in corrupted:
            print(f"    - {Path(r['file']).name}: {'; '.join(r['errors'])}")
    if empty:
        print("\n  Empty:")
        for r in empty:
            print(f"    - {Path(r['file']).name}")
    print("=" * 55)
