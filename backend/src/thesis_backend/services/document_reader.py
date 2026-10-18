"""Native PyMuPDF reading with RapidOCR-only fallback."""
from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Any
from thesis_backend.schemas.extraction import SourceDocument, SourceLine, SourcePage


SECTION_HEADINGS = {
    'summary': {'summary', 'professional summary', 'profile', 'objective', 'career objective', 'about me'},
    'experience': {'experience', 'work experience', 'professional experience', 'employment', 'employment history', 'work history'},
    'education': {'education', 'academic background', 'qualifications'},
    'skills': {'skills', 'technical skills', 'core skills', 'core competencies', 'highlights', 'technical expertise'},
    'coursework': {'coursework', 'relevant coursework', 'courses', 'relevant courses'},
    'awards': {'awards', 'honors', 'honours', 'awards and honors', 'honors and awards', 'achievements'},
    'certifications': {'certifications', 'certificates', 'licenses and certifications', 'professional certifications'},
    'projects': {'projects', 'personal projects', 'academic projects', 'selected projects'},
    'languages': {'languages', 'spoken languages'},
    'research': {'research', 'research experience'},
    'publications': {'publications'},
    'links': {'links', 'social links'},
    'contact': {'contact', 'contact information', 'personal information'},
}


def label_sections(lines):
    """Recognize explicit headings only; keep independent state per column."""
    active = {}
    for line in sorted(lines, key=lambda item: item.reading_order):
        heading = re.sub(r'\s+', ' ', line.text.casefold().strip(' \t:#•')).replace('&', 'and')
        section = next((key for key, names in SECTION_HEADINGS.items() if heading in names), None)
        if section:
            active[line.column] = (section, line.line_id)
        line.section, line.section_id = active.get(line.column, (None, None))
    return lines


def _column_order(indexed, page_width):
    """Detect a strong two-column gutter; otherwise retain row-based order."""
    row_key = lambda item: (item[2][1], item[2][0], item[0])
    if len(indexed) < 12 or not page_width or any(item[2] is None for item in indexed):
        return None
    edges = sorted({item[2][edge] for item in indexed for edge in (0, 2)})
    options = []
    for a, b in zip(edges, edges[1:]):
        split = (a + b) / 2
        if b - a < 8 or not page_width * .25 < split < page_width * .7:
            continue
        left = [item for item in indexed if item[2][2] <= split]
        right = [item for item in indexed if item[2][0] >= split]
        crossings = len(indexed) - len(left) - len(right)
        paired = [l[2][1] for l in left if any(abs(l[2][1] - r[2][1]) < 12 for r in right)]
        if min(len(left), len(right)) >= 4 and len(paired) >= 3 and crossings <= max(4, len(indexed) * .15):
            options.append((min(len(left), len(right)), b - a, split, min(paired)))
    if not options:
        return None
    _, _, split, body_top = max(options)
    header = [item for item in indexed if item[2][1] < body_top - 12]
    body = [item for item in indexed if item not in header]
    result = [(item, 0) for item in sorted(header, key=row_key)]
    band = []

    def flush():
        for column in (1, 2):
            result.extend((item, column) for item in sorted(band, key=row_key)
                          if (1 if item[2][2] <= split else 2) == column)
        band.clear()

    for item in sorted(body, key=row_key):
        if item[2][0] < split < item[2][2]:
            flush()
            result.append((item, 0))
        else:
            band.append(item)
    flush()
    return result

def _pdf_bytes(source: str | Path | bytes) -> bytes:
    maximum = int(os.getenv("CV_MAX_PDF_BYTES", str(25 * 1024 * 1024)))
    if isinstance(source, bytes):
        data = source
    else:
        path = Path(source)
        if path.stat().st_size > maximum:
            raise ValueError(f"PDF exceeds CV_MAX_PDF_BYTES ({maximum})")
        data = path.read_bytes()
    if len(data) > maximum:
        raise ValueError(f"PDF exceeds CV_MAX_PDF_BYTES ({maximum})")
    return data


def has_usable_text(text: str, minimum_characters: int = 100) -> bool:
    compact = "".join(text.split())
    if len(compact) < minimum_characters:
        return False
    readable = sum(character.isprintable() and character != "\ufffd" for character in compact)
    return readable / len(compact) >= 0.95


def _check_render_size(page: Any, dpi: int) -> None:
    scale = dpi / 72
    pixels = page.rect.width * scale * page.rect.height * scale
    maximum = int(os.getenv("CV_MAX_RENDER_PIXELS", "40000000"))
    if pixels > maximum:
        raise ValueError(f"Rendered page exceeds CV_MAX_RENDER_PIXELS ({maximum})")


