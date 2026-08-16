# JSM Knowledge Sync with Codex

Jira Service Management Cloud（JSM）の対象課題と公開コメントを取得し、Codexで再利用可能なMarkdownへ整理して、Pull Requestとして蓄積するGitHub Actions一式です。

## 処理の流れ

1. JQLまたは課題キーで対象を限定
2. Jira REST API v3で課題本文を取得
3. JSM REST APIで公開コメントだけを取得
4. 明らかなメールアドレス・トークン等を機械的にマスク
5. Codexが `knowledge/articles/<ISSUE-KEY>.md` と `knowledge/index.md` を更新
6. 構造・秘密情報を検査し、`automation/jsm-knowledge` ブランチのPull Requestを作成または更新

## 前提

- 対象は **Jira Service Management Cloud** です。Data CenterではAPIパスと認証方式の調整が必要です。
- JSMの認証ユーザーには、対象課題とコメントを参照する権限が必要です。
- JSMデータをOpenAI APIへ送信できることを、組織の情報管理ルール上確認してください。
- 自動マスクは完全ではありません。秘密情報を含む可能性がある課題をJQLで除外し、Pull Requestで人が確認してください。

## GitHub Secrets

Repositoryの `Settings > Secrets and variables > Actions` に次を登録します。

| Secret | 必須 | 内容 |
| --- | --- | --- |
| `JSM_BASE_URL` | 必須 | `https://your-domain.atlassian.net` |
| `JSM_EMAIL` | Basic認証時 | Atlassian API tokenを発行したユーザーのメールアドレス |
| `JSM_API_TOKEN` | 必須 | Atlassian API token。Bearer認証時はアクセストークン |
| `OPENAI_API_KEY` | 必須 | Codex GitHub Actionが使うOpenAI API key |
| `GH_PAT` | 任意 | GitHubへのpush/PR作成用PAT。同一リポジトリなら通常は `GITHUB_TOKEN` で足ります |

> GitHub PATはOpenAI/Codexの認証には使えません。Codex GitHub Actionには `OPENAI_API_KEY` が必要です。取得済みPATは、組織ポリシーにより `GITHUB_TOKEN` でpushやPR作成ができない場合だけ `GH_PAT` として使います。

`GH_PAT` を使う場合は、対象リポジトリだけに限定したfine-grained PATとし、Repository permissionsは原則 `Contents: Read and write`、`Pull requests: Read and write` に絞ります。

## GitHub Variables

| Variable | 必須 | 例・説明 |
| --- | --- | --- |
| `JSM_JQL` | 定期実行時に必須 | `project = ITSD AND issuetype = "問い合わせ" AND resolution IS NOT EMPTY ORDER BY updated ASC` |
| `JSM_AUTH_MODE` | 任意 | `basic`（既定）または `bearer` |
| `JSM_MAX_ISSUES` | 任意 | 1回の上限。既定100、最大500 |
| `CODEX_MODEL` | 任意 | 空欄ならCodex GitHub Actionの既定モデル |
| `CODEX_EFFORT` | 任意 | 既定 `medium` |

追加のカスタムフィールドを入力へ含める場合は、workflowのFetch stepに `JSM_EXTRA_FIELDS` を追加してください。値は `customfield_12345,customfield_67890` のように指定します。

## 導入

1. このディレクトリの中身を対象リポジトリのルートへ配置します。
2. 上記SecretsとVariablesを登録します。
3. RepositoryのActions設定で、workflowからPull Requestを作成できるようにします。
4. `Actions > Sync JSM knowledge > Run workflow` から、まず課題キー1件を指定して試します。
5. 作成されたPull Requestで、問い合わせ・回答の対応と機密情報の除去を確認します。
6. 問題なければ定期実行を利用します。既定は毎日03:00（日本時間）です。

## Workatoから1件ずつ起動する場合

WorkatoからGitHubのRepository dispatch APIを呼び、`event_type` とJSM課題キーを渡します。

```json
{
  "event_type": "jsm_knowledge_sync",
  "client_payload": {
    "issue_key": "ITSD-123"
  }
}
```

この場合、Repository variableのJQLより課題キーが優先されます。課題キーは `A-Z / 0-9 / _` とハイフンからなる形式だけを受け付けます。

## ローカルテスト

```bash
python -m unittest discover -s tests -v
python -m py_compile scripts/fetch_jsm.py scripts/validate_knowledge.py
```

## 運用上の注意

- JSM上の公開コメントをすべて「回答候補」として渡します。Codexが会話から回答を整理しますが、最終判断はPull Requestレビューで行います。
- 顧客本人と同じaccount IDのコメントを `requester`、それ以外を `support_candidate` と分類します。代理起票や参加者の発言がある場合、この分類は完全ではありません。
- 内部コメントは取得しても入力から除外します。ただし認証ユーザーが顧客権限だけの場合、JSM APIは公開コメントのみ返します。
- 取得結果は `.work/` に置き、Gitにはコミットしません。
- Codexによる `knowledge/` 外の変更はworkflowを失敗させます。
