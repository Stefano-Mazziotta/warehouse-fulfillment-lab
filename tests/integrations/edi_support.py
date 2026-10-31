"""Shared access to the sample X12 files under fixtures/edi."""
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "edi"


def fixture(name):
    return (FIXTURES / name).read_text()
