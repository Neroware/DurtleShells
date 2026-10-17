import json
from pathlib import Path

import pytest

from durtleshells.api.models import Subject

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def subject_resources() -> list[dict]:
    return json.loads((FIXTURES / "subjects.json").read_text())


@pytest.fixture(scope="session")
def subjects(subject_resources) -> dict[str, Subject]:
    """Fixture subjects keyed by "<object>:<characters>" (image radical: "radical:<id>")."""
    out = {}
    for r in subject_resources:
        s = Subject.from_resource(r)
        out[f"{s.object}:{s.characters or s.id}"] = s
    return out
