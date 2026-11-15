-- =============================================================
-- schema_sqlite.sql : 受注メール取り込み・月次帳票システムの DDL（SQLite）
-- 方針: 標準 SQL の範囲で書き、SQL Server 版（schema_sqlserver.sql）と
--       列名・制約名・インデックス名をそろえる。型の対応は docs/04_テーブル定義書.md
-- =============================================================

-- 顧客マスタ: メールに書かれた顧客名を初回出現時に仮登録する（名寄せは運用で行う）
CREATE TABLE IF NOT EXISTS customers (
    id          INTEGER      NOT NULL PRIMARY KEY AUTOINCREMENT,
    name        VARCHAR(100) NOT NULL,
    created_at  VARCHAR(19)  NOT NULL,
    CONSTRAINT uq_customers_name UNIQUE (name)
);

-- 商品マスタ: 顧客マスタと同じ方針
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER      NOT NULL PRIMARY KEY AUTOINCREMENT,
    name        VARCHAR(100) NOT NULL,
    created_at  VARCHAR(19)  NOT NULL,
    CONSTRAINT uq_products_name UNIQUE (name)
);

-- 受注: message_id の一意制約が重複登録防止の最終防衛線（ADR-0003）
CREATE TABLE IF NOT EXISTS orders (
    id           INTEGER      NOT NULL PRIMARY KEY AUTOINCREMENT,
    message_id   VARCHAR(255) NOT NULL,
    customer_id  INTEGER      NOT NULL,
    product_id   INTEGER      NOT NULL,
    quantity     INTEGER      NOT NULL,
    due_date     VARCHAR(10)  NOT NULL,
    received_at  VARCHAR(19)  NOT NULL,
    extractor    VARCHAR(10)  NOT NULL,
    created_at   VARCHAR(19)  NOT NULL,
    CONSTRAINT uq_orders_message_id UNIQUE (message_id),
    CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) REFERENCES customers (id),
    CONSTRAINT fk_orders_product  FOREIGN KEY (product_id)  REFERENCES products (id),
    CONSTRAINT ck_orders_quantity CHECK (quantity BETWEEN 1 AND 100000),
    CONSTRAINT ck_orders_extractor CHECK (extractor IN ('llm', 'rule', 'manual'))
);

-- 月次集計は受注日時の範囲で絞るため、受注日時に索引を張る
CREATE INDEX IF NOT EXISTS ix_orders_received_at ON orders (received_at);
CREATE INDEX IF NOT EXISTS ix_orders_customer_id ON orders (customer_id);

-- 取込エラー: 検証に不合格だったメールの記録。本文は保存せず、理由だけを残す（REQ-011）
CREATE TABLE IF NOT EXISTS intake_rejections (
    id          INTEGER       NOT NULL PRIMARY KEY AUTOINCREMENT,
    message_id  VARCHAR(255)  NULL,
    source      VARCHAR(20)   NOT NULL,
    errors      VARCHAR(2000) NOT NULL,
    created_at  VARCHAR(19)   NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_intake_rejections_created_at ON intake_rejections (created_at);
