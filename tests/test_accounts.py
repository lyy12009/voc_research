import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

from account_admin import parse_students


class AccountTests(unittest.TestCase):
    def test_csv_utf8_bom_leading_zero_and_password_redaction(self):
        entries=parse_students("班,學號,密碼\n一班,00123,fixture-pin\n".encode("utf-8-sig"))
        self.assertEqual(entries[0]["student_code"],"00123")
        with self.assertRaisesRegex(ValueError,"學號重複"):
            parse_students("班,學號,密碼\n一班,00123,fixture-pin\n二班,00123,fixture-other\n".encode())
        with self.assertRaisesRegex(ValueError,"欄位須依序"):
            parse_students("學號,班,密碼\n00123,一班,fixture-pin\n".encode())

    def test_management_denies_teacher_without_operator_role(self):
        app=AppTest.from_file("account_admin.py")
        app.secrets["teacher"]={"issuer":"https://issuer.test"}
        class Claims(dict):
            is_logged_in=True
        with patch("streamlit.user",Claims(iss="https://issuer.test",sub="teacher")), patch("cloud_teacher.TeacherStore") as store:
            store.return_value.accounts.side_effect=PermissionError("teacher_denied")
            app.run()
        self.assertIn("沒有帳號管理權限",app.error[0].value)
        self.assertFalse(any("匯入學生" in x.label for x in app.button))
