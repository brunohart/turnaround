import pytest
from pydantic import ValidationError

from turnaround.model import Brief, Policy, fmt_time, parse_time


def test_parse_time_roundtrip() -> None:
    assert parse_time("19:30") == 1170
    assert fmt_time(1170) == "19:30"
    assert parse_time("25:00") == 1500
    assert fmt_time(1500) == "01:00"


def test_parse_time_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_time("7pm")
    with pytest.raises(ValueError):
        parse_time("19:75")


def test_policy_rejects_inverted_hours() -> None:
    with pytest.raises(ValidationError):
        Policy(open="22:00", last_start="10:00")


def test_brief_rejects_duplicate_ids() -> None:
    with pytest.raises(ValidationError):
        Brief.model_validate(
            {
                "house": "h",
                "screens": [{"id": "1", "capacity": 10}, {"id": "1", "capacity": 10}],
                "films": [{"id": "f", "title": "F", "runtime_min": 90}],
            }
        )


def test_brief_rejects_unknown_screen_in_terms() -> None:
    with pytest.raises(ValidationError):
        Brief.model_validate(
            {
                "house": "h",
                "screens": [{"id": "1", "capacity": 10}],
                "films": [
                    {"id": "f", "title": "F", "runtime_min": 90, "terms": {"screens": ["9"]}}
                ],
            }
        )


def test_block_len_uses_screen_override(regent: Brief) -> None:
    s3 = regent.screen("3")
    f = regent.film("harvest")
    assert regent.block_len(s3, f) == 20 + 104 + 15


def test_can_play_respects_format(regent: Brief) -> None:
    assert regent.can_play(regent.screen("1"), regent.film("odyssey"))
    assert not regent.can_play(regent.screen("2"), regent.film("odyssey"))
    assert not regent.can_play(regent.screen("3"), regent.film("bees"))
