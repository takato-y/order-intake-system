"""月次バッチのテスト。DB 直接読みと API 経由の両方で同じ出力になることを確かめる。"""
from datetime import datetime

from openpyxl import load_workbook

from app import db
from batch import monthly_report as mr
from tests.conftest import make_order


def _seed(db_path):
    conn = db.connect(db_path)
    db.init_db(conn)
    for mid, cust, prod, qty in [("<1@example.com>", "サンプル商事株式会社", "A4コピー用紙", 20),
                                 ("<2@example.com>", "サンプル商事株式会社", "A4コピー用紙", 15),
                                 ("<3@example.com>", "例示工業株式会社", "ボールペン", 1200)]:
        o = make_order(message_id=mid, customer_name=cust, product=prod, quantity=qty)
        o["received_at"] = "2026-11-05T09:30:00"
        db.insert_order(conn, o)
    conn.close()


def test_previous_month():
    assert mr.previous_month(datetime(2026, 12, 1)) == "2026-11"
    assert mr.previous_month(datetime(2027, 1, 15)) == "2026-12"


def test_run_from_db_writes_csv_and_xlsx(db_path, tmp_path):
    _seed(db_path)
    result = mr.run("2026-11", tmp_path, db_path=db_path)
    assert result["order_count"] == 3 and result["total_quantity"] == 1235

    raw = (tmp_path / "monthly_orders_2026-11.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # Excel 用の BOM
    lines = raw.decode("utf-8-sig").splitlines()
    assert lines[0] == "集計月,顧客名,商品,件数,数量合計"
    assert lines[1] == "2026-11,サンプル商事株式会社,A4コピー用紙,2,35"

    wb = load_workbook(tmp_path / "monthly_orders_2026-11.xlsx")
    assert wb.sheetnames == ["顧客×商品", "顧客別", "商品別"]
    ws = wb["顧客別"]
    assert [c.value for c in ws[ws.max_row]] == ["合計", 3, 1235]
    # 一時ファイルが残っていないこと
    assert not list(tmp_path.glob(".tmp_*"))


def test_api_and_db_paths_match(db_path, tmp_path, client, monkeypatch):
    _seed(db_path)

    def via_testclient(api_url, month, group_by, timeout=30):
        return client.get("/reports/monthly", params={"month": month, "group_by": group_by}).json()["rows"]
    monkeypatch.setattr(mr, "fetch_from_api", via_testclient)
    mr.run("2026-11", tmp_path / "api", api_url="http://test")
    mr.run("2026-11", tmp_path / "db", db_path=db_path)
    assert (tmp_path / "api" / "monthly_orders_2026-11.csv").read_bytes() == \
        (tmp_path / "db" / "monthly_orders_2026-11.csv").read_bytes()


def test_empty_month_writes_header_only(db_path, tmp_path):
    _seed(db_path)
    assert mr.main(["--db", db_path, "--month", "2026-01", "--out-dir", str(tmp_path)]) == 0
    assert (tmp_path / "monthly_orders_2026-01.csv").read_text(encoding="utf-8-sig").splitlines() == \
        ["集計月,顧客名,商品,件数,数量合計"]


def test_exit_codes(tmp_path, monkeypatch):
    assert mr.main(["--month", "2026-13", "--out-dir", str(tmp_path)]) == 2

    # API に接続できない場合は取得失敗で 1（環境による接続待ちを避けるため例外を差し込む）
    def refused(*a, **k):
        raise mr.urllib.error.URLError("connection refused")
    monkeypatch.setattr(mr.urllib.request, "urlopen", refused)
    assert mr.main(["--month", "2026-11", "--out-dir", str(tmp_path)]) == 1
    assert mr.main(["--month", "2026-11", "--db", str(tmp_path / "none.db"), "--out-dir", str(tmp_path)]) == 1


def test_formula_like_names_are_neutralized(client, db_path, tmp_path):
    # 全角の「＝」は登録時の NFKC で「=」になる。帳票を開いた PC で数式として動かないこと
    names = [("<f1@example.com>", "＝HYPERLINK(\"http://example.com\",\"x\")", "=1+1"),
             ("<f2@example.com>", "@SUM(A1)", "+81品番"),
             ("<f3@example.com>", "通常商事株式会社", "-5mm ネジ")]
    for mid, cust, prod in names:
        r = client.post("/orders", json=make_order(message_id=mid, customer_name=cust, product=prod))
        assert r.status_code == 201
    mr.run("2026-11", tmp_path, db_path=db_path)

    import csv
    with (tmp_path / "monthly_orders_2026-11.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))[1:]
    cells = [c for row in rows for c in row[1:3]]
    for c in cells:
        assert not c.startswith(("=", "+", "-", "@")), c
    assert "'=HYPERLINK(\"http://example.com\",\"x\")" in cells
    assert "'=1+1" in cells and "'+81品番" in cells and "'-5mm ネジ" in cells

    wb = load_workbook(tmp_path / "monthly_orders_2026-11.xlsx")
    for ws in wb.worksheets:
        for row in ws.iter_rows(min_row=4):
            for c in row:
                if isinstance(c.value, str):
                    assert c.data_type == "s", (ws.title, c.coordinate, c.value)
    values = [c.value for row in wb["顧客×商品"].iter_rows(min_row=4) for c in row]
    assert '=HYPERLINK("http://example.com","x")' in values and "=1+1" in values


def test_neutralize_csv_unit():
    assert mr.neutralize_csv("=1+1") == "'=1+1"
    assert mr.neutralize_csv("\tx") == "'\tx"
    assert mr.neutralize_csv("普通の名前") == "普通の名前"
    assert mr.neutralize_csv(5) == 5
