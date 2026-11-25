# voc_research

`main/app.py` 是現有 Streamlit Community Cloud App 的來源。新版入口保留 Moodle GIFT 頁作為預設，並新增 VocabResearch 教師頁。

## 本機驗收

在儲存庫根目錄執行：

```text
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py"
npm install
npm run test:db
npm run test:browser
python -m streamlit run app.py
```

Chrome 測試使用隔離的 PGlite PostgreSQL 與真實學生頁面。若系統上的 Chrome 不在 Playwright 預設路徑，設定 `VOCAB_E2E_CHROME` 指向執行檔，或使用 `npx playwright-core install chromium`。可選的 Supabase HTTP 測試變數記在 `tests/cloud-browser.test.mjs`，僅供合成測試環境使用。

## 隔離 Community Cloud App

- 部署獨立的測試 App，選擇開發分支、`app.py` 和 Python 3.12。現有 `voc_research` App 綁定 `main`。
- 在隔離 Supabase 專案先核對遷移史。空白測試庫依序套用所有 migration。既有資料庫依遷移史僅審查及套用尚未執行的增量 migration。正式環境需先確認安全設定與權限。
- 由資料庫管理者在受控連線建立專用 LOGIN 角色，例如 `vocab_teacher_web`，啟用繼承，停用 superuser、createrole、createdb、replication 及 bypassrls，僅授予 `vocab_teacher_runtime` 成員資格。使用管理端安全輸入方式設定密碼，勿把密碼放入指令歷史或 SQL 檔。不要將私有 schema 加到 Data API exposed schemas。
- 以 OIDC 提供者的正確 issuer 與穩定 subject，在 `vocab_teacher.identities` 登錄已核准的教師。Streamlit 驗證登入，資料庫每次操作重新確認帳號仍啟用。停權可將 `active` 設為 false。教師僅查閱其負責的課程與學生。研究紀錄不經由瀏覽器持有的資料庫憑證。
- 以官方 OIDC 設定啟用 Streamlit 身分驗證。回呼使用測試 App 的 `/oauth2callback`。確認 Community Cloud 帳號的私有 App 額度及現有 Moodle 使用者可見性，再規劃正式切換。
- 教師資料庫使用 Supabase Session Pooler，使用者格式為 `vocab_teacher_web.<PROJECT_REF>`。以 `sslmode=verify-full` 及受信任 CA 驗證。App Secrets 範例僅列欄位：

```toml
[auth]
redirect_uri = "https://<test-app>.streamlit.app/oauth2callback"
cookie_secret = "<random-secret>"
client_id = "<oidc-client-id>"
client_secret = "<oidc-client-secret>"
server_metadata_url = "<oidc-discovery-url>"

[teacher]
issuer = "<exact-oidc-issuer>"
dsn = "<restricted postgres DSN with sslmode=verify-full>"
test_branch = "codex/vocab-cloud-test-synthetic"
project_url = "https://<isolated-project-ref>.supabase.co"
publishable_key = "<isolated-project-publishable-key>"
github_token = "<repository-scoped contents-write credential>"
```

測試分支必須預先存在，且未綁定 GitHub Pages 或正式 App。發布私有答案鍵後才提交公開檔案，GitHub 連線失敗可用相同版本與內容重試。改動同版內容需提高版本號。正式公開教材目的地需另行確認。

## 私人資料

教師可在 GUI 匯入既有課文 JSON（冊、課、對話／文章）與既有草稿 JSON（含 `lesson_key`、`meta`、`rows`）。舊詞庫可先用原專案的轉換器產生含三語詞義的草稿，再匯入。部署儲存庫不含正式教材、詞庫、草稿與答案鍵。未獲授權前，僅匯入合成資料。

私人文件按教師、名稱與修訂儲存在 PostgreSQL。相同內容可重送，過時的編輯會收到衝突提示。發布以課程 ID、版本及公開內容摘要比對，私人答案只登錄至資料庫。資料庫稽核保存操作者、時間、操作和資源識別，排除 PIN 與私有作答內容。

## 研究資料結構檢核

[研究資料欄位、指標及延宕測驗缺口](RESEARCH.md)

## 合成學習歷程驗收

在開發環境執行：

```text
python -m pip install -r requirements.txt "openpyxl>=3.1,<4"
npm install
npm run synthetic
npm run test:study
```

`npm run synthetic` 以固定種子 20261125 建立合成 PostgreSQL 資料並核對筆數。每次啟動都在獨立 PGlite 記憶體 DB 重新產生，流程結束自動銷毀，不需要連線字串，也沒有清除正式資料的指令。`npm run test:study` 重新產生同一資料集，經授權 SQL 對帳、操作五個 Streamlit 研究頁面、讀回 CSV 與 Excel 比較。大量歷史日期以測試專用種入，真實作答送出、斷線重送和首次延宕鎖定由小型 RPC 及 Chrome 測試另外驗證。