def _ordered_source_lines(
    candidates: list[tuple[str, tuple[float, float, float, float] | None, float | None]],
    page_number: int,
    source_method: str,
    page_width: float | None = None,
) -> list[SourceLine]:
    indexed = [
        (original_order, text.strip(), bbox, confidence)
        for original_order, (text, bbox, confidence) in enumerate(candidates)
        if text.strip()
    ]
    ordered = sorted(
        indexed,
        key=lambda item: (
            item[2][1] if item[2] else float("inf"),
            item[2][0] if item[2] else item[0],
            item[0],
        ),
    )
    layout = _column_order(indexed, page_width) or [(item, 0) for item in ordered]
    return label_sections([
        SourceLine(
            line_id=f"P{page_number}-L{reading_order:03d}",
            page=page_number,
            text=text,
            bbox=bbox,
            source_method=source_method,
            confidence=confidence,
            original_order=original_order,
            reading_order=reading_order,
            column=column,
        )
        for reading_order, ((original_order, text, bbox, confidence), column) in enumerate(
            layout, 1
        )
    ])


def _native_page_lines(page: Any, page_number: int) -> list[SourceLine]:
    candidates = []
    for block in page.get_text("dict", sort=False)["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            bbox = tuple(float(value) for value in line["bbox"])
            candidates.append((text, bbox, None))
    return _ordered_source_lines(candidates, page_number, "native:pymupdf", page.rect.width)


def _load_ocr_engine():
    from rapidocr import RapidOCR
    return RapidOCR()


def _box_bounds(box: Any, scale: float = 1.0) -> tuple[float, float, float, float] | None:
    try:
        points = list(box)
        xs = [float(point[0]) / scale for point in points]
        ys = [float(point[1]) / scale for point in points]
        return min(xs), min(ys), max(xs), max(ys)
    except (TypeError, ValueError, IndexError):
        return None


def _ocr_page_lines(image_bytes: bytes, page_number: int, dpi: int, runtime: Any,
                    page_width: float | None = None) -> list[SourceLine]:
    candidates: list[tuple[str, tuple[float, float, float, float] | None, float | None]] = []
    scale = dpi / 72
    result = runtime(image_bytes)
    texts = list(result.txts or ())
    boxes = getattr(result, 'boxes', None)
    scores = getattr(result, 'scores', None)
    for index, text in enumerate(texts):
        box = boxes[index] if boxes is not None and index < len(boxes) else None
        score = scores[index] if scores is not None and index < len(scores) else None
        candidates.append((text, _box_bounds(box, scale) if box is not None else None, float(score) if score is not None else None))
    return _ordered_source_lines(candidates, page_number, 'ocr:rapidocr', page_width)


def extract_document(
    pdf: str | Path | bytes,
    *,
    ocr_dpi: int = 200,
    force_ocr: bool = False,
    ocr_runtime: Any | None = None,
) -> SourceDocument:
    """Read explicit UTF-8 text paths, or route PDF pages through native text/OCR."""
    if not isinstance(pdf, bytes) and Path(pdf).suffix.lower() in {".txt", ".md"}:
        text = _pdf_bytes(pdf).decode("utf-8-sig")
        lines = [
            SourceLine(
                line_id=f"P1-L{index + 1:03d}",
                page=1,
                text=line,
                source_method="native:plain_text",
                original_order=index,
                reading_order=index + 1,
            )
            for index, line in enumerate(text.splitlines())
            if line.strip()
        ]
        return SourceDocument(pages=[SourcePage(
            page=1, width=0, height=0, source_method="native:plain_text", lines=label_sections(lines),
        )])
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError("PDF extraction requires PyMuPDF") from exc

    if not 72 <= ocr_dpi <= 400:
        raise ValueError("OCR DPI must be between 72 and 400")
    pages = []
    warnings = []
    with pymupdf.open(stream=_pdf_bytes(pdf), filetype="pdf") as document:
        maximum_pages = int(os.getenv("CV_MAX_PAGES", "20"))
        if len(document) > maximum_pages:
            raise ValueError(f"PDF exceeds CV_MAX_PAGES ({maximum_pages})")
        for page_number, page in enumerate(document, 1):
            native_lines = _native_page_lines(page, page_number)
            native_text = "\n".join(line.text for line in native_lines)
            if not force_ocr and has_usable_text(native_text, minimum_characters=50):
                lines = native_lines
                source_method = "native:pymupdf"
            else:
                ocr_runtime = ocr_runtime or _load_ocr_engine()
                _check_render_size(page, ocr_dpi)
                matrix = pymupdf.Matrix(ocr_dpi / 72, ocr_dpi / 72)
                image = page.get_pixmap(matrix=matrix, alpha=False).tobytes("png")
                lines = _ocr_page_lines(
                    image,
                    page_number,
                    ocr_dpi,
                    ocr_runtime,
                    page.rect.width,
                )
                source_method = "ocr:rapidocr"
                if not lines:
                    warnings.append(f"Page {page_number}: OCR returned no text")
            pages.append(
                SourcePage(
                    page=page_number,
                    width=float(page.rect.width),
                    height=float(page.rect.height),
                    source_method=source_method,
                    lines=lines,
                )
            )
    return SourceDocument(pages=pages, warnings=warnings)

