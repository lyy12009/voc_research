"""Authenticated Streamlit teacher workspace."""
import hashlib
import json
from pathlib import Path

import streamlit as st
from streamlit.components.v1 import html

import github_publish
from cloud_teacher import KEY, PublicationConflict, TeacherStore, enrollment_subject, new_draft, principal, read_import, validated_publication
from core import TEXT_PARTS, accepted_answers, sentence_candidates, validate_and_build
from preview import preview_html
from research_metrics import CATEGORIES
from research_ui import render as research_workspace

ROOT = Path(__file__).resolve().parent
ASSETS = {ROOT / path: path for path in github_publish.ASSETS}


def controls():
    st.title("VocabResearch 教師端")
    try:
        settings = st.secrets["teacher"]
    except (FileNotFoundError, KeyError):
        st.info("教師端尚未設定")
        st.stop()

    if not st.user.is_logged_in:
        st.button("教師登入", on_click=lambda: st.login())
        st.stop()
    st.sidebar.button("教師登出", on_click=st.logout)
    try:
        identity = principal(st.user, settings.get("issuer"))
        enrollment = enrollment_subject(st.user, identity, settings)
        if enrollment:
            st.info("正在核對測試教師身分。教師權限尚未開通。")
            st.code(enrollment)
            st.stop()
        store = TeacherStore(settings.get("dsn", ""), identity, settings.get("project_url", ""), settings.get("ssl_root_cert_pem"))
        store.call("authorize")
    except (PermissionError, RuntimeError) as error:
        st.error(str(error))
        st.stop()

    if st.session_state.get("teacher_identity") != identity:
        for key in list(st.session_state):
            if key.startswith("teacher_"):
                del st.session_state[key]
        st.session_state["teacher_identity"] = identity
    return settings, store


def read_document(store, kind, name):
    return store.call("read", {"kind": kind, "name": name})


def save_document(store, kind, name, document, expected):
    if not KEY.fullmatch(name):
        raise ValueError("名稱限英數、句點、底線或連字號，最多 90 字元")
    return store.call("save", {"kind": kind, "name": name, "document": document, "expected": expected})


def imports(store):
    with st.form("teacher_import"):
        kind = st.selectbox("匯入類型", ["book", "draft"], format_func=lambda x: "原教材 JSON" if x == "book" else "既有草稿 JSON")
        name = st.text_input("私人檔案名稱")
        file = st.file_uploader("選擇 JSON", type=["json"])
        confirmed = st.checkbox("我已確認檔案可儲存於本環境")
        if st.form_submit_button("匯入私人檔案"):
            if not file or not confirmed:
                st.warning("請選擇檔案並確認存放環境")
            else:
                doc = read_import(file.getvalue(), kind)
                revision = save_document(store, kind, name, doc, 0)
                st.success(f"已匯入修訂 {revision}")


def draft_picker(store):
    left, right = st.columns(2)
    with left:
        title = st.selectbox("開啟私人草稿", [""] + store.call("list", {"kind": "draft"}))
        if st.button("開啟草稿", disabled=not title):
            record = read_document(store, "draft", title)
            doc = record["document"]
            if "lesson" not in doc:
                parts = str(doc.get("lesson_key", "")).split("｜", 1)
                if len(parts) != 2:
                    raise ValueError("無法辨識舊版草稿的冊課")
                doc = {**doc, "lesson": dict(zip(("冊", "課"), parts))}
            st.session_state["teacher_editor"] = (title, record["revision"], doc)
            st.session_state["teacher_editor_epoch"] = st.session_state.get("teacher_editor_epoch", 0) + 1
    with right:
        books = store.call("list", {"kind": "book"})
        if books:
            book = st.selectbox("教材", books)
            lessons = read_document(store, "book", book)["document"]
            volume = st.selectbox("冊次", list(dict.fromkeys(str(lesson["冊"]) for lesson in lessons)))
            available = [lesson for lesson in lessons if str(lesson["冊"]) == volume]
            index = st.selectbox("課次", list(range(len(available))), format_func=lambda i: str(available[i]["課"]))
            parts = st.multiselect("課文節次", TEXT_PARTS, default=list(TEXT_PARTS))
            if st.button("以選擇的課次建立草稿"):
                doc = new_draft(available[index], parts)
                for row in doc["rows"]:
                    candidates = sentence_candidates(available[index], row["word"], parts)
                    if candidates:
                        row["sentence"] = candidates[0]
                st.session_state["teacher_editor"] = ("", 0, doc)
                st.session_state["teacher_editor_epoch"] = st.session_state.get("teacher_editor_epoch", 0) + 1
        if st.button("建立空白草稿"):
            st.session_state["teacher_editor"] = ("", 0, new_draft({"冊": "", "課": ""}, []))
            st.session_state["teacher_editor_epoch"] = st.session_state.get("teacher_editor_epoch", 0) + 1


def publish(store, settings, public, private):
    branch, config = validated_publication(settings)
    token = settings.get("github_token")
    if not token:
        raise ValueError("尚未設定測試發布憑證")
    digest = hashlib.sha256(github_publish.encode_json(public)).hexdigest()
    packet = {"document": private, "manifest": {"sha256": digest, "branch": branch, "backend": config["projectUrl"]}}
    try:
        store.call("course", packet)
    except PublicationConflict:
        if any(word.get("part_of_speech") for word in private["words"]):
            raise
        # The bridge verifies the immutable manifest and every legacy private field.
        legacy = private | {"words": [{key: value for key, value in word.items() if key != "category"}
                                      for word in private["words"]]}
        store.call("course", packet | {"document": legacy})
    st.info("Supabase 私人答案鍵已確認。若 GitHub 階段失敗，請用相同版本及內容重試。")
    path, _ = github_publish.publish(token, public, ASSETS, config, branch)
    st.success(f"已發布至測試分支的 {path}")


