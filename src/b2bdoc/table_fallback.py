from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from decimal import Decimal, InvalidOperation
from typing import Iterable


@dataclass(frozen=True, slots=True)
class TableExtractionResult:
    rows: list[list[str]]
    confidence: float
    strategy: str
    flagged_rows: list[int] = field(default_factory=list)


def normalize_cell(value: object) -> str:
    return " ".join(str(value or "").replace("\n", " ").split())


def normalize_row(row: Iterable[object]) -> list[str]:
    return [normalize_cell(cell) for cell in row]


def _is_blank(row: list[str]) -> bool:
    return not any(cell.strip() for cell in row)


def _row_similarity(left: list[str], right: list[str]) -> float:
    return SequenceMatcher(None, " | ".join(left).lower(), " | ".join(right).lower()).ratio()


def _find_header(rows: list[list[str]]) -> tuple[int | None, list[str] | None]:
    header_words = {
        "item",
        "description",
        "qty",
        "quantity",
        "unit",
        "price",
        "amount",
        "total",
        "tax",
    }
    best_index: int | None = None
    best_score = 0
    best_row: list[str] | None = None
    for index, row in enumerate(rows[:8]):
        words = {cell.lower().strip(":") for cell in row}
        score = len(words & header_words)
        if score > best_score:
            best_index = index
            best_score = score
            best_row = row
    if best_score >= 2:
        return best_index, best_row
    return None, None


def _align_to_width(row: list[str], width: int) -> list[str]:
    if len(row) == width:
        return row
    if len(row) > width:
        head = row[: width - 1]
        tail = " ".join(row[width - 1 :])
        return head + [tail]
    return row + [""] * (width - len(row))


def _looks_like_continuation(row: list[str]) -> bool:
    if not row:
        return False
    first = row[0].strip()
    numeric_cells = sum(1 for cell in row[1:] if _parse_decimal(cell) is not None)
    return first == "" and numeric_cells == 0 and any(cell for cell in row)


def _parse_decimal(value: str) -> Decimal | None:
    cleaned = value.replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _numeric_consistency(rows: list[list[str]]) -> float:
    if not rows:
        return 0.0
    numeric_rows = 0
    consistent_rows = 0
    for row in rows:
        numbers = [_parse_decimal(cell) for cell in row]
        numbers = [number for number in numbers if number is not None]
        if numbers:
            numeric_rows += 1
        if len(numbers) >= 2:
            consistent_rows += 1
    if numeric_rows == 0:
        return 0.4
    return consistent_rows / numeric_rows


def reconstruct_multipage_tables(page_tables: list[list[list[object]]]) -> TableExtractionResult:
    """Rebuild table rows across pages where headers shift or physical pages split rows."""

    normalized_pages = [
        [normalize_row(row) for row in table if not _is_blank(normalize_row(row))]
        for table in page_tables
        if table
    ]
    all_rows: list[list[str]] = []
    flagged_rows: list[int] = []
    canonical_header: list[str] | None = None
    repeated_header_hits = 0
    max_width = 0

    for rows in normalized_pages:
        header_index, header = _find_header(rows)
        if header is not None:
            if canonical_header is None:
                canonical_header = header
                max_width = max(max_width, len(header))
            elif _row_similarity(canonical_header, header) >= 0.65:
                repeated_header_hits += 1
                max_width = max(max_width, len(canonical_header), len(header))
            data_rows = rows[header_index + 1 :] if header_index is not None else rows
        else:
            data_rows = rows

        for row in data_rows:
            max_width = max(max_width, len(row))
            if canonical_header and _row_similarity(canonical_header, row) >= 0.75:
                repeated_header_hits += 1
                continue
            all_rows.append(row)

    if canonical_header is None:
        max_width = max((len(row) for row in all_rows), default=0)

    aligned: list[list[str]] = []
    for row in all_rows:
        row = _align_to_width(row, max_width)
        if aligned and _looks_like_continuation(row):
            previous = aligned[-1]
            for index, cell in enumerate(row):
                if cell:
                    previous[index] = f"{previous[index]} {cell}".strip()
            flagged_rows.append(len(aligned) - 1)
            continue
        aligned.append(row)

    column_stability = 1.0 if not aligned else sum(1 for row in aligned if len(row) == max_width) / len(aligned)
    row_completeness = 1.0 if not aligned else sum(1 for row in aligned if any(row)) / len(aligned)
    continuity = min(1.0, 0.55 + (0.15 * repeated_header_hits) + (0.10 if flagged_rows else 0.0))
    numeric_score = _numeric_consistency(aligned)
    confidence = round(
        max(0.0, min(1.0, (column_stability * 0.30) + (row_completeness * 0.25) + (continuity * 0.20) + (numeric_score * 0.25))),
        3,
    )
    return TableExtractionResult(
        rows=aligned,
        confidence=confidence,
        strategy="multipage_header_alignment",
        flagged_rows=flagged_rows,
    )


def choose_best_table(candidates: list[TableExtractionResult]) -> TableExtractionResult:
    if not candidates:
        return TableExtractionResult(rows=[], confidence=0.0, strategy="none")
    return max(candidates, key=lambda item: (item.confidence, len(item.rows)))
