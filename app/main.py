"""受注 API（FastAPI）。

n8n の取込フロー・月次バッチから呼ばれる。入力検証と重複判定はすべてこの API で行い、
呼び出し側（n8n）の検証が漏れても不正データが DB に入らないようにする。
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import unicodedata
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from . import db
from .extractor import extract
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
    # 抽出方式によって全角・半角が揺れる（「（黒）」と「(黒)」など）と別の顧客・商品として
    # マスタに登録されてしまうため、名称は登録前に NFKC でそろえる
    for key in ("customer_name", "product"):
        order[key] = unicodedata.normalize("NFKC", order[key]).strip()
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

    @app.post("/extract")
    def extract_only(payload: dict = Body(...),
                     mode: Literal["rule", "llm", "auto"] = "rule"):
        # n8n で LLM 呼び出しが失敗したときの代替経路。登録はせず抽出結果だけを返す
        email = _read_email(payload, need_id=False)
        result = extract(email["subject"], email["body"], email["received_date"], mode)
        return {"extractor": result.extractor, "fields": result.fields,
                "missing": result.missing, "llm_error": result.llm_error}

    @app.post("/intake/email")
    def intake_email(payload: dict = Body(...), conn=Depends(get_conn)):
        # n8n を使わない経路（メールサーバからの直接連携・手動取込）向け。抽出→検証→登録を一度に行う
        email = _read_email(payload, need_id=True)
        # 再送メールで LLM を呼び直さないよう、抽出前に登録済みかを確認する。
        # 最終的な重複防止は INSERT 時の一意制約が担う
        existing = db.get_order_by_message_id(conn, email["message_id"])
        if existing:
            return JSONResponse(status_code=200, content={"duplicate": True, "order": existing})
        mode = os.environ.get("EXTRACTOR_MODE", "rule")
        result = extract(email["subject"], email["body"], email["received_date"], mode)
        if result.llm_error:
            logger.warning("LLM fallback message_id=%s reason=%s", email["message_id"], result.llm_error)
        order = {**result.fields, "message_id": email["message_id"],
                 "received_at": email["received_at"], "extractor": result.extractor}
        return register_order(conn, order, source="intake")

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


def _read_email(payload: dict, need_id: bool) -> dict:
    body = payload.get("body")
    if not isinstance(body, str) or not body.strip():
        raise HTTPException(422, "body（メール本文）が必要です")
    if len(body) > 20000:
        raise HTTPException(413, "メール本文が長すぎます（20,000 文字まで）")
    message_id = payload.get("message_id")
    if need_id and (not isinstance(message_id, str) or not re.fullmatch(r"\S{3,255}", message_id)):
        raise HTTPException(422, "message_id（空白を含まない 3〜255 文字）が必要です")
    try:
        received_at = normalize_received_at(payload.get("received_at"))
    except (ValueError, AttributeError):
        raise HTTPException(422, "received_at は ISO 8601 形式で指定してください")
    subject = payload.get("subject") if isinstance(payload.get("subject"), str) else ""
    return {"message_id": message_id, "subject": subject, "body": body,
            "received_at": received_at, "received_date": date.fromisoformat(received_at[:10])}


app = create_app()
