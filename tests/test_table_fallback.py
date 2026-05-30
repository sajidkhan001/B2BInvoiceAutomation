from __future__ import annotations

from b2bdoc.table_fallback import reconstruct_multipage_tables


def test_reconstruct_multipage_tables_removes_repeated_headers_and_merges_split_rows():
    page_one = [
        ["Item", "Description", "Qty", "Unit", "Total"],
        ["1", "Consulting", "2", "100.00", "200.00"],
        ["2", "Long implementation", "", "", ""],
    ]
    page_two = [
        ["Description", "Item", "Qty", "Unit", "Total"],
        ["", "support", "", "", ""],
        ["3", "Hosting", "1", "50.00", "50.00"],
    ]
    result = reconstruct_multipage_tables([page_one, page_two])
    joined = [" | ".join(row) for row in result.rows]
    assert not any("Item | Description" in row for row in joined[1:])
    assert any("Long implementation support" in row for row in joined)
    assert result.confidence > 0.5
