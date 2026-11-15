-- =============================================================
-- schema_sqlserver.sql : 受注メール取り込み・月次帳票システムの DDL（SQL Server）
-- 方針: SQLite 版と列名・制約名・インデックス名をそろえ、移行時の差分を型だけにする。
--       日本語を扱う列は NVARCHAR、日時は DATETIME2(0)。
-- 状態: 未実行（SQL Server 実機での実行確認はしていない）
-- =============================================================

CREATE TABLE dbo.customers (
    id          INT IDENTITY(1,1) NOT NULL,
    name        NVARCHAR(100)     NOT NULL,
    created_at  DATETIME2(0)      NOT NULL,
    CONSTRAINT pk_customers PRIMARY KEY (id),
    CONSTRAINT uq_customers_name UNIQUE (name)
);

CREATE TABLE dbo.products (
    id          INT IDENTITY(1,1) NOT NULL,
    name        NVARCHAR(100)     NOT NULL,
    created_at  DATETIME2(0)      NOT NULL,
    CONSTRAINT pk_products PRIMARY KEY (id),
    CONSTRAINT uq_products_name UNIQUE (name)
);

CREATE TABLE dbo.orders (
    id           INT IDENTITY(1,1) NOT NULL,
    message_id   NVARCHAR(255)     NOT NULL,
    customer_id  INT               NOT NULL,
    product_id   INT               NOT NULL,
    quantity     INT               NOT NULL,
    due_date     DATE              NOT NULL,
    received_at  DATETIME2(0)      NOT NULL,
    extractor    VARCHAR(10)       NOT NULL,
    created_at   DATETIME2(0)      NOT NULL,
    CONSTRAINT pk_orders PRIMARY KEY (id),
    CONSTRAINT uq_orders_message_id UNIQUE (message_id),
    CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) REFERENCES dbo.customers (id),
    CONSTRAINT fk_orders_product FOREIGN KEY (product_id) REFERENCES dbo.products (id),
    CONSTRAINT ck_orders_quantity CHECK (quantity BETWEEN 1 AND 100000),
    CONSTRAINT ck_orders_extractor CHECK (extractor IN ('llm', 'rule', 'manual'))
);

CREATE INDEX ix_orders_received_at ON dbo.orders (received_at);
CREATE INDEX ix_orders_customer_id ON dbo.orders (customer_id);

CREATE TABLE dbo.intake_rejections (
    id          INT IDENTITY(1,1) NOT NULL,
    message_id  NVARCHAR(255)     NULL,
    source      VARCHAR(20)       NOT NULL,
    errors      NVARCHAR(2000)    NOT NULL,
    created_at  DATETIME2(0)      NOT NULL,
    CONSTRAINT pk_intake_rejections PRIMARY KEY (id)
);

CREATE INDEX ix_intake_rejections_created_at ON dbo.intake_rejections (created_at);

EXEC sys.sp_addextendedproperty N'MS_Description', N'顧客マスタ：メールに書かれた顧客名を初回出現時に仮登録する', N'SCHEMA', N'dbo', N'TABLE', N'customers';
EXEC sys.sp_addextendedproperty N'MS_Description', N'顧客ID', N'SCHEMA', N'dbo', N'TABLE', N'customers', N'COLUMN', N'id';
EXEC sys.sp_addextendedproperty N'MS_Description', N'顧客名', N'SCHEMA', N'dbo', N'TABLE', N'customers', N'COLUMN', N'name';
EXEC sys.sp_addextendedproperty N'MS_Description', N'登録日時', N'SCHEMA', N'dbo', N'TABLE', N'customers', N'COLUMN', N'created_at';
EXEC sys.sp_addextendedproperty N'MS_Description', N'商品マスタ：メールに書かれた商品名を初回出現時に仮登録する', N'SCHEMA', N'dbo', N'TABLE', N'products';
EXEC sys.sp_addextendedproperty N'MS_Description', N'商品ID', N'SCHEMA', N'dbo', N'TABLE', N'products', N'COLUMN', N'id';
EXEC sys.sp_addextendedproperty N'MS_Description', N'商品名', N'SCHEMA', N'dbo', N'TABLE', N'products', N'COLUMN', N'name';
EXEC sys.sp_addextendedproperty N'MS_Description', N'登録日時', N'SCHEMA', N'dbo', N'TABLE', N'products', N'COLUMN', N'created_at';
EXEC sys.sp_addextendedproperty N'MS_Description', N'受注：受注メール1通につき1行', N'SCHEMA', N'dbo', N'TABLE', N'orders';
EXEC sys.sp_addextendedproperty N'MS_Description', N'受注ID', N'SCHEMA', N'dbo', N'TABLE', N'orders', N'COLUMN', N'id';
EXEC sys.sp_addextendedproperty N'MS_Description', N'メッセージID', N'SCHEMA', N'dbo', N'TABLE', N'orders', N'COLUMN', N'message_id';
EXEC sys.sp_addextendedproperty N'MS_Description', N'顧客ID', N'SCHEMA', N'dbo', N'TABLE', N'orders', N'COLUMN', N'customer_id';
EXEC sys.sp_addextendedproperty N'MS_Description', N'商品ID', N'SCHEMA', N'dbo', N'TABLE', N'orders', N'COLUMN', N'product_id';
EXEC sys.sp_addextendedproperty N'MS_Description', N'数量', N'SCHEMA', N'dbo', N'TABLE', N'orders', N'COLUMN', N'quantity';
EXEC sys.sp_addextendedproperty N'MS_Description', N'希望納期', N'SCHEMA', N'dbo', N'TABLE', N'orders', N'COLUMN', N'due_date';
EXEC sys.sp_addextendedproperty N'MS_Description', N'受信日時', N'SCHEMA', N'dbo', N'TABLE', N'orders', N'COLUMN', N'received_at';
EXEC sys.sp_addextendedproperty N'MS_Description', N'抽出方式', N'SCHEMA', N'dbo', N'TABLE', N'orders', N'COLUMN', N'extractor';
EXEC sys.sp_addextendedproperty N'MS_Description', N'登録日時', N'SCHEMA', N'dbo', N'TABLE', N'orders', N'COLUMN', N'created_at';
EXEC sys.sp_addextendedproperty N'MS_Description', N'取込エラー：検証に不合格だったメールの記録（本文は保存しない）', N'SCHEMA', N'dbo', N'TABLE', N'intake_rejections';
EXEC sys.sp_addextendedproperty N'MS_Description', N'取込エラーID', N'SCHEMA', N'dbo', N'TABLE', N'intake_rejections', N'COLUMN', N'id';
EXEC sys.sp_addextendedproperty N'MS_Description', N'メッセージID', N'SCHEMA', N'dbo', N'TABLE', N'intake_rejections', N'COLUMN', N'message_id';
EXEC sys.sp_addextendedproperty N'MS_Description', N'検出元', N'SCHEMA', N'dbo', N'TABLE', N'intake_rejections', N'COLUMN', N'source';
EXEC sys.sp_addextendedproperty N'MS_Description', N'エラー内容', N'SCHEMA', N'dbo', N'TABLE', N'intake_rejections', N'COLUMN', N'errors';
EXEC sys.sp_addextendedproperty N'MS_Description', N'登録日時', N'SCHEMA', N'dbo', N'TABLE', N'intake_rejections', N'COLUMN', N'created_at';
