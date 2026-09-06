from pathlib import Path

import pytest

from turnaround.model import Brief

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def regent() -> Brief:
    return Brief.model_validate_json((EXAMPLES / "regent.json").read_text())


@pytest.fixture
def tiny() -> Brief:
    return Brief.model_validate(
        {
            "house": "Tiny",
            "screens": [{"id": "a", "capacity": 100}, {"id": "b", "capacity": 60}],
            "films": [
                {"id": "x", "title": "X", "runtime_min": 100, "terms": {"min_shows": 2}},
                {
                    "id": "y",
                    "title": "Y",
                    "runtime_min": 90,
                    "weight": 0.5,
                    "terms": {"min_shows": 1},
                },
            ],
            "policy": {"open": "12:00", "last_start": "20:00", "stagger_min": 10},
        }
    )
