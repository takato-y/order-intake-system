"""受注 API のテスト（正常・入力不正・重複・集計）。"""
from tests.conftest import make_order


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_order_returns_201(client):
    r = client.post("/orders", json=make_order())
    assert r.status_code == 201
    body = r.json()
    assert body["duplicate"] is False
    assert body["order"]["customer_name"] == "サンプル商事株式会社"
    # タイムゾーン付きの受信日時は JST にそろえて保存される
    assert body["order"]["received_at"] == "2026-11-05T09:30:00"


def test_utc_received_at_is_converted_to_jst(client):
    r = client.post("/orders", json=make_order(received_at="2026-10-31T16:00:00Z"))
    assert r.json()["order"]["received_at"] == "2026-11-01T01:00:00"


def test_duplicate_message_id_returns_existing(client):
    first = client.post("/orders", json=make_order())
    second = client.post("/orders", json=make_order(quantity=999))
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    # 2 回目の内容で上書きされず、初回の受注が返る
    assert second.json()["order"] == first.json()["order"]
    assert len(client.get("/orders").json()["orders"]) == 1


def test_missing_field_is_rejected_and_recorded(client):
    payload = make_order()
    del payload["product"]
    r = client.post("/orders", json=payload)
    assert r.status_code == 422
    assert {"field": "商品", "message": "必須項目がありません"} in r.json()["detail"]["errors"]
    rej = client.get("/rejections").json()["rejections"]
    assert rej[0]["message_id"] == "<order-001@example.com>"
    assert rej[0]["source"] == "api"
    assert client.get("/orders").json()["orders"] == []


def test_invalid_values_are_rejected(client):
    cases = [
        make_order(quantity=0),
        make_order(quantity="20"),
        make_order(quantity=100001),
        make_order(due_date="2026/11/20"),
        make_order(due_date="2026-02-30"),
        make_order(due_date="2026-11-01"),  # 受信日（11/05）より前
        make_order(customer_name=""),
        make_order(message_id="has space"),
        make_order(unknown="x"),
    ]
    for payload in cases:
        r = client.post("/orders", json=payload)
        assert r.status_code == 422, payload
    assert client.get("/orders").json()["orders"] == []
    assert len(client.get("/rejections").json()["rejections"]) == len(cases)


def test_non_object_body_is_rejected(client):
    assert client.post("/orders", json=["x"]).status_code == 422


def test_list_orders_filters_by_month_and_customer(client):
    client.post("/orders", json=make_order(message_id="<a@example.com>"))
    client.post("/orders", json=make_order(message_id="<b@example.com>", customer_name="例示工業株式会社"))
    client.post("/orders", json=make_order(message_id="<c@example.com>",
                                           received_at="2026-12-01T00:00:00+09:00",
                                           due_date="2026-12-10"))
    assert len(client.get("/orders", params={"month": "2026-11"}).json()["orders"]) == 2
    only = client.get("/orders", params={"month": "2026-11", "customer": "例示工業株式会社"}).json()["orders"]
    assert [o["message_id"] for o in only] == ["<b@example.com>"]
    assert client.get("/orders", params={"month": "2026-13"}).status_code == 422


def test_monthly_report_groups(client):
    orders = [
        ("<1@example.com>", "サンプル商事株式会社", "A4コピー用紙", 20),
        ("<2@example.com>", "サンプル商事株式会社", "A4コピー用紙", 10),
        ("<3@example.com>", "サンプル商事株式会社", "ボールペン（黒）", 100),
        ("<4@example.com>", "例示工業株式会社", "A4コピー用紙", 5),
    ]
    for mid, cust, prod, qty in orders:
        client.post("/orders", json=make_order(message_id=mid, customer_name=cust, product=prod, quantity=qty))
    # 月の境界: 10/31 23:59 の受注は 11 月に入らない
    client.post("/orders", json=make_order(message_id="<5@example.com>", received_at="2026-10-31T23:59:59+09:00"))

    r = client.get("/reports/monthly", params={"month": "2026-11"}).json()
    assert r["total"] == {"order_count": 4, "total_quantity": 135}
    assert r["rows"][0] == {"customer_name": "サンプル商事株式会社", "product": "A4コピー用紙",
                            "order_count": 2, "total_quantity": 30}

    by_customer = client.get("/reports/monthly", params={"month": "2026-11", "group_by": "customer"}).json()
    assert [(x["customer_name"], x["total_quantity"]) for x in by_customer["rows"]] == \
        [("サンプル商事株式会社", 130), ("例示工業株式会社", 5)]
    by_product = client.get("/reports/monthly", params={"month": "2026-11", "group_by": "product"}).json()
    assert {x["product"]: x["order_count"] for x in by_product["rows"]} == {"A4コピー用紙": 3, "ボールペン(黒)": 1}


def test_monthly_report_rejects_bad_params(client):
    assert client.get("/reports/monthly").status_code == 422
    assert client.get("/reports/monthly", params={"month": "2026-11", "group_by": "x"}).status_code == 422


def test_empty_month_returns_zero(client):
    r = client.get("/reports/monthly", params={"month": "2026-01"}).json()
    assert r["rows"] == [] and r["total"] == {"order_count": 0, "total_quantity": 0}


def test_rejection_endpoint_validates_input(client):
    ok = client.post("/rejections", json={"message_id": "<x@example.com>", "source": "n8n",
                                          "errors": [{"field": "数量", "message": "必須項目がありません"}]})
    assert ok.status_code == 201
    assert client.post("/rejections", json={"source": "n8n", "errors": []}).status_code == 422
    assert client.post("/rejections", json={"source": "N8N!", "errors": ["x"]}).status_code == 422
