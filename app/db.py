"""データアクセス層。

SQL は標準 SQL の範囲で書き、SQL Server へ移すときに変更が必要な箇所
（接続・一意制約違反の例外・採番値の取得）をこのファイルに閉じ込める（ADR-0001）。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .validation import JST

SCHEMA_SQL = Path(__file__).resolve().parent.parent / "sql" / "schema_sqlite.sql"

# 集計の切り口。列名を外部入力から組み立てないよう、許可した組み合わせだけを持つ
GROUP_COLUMNS = {
    "customer": ["c.name"],
    "product": ["p.name"],
    "customer_product": ["c.name", "p.name"],
}


def now_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S")


def connect(db_path: str) -> sqlite3.Connection:
    # API はリクエストごとに接続を開くため check_same_thread は不要だが、
    # 同時書き込み時にすぐ失敗しないよう待ち時間を設ける
    conn = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    conn.commit()


def _get_or_create(conn: sqlite3.Connection, table: str, name: str) -> int:
    # 存在確認→登録の順だと同時実行で一意制約違反になりうるため、
    # 先に登録を試み、違反したら既存行を引く
    row = conn.execute(f"SELECT id FROM {table} WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    try:
        cur = conn.execute(f"INSERT INTO {table} (name, created_at) VALUES (?, ?)", (name, now_jst()))
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return conn.execute(f"SELECT id FROM {table} WHERE name = ?", (name,)).fetchone()["id"]


_ORDER_SELECT = """
SELECT o.id, o.message_id, c.name AS customer_name, p.name AS product,
       o.quantity, o.due_date, o.received_at, o.extractor, o.created_at
FROM orders o
JOIN customers c ON c.id = o.customer_id
JOIN products p ON p.id = o.product_id
"""


def get_order_by_message_id(conn: sqlite3.Connection, message_id: str) -> dict | None:
    row = conn.execute(_ORDER_SELECT + " WHERE o.message_id = ?", (message_id,)).fetchone()
    return dict(row) if row else None


def insert_order(conn: sqlite3.Connection, order: dict) -> tuple[dict, bool]:
    """受注を登録する。戻り値は (受注, 新規登録なら True)。

    重複判定は事前の SELECT ではなく INSERT 時の一意制約違反で行う。
    事前確認方式だと、同じメールが同時に 2 件届いたときに両方が「未登録」と判定されるため。
    """
    try:
        customer_id = _get_or_create(conn, "customers", order["customer_name"])
        product_id = _get_or_create(conn, "products", order["product"])
        conn.execute(
            "INSERT INTO orders (message_id, customer_id, product_id, quantity, due_date,"
            " received_at, extractor, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (order["message_id"], customer_id, product_id, order["quantity"], order["due_date"],
             order["received_at"], order.get("extractor", "manual"), now_jst()),
        )
        conn.commit()
        return get_order_by_message_id(conn, order["message_id"]), True
    except sqlite3.IntegrityError:
        conn.rollback()
        existing = get_order_by_message_id(conn, order["message_id"])
        if existing is None:
            # message_id 以外の制約違反（CHECK 等）は重複ではないので呼び出し元へ伝える
            raise
        return existing, False


def list_orders(conn: sqlite3.Connection, month: str | None = None,
                customer: str | None = None, limit: int = 100) -> list[dict]:
    where, params = [], []
    if month:
        start, end = month_range(month)
        where.append("o.received_at >= ? AND o.received_at < ?")
        params += [start, end]
    if customer:
        where.append("c.name = ?")
        params.append(customer)
    sql = _ORDER_SELECT + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY o.received_at, o.id LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params)]


def month_range(month: str) -> tuple[str, str]:
    """'2026-11' → ('2026-11-01T00:00:00', '2026-12-01T00:00:00')。

    strftime 等の方言関数で月を切り出すと SQL Server へ移せず索引も効かないため、範囲条件にする。
    """
    y, m = (int(x) for x in month.split("-"))
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return f"{y:04d}-{m:02d}-01T00:00:00", f"{ny:04d}-{nm:02d}-01T00:00:00"


def monthly_summary(conn: sqlite3.Connection, month: str, group_by: str) -> list[dict]:
    cols = GROUP_COLUMNS[group_by]
    start, end = month_range(month)
    select_cols = ", ".join(
        f"{c} AS {'customer_name' if c == 'c.name' else 'product'}" for c in cols)
    sql = (f"SELECT {select_cols}, COUNT(*) AS order_count, SUM(o.quantity) AS total_quantity"
           " FROM orders o JOIN customers c ON c.id = o.customer_id"
           " JOIN products p ON p.id = o.product_id"
           " WHERE o.received_at >= ? AND o.received_at < ?"
           f" GROUP BY {', '.join(cols)} ORDER BY {', '.join(cols)}")
    rows = []
    for r in conn.execute(sql, (start, end)):
        d = dict(r)
        d.setdefault("customer_name", None)
        d.setdefault("product", None)
        rows.append(d)
    return rows


def insert_rejection(conn: sqlite3.Connection, message_id: str | None, source: str,
                     errors: list[dict]) -> dict:
    # 本文は保存しない。後から原因を追えるよう、メッセージIDと理由だけを残す
    # 列の長さ上限を超えて JSON が途中で切れないよう、件数と文字数を先に絞る
    trimmed = [{k: str(v)[:200] for k, v in e.items()} for e in errors[:10]]
    text = json.dumps(trimmed, ensure_ascii=False)
    cur = conn.execute(
        "INSERT INTO intake_rejections (message_id, source, errors, created_at) VALUES (?, ?, ?, ?)",
        (message_id, source, text, now_jst()))
    conn.commit()
    return {"id": cur.lastrowid, "message_id": message_id, "source": source, "errors": errors}


def list_rejections(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        "SELECT id, message_id, source, errors, created_at FROM intake_rejections"
        " ORDER BY id DESC LIMIT ?", (limit,))
    return [{**dict(r), "errors": json.loads(r["errors"])} for r in rows]
