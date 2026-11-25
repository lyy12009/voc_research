import streamlit as st

st.navigation([
    st.Page("legacy_gift.py", title="Moodle GIFT", default=True),
    st.Page("teacher_app.py", title="VocabResearch 教師端", url_path="teacher"),
]).run()
