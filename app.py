import streamlit as st

st.navigation([
    st.Page("legacy_gift.py", title="Moodle GIFT", default=True),
    st.Page("teacher_app.py", title="VocabResearch 教師端", url_path="teacher"),
    st.Page("account_admin.py", title="私人帳號管理", url_path="accounts"),
]).run()
