"""n8n 取込フローの静的テスト。

API と n8n で検証規則がずれると「n8n では合格・API では不合格」の受注が出るため、
埋め込んだスキーマが app/order_schema.json と同じか、JS の検証器が Python と同じ判定をするかを確かめる。
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.validation import ORDER_SCHEMA, validate_order
from tests.conftest import make_order

WF = json.loads((Path(__file__).resolve().parent.parent / "n8n" / "order-intake.json").read_text(encoding="utf-8"))
NODES = {n["name"]: n for n in WF["nodes"]}


def _validate_js() -> str:
    return NODES["スキーマ検証"]["parameters"]["jsCode"]


def test_embedded_schema_matches_api_schema():
    code = _validate_js()
    embedded = code.split("/*SCHEMA_BEGIN*/")[1].split("/*SCHEMA_END*/")[0]
    assert json.loads(embedded) == ORDER_SCHEMA


def test_webhook_has_id_and_expressions_have_prefix():
    assert NODES["Webhook受信"].get("webhookId")
    for n in WF["nodes"]:
        for v in json.dumps(n["parameters"], ensure_ascii=False).split('"'):
            if "{{" in v and "}}" in v and n["type"] != "n8n-nodes-base.code":
                assert v.startswith("="), (n["name"], v)


def test_all_connections_point_to_existing_nodes():
    for src, typed in WF["connections"].items():
        assert src in NODES
        for branch in typed["main"]:
            for c in branch:
                assert c["node"] in NODES


CASES = [
    make_order(),
    make_order(quantity=0),
    make_order(quantity="20"),
    make_order(quantity=100001),
    make_order(due_date="2026/11/20"),
    make_order(customer_name=""),
    make_order(customer_name="あ" * 101),
    make_order(message_id="has space"),
    make_order(extractor="other"),
    make_order(unknown="x"),
    {k: v for k, v in make_order().items() if k != "product"},
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node がない環境では JS の検証器を実行できない")
def test_js_validator_agrees_with_python():
    code = _validate_js()
    validator_src = code.split("// 「11月28日」")[0]  # validate() の定義までを取り出す
    script = validator_src + "\nconst cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n" \
        "console.log(JSON.stringify(cases.map(c => validate(SCHEMA, c).length === 0)));"
    out = subprocess.run(["node", "-e", script], input=json.dumps(CASES, ensure_ascii=False),
                         capture_output=True, text=True, check=True, encoding="utf-8").stdout
    js = json.loads(out)
    # Python 側はスキーマに加えて業務ルールも見るが、ここの事例は業務ルールに触れないものだけ
    py = [validate_order(c) == [] for c in CASES]
    assert js == py
    assert js[0] is True and not any(js[1:])
