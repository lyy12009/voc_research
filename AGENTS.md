# VocabResearch Streamlit 整合

- `app.py` 是 Community Cloud 入口。`legacy_gift.py` 保留 Moodle GIFT 題庫產生器。`teacher_app.py` 是成人華語生詞記憶研究的教師頁。
- 學生練習以臺灣日期為準，每位學生每課跨版本每日一次。可在同一工作階段反覆作答，後端驗證全對後鎖定。
- 保存實際輸入、目標詞命中、首次作答及錯誤紀錄。備選答案由教師審閱。公開教材只含可發布欄位，答案鍵留在 Supabase。
- 使用私人教材、草稿及研究資料前先確認環境與授權。以合成資料驗收。基準及已套用 SQL 不重跑。
- `main/app.py` 為現有正式 App 的部署來源。合併或推送可能觸發自動部署。獲准前只使用獨立開發與測試分支。
- 依 README 執行 AppTest、隔離 PostgreSQL 與 Chrome 測試。正式部署前另行驗證 OIDC 和 Supabase Session Pooler。
