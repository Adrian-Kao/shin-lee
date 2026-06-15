"""_jurisdiction_for_patent drives both the deadline calendar and the
cross-jurisdiction citation-leak gate (verify_citations), so its mapping is
load-bearing. Pin the country/office-code derivation and the fall-throughs.
"""

from __future__ import annotations

import pytest

from backend.gateway.orchestrator import _jurisdiction_for_patent


@pytest.mark.parametrize(
    "patent_no, expected",
    [
        ("US9999999", "US"),
        ("US-9,999,999", "US"),
        ("us9999999", "US"),  # case-insensitive
        ("  TW I123456 ", "TW"),  # leading/embedded space, stripped + TWI→TW
        ("TWI123456", "TW"),  # TW invention prefix
        ("TWM123456", "TW"),  # TW utility-model prefix
        ("EP1234567", "EP"),
        ("JP2020-123456", "JP"),
        ("CN108765432A", "CN"),
        ("KR1020200012345", "KR"),
        ("WO2021123456", "TW"),  # PCT → home office
        ("DE10201512345", "TW"),  # unsupported jurisdiction → fallback
        ("1234567", "TW"),  # bare numeric must NOT match its digits
        ("", "TW"),
    ],
)
def test_jurisdiction_mapping(patent_no, expected):
    assert _jurisdiction_for_patent(patent_no) == expected


def test_numeric_prefix_does_not_coincidentally_match():
    # Regression: the old [:2] slice would treat the first two CHARS as the code.
    # A letters-only derivation must not classify a digit-led number.
    assert _jurisdiction_for_patent("99-US-thing") == "TW"
