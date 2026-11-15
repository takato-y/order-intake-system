"""受注 API（FastAPI）。

n8n の取込フロー・月次バッチから呼ばれる。入力検証と重複判定はすべてこの API で行い、
呼び出し側（n8n）の検証が漏れても不正データが DB に入らないようにする。
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from . import db
from .validation import normalize_received_at, validate_order

logger = logging.getLogger("order_api")
MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


def create_app(db_path: str | None = None) -> FastAPI:
    db_path = db_path or os.environ.get("DB_PATH", "data/orders.db")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = db.connect(db_path)
        db.init_db(conn)
        conn.close()
        yield

    app = FastAPI(title="受注 API", version="1.0.0", lifespan=lifespan)
    app.state.db_path = db_path
    register_routes(app)
    return app


def get_conn(request: Request):
    # SQLite の接続はスレッドをまたいで共有しないよう、リクエストごとに開閉する
    conn = db.connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def register_order(conn: sqlite3.Connection, payload: dict, source: str) -> JSONResponse:
    """検証→登録→応答の共通処理。/orders と /intake/email の両方から使う。"""
    errors = validate_order(payload)
    if errors:
        message_id = payload.get("message_id") if isinstance(payload, dict) else None
        db.insert_rejection(conn, message_id if isinstance(message_id, str) else None, source, errors)
        logger.warning("validation failed message_id=%s errors=%d", message_id, len(errors))
        return JSONResponse(status_code=422, content={"detail": {"errors": errors}})

    order = {**payload, "received_at": normalize_received_at(payload.get("received_at"))}
    saved, created = db.insert_order(conn, order)
    logger.info("order %s message_id=%s", "created" if created else "duplicate", order["message_id"])
    # 重複は失敗ではない。既存の受注を返し、再送した側が成功として扱えるようにする（ADR-0003）
    return JSONResponse(status_code=201 if created else 200,
                        content={"duplicate": not created, "order": saved})


def register_routes(app: FastAPI) -> None:
    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/orders", status_code=201)
    def create_order(payload: dict = Body(...), conn=Depends(get_conn)):
        return register_order(conn, payload, source="api")

    @app.get("/orders")
    def get_orders(month: str | None = Query(None, pattern=MONTH_PATTERN),
                   customer: str | None = Query(None, max_length=100),
                   limit: int = Query(100, ge=1, le=1000),
                   conn=Depends(get_conn)):
        return {"orders": db.list_orders(conn, month, customer, limit)}

    @app.get("/reports/monthly")
    def monthly_report(month: str = Query(..., pattern=MONTH_PATTERN),
                       group_by: Literal["customer", "product", "customer_product"] = "customer_product",
                       conn=Depends(get_conn)):
        rows = db.monthly_summary(conn, month, group_by)
        return {
            "month": month,
            "group_by": group_by,
            "rows": rows,
            "total": {"order_count": sum(r["order_count"] for r in rows),
                      "total_quantity": sum(r["total_quantity"] for r in rows)},
        }

    @app.post("/rejections", status_code=201)
    def create_rejection(payload: dict = Body(...), conn=Depends(get_conn)):
        # n8n のスキーマ検証で不合格になったメールを記録する入口
        errors = payload.get("errors")
        source = payload.get("source", "n8n")
        message_id = payload.get("message_id")
        if not isinstance(errors, list) or not errors or not isinstance(source, str) \
                or not re.fullmatch(r"[a-z0-9_-]{1,20}", source):
            raise HTTPException(422, "errors（1件以上の配列）と source（英小文字20字以内）が必要です")
        if message_id is not None and not isinstance(message_id, str):
            raise HTTPException(422, "message_id は文字列で指定してください")
        errors = [e if isinstance(e, dict) else {"message": str(e)} for e in errors]
        return db.insert_rejection(conn, message_id, source, errors)

    @app.get("/rejections")
    def get_rejections(limit: int = Query(100, ge=1, le=1000), conn=Depends(get_conn)):
        return {"rejections": db.list_rejections(conn, limit)}


app = create_app()
