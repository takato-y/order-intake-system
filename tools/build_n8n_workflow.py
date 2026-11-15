"""n8n 取込フロー（n8n/order-intake.json）を生成する。

スキーマ検証ノードに app/order_schema.json をそのまま埋め込むため、手で JSON を直さず
このスクリプトで作り直す（API と n8n の検証規則がずれないようにするため）。
  python tools/build_n8n_workflow.py
"""
import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "app" / "order_schema.json").read_text(encoding="utf-8"))
OUT = ROOT / "n8n" / "order-intake.json"

# 再生成しても差分が出ないよう、ID は名前から決まる値にする
NS = uuid.UUID("6f1d2c3a-0000-4000-8000-000000000000")


def nid(name):
    return str(uuid.uuid5(NS, name))


PREP_JS = r"""// Webhook で受けたメールから LLM への依頼を作る。
// Gmail トリガーに差し替えた場合は、下の src の取り方だけを変える（README 参照）。
const src = $('Webhook受信').first().json.body || {};
const cfg = $('設定').first().json;
const receivedAt = src.received_at || new Date().toISOString();
const prompt = [
  'You extract order data from a Japanese business email.',
  'Return JSON with keys customer_name, product, quantity, due_date.',
  "- customer_name: the sender's company name (not the recipient addressed with 御中/様).",
  '- product: product name exactly as written, without quantity.',
  '- quantity: integer only.',
  `- due_date: requested delivery date as YYYY-MM-DD. The email was received on ${receivedAt.slice(0, 10)}; resolve dates without a year relative to it.`,
  '- Use null when a value is not written. Do not guess.',
  'Keep Japanese values in Japanese.',
  '',
  `Subject: ${src.subject || ''}`,
  'Body:',
  src.body || '',
].join('\n');
return [{ json: {
  message_id: src.message_id,
  received_at: receivedAt,
  subject: src.subject || '',
  body: src.body || '',
  llm_request: {
    model: cfg.ollama_model,
    stream: false,
    // JSON 以外を返させないよう、出力の形を指定する
    format: {
      type: 'object',
      properties: {
        customer_name: { type: ['string', 'null'] },
        product: { type: ['string', 'null'] },
        quantity: { type: ['integer', 'null'] },
        due_date: { type: ['string', 'null'] },
      },
      required: ['customer_name', 'product', 'quantity', 'due_date'],
    },
    options: { temperature: 0 },
    messages: [{ role: 'user', content: prompt }],
  },
} }];
"""

VALIDATE_JS = r"""// LLM の結果（または API の規則抽出の結果）を受注データにそろえ、JSON スキーマで検証する。
// スキーマは app/order_schema.json と同じもの（tools/build_n8n_workflow.py が埋め込む）。
const SCHEMA = /*SCHEMA_BEGIN*/__SCHEMA__/*SCHEMA_END*/;

function validate(schema, obj) {
  const errors = [];
  for (const k of schema.required) {
    if (obj[k] === undefined) errors.push({ field: k, message: '必須項目がありません' });
  }
  for (const k of Object.keys(obj)) {
    if (!schema.properties[k]) errors.push({ field: k, message: '定義されていない項目です' });
  }
  for (const [k, rule] of Object.entries(schema.properties)) {
    const v = obj[k];
    if (v === undefined) continue;
    if (rule.type === 'integer' && !Number.isInteger(v)) { errors.push({ field: k, message: '整数ではありません' }); continue; }
    if (rule.type === 'string' && typeof v !== 'string') { errors.push({ field: k, message: '文字列ではありません' }); continue; }
    // 文字数は Python 側と同じくコードポイント単位で数える
    const len = typeof v === 'string' ? [...v].length : 0;
    if (rule.minLength !== undefined && len < rule.minLength) errors.push({ field: k, message: `${rule.minLength} 文字以上にしてください` });
    if (rule.maxLength !== undefined && len > rule.maxLength) errors.push({ field: k, message: `${rule.maxLength} 文字以内にしてください` });
    if (rule.minimum !== undefined && v < rule.minimum) errors.push({ field: k, message: `${rule.minimum} 以上にしてください` });
    if (rule.maximum !== undefined && v > rule.maximum) errors.push({ field: k, message: `${rule.maximum} 以下にしてください` });
    if (rule.pattern !== undefined && !new RegExp(rule.pattern, 'u').test(v)) errors.push({ field: k, message: '形式が正しくありません' });
    if (rule.enum !== undefined && !rule.enum.includes(v)) errors.push({ field: k, message: '許可されていない値です' });
  }
  return errors;
}

// 「11月28日」「2026/11/28」のような表記を YYYY-MM-DD にする。年がなければ受信日から補う
function toIsoDate(text, receivedAt) {
  if (typeof text !== 'string') return text;
  const t = text.normalize('NFKC');
  const pad = (n) => String(n).padStart(2, '0');
  let m = t.match(/(\d{4})\s*[年\/\-.]\s*(\d{1,2})\s*[月\/\-.]\s*(\d{1,2})/);
  if (m) return `${m[1]}-${pad(m[2])}-${pad(m[3])}`;
  m = t.match(/(\d{1,2})\s*[月\/]\s*(\d{1,2})/);
  if (m) {
    const rd = receivedAt.slice(0, 10);
    let y = Number(rd.slice(0, 4));
    if (`${y}-${pad(m[1])}-${pad(m[2])}` < rd) y += 1;
    return `${y}-${pad(m[1])}-${pad(m[2])}`;
  }
  return t;
}

const prep = $('LLM依頼の作成').first().json;
const input = $input.first().json;
let fields = {};
let extractor = 'llm';
if (input.fields) {
  // API の規則抽出（LLM が使えなかったときの代替経路）
  fields = input.fields;
  extractor = 'rule';
} else {
  try {
    fields = JSON.parse(input.message.content);
  } catch (e) {
    fields = {};
  }
}

const order = { message_id: prep.message_id, received_at: prep.received_at, extractor };
for (const k of ['customer_name', 'product', 'quantity', 'due_date']) {
  let v = fields[k];
  if (v === null || v === undefined || v === '') continue;
  if (k === 'quantity' && typeof v === 'string') {
    const d = v.normalize('NFKC').replace(/,/g, '').match(/\d+/);
    v = d ? Number(d[0]) : v;
  }
  if (k === 'due_date') v = toIsoDate(v, prep.received_at);
  order[k] = typeof v === 'string' ? v.trim() : v;
}
for (const k of Object.keys(order)) if (order[k] === undefined) delete order[k];

const errors = validate(SCHEMA, order);
return [{ json: { valid: errors.length === 0, errors, order } }];
"""

