"""データアクセス層のテスト。特に同時登録時の重複防止（REQ-009）を確かめる。"""
import threading

from app import db
from tests.conftest import make_order


def _order(**over):
    o = make_order(**over)
    o["received_at"] = "2026-11-05T09:30:00"
    return o


def test_master_rows_are_reused(db_path):
    conn = db.connect(db_path)
    db.init_db(conn)
    db.insert_order(conn, _order(message_id="<a@example.com>"))
    db.insert_order(conn, _order(message_id="<b@example.com>"))
    assert conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1


def test_concurrent_duplicates_insert_only_once(db_path):
    conn = db.connect(db_path)
    db.init_db(conn)
    conn.close()
    results, barrier = [], threading.Barrier(8)

    def worker():
        c = db.connect(db_path)
        barrier.wait()  # 8 スレッドを同時に走らせ、事前確認方式なら破綻する状況を作る
        results.append(db.insert_order(c, _order())[1])
        c.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1 and results.count(False) == 7
    c = db.connect(db_path)
    assert c.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1


def test_check_constraint_is_not_treated_as_duplicate(db_path):
    # API の検証をすり抜けた不正値は、重複ではなくエラーとして上がること
    import sqlite3
    import pytest
    conn = db.connect(db_path)
    db.init_db(conn)
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_order(conn, _order(quantity=0))


def test_month_range_december():
    assert db.month_range("2026-12") == ("2026-12-01T00:00:00", "2027-01-01T00:00:00")
