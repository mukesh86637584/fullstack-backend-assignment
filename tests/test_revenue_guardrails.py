"""Guardrail: detect duplicate revenue status logic elsewhere in the codebase."""

from pathlib import Path

FORBIDDEN_PATTERNS = [
    "status != 'pending'",
    "status not in",
    "NOT IN ('pending'",
    "exclude_status",
]

ALLOWED_FILE_FRAGMENTS = [
    "revenue_definition.py",
    "test_revenue.py",
]


def test_no_duplicate_revenue_status_logic_in_codebase():
    root = Path(__file__).resolve().parents[1] / "src"
    violations: list[str] = []

    for path in root.rglob("*.py"):
        if any(fragment in str(path) for fragment in ALLOWED_FILE_FRAGMENTS):
            continue
        text = path.read_text()
        for pattern in FORBIDDEN_PATTERNS:
            if pattern in text:
                violations.append(f"{path}: contains forbidden pattern '{pattern}'")

    assert not violations, "Duplicate revenue logic detected:\n" + "\n".join(violations)


def test_revenue_queries_use_shared_filter_builder():
    service_path = Path(__file__).resolve().parents[1] / "src" / "metrics" / "service.py"
    text = service_path.read_text()
    assert "build_revenue_filter_clause" in text
    assert "collected_status_sql_param" in text
    assert "status !=" not in text
    assert "NOT IN" not in text.upper().replace("INSERT", "")
