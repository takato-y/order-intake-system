"""設計書のエラーIDと障害対応手順書の突き合わせ。

設計書（詳細設計・インターフェース設計）にエラーIDを足したのに手順書に対応手順がない、
または手順書に設計書にない ID が残る、という食い違いを防ぐ。
"""
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
DESIGN_DOCS = ["05_インターフェース設計.md", "06_詳細設計.md"]
RUNBOOK = DOCS / "09_障害対応手順書.md"
ERR_ID = re.compile(r"(?<![A-Za-z0-9_-])ERR-\d+(?![A-Za-z0-9_-])")


def _chapter(text: str, number: int) -> str:
    """「## N. 」で始まる章の本文を返す（次の「## 」の手前まで）。"""
    m = re.search(rf"^## {number}\. .*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m, f"障害対応手順書に {number} 章がありません"
    return m.group(1)


def test_runbook_covers_every_design_error_id():
    design_ids = set()
    for name in DESIGN_DOCS:
        design_ids |= set(ERR_ID.findall((DOCS / name).read_text(encoding="utf-8")))
    assert design_ids, "設計書にエラーIDが見つかりません"

    text = RUNBOOK.read_text(encoding="utf-8")
    # 4 章：エラーIDごとの見出し（### 4.n ERR-xxx 名称）
    headings = set(re.findall(r"^### (?:\d+\.\d+ )?(ERR-\d+) ", _chapter(text, 4), re.M))
    # 7 章：エラーID対応表の 1 列目
    table_ids = set(re.findall(r"^\| (ERR-\d+) \|", _chapter(text, 7), re.M))

    assert design_ids - headings == set(), "4 章に対応手順の節がないエラーID"
    assert design_ids - table_ids == set(), "7 章の対応表にないエラーID"
    # 手順書のどこにも、設計書にない ID を書かない
    assert set(ERR_ID.findall(text)) - design_ids == set(), "設計書にないエラーID"
