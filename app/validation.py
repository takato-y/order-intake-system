"""受注データの検証。

JSON スキーマ（order_schema.json）を唯一の定義とし、n8n 側と同じ規則で判定する。
スキーマで表せない業務ルール（実在する日付か、納期が受信日より前でないか）は
ここで追加検査する。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).with_name("order_schema.json")
ORDER_SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
_validator = Draft202012Validator(ORDER_SCHEMA)

# 業務は日本国内のため、受信日時は日本時間に揃えて保存する（月の区切りを JST で判定するため）
JST = timezone(timedelta(hours=9))

FIELD_LABELS = {
    "message_id": "メッセージID",
    "customer_name": "顧客名",
    "product": "商品",
    "quantity": "数量",
    "due_date": "希望納期",
    "received_at": "受信日時",
    "extractor": "抽出方式",
}


def _label(path) -> str:
    key = path[0] if path else ""
    return FIELD_LABELS.get(key, str(key) or "全体")


def normalize_received_at(value: str | None) -> str:
    """受信日時を JST の 'YYYY-MM-DDTHH:MM:SS' にそろえる。省略時は現在時刻。"""
    if not value:
        return datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(JST)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def validate_order(data: object) -> list[dict]:
    """エラーの一覧を返す。空なら合格。"""
    if not isinstance(data, dict):
        return [{"field": "全体", "message": "JSON オブジェクトで送ってください"}]
    errors = []
    for e in sorted(_validator.iter_errors(data), key=lambda e: list(e.path)):
        if e.validator == "required":
            missing = e.message.split("'")[1]
            errors.append({"field": FIELD_LABELS.get(missing, missing), "message": "必須項目がありません"})
        elif e.validator == "additionalProperties":
            errors.append({"field": "全体", "message": f"定義されていない項目があります: {e.message}"})
        else:
            errors.append({"field": _label(list(e.path)), "message": f"{e.validator} 違反: {e.message}"})
    if errors:
        return errors

    # ここから業務ルール。スキーマ合格後なので型は保証されている
    try:
        due = date.fromisoformat(data["due_date"])
    except ValueError:
        return [{"field": "希望納期", "message": "存在しない日付です"}]
    try:
        received = normalize_received_at(data.get("received_at"))
    except ValueError:
        return [{"field": "受信日時", "message": "日時として解釈できません"}]
    if due < date.fromisoformat(received[:10]):
        errors.append({"field": "希望納期", "message": "受信日より前の日付です"})
    return errors
