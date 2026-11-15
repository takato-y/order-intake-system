"""月次集計バッチ: 受注の月次集計を CSV と xlsx に出力する。

  python -m batch.monthly_report                 # 前月分を API から集計
  python -m batch.monthly_report --month 2026-11
  python -m batch.monthly_report --db data/orders.db --month 2026-11   # API 停止時は DB を直接読む

CSV は Excel VBA の帳票マクロ（src/MonthlyReport.bas）が取り込む。
終了コード: 0=正常（データ 0 件も正常）、1=集計の取得に失敗、2=引数の誤り
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

JST = timezone(timedelta(hours=9))
CSV_HEADER = ["集計月", "顧客名", "商品", "件数", "数量合計"]
GROUPS = [("customer_product", "顧客×商品"), ("customer", "顧客別"), ("product", "商品別")]
log = logging.getLogger("monthly_report")


def previous_month(today: datetime | None = None) -> str:
    # 月初に前月分を締める運用のため、既定は実行日の前月
    today = today or datetime.now(JST)
    first = today.replace(day=1)
    return (first - timedelta(days=1)).strftime("%Y-%m")


def fetch_from_api(api_url: str, month: str, group_by: str, timeout: float = 30) -> list[dict]:
    url = f"{api_url.rstrip('/')}/reports/monthly?month={month}&group_by={group_by}"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())["rows"]


def fetch_from_db(db_path: str, month: str, group_by: str) -> list[dict]:
    # API と同じ集計関数を使い、経路によって数字が変わらないようにする
    from app import db
    if not Path(db_path).exists():
        raise FileNotFoundError(db_path)
    conn = db.connect(db_path)
    try:
        return db.monthly_summary(conn, month, group_by)
    finally:
        conn.close()


def _atomic_write(path: Path, writer) -> None:
    # 書き込み途中のファイルを帳票マクロや共有フォルダの利用者が開かないよう、
    # 一時ファイルに書いてから置き換える
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=path.suffix)
    os.close(fd)
    try:
        writer(Path(tmp))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_csv(path: Path, month: str, rows: list[dict]) -> None:
    def w(p: Path):
        # Excel で文字化けしないよう BOM 付き UTF-8 にする
        with p.open("w", encoding="utf-8-sig", newline="") as f:
            out = csv.writer(f, lineterminator="\r\n")
            out.writerow(CSV_HEADER)
            for r in rows:
                out.writerow([month, r["customer_name"], r["product"], r["order_count"], r["total_quantity"]])
    _atomic_write(path, w)


def write_xlsx(path: Path, month: str, data: dict[str, list[dict]]) -> None:
    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="DDE7F3")

    def w(p: Path):
        wb = Workbook()
        wb.remove(wb.active)
        for key, title in GROUPS:
            ws = wb.create_sheet(title)
            ws["A1"] = f"受注月次集計（{title}） {month}"
            ws["A1"].font = Font(bold=True, size=12)
            cols = (["顧客名"] if key != "product" else []) + (["商品"] if key != "customer" else []) + ["件数", "数量合計"]
            ws.append([])
            ws.append(cols)
            for c in ws[3]:
                c.font, c.fill, c.border = Font(bold=True), head_fill, border
                c.alignment = Alignment(horizontal="center")
            rows = data[key]
            for r in rows:
                vals = ([r["customer_name"]] if key != "product" else []) + \
                       ([r["product"]] if key != "customer" else []) + [r["order_count"], r["total_quantity"]]
                ws.append(vals)
            total = ["合計"] + [""] * (len(cols) - 3) + [sum(r["order_count"] for r in rows),
                                                        sum(r["total_quantity"] for r in rows)]
            ws.append(total)
            for row in ws.iter_rows(min_row=4, max_row=ws.max_row):
                for c in row:
                    c.border = border
                    if isinstance(c.value, int):
                        c.number_format = "#,##0"
            for c in ws[ws.max_row]:
                c.font = Font(bold=True)
            for i, _ in enumerate(cols, start=1):
                ws.column_dimensions[chr(64 + i)].width = 30 if i <= len(cols) - 2 else 12
        wb.save(p)
    _atomic_write(path, w)


def run(month: str, out_dir: Path, api_url: str | None = None, db_path: str | None = None) -> dict:
    data = {}
    for key, _ in GROUPS:
        data[key] = fetch_from_db(db_path, month, key) if db_path else fetch_from_api(api_url, month, key)
    csv_path = out_dir / f"monthly_orders_{month}.csv"
    xlsx_path = out_dir / f"monthly_orders_{month}.xlsx"
    write_csv(csv_path, month, data["customer_product"])
    write_xlsx(xlsx_path, month, data)
    rows = data["customer_product"]
    return {"month": month, "csv": str(csv_path), "xlsx": str(xlsx_path), "rows": len(rows),
            "order_count": sum(r["order_count"] for r in rows),
            "total_quantity": sum(r["total_quantity"] for r in rows)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="受注の月次集計を CSV / xlsx に出力する")
    ap.add_argument("--month", help="集計月 YYYY-MM（省略時は前月）")
    ap.add_argument("--api-url", default=os.environ.get("ORDER_API_URL", "http://localhost:8000"))
    ap.add_argument("--db", help="API を使わず SQLite を直接読む場合のパス")
    ap.add_argument("--out-dir", default="output")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    month = args.month or previous_month()
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        log.error("集計月の形式が正しくありません: %s（YYYY-MM）", month)
        return 2
    try:
        result = run(month, Path(args.out_dir), api_url=args.api_url, db_path=args.db)
    except (urllib.error.URLError, OSError, KeyError, json.JSONDecodeError) as e:
        # 定期実行で失敗に気づけるよう、0 以外で終了してスケジューラの履歴に残す
        log.error("集計の取得に失敗しました: %s", e)
        return 1
    if result["rows"] == 0:
        log.warning("%s の受注は 0 件です（見出しだけの CSV を出力しました）", month)
    log.info("出力しました %s", json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
