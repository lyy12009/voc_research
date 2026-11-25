import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from cloud_teacher import principal, read_import, validated_publication, verify_pooler


def find(elements, label):
    return next(element for element in elements if element.label == label)


class MemoryStore:
    def __init__(self):
        self.docs = {}
        self.registrations = []
        self.permitted = True

    def call(self, action, payload=None):
        if not self.permitted:
            raise PermissionError("此帳號沒有教師權限")
        if action == "authorize":
            return True
        if action == "list":
            return [name for kind, name in self.docs if kind == payload["kind"]]
        if action in ("read", "save"):
            key = payload["kind"], payload["name"]
            if action == "save":
                previous = self.docs.get(key, {"revision": 0})
                self.docs[key] = {"revision": previous["revision"] + 1, "document": payload["document"]}
                return self.docs[key]["revision"]
            return self.docs[key]
        if action == "versions":
            return [{"id":"IT_fixture","version":"v1"}]
        if action == "practice":
            return [{"session_id":"fixture-session","incorrect_answers":1}]
        if action == "answers":
            return [{"selected":"錯誤","correct_server":False}]
        self.registrations.append((action, payload))
        return True


class TeacherTests(unittest.TestCase):
    def app(self):
        return AppTest.from_file("teacher_app.py", default_timeout=12)

    def teacher(self):
        app = self.app()
        app.secrets["teacher"] = {"issuer": "https://issuer.test", "dsn": "synthetic",
                                  "test_branch": "codex/vocab-cloud-test-synthetic",
                                  "project_url": "https://fixture.supabase.co",
                                  "publishable_key": "sb_publishable_fixture", "github_token": "fixture-token"}
        return app

    def test_moodle_gift_still_generates_category_and_questions(self):
        app = AppTest.from_file("app.py", default_timeout=15).run()
        for box in app.checkbox:
            box.set_value(False)
        app.run()
        find(app.button, "🔄 點此生成/更新題庫 (需向 Google 獲取語音)").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.get("download_button"))
        self.assertIn("$CATEGORY:", app.session_state["generated_gift"])
        self.assertIn("鞏固", app.session_state["generated_gift"])

    def test_missing_settings_and_unlisted_teacher_are_blocked(self):
        app = self.app().run()
        self.assertTrue(app.info)
        self.assertFalse(app.tabs)
        store = MemoryStore()
        store.permitted = False
        class Claims(dict):
            is_logged_in = True
        with patch("streamlit.user", Claims(iss="https://issuer.test", sub="s")), patch("cloud_teacher.TeacherStore", return_value=store):
            app = self.teacher().run()
            self.assertFalse(app.exception)
            self.assertIn("沒有教師權限", app.error[0].value)
            self.assertFalse(app.tabs)

    def test_edit_reload_and_publish_with_private_alias_only(self):
        class Claims(dict):
            is_logged_in = True
        store = MemoryStore()
        store.docs["book", "intro"] = {"revision": 1, "document": [
            {"冊": "一", "課": "一", "對話1生詞": ["甲"], "對話1": "這裡有甲。"},
            {"冊": "二", "課": "二", "對話1生詞": ["乙"], "對話1": "這裡有乙。"},
        ]}
        with patch("streamlit.user", Claims(iss="https://issuer.test", sub="s")), patch("cloud_teacher.TeacherStore", return_value=store), patch("github_publish.publish", return_value=("synthetic.json", {})) as push:
            app = self.teacher().run()
            find(app.selectbox, "冊次").select("二").run()
            find(app.button, "以選擇的課次建立草稿").click().run()
            self.assertEqual(find(app.text_input, "生詞").value, "乙")
            self.assertIn("＿＿", find(app.text_input, "填空句").value)
            for label, value in [("草稿名稱","synthetic"),("課程 ID","IT_gui"),("課程名稱","合成教材"),
                                 ("拼音","yǐ"),("英語","beta"),("越南語","beta-vi"),("印尼語","beta-id")]:
                find(app.text_input, label).set_value(value)
            find(app.text_area, "其他可接受答案（選填，每行一個）").set_value("第二")
            find(app.button, "儲存私人草稿").click().run()
            self.assertFalse(app.exception)
            app = self.teacher().run()
            find(app.selectbox, "開啟私人草稿").select("synthetic").run()
            find(app.button, "開啟草稿").click().run()
            self.assertEqual(find(app.text_area, "其他可接受答案（選填，每行一個）").value, "第二")
            self.assertEqual(find(app.text_input, "越南語").value, "beta-vi")
            find(app.button, "登錄並發布合成測試教材").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(store.registrations[-1][1]["document"]["words"][0]["accepted"], ["第二"])
            self.assertNotIn("accepted", push.call_args.args[1]["words"][0])
            push.side_effect = RuntimeError("測試 GitHub 失敗")
            find(app.button, "登錄並發布合成測試教材").click().run()
            self.assertIn("Supabase 私人答案鍵已確認", app.info[-1].value)
            self.assertIn("測試 GitHub 失敗", app.error[-1].value)

    def test_teacher_student_and_research_widgets(self):
        class Claims(dict):
            is_logged_in = True
        store = MemoryStore()
        with patch("streamlit.user", Claims(iss="https://issuer.test", sub="s")), patch("cloud_teacher.TeacherStore", return_value=store), patch("github_publish.set_visibility") as visibility:
            app = self.teacher().run()
            find(app.text_input, "新學生代碼").set_value("IT_S")
            find(app.text_input, "學生 PIN").set_value("fixture-participant-pin")
            find(app.button, "建立測試學生").click().run()
            self.assertEqual(store.registrations[0][0], "student")
            find(app.checkbox, "查閱已登錄版本及練習紀錄").check().run()
            find(app.selectbox, "作答明細").select("fixture-session").run()
            self.assertEqual(len(app.dataframe), 3)
            find(app.checkbox, "在測試教材清單顯示").uncheck()
            find(app.button, "更新測試版本顯示狀態").click().run()
            self.assertFalse(app.exception)
            self.assertEqual([name for name, _ in store.registrations[1:]], ["can_manage_version", "visibility"])
            self.assertEqual(visibility.call_args.args[1:3], ("IT_fixture__v1.json", False))

    def test_input_boundaries(self):
        with self.assertRaises(PermissionError):
            principal({"iss":"different", "sub":"teacher"}, "https://issuer.test")
        with self.assertRaises(ValueError):
            validated_publication({"test_branch":"main"})
        with self.assertRaises(ValueError):
            read_import(b'{"rows":[]}',"draft")
        verify_pooler({"host":"aws-0-fixture.pooler.supabase.com", "user":"vocab_teacher_web.fixture",
                       "dbname":"postgres", "sslmode":"verify-full"}, "https://fixture.supabase.co")
        with self.assertRaises(ValueError):
            verify_pooler({"host":"aws-0-fixture.pooler.supabase.com", "user":"postgres.fixture",
                           "dbname":"postgres", "sslmode":"verify-full"}, "https://fixture.supabase.co")
        self.assertEqual(read_import(b'{"rows":[],"meta":{}}',"draft")["rows"], [])


if __name__ == "__main__":
    unittest.main()
