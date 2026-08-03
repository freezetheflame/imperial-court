"""Shared fixtures for protocol-layer tests."""
from pathlib import Path

import pytest

from imperial.institution import Institution, load_institution
from imperial.storage import Storage

INSTITUTION_YAML = Path(__file__).resolve().parent.parent / "institutions" / "sanguan-jiuqing.yaml"


@pytest.fixture
def institution() -> Institution:
    return load_institution(INSTITUTION_YAML)


@pytest.fixture
def storage(tmp_path) -> Storage:
    return Storage(tmp_path / "test.db")


@pytest.fixture
def tmp_db(tmp_path) -> Path:
    return tmp_path / "test.db"
