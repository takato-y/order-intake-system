# 変更履歴

このプロジェクトの主な変更を記録します。書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に、版の付け方は [セマンティック バージョニング](https://semver.org/lang/ja/) に従います。

## [1.0.0] - 2026-11-15

### 追加

- 受注 API（FastAPI）：受注の登録・一覧・月次集計、取込エラーの記録、メール取込（`/intake/email`）、抽出のみ（`/extract`）
- Message-ID の一意制約による重複登録の防止（同時登録にも対応）
- JSON スキーマによる入力検証と、実在日付・納期の業務ルール
- 規則による抽出と LLM（Ollama）による抽出、LLM 失敗時の自動切替
- n8n 取込フロー（LLM 抽出、規則抽出への切替、スキーマ検証、登録・不合格・障害の分岐）と生成スクリプト
- 月次集計バッチ（CSV・xlsx 出力）と PowerShell ラッパー
- 月次帳票を作成する Excel VBA モジュール
- SQLite と SQL Server の DDL
- Dockerfile・docker-compose.yml、GitHub Actions による自動テスト
- 設計書一式（要件定義〜運用設計、テーブル定義書、フロー設計書、ADR）

### 修正

- API の登録・重複・検証エラーのログが出力されなかった問題