def editor(store, settings):
    draft_picker(store)
    entry = st.session_state.get("teacher_editor")
    if entry is None:
        return
    previous_name, revision, document = entry
    epoch = st.session_state["teacher_editor_epoch"]

    def input_text(label, value, suffix, multiline=False):
        widget = st.text_area if multiline else st.text_input
        return widget(label, value=str(value or ""), key=f"teacher_{epoch}_{suffix}")

    name = input_text("草稿名稱", previous_name, "name")
    lesson = {field: input_text(field, document["lesson"].get(field), field) for field in ("冊", "課")}
    meta = {**document["meta"]}
    labels = {"id": "課程 ID", "version": "教材版本", "title": "課程名稱"}
    for field, label in labels.items():
        meta[field] = input_text(label, meta.get(field), field)
    rows = []
    for index, original in enumerate(document["rows"]):
        with st.expander(f"生詞 {index + 1} {original.get('word', '')}"):
            row = dict(original)
            row["included"] = st.checkbox("納入練習", value=bool(row.get("included", True)), key=f"teacher_{epoch}_{index}_included")
            for field, label in {"word": "生詞", "pinyin": "拼音", "sentence": "填空句"}.items():
                row[field] = input_text(label, row.get(field), f"{index}_{field}")
            source = row.get("meanings")
            source = source if isinstance(source, dict) else {}
            row["meanings"] = {language: input_text(label, source.get(language), f"{index}_{language}")
                               for language, label in (("en", "英語"), ("vi", "越南語"), ("id", "印尼語"))}
            categories = list(CATEGORIES)[:-1]
            stored_category = row.get("category") or "unknown"
            if stored_category not in categories:
                categories.append(stored_category)
            row["category"] = st.selectbox("生詞類別", categories, index=categories.index(stored_category),
                                          format_func=lambda value: CATEGORIES.get(value, value),
                                          key=f"teacher_{epoch}_{index}_category")

            row["part_of_speech"] = st.text_input("詞性（教師確認，選填）", value=str(row.get("part_of_speech") or ""),
                                                 max_chars=40, key=f"teacher_{epoch}_{index}_pos")
            row["accepted"] = input_text("其他可接受答案（選填，每行一個）",
                                         "\n".join(accepted_answers(row.get("accepted"))), f"{index}_accepted", True)
            rows.append(row)
    updated = {**document, "lesson": lesson, "rows": rows, "meta": meta}
    if st.button("新增補充生詞"):
        updated["rows"].append({"category": "supplement"})
        st.session_state["teacher_editor"] = (previous_name, revision, updated)
        st.rerun()
    if st.button("儲存私人草稿"):
        saved = save_document(store, "draft", name, updated, revision if name == previous_name else 0)
        st.session_state["teacher_editor"] = (name, saved, updated)
        st.success(f"已儲存修訂 {saved}")
    if st.checkbox("預覽學生練習"):
        _, preview, _ = validate_and_build(lesson["冊"], lesson, rows, meta, preview=True)
        html(preview_html(preview, ROOT / "student"), height=560, scrolling=True)
    if st.button("登錄並發布合成測試教材"):
        problems, public, private = validate_and_build(lesson["冊"], lesson, rows, meta)
        if problems:
            for problem in problems:
                st.error(problem)
        else:
            publish(store, settings, public, private)


def management(store, settings):
    with st.form("teacher_student", clear_on_submit=True):
        code = st.text_input("新學生代碼")
        pin = st.text_input("學生 PIN", type="password")
        if st.form_submit_button("建立測試學生"):
            store.call("student", {"code": code, "pin": pin})
            st.success("已確認學生帳號")
    if st.checkbox("查閱已登錄版本及練習紀錄"):
        versions = store.call("versions")
        st.dataframe(versions)
        sessions = store.call("practice")
        st.dataframe(sessions)
        selected = st.selectbox("作答明細", [""] + [session["session_id"] for session in sessions])
        if selected:
            st.dataframe(store.call("answers", {"name": selected}))
        if versions:
            index = st.selectbox("顯示管理版本", list(range(len(versions))),
                                 format_func=lambda i: f"{versions[i]['id']} / {versions[i]['version']}")
            visible = st.checkbox("在測試教材清單顯示", value=True)
            if st.button("更新測試版本顯示狀態"):
                branch, _ = validated_publication(settings)
                version = versions[index]
                file = version["id"] + "__" + version["version"] + ".json"
                store.call("can_manage_version", {"name": version["id"], "version": version["version"], "branch": branch})
                github_publish.set_visibility(settings.get("github_token"), file, visible, branch)
                store.call("visibility", {"name": version["id"], "version": version["version"], "branch": branch, "visible": visible})
                st.success("已確認測試版本顯示狀態")


settings, store = controls()
for tab, operation in zip(st.tabs(["教材與草稿匯入", "編輯與發布", "學生與研究紀錄", "研究資料與分析"]), (imports, editor, management, research_workspace)):
    with tab:
        try:
            if operation is imports:
                operation(store)
            else:
                operation(store, settings)
        except (ValueError, RuntimeError, PermissionError) as error:
            st.error(str(error))