SETUP_NOTE = """## 設定手順
- [ ] 「設定」ノードの api_url を受注 API の URL にする（Docker の n8n から同じ PC の API へは host.docker.internal）
- [ ] 「設定」ノードの ollama_url・ollama_model を使う LLM に合わせる
- [ ] 受注 API を起動しておく（README の「動かし方」）
- [ ] ワークフローを有効化し、Webhook の本番 URL に受注メールの JSON を POST する
- [ ] Gmail から直接取り込む場合は、Webhook受信 を Gmail Trigger に差し替える（README 参照）"""


def set_node():
    vals = [("api_url", "http://host.docker.internal:8000"),
            ("ollama_url", "http://host.docker.internal:11434"),
            ("ollama_model", "qwen2.5:7b")]
    return {"assignments": {"assignments": [
        {"id": nid("set-" + k), "name": k, "value": v, "type": "string"} for k, v in vals]},
        "options": {}}


def if_node(left, op_type, operation, right=None):
    cond = {"id": nid("if-" + left), "leftValue": left,
            "operator": {"type": op_type, "operation": operation}}
    if right is None:
        cond["rightValue"] = ""
        cond["operator"]["singleValue"] = True
    else:
        cond["rightValue"] = right
    return {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict"},
                           "conditions": [cond], "combinator": "and"}, "options": {}}


def http(url, body, timeout, extra=None):
    p = {"method": "POST", "url": url, "sendBody": True, "specifyBody": "json",
         "jsonBody": body, "options": {"timeout": timeout}}
    if extra:
        p["options"].update(extra)
    return p


def respond(body, code):
    return {"respondWith": "json", "responseBody": body, "options": {"responseCode": code}}


