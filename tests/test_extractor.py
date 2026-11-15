"""抽出処理のテスト。LLM は通信部分を差し替え、実サービスなしで動くようにする。"""
import io
import json
import os
from datetime import date
from pathlib import Path

import pytest

from app import extractor
from app.extractor import extract, extract_rule, parse_due_date

SAMPLES = Path(__file__).resolve().parent.parent / "samples" / "emails"


def load(name):
    e = json.loads((SAMPLES / name).read_text(encoding="utf-8"))
    return e["subject"], e["body"], date.fromisoformat(e["received_at"][:10])


def test_labeled_email():
    r = extract_rule(*load("01_定型_項目名あり.json"))
    assert r.fields == {"customer_name": "サンプル商事株式会社", "product": "A4コピー用紙(500枚×5冊)",
                        "quantity": 20, "due_date": "2026-11-10"}
    assert r.missing == []


def test_bracket_labels_and_signature_company():
    r = extract_rule(*load("02_隅付き括弧の項目名.json"))
    # 宛名（当社）ではなく差出人の会社名を採ること
    assert r.fields["customer_name"] == "例示工業株式会社"
    assert r.fields["quantity"] == 1200
    assert r.fields["due_date"] == "2026-11-20"


def test_signature_company_at_bottom():
    r = extract_rule(*load("03_署名から顧客名.json"))
    assert r.fields == {"customer_name": "見本トレーディング合同会社", "product": "クリアファイル A4 透明",
                        "quantity": 300, "due_date": "2026-11-25"}


def test_narrative_email_is_incomplete_with_rule():
    r = extract_rule(*load("06_文章形式_項目名なし.json"))
    assert set(r.missing) == {"product", "quantity", "due_date"}


def test_missing_quantity_is_reported():
    r = extract_rule(*load("07_数量なし_不備.json"))
    assert r.missing == ["quantity"]


@pytest.mark.parametrize("text,received,expected", [
    ("2026年11月10日", date(2026, 11, 1), "2026-11-10"),
    ("２０２６／１１／２５", date(2026, 11, 1), "2026-11-25"),
    ("11/20（金）", date(2026, 11, 4), "2026-11-20"),
    ("1月10日", date(2026, 12, 20), "2027-01-10"),  # 年またぎ
    ("2026年2月30日", date(2026, 1, 5), None),        # 存在しない日付
    ("なるべく早く", date(2026, 11, 1), None),
])
def test_parse_due_date(text, received, expected):
    assert parse_due_date(text, received) == expected


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_llm(content: dict):
    def urlopen(req, timeout):
        sent = json.loads(req.data)
        assert sent["format"]["required"] == list(extractor.FIELDS)  # JSON 形式の強制を渡していること
        return _FakeResponse(json.dumps({"message": {"content": json.dumps(content, ensure_ascii=False)}}).encode())
    return urlopen


def test_llm_success(monkeypatch):
    monkeypatch.setattr(extractor.urllib.request, "urlopen", _fake_llm(
        {"customer_name": "試験精機株式会社", "product": "付箋（75mm角・黄色）", "quantity": "50冊", "due_date": "11月28日"}))
    r = extract(*load("06_文章形式_項目名なし.json"), mode="auto")
    assert r.extractor == "llm"
    assert r.fields["quantity"] == 50 and r.fields["due_date"] == "2026-11-28"


def test_auto_falls_back_when_llm_down(monkeypatch):
    def down(req, timeout):
        raise OSError("connection refused")
    monkeypatch.setattr(extractor.urllib.request, "urlopen", down)
    r = extract(*load("01_定型_項目名あり.json"), mode="auto")
    assert r.extractor == "rule" and r.missing == []
    assert "connection refused" in r.llm_error


def test_auto_falls_back_when_llm_incomplete(monkeypatch):
    monkeypatch.setattr(extractor.urllib.request, "urlopen", _fake_llm(
        {"customer_name": "サンプル商事株式会社", "product": None, "quantity": None, "due_date": None}))
    r = extract(*load("01_定型_項目名あり.json"), mode="auto")
    assert r.extractor == "rule" and "不足項目" in r.llm_error


@pytest.mark.skipif(os.environ.get("OLLAMA_TEST") != "1", reason="実際の Ollama を使う試験は OLLAMA_TEST=1 のときだけ")
def test_real_ollama_narrative_email():
    r = extract(*load("06_文章形式_項目名なし.json"), mode="llm")
    assert r.missing == [], r.fields
    assert r.fields["quantity"] == 50 and r.fields["due_date"] == "2026-11-28"
