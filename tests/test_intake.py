"""メール取込 API（/intake/email・/extract）のテスト。"""
import json
from pathlib import Path

SAMPLES = Path(__file__).resolve().parent.parent / "samples" / "emails"


def email(name):
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


def test_intake_registers_order(client):
    r = client.post("/intake/email", json=email("01_定型_項目名あり.json"))
    assert r.status_code == 201
    o = r.json()["order"]
    assert (o["customer_name"], o["quantity"], o["extractor"]) == ("サンプル商事株式会社", 20, "rule")


def test_resent_email_is_duplicate(client):
    client.post("/intake/email", json=email("01_定型_項目名あり.json"))
    r = client.post("/intake/email", json=email("04_再送メール_重複.json"))
    assert r.status_code == 200 and r.json()["duplicate"] is True


def test_incomplete_email_is_rejected(client):
    r = client.post("/intake/email", json=email("07_数量なし_不備.json"))
    assert r.status_code == 422
    rej = client.get("/rejections").json()["rejections"][0]
    assert rej["source"] == "intake" and rej["errors"][0]["field"] == "数量"


def test_names_are_normalized_across_extractors(client):
    # LLM 経路（全角括弧）と規則経路（半角括弧）で同じ商品が別マスタにならないこと
    base = {"customer_name": "サンプル商事株式会社", "quantity": 1, "due_date": "2026-11-30",
            "received_at": "2026-11-02T10:00:00+09:00"}
    client.post("/orders", json={**base, "message_id": "<n1@example.com>", "product": "ボールペン（黒）", "extractor": "llm"})
    client.post("/orders", json={**base, "message_id": "<n2@example.com>", "product": "ボールペン(黒)", "extractor": "rule"})
    rows = client.get("/reports/monthly", params={"month": "2026-11", "group_by": "product"}).json()["rows"]
    assert rows == [{"customer_name": None, "product": "ボールペン(黒)", "order_count": 2, "total_quantity": 2}]


def test_extract_endpoint_does_not_register(client):
    r = client.post("/extract", json={"subject": "x", "body": email("03_署名から顧客名.json")["body"],
                                       "received_at": "2026-11-09T08:30:00+09:00"})
    assert r.status_code == 200 and r.json()["missing"] == []
    assert client.get("/orders").json()["orders"] == []


def test_intake_input_errors(client):
    assert client.post("/intake/email", json={"message_id": "<x@example.com>"}).status_code == 422
    assert client.post("/intake/email", json={"body": "本文"}).status_code == 422
    assert client.post("/intake/email", json={"message_id": "<x@example.com>", "body": "a" * 20001}).status_code == 413
    assert client.post("/intake/email", json={"message_id": "<x@example.com>", "body": "本文",
                                              "received_at": "昨日"}).status_code == 422