API = "{{ $('設定').first().json.api_url }}"
nodes = [
    ("Webhook受信", "n8n-nodes-base.webhook", 2, [0, 300],
     {"httpMethod": "POST", "path": "order-intake", "responseMode": "responseNode", "options": {}}, {}),
    ("設定", "n8n-nodes-base.set", 3.4, [220, 300], set_node(), {}),
    ("LLM依頼の作成", "n8n-nodes-base.code", 2, [440, 300], {"jsCode": PREP_JS}, {}),
    ("LLMで項目抽出", "n8n-nodes-base.httpRequest", 4.2, [660, 300],
     http("={{ $('設定').first().json.ollama_url }}/api/chat",
          "={{ JSON.stringify($json.llm_request) }}", 120000),
     {"onError": "continueErrorOutput"}),
    ("規則抽出に切替", "n8n-nodes-base.httpRequest", 4.2, [880, 500],
     http("=" + API + "/extract?mode=rule",
          "={{ JSON.stringify({ subject: $('LLM依頼の作成').first().json.subject, body: $('LLM依頼の作成').first().json.body, received_at: $('LLM依頼の作成').first().json.received_at }) }}",
          30000), {}),
    ("スキーマ検証", "n8n-nodes-base.code", 2, [1100, 300],
     {"jsCode": VALIDATE_JS.replace("__SCHEMA__", json.dumps(SCHEMA, ensure_ascii=False, indent=2))}, {}),
    ("検証結果で分岐", "n8n-nodes-base.if", 2, [1320, 300], if_node("={{ $json.valid }}", "boolean", "true"), {}),
    ("受注登録", "n8n-nodes-base.httpRequest", 4.2, [1540, 200],
     http("=" + API + "/orders", "={{ JSON.stringify($json.order) }}", 30000,
          {"response": {"response": {"fullResponse": True, "neverError": True}}}),
     # 4xx は応答として受け取り（neverError）、通信失敗だけを再試行する。登録は冪等なので再試行しても二重にならない
     {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000, "onError": "continueErrorOutput"}),
    ("登録結果で分岐", "n8n-nodes-base.if", 2, [1760, 100], if_node("={{ $json.statusCode }}", "number", "lt", 300), {}),
    ("登録完了の応答", "n8n-nodes-base.respondToWebhook", 1.1, [1980, 0],
     respond("={{ JSON.stringify($json.body) }}", "={{ $json.statusCode }}"), {}),
    ("登録エラーの応答", "n8n-nodes-base.respondToWebhook", 1.1, [1980, 200],
     respond("={{ JSON.stringify({ stage: 'api', status: $json.statusCode, detail: $json.body }) }}", 422), {}),
    ("API障害の応答", "n8n-nodes-base.respondToWebhook", 1.1, [1760, 400],
     respond("={{ JSON.stringify({ stage: 'api', message: '受注 API に接続できませんでした' }) }}", 503), {}),
    ("不合格の記録", "n8n-nodes-base.httpRequest", 4.2, [1540, 600],
     http("=" + API + "/rejections",
          "={{ JSON.stringify({ message_id: typeof $json.order.message_id === 'string' ? $json.order.message_id : null, source: 'n8n', errors: $json.errors }) }}",
          30000),
     # 記録に失敗しても、呼び出し元への不合格の応答は返す
     {"onError": "continueRegularOutput"}),
    ("不合格の応答", "n8n-nodes-base.respondToWebhook", 1.1, [1760, 600],
     respond("={{ JSON.stringify({ stage: 'validation', errors: $('スキーマ検証').first().json.errors }) }}", 422), {}),
]

out_nodes = [{
    "id": nid("sticky-setup"), "name": "設定手順", "type": "n8n-nodes-base.stickyNote", "typeVersion": 1,
    "position": [-480, 160], "parameters": {"content": SETUP_NOTE, "height": 300, "width": 420}}]
for name, typ, ver, pos, params, extra in nodes:
    n = {"id": nid(name), "name": name, "type": typ, "typeVersion": ver, "position": pos, "parameters": params}
    if typ == "n8n-nodes-base.webhook":
        n["webhookId"] = nid("webhook-order-intake")
    n.update(extra)
    out_nodes.append(n)


def link(*targets):
    return [[{"node": t, "type": "main", "index": 0}] if t else [] for t in targets]


connections = {
    "Webhook受信": {"main": link("設定")},
    "設定": {"main": link("LLM依頼の作成")},
    "LLM依頼の作成": {"main": link("LLMで項目抽出")},
    "LLMで項目抽出": {"main": link("スキーマ検証", "規則抽出に切替")},  # 0=成功, 1=失敗
    "規則抽出に切替": {"main": link("スキーマ検証")},
    "スキーマ検証": {"main": link("検証結果で分岐")},
    "検証結果で分岐": {"main": link("受注登録", "不合格の記録")},
    "受注登録": {"main": link("登録結果で分岐", "API障害の応答")},
    "登録結果で分岐": {"main": link("登録完了の応答", "登録エラーの応答")},
    "不合格の記録": {"main": link("不合格の応答")},
}

wf = {"name": "受注メール取込", "nodes": out_nodes, "connections": connections,
      "settings": {"executionOrder": "v1"}, "pinData": {}}
OUT.write_text(json.dumps(wf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"wrote {OUT.relative_to(ROOT)} ({len(out_nodes)} nodes)")
