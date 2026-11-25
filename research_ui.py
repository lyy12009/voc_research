"""Teacher-only research workspace."""
import csv
from datetime import date, datetime, timedelta
import hashlib
import hmac
import io
import re
import secrets
from zipfile import ZipFile, ZIP_DEFLATED
from zoneinfo import ZoneInfo

import streamlit as st

from delayed_metrics import associations, delayed_links, first_per_word, retention_by_category
from research_metrics import category_stats, course_stats, integer, retrieval_stats

PAGES = ("研究總覽", "學生學習歷程", "不同類別生詞的比較分析", "主動提取練習與延宕記憶分析", "研究資料匯出")


def export_zip(linked, events, tests):
    salt = secrets.token_bytes(32)

    def pseudonym(kind, value):
        return hmac.new(salt, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:24]

    def safe(value):
        return "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value

    def encode(rows, fields):
        text = io.StringIO(newline="")
        writer = csv.DictWriter(text, fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: safe(row.get(key)) for key in fields})
        return text.getvalue().encode("utf-8-sig")

    def identity(row):
        return {"student": pseudonym("student", row["student_code"]), "course": row["course_id"],
                "version": row["course_version"]}

    delayed = [identity(r) | {k: r[k] for k in ("word_id", "target_hit", "correct_server", "answer_type",
                                                           "is_makeup", "delay_days")} |
               {"initial_event": pseudonym("event", r["initial_event"]) if r.get("initial_event") else None,
                "interim_events": " ".join(pseudonym("event", e) for e in r.get("interim_practice_event_ids", [])),
                "timing_uncertain_events": " ".join(pseudonym("event", e) for e in r.get("boundary_time_uncertain_event_ids", []))}
               for r in linked]
    assessments = [identity(r) | {"status": r["status"], "delay_days": r["delay_days"], "missed_regular_window": r.get("missed_regular_window")} for r in tests]
    dated = {}
    for event in events:
        student, day = event["student_code"], event["practice_date"]
        dated[student] = min(day, dated.get(student, day))
    practice = [identity(r) | {
        "word_id": r["word_id"], "event": pseudonym("event", r["event_id"]),
        "day": (date.fromisoformat(r["practice_date"]) - date.fromisoformat(dated[r["student_code"]])).days,
        "correct_server": r["correct_server"], "target_hit": r["target_hit"],
        "word_attempt": integer(r["word_attempt"]), "session": pseudonym("session", r["session_id"]),
        "submission": pseudonym("submission", r["submission_id"]) if r["submission_id"] else None,
        "stage": r["stage"] if r["stage"] in ("card", "match", "cloze") else None,
        "action": r["action"] if r["action"] in ("answer", "card_audio", "card_flip", "card_next") else "other",
    } for r in events]
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        shared = ("student", "course", "version")
        archive.writestr("delayed.csv", encode(delayed, (*shared, "word_id", "target_hit", "correct_server",
                    "answer_type", "is_makeup", "delay_days", "initial_event", "interim_events", "timing_uncertain_events")))
        archive.writestr("assessments.csv", encode(assessments, (*shared, "status", "delay_days", "missed_regular_window")))
        archive.writestr("practice.csv", encode(practice, (*shared, "word_id", "event", "day", "correct_server",
                    "target_hit", "word_attempt", "session", "submission", "stage", "action")))
        archive.writestr("欄位說明.txt", "student、event、session、submission 為此份 ZIP 專用的代碼。\n"
            "practice.day 從學生在本次查詢最早練習日算起。delay_days 從課程結束日算起。\n"
            "target_hit 為原目標詞判定，correct_server 為後端語境正確性。缺考僅見於 assessments。\n"
            "初期與再次接觸以事件代碼連回 practice。刪除實際答案及絕對時間以降低間接辨識風險。")
    return stream.getvalue()


def schedule(store):
    with st.form("delayed_schedule"):
        operation = st.selectbox("安排方式", ("assign", "makeup"), format_func=lambda value: {"assign": "首次安排", "makeup": "允許補測"}[value])
        student = st.text_input("安排學生代碼")
        course = st.text_input("安排課程 ID")
        version = st.text_input("指定教材版本")
        end = st.date_input("課程正式結束日")
        makeup = st.date_input("補測日期")
        if st.form_submit_button("儲存延宕測驗安排"):
            if not student or not course or (operation == "assign" and not version):
                st.error("請填入必要代碼與版本")
            else:
                packet = {"operation": operation, "student": student.strip(), "course": course.strip()}
                packet.update({"version": version.strip(), "end_date": end.isoformat()} if operation == "assign"
                              else {"makeup_date": makeup.isoformat()})
                store.delayed(packet)
                st.success("延宕測驗安排已確認")


