"""テスト共通の準備。DB は一時ファイルを使い、テストごとに作り直す。"""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def client(db_path):
    with TestClient(create_app(db_path)) as c:
        yield c


def make_order(**over):
    base = {
        "message_id": "<order-001@example.com>",
        "customer_name": "サンプル商事株式会社",
        "product": "A4コピー用紙",
        "quantity": 20,
        "due_date": "2026-11-20",
        "received_at": "2026-11-05T09:30:00+09:00",
        "extractor": "rule",
    }
    base.update(over)
    return base
