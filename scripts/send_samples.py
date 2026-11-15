"""samples/emails の受注メールを送り、結果を一覧で表示する（動作確認用）。

送り先は 2 通り。どちらも同じ JSON を受け付ける。
  受注 API に直接（規則抽出）: python scripts/send_samples.py --url http://localhost:8000/intake/email
  n8n の取込フロー経由      : python scripts/send_samples.py --url http://localhost:5678/webhook/order-intake
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

SAMPLES = Path(__file__).resolve().parent.parent / "samples" / "emails"


def post(url: str, payload: dict, timeout: float) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        # 422 などもフローの結果として表示したいので例外にしない
        return e.code, json.loads(e.read().decode() or "{}")


def summarize(status: int, body: dict) -> str:
    if "order" in body:
        o = body["order"]
        tag = "重複（既存を返却）" if body.get("duplicate") else "登録"
        return f"{tag}: {o['customer_name']} / {o['product']} / {o['quantity']} / {o['due_date']} [{o['extractor']}]"
    detail = body.get("detail", body)
    errors = detail.get("errors") if isinstance(detail, dict) else None
    if errors is None and isinstance(body.get("errors"), list):
        errors = body["errors"]
    if errors:
        return "不合格: " + "、".join(f"{e.get('field')}={e.get('message')}" for e in errors)
    return json.dumps(body, ensure_ascii=False)[:200]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000/intake/email")
    ap.add_argument("--timeout", type=float, default=180)
    ap.add_argument("files", nargs="*", help="送るファイル（省略時は全件）")
    args = ap.parse_args()
    files = [Path(f) for f in args.files] or sorted(SAMPLES.glob("*.json"))
    for f in files:
        status, body = post(args.url, json.loads(f.read_text(encoding="utf-8")), args.timeout)
        print(f"{status}  {f.stem:<22} {summarize(status, body)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
