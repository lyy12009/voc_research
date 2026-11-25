# VocabResearch 隔離雲端驗收

## 環境

- Streamlit 測試 App 為 [VocabResearch Integration](https://vocabresearch-integration.streamlit.app)，來源 `lyy12009/voc_research` 的 `codex/voc-research-cloud-teacher`、`app.py`、Python 3.12。
- 獨立 Supabase 專案是 GZB 的 [VocabResearch Integration](https://supabase.com/dashboard/project/pcqzkpuxolmfvcfvwxyg)，專用於合成資料。已套用 `001`–`006` 並確認重新預演無待執行項目。已強制資料庫 TLS。
- 正式專案只讀取系統目錄。遷移史有 `001`、`002`，預演僅列出 `003`–`006`，未列初始化、種子資料或額外角色檔。沒有職能角色或 schema 同名衝突，五個既有登錄／判分函式的原始內容雜湊與測試環境一致。
- 正式五張私人表皆開啟 RLS，兩個既有研究檢視亦不授權匿名或登入角色讀取。隔離環境的十二張私人表皆開啟 RLS，匿名、登入角色及教師執行角色皆無直接 SELECT。教師 RPC 限受限角色，學生 RPC 限匿名公開入口，再核對學生代碼與 PIN。
- 正式專案暫停實際增量部署，等候教師真實 OIDC 驗收。測試端未對正式 Supabase、正式 App、GitHub Pages 或 `main` 做異動。

## 驗收結果與重跑

- 測試 App 可生成 Moodle GIFT，教師頁在登入設定缺失時關閉。真實 OIDC 使用者登入、從已部署 Streamlit 連入資料庫，以及測試 App 重啟後教師資料重讀，待授權的 OIDC 與 Secrets 完成後驗證。
- Chrome 從本機供應開發版學生頁，實際跨 HTTPS 連到隔離 Supabase，完成七項子測試，含帳號隔離、兩頁、離線、重送、原詞與備選答案、課程跨版本鎖定。實際延宕 HTTPS 測試另外確認第 8 天進場、備選答案判正且未命中原詞，以及交卷重送不覆寫。
- 在隔離 Supabase 以 `sslmode=verify-full`、官方 CA 與受限登入連線，確認可走教師 RPC、不可讀私人表，並跨新連線讀回草稿。TLS 驗證結束後停用一次性登入。應用程式可從 Secrets 載入公開 CA PEM。
- 真實教師 RPC 和 GitHub 測試分支也透過本機 AppTest 操作驗證，涵蓋教材編輯、私密草稿跨工作階段重開、詞性登錄、公開教材排除詞性與備選答案、相同發布重試不新增提交。OIDC 身分在此步驟以合成聲明代入，後端與 GitHub 都是真實測試服務。
- 隔離雲端合成資料包含 10 位學生、25 個工作階段、3,002 筆事件及 10 次測驗安排。使用測試資料庫 SQL 結果操作本機 Streamlit AppTest 的五頁，對帳七張 CSV／Excel 彙總表。這些是驗收規模。
- 雲端研究重跑命令為 `node --test tests/cloud-study.test.mjs`，使用 `VOCAB_STAGE_REF`、`VOCAB_SUPABASE_CLI`。會核對專案名稱並拒絕正式專案。設 `VOCAB_STAGE_REUSE=1` 可使用已經建立且筆數一致的合成資料。SQL 讀取維持 PostgreSQL 唯讀交易，使用管理連線而不放寬教師 RPC 權限。
- 雲端部署冒煙測試為 `node --test tests/cloud-streamlit.test.mjs`，`VOCAB_STAGE_STREAMLIT` 使用上述測試 App，搭配既有 Playwright 瀏覽器設定。

## 尚需授權

使用您控制的 OIDC 提供者建立或授權測試用戶端，回呼為 `https://vocabresearch-integration.streamlit.app/oauth2callback`。OAuth 客戶端憑證與隔離測試分支的 repository-scoped 寫入憑證放在測試 App Secrets。只要授權可使用的測試教師身分，即可完成受限資料庫登入設定與後續端到端重跑。全程不需提供正式資料庫管理密碼。
