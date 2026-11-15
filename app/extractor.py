"""メール本文から受注項目（顧客名・商品・数量・希望納期）を取り出す。

方式は 2 つ（ADR-0002）。
- rule: 正規表現による抽出。外部サービスに依存せず、項目名のある定型メールに強い
- llm : ローカル LLM（Ollama）による抽出。書式の揺れに強いが、停止・形式崩れがありうる
auto は LLM を試し、失敗または項目不足なら rule に切り替える。
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.request
from dataclasses import dataclass, field
from datetime import date

FIELDS = ("customer_name", "product", "quantity", "due_date")

# 行頭の記号（・ - ■ など）と【】で囲んだ項目名の両方を受け付ける
_PREFIX = r"^[\s・\-■●◆*]*"
_LABELS = {
    "customer_name": r"顧客名|会社名|御社名|貴社名|発注者|発注元|注文者",
    "product": r"商品名|商品|品名|品目|注文商品",
    "quantity": r"数量|個数|注文数",
    "due_date": r"希望納期|納期|納品希望日|希望納品日|お届け希望日",
}
_LABEL_RES = {
    k: re.compile(_PREFIX + r"(?:【(?:" + v + r")】\s*:?|(?:" + v + r")\s*:)\s*(.+?)\s*$", re.M)
    for k, v in _LABELS.items()
}
_COMPANY_RE = re.compile(r"((?:株式会社|有限会社|合同会社)\s?[^\s、。,]+|[^\s、。,]+(?:株式会社|有限会社|合同会社))")
_YMD_RE = re.compile(r"(\d{4})\s*[年/\-.]\s*(\d{1,2})\s*[月/\-.]\s*(\d{1,2})")
_MD_RE = re.compile(r"(\d{1,2})\s*[月/]\s*(\d{1,2})")


@dataclass
class Extraction:
    fields: dict
    extractor: str
    missing: list = field(default_factory=list)
    llm_error: str | None = None


def _normalize(text: str) -> str:
    # 全角数字・全角コロンを半角にそろえ、正規表現を 1 種類で済ませる
    return unicodedata.normalize("NFKC", text or "").replace("\r\n", "\n")


def parse_due_date(text: str, received: date) -> str | None:
    """日付表記を 'YYYY-MM-DD' にする。年がない場合は受信日を基準に補う。"""
    t = _normalize(text)
    m = _YMD_RE.search(t)
    try:
        if m:
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        m = _MD_RE.search(t)
        if m:
            d = date(received.year, int(m[1]), int(m[2]))
            # 12 月に「1 月 10 日」と書かれた場合などは翌年とみなす
            if d < received:
                d = date(received.year + 1, d.month, d.day)
            return d.isoformat()
    except ValueError:
        # 2 月 30 日など存在しない日付は「取り出せなかった」扱いにし、検証で不合格にする
        return None
    return None


def extract_rule(subject: str, body: str, received: date) -> Extraction:
    text = _normalize(body)
    found: dict = {}
    for key, rx in _LABEL_RES.items():
        m = rx.search(text)
        if m:
            found[key] = m.group(1)

    if "quantity" in found:
        q = re.search(r"\d[\d,]*", found["quantity"])
        found["quantity"] = int(q.group().replace(",", "")) if q else None
    if "due_date" in found:
        found["due_date"] = parse_due_date(found["due_date"], received)
    if "customer_name" not in found:
        # 項目名がない場合は署名の会社名を使う。宛名（御中・様の行）は当社なので除外し、
        # 署名は末尾にあることが多いため最後に出てきた会社名を採る
        candidates = [m.group(1) for line in text.split("\n")
                      if "御中" not in line and "様" not in line
                      for m in _COMPANY_RE.finditer(line)]
        if candidates:
            found["customer_name"] = candidates[-1]

    fields = {k: v for k, v in found.items() if v not in (None, "")}
    return Extraction(fields=fields, extractor="rule", missing=[k for k in FIELDS if k not in fields])


# LLM に返させる形。Ollama の format にこのスキーマを渡し、JSON 以外の出力を防ぐ
_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "customer_name": {"type": ["string", "null"]},
        "product": {"type": ["string", "null"]},
        "quantity": {"type": ["integer", "null"]},
        "due_date": {"type": ["string", "null"]},
    },
    "required": list(FIELDS),
}

_LLM_PROMPT = """You extract order data from a Japanese business email.
Return JSON with keys customer_name, product, quantity, due_date.
- customer_name: the sender's company name (not the recipient addressed with 御中/様).
- product: product name exactly as written, without quantity.
- quantity: integer only.
- due_date: requested delivery date as YYYY-MM-DD. The email was received on {received}; resolve dates without a year relative to it.
- Use null when a value is not written. Do not guess.
Keep Japanese values in Japanese.

Subject: {subject}
Body:
{body}"""


def extract_llm(subject: str, body: str, received: date) -> Extraction:
    url = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/") + "/api/chat"
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
    timeout = float(os.environ.get("OLLAMA_TIMEOUT", "120"))
    payload = {
        "model": model,
        "stream": False,
        "format": _LLM_SCHEMA,
        "options": {"temperature": 0},
        "messages": [{"role": "user", "content": _LLM_PROMPT.format(
            received=received.isoformat(), subject=subject or "", body=body or "")}],
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        content = json.loads(r.read().decode())["message"]["content"]
    data = json.loads(content)
    fields = {k: data.get(k) for k in FIELDS if data.get(k) not in (None, "")}
    if isinstance(fields.get("quantity"), str):
        # 「20箱」のような文字列で返された場合に備える
        q = re.search(r"\d+", _normalize(fields["quantity"]))
        fields["quantity"] = int(q.group()) if q else None
    if "due_date" in fields:
        fields["due_date"] = parse_due_date(str(fields["due_date"]), received)
    fields = {k: v for k, v in fields.items() if v not in (None, "")}
    return Extraction(fields=fields, extractor="llm", missing=[k for k in FIELDS if k not in fields])


def extract(subject: str, body: str, received: date, mode: str = "rule") -> Extraction:
    if mode == "rule":
        return extract_rule(subject, body, received)
    if mode == "llm":
        return extract_llm(subject, body, received)
    # auto: LLM の停止・形式崩れ・項目不足のいずれでも、取り込みを止めず規則抽出に切り替える
    try:
        result = extract_llm(subject, body, received)
        if not result.missing:
            return result
        err = f"LLM の結果に不足項目があります: {','.join(result.missing)}"
    except Exception as e:  # noqa: BLE001 - LLM 側の失敗理由は問わず代替する
        err = f"{type(e).__name__}: {e}"
    fallback = extract_rule(subject, body, received)
    fallback.llm_error = err[:300]
    return fallback
