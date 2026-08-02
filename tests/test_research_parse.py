"""Unit tests at the serialization boundary for Lisa parse helpers.

Six cases per phase-5-lisa.md §12.2.
"""

from __future__ import annotations

import pytest

from autopilot.domain.errors import ParseError
from autopilot.domain.parse import (
    _parse_enquiry_output,
    _parse_enquiry_plan,
    parse_coverage_verdict,
)

# --- parse_coverage_verdict ---------------------------------------------------


def test_coverage_satisfied_no_gaps() -> None:
    v = parse_coverage_verdict("COVERAGE: SATISFIED\n")
    assert v.satisfied is True
    assert v.gaps == []


def test_coverage_insufficient_with_gaps() -> None:
    text = """COVERAGE: INSUFFICIENT

## Gaps
- gap one: explanation
- gap two
"""
    v = parse_coverage_verdict(text)
    assert v.satisfied is False
    assert v.gaps == ["gap one: explanation", "gap two"]


def test_coverage_malformed_raises() -> None:
    with pytest.raises(ParseError):
        parse_coverage_verdict("no marker present\n## Gaps\n- x")


# --- _parse_enquiry_plan ------------------------------------------------------


def test_enquiry_plan_n_envelopes_sequential_ids() -> None:
    text = """### ENQUIRY: First
scope line one

### ENQUIRY: Second

### ENQUIRY: Third
"""
    out = _parse_enquiry_plan(text, starting_id=1, iteration=2, cap=10)
    assert len(out) == 3
    assert [e.id for e in out] == ["001", "002", "003"]
    assert all(e.iteration == 2 for e in out)
    assert out[0].question.startswith("First")
    assert "scope line one" in out[0].question


def test_enquiry_plan_prose_only_raises() -> None:
    with pytest.raises(ParseError):
        _parse_enquiry_plan("just some prose, no envelopes", starting_id=1, iteration=1, cap=5)


# --- _parse_enquiry_output ----------------------------------------------------


def test_enquiry_output_extracts_sources_and_findings() -> None:
    text = """## Findings

Body text.

## Sources
- https://example.com/a
- https://example.com/b
"""
    findings, sources = _parse_enquiry_output(text)
    assert "Body text." in findings
    assert "## Sources" not in findings
    assert sources == ["https://example.com/a", "https://example.com/b"]


def test_enquiry_output_no_sources_returns_empty_list() -> None:
    text = "Some findings without a sources section.\n"
    findings, sources = _parse_enquiry_output(text)
    assert "Some findings" in findings
    assert sources == []
