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
import pandas as pd

from study_data import build_study
from research_metrics import integer, retrieval_stats

PAGES = ("研究總覽", "學生學習歷程", "不同類別生詞的比較分析", "主動提取練習與延宕記憶分析", "研究資料匯出")


def export_zip(linked, events, tests, tables=None, initial=(), rounds=(), course=()):
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
    summary = tables or {}
    initial_export = [{"student":pseudonym("student",r["student_code"]),"word_id":r["word_id"],
                       **{k:r.get(k) for k in ("initial_target_hit","initial_acceptable","target_status",
                          "retrievals_to_first_target","retrievals_to_first_correct","observed_retrievals")}}
                      for r in initial]
    rounds_export = [identity(r) | {"session":pseudonym("session",r["session_id"]),
                     "completed":r["completed"],"first_all_correct_round":r["first_all_correct_round"]} for r in rounds]
    course_export = [{k:v for k,v in r.items() if k!="student_code"} |
                     {"student":pseudonym("student",r["student_code"])} for r in course]
    summary = summary | {"course_overview":course_export}
    workbook_tables = summary | {"acquisition_detail":initial_export,"daily_rounds":rounds_export,
                                 "delayed":delayed,"assessments":assessments,"practice":practice}
    workbook = io.BytesIO()
    with pd.ExcelWriter(workbook, engine="xlsxwriter", engine_kwargs={"options":{
            "strings_to_formulas":False,"strings_to_urls":False}}) as writer:
        for sheet, rows in workbook_tables.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=sheet, index=False)

    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("research.xlsx",workbook.getvalue())
        for name, rows in (summary | {"acquisition_detail":initial_export,"daily_rounds":rounds_export}).items():
            archive.writestr(name+".csv", encode(rows, list(dict.fromkeys(key for row in rows for key in row))))
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
    data = build_study(store,query)
    if data.get("overflow"):
        st.warning("資料不足：單一學生或查詢總量超過上限。請縮小範圍。")
        return
    st.caption("日期篩選適用於日常明細與開始的課程。延宕依學生與課程篩選，並以授權範圍完整歷程追查初期表現。")
    links, tables = data["links"],data["tables"]
    if page == PAGES[0]:
        st.subheader("學生 × 課次")
        st.dataframe(data["course"])
        st.subheader("首次提取與未達標")
        st.dataframe(tables["acquisition"])
        st.dataframe(tables["target_curve"])
        st.caption("命中曲線保留有觀測但未命中的個案。無作答及無法確認次序的個案另列。")
        st.subheader("每日首次全對輪次")
        st.dataframe(data["rounds"])
        st.subheader("延宕出席與試卷狀態")
        st.dataframe(data["tests"])
    elif page == PAGES[1]:
        st.subheader("逐事件日常作答")
        st.dataframe(data["events"])
        st.subheader("各版本答案鍵")
        st.dataframe(data["words"])
        st.subheader("正式延宕作答與再次接觸")
        st.dataframe(links)
    elif page == PAGES[2]:
        st.dataframe(tables["category_practice"])
        st.subheader("詞性 × 題型")
        st.dataframe(tables["pos_practice"])
        st.subheader("目標詞保留率與可接受答案正確率")
        st.caption("首次正式提交的題數為分母，期限內與補測分開。已交卷的空白題計入分母。缺考排除。")
        if links:
            st.dataframe(tables["category_delayed"])
            st.dataframe(tables["pos_delayed"])
        else:
            st.info("延宕保留率：資料不足")
    elif page == PAGES[3]:
        st.dataframe(retrieval_stats(data["events"]))
        st.subheader("初期表現、提取成本與延宕結果")
        st.dataframe(data["initial"])
        if links:
            st.dataframe(links)
            st.caption("相關係數依期限內／補測分列，只用完整配對題。少於三題或無變異時留空；同一學生與生詞可重複，僅作探索。")
            st.dataframe(tables["associations"])
        else:
            st.info("延宕關聯：資料不足")
        st.caption("空白指標表示資料不足。混合來源的同日作答及缺漏序號會影響可辨識的初期指標。")
    else:
        st.caption("研究 ZIP 移除原始學生代碼、正式作答文字與絕對時間。課程、生詞和間隔仍應按研究資料管理。")
        references = {event_id for row in links for event_id in row["interim_practice_event_ids"]}
        references.update(event_id for row in links for event_id in row["boundary_time_uncertain_event_ids"])
        references.update(row["initial_event"] for row in links if row.get("initial_event"))
        references.update(row["first_correct_event"] for row in links if row.get("first_correct_event"))
        export_ids = references | {row["event_id"] for row in data["events"]}
        export_events = [row for row in data["history"] if row["event_id"] in export_ids]
        st.download_button("下載去識別化研究 ZIP", export_zip(links, export_events, data["tests"],tables,data["initial"],data["rounds"],data["course"]),
                           "vocab-research.zip", "application/zip")
