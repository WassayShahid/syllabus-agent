import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("BUCKET_NAME", "test-bucket")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")


class FakeTable:
    """Records update_item calls; enough for handlers that only write META."""

    def __init__(self):
        self.updates = []

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        return {"Attributes": {}}


@pytest.fixture
def fake_table(monkeypatch):
    from lib import aws
    table = FakeTable()
    monkeypatch.setattr(aws, "table", lambda: table)
    return table
