# 変更履歴

このプロジェクトの主な変更を記録します。書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に、版の付け方は [セマンティック バージョニング](https://semver.org/lang/ja/) に従います。

## [1.0.3] - 2026-11-15

### ドキュメント

- 公開後に GitHub Actions で自動テストを実行した結果（47 件合格・1 件スキップ）を README とテスト仕様書（TC-043）に反映

## [1.0.2] - 2026-11-15

### セキュリティ

- 月次バッチの数式対策で、数式とみなす先頭文字に改行（LF）を追加（帳票マクロは対応済み）

## [1.0.1] - 2026-11-15

### セキュリティ

- 顧客名・商品名が `=` `+` `-` `@` などで始まる場合に、CSV・xlsx・帳票マクロで数式として動かないよう無害化（全角の `＝` を含む）
- docker-compose.yml の公開ポートを 127.0.0.1 に限定（API・n8n とも認証がないため）
- n8n フローで成功時の実行履歴を保存しない設定を追加（メール本文を残さないため）
- PowerShell の実行ポリシーの例を Bypass から RemoteSigned に変更
- GitHub Actions のトークン権限を読み取りに限定

### 変更

- README に未確認の事項（compose での起動、SQL Server での実行、PowerShell ラッパー、GitHub Actions）と、認証なし・ローカル専用の構成であることを明記
- 要件定義書（REQ-011）・基本設計書・インターフェース設計書・詳細設計書・テスト仕様書（TC-040〜TC-042）・運用設計書を更新

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

[1.0.3]: https://github.com/takato-y/order-intake-system/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/takato-y/order-intake-system/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/takato-y/order-intake-system/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/takato-y/order-intake-system/releases/tag/v1.0.0
