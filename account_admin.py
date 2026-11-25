"""Private account administration for the authenticated Google account operator."""
import csv
import io
import re

import streamlit as st

from cloud_teacher import TeacherStore, principal

HEADERS = ["班", "學號", "密碼"]


def parse_students(raw):
    if len(raw) > 512_000:
        raise ValueError("CSV 大小超過上限")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        if reader.fieldnames != HEADERS:
            raise ValueError("CSV 欄位須依序為：班,學號,密碼")
        result = []
        seen = set()
        for row in reader:
            if None in row or any(row.get(key) is None for key in HEADERS):
                raise ValueError(f"CSV 第 {reader.line_num} 列欄位數不正確")
            group, code, password = row["班"].strip(), row["學號"].strip(), row["密碼"]
            if (not 1 <= len(group) <= 80 or not re.fullmatch(r"[A-Za-z0-9_-]{3,32}", code)
                    or not password.strip() or not 8 <= len(password) or len(password.encode()) > 72):
                raise ValueError(f"CSV 第 {reader.line_num} 列有無效班級、學號或密碼")
            if code in seen:
                raise ValueError(f"CSV 第 {reader.line_num} 列學號重複")
            seen.add(code)
            result.append({"class_name":group,"student_code":code,"password":password})
        if not 1 <= len(result) <= 500:
            raise ValueError("每批須包含 1 至 500 位學生")
        return result
    except (UnicodeError, csv.Error):
        raise ValueError("請使用 Excel 匯出的 UTF-8 CSV") from None


def render():
    st.title("私人帳號管理")
    try:
        settings = st.secrets["teacher"]
    except (FileNotFoundError, KeyError):
        st.info("教師端尚未設定")
        return
    if not st.user.is_logged_in:
        st.button("管理者登入", on_click=st.login)
        return
    try:
        identity = principal(st.user, settings.get("issuer"))
        store = TeacherStore(settings.get("dsn", ""), identity, settings.get("project_url", ""),
                             settings.get("ssl_root_cert_pem"))
        store.accounts("authorize")
    except (PermissionError, RuntimeError):
        st.error("此帳號沒有帳號管理權限")
        return
    st.sidebar.button("管理者登出", on_click=st.logout)
    try:
        with st.form("account_invite", clear_on_submit=True):
            email = st.text_input("出題教師 Google 電子郵件")
            if st.form_submit_button("邀請出題教師"):
                store.accounts("invite", {"email":email})
                st.success("已加入出題邀請。測試期也須在 Google Auth Platform 登記該使用者。")
        with st.form("account_csv", clear_on_submit=True):
            upload = st.file_uploader("學生 CSV（班、學號、密碼）", type=["csv"])
            if st.form_submit_button("匯入學生帳號"):
                if upload is None:
                    raise ValueError("請選擇 CSV 檔")
                n = store.accounts("import_students", {"students":parse_students(upload.getvalue())})
                st.success(f"已匯入 {n} 位學生")
        accounts = store.accounts("list")
        st.subheader("出題教師")
        st.dataframe(accounts["teachers"], hide_index=True)
        st.subheader("學生（最多顯示 500 筆）")
        st.dataframe(accounts["students"], hide_index=True)
    except (ValueError, RuntimeError, PermissionError) as error:
        st.error(str(error))

if __name__ == '__main__':
    render()