def render(store, settings):
    st.header("學習歷程與分析")
    allowed = settings.get("dashboard_admin_subjects", [])
    ref = re.fullmatch(r"https://([a-z0-9-]+)\.supabase\.co/?", settings.get("project_url", ""))
    if isinstance(allowed, (list, tuple)) and store.identity[1] in allowed and ref:
        st.link_button("Supabase 資料庫管理", f"https://supabase.com/dashboard/project/{ref[1]}")
    with st.expander("安排正式測驗或補測"):
        schedule(store)
    page = st.radio("研究頁面", PAGES, horizontal=True)
    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    with st.form("research_scope"):
        start = st.date_input("起始臺灣日期", today - timedelta(days=30))
        end = st.date_input("結束臺灣日期", today)
        course = st.text_input("課程 ID")
        student = st.text_input("學生代碼")
        word = st.text_input("生詞或生詞 ID")
        category = st.selectbox("詞類", ("", "textbook", "topic", "supplement", "unknown"))
        if st.form_submit_button("查詢研究紀錄"):
            if not 0 <= (end-start).days <= 365:
                st.error("日常紀錄查詢範圍最多相差 365 天")
            else:
                st.session_state["teacher_research_scope"] = {"from":start.isoformat(), "to":end.isoformat(),
                    "course":course.strip(), "student":student.strip(), "word":word.strip(), "category":category}
    query = st.session_state.get("teacher_research_scope")
    if not query:
        return
    data = store.research(query)
    delayed = store.delayed({"operation":"read", "course":query["course"], "student":query["student"]})
    history = store.delayed({"operation":"history", "student":query["student"]})
    if any(r.get("overflow") for r in (data, delayed, history)):
        st.warning("資料不足：超過安全查詢上限。請使用學生代碼縮小範圍。")
        return
    st.caption("日期篩選適用於日常明細。初期表現使用授權範圍內的完整歷程；延宕測驗依學生與課程篩選。")
    initial = first_per_word(history["events"])
    selected_words = {row["word_id"] for row in data["words"]}
    delayed_rows = [r for r in delayed["answers"] if (not query["word"] or r["word_id"] in selected_words)
                    and (not query["category"] or r["category"] == query["category"])]
    links = delayed_links(delayed["tests"], delayed_rows, history["events"])
    if page == PAGES[0]:
        st.subheader("學生 × 課次")
        st.dataframe(course_stats(data["sessions"], data["events"] if not query["word"] and not query["category"] else []))
        st.subheader("延宕出席與試卷狀態")
        st.dataframe(delayed["tests"])
    elif page == PAGES[1]:
        st.subheader("逐事件日常作答")
        st.dataframe(data["events"])
        st.subheader("各版本答案鍵")
        st.dataframe(data["words"])
        st.subheader("正式延宕作答與再次接觸")
        st.dataframe(links)
    elif page == PAGES[2]:
        st.dataframe(category_stats(data["events"]))
        st.subheader("目標詞保留率與可接受答案正確率")
        st.caption("首次正式提交的題數為分母，期限內與補測分開。已交卷的空白題計入分母。缺考排除。")
        if links:
            st.dataframe(retention_by_category(links))
        else:
            st.info("延宕保留率：資料不足")
    elif page == PAGES[3]:
        st.dataframe(retrieval_stats(data["events"]))
        st.subheader("初期表現、提取成本與延宕結果")
        st.dataframe([{ "student_code":key[0], "word_id":key[1], **record} for key, record in initial.items()
                      if not (query["course"] or query["word"] or query["category"]) or key[1] in selected_words])
        if links:
            st.dataframe(links)
            st.caption("相關係數依期限內／補測分列，只用完整配對題。少於三題或無變異時留空；同一學生與生詞可重複，僅作探索。")
            st.dataframe(associations(links))
        else:
            st.info("延宕關聯：資料不足")
        st.caption("空白指標表示資料不足。混合來源的同日作答及缺漏序號會影響可辨識的初期指標。")
    else:
        st.caption("研究 ZIP 移除原始學生代碼、正式作答文字與絕對時間。課程、生詞和間隔仍應按研究資料管理。")
        references = {event_id for row in links for event_id in row["interim_practice_event_ids"]}
        references.update(event_id for row in links for event_id in row["boundary_time_uncertain_event_ids"])
        references.update(row["initial_event"] for row in links if row.get("initial_event"))
        references.update(row["first_correct_event"] for row in links if row.get("first_correct_event"))
        visible_events = {row["event_id"] for row in data["events"]}
        export_events = [row for row in history["events"] if row["event_id"] in references | visible_events]
        st.download_button("下載去識別化研究 ZIP", export_zip(links, export_events, delayed["tests"]),
                           "vocab-research.zip", "application/zip")
