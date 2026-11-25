"""Verify the actual Streamlit widgets and downloads using results read from isolated SQL."""
from datetime import date
import csv
import io
import json
import sys
from unittest.mock import patch
from zipfile import ZipFile

from openpyxl import load_workbook
from streamlit.testing.v1 import AppTest

from research_ui import PAGES, export_zip
from study_data import build_study
from test_gui import MemoryStore, find

fixture = json.loads(sys.stdin.buffer.read())


class Store(MemoryStore):
    def study_metadata(self, _):
        return fixture["metadata"]

    def research(self, scope):
        return fixture["parts"].get(scope["student"], {"overflow":True})

    def delayed(self, scope):
        if scope["operation"] == "read":
            return fixture["delayed"]
        return fixture["history"].get(scope["student"], {"overflow":True})


class Claims(dict):
    is_logged_in = True


store = Store()
data = build_study(store, fixture["scope"])
stored = fixture["stored"]
assert len(data["events"]) == stored["events"]
assert len(data["rounds"]) == stored["sessions"]
assert sum(not row["completed"] for row in data["rounds"]) == stored["interrupted"]
assert sum(row["status"] == "missing" for row in data["tests"]) == stored["missed"]
assert sum(row["is_makeup"] is True for row in data["tests"]) == stored["makeup"]
assert sum(row["target_hit"] for row in data["links"]) == stored["target"]
assert sum(row["correct_server"] for row in data["links"]) == stored["acceptable"]
assert len(data["links"]) == stored["items"]
assert any(row["interim_practice_event_ids"] for row in data["links"])
assert any(row["target_status"] == "right_censored" for row in data["initial"])
assert any(row["first_all_correct_round"] == 3 for row in data["rounds"])
assert all(row["first_all_correct_round"] is None for row in data["rounds"] if not row["completed"])
assert any(row["retrievals_to_first_target"] == 1 for row in data["initial"])
assert any(row["retrievals_to_first_target"] == 3 for row in data["initial"])
assert any(row["initial_acceptable"] and not row["initial_target_hit"] for row in data["initial"])
assert any(not row["target_hit"] and row["prior_retrievals"]>0 for row in data["links"])
assert any(row["target_hit"] and row["prior_retrievals"]>1 for row in data["links"])
assert all(row["delay_days"] is not None for row in data["links"])
assert sum(row["answered_items"] for row in data["tables"]["category_delayed"]) == stored["items"]
assert any(row["measure"] == "prior_retrievals" and row["paired_items"]>0 for row in data["tables"]["associations"])
assert set(row["part_of_speech"] for row in data["tables"]["pos_practice"]) == {"名詞","動詞","形容詞","未標註"}
assert set(row["類別"] for row in data["tables"]["category_practice"]) == {"教材基本生詞","主題生詞","教師臨時補充生詞"}

app = AppTest.from_file("teacher_app.py",default_timeout=60)
app.secrets["teacher"] = {"issuer":"https://issuer.test","dsn":"test","project_url":"https://fixture.supabase.co"}
with patch("streamlit.user",Claims(iss="https://issuer.test",sub="s")),patch("cloud_teacher.TeacherStore",return_value=store):
    app.run()
    find(app.date_input,"起始臺灣日期").set_value(date.fromisoformat(fixture["scope"]["from"]))
    find(app.date_input,"結束臺灣日期").set_value(date.fromisoformat(fixture["scope"]["to"]))
    find(app.button,"查詢研究紀錄").click().run()
    assert not app.exception and not app.error
    expected = data["tables"]["acquisition"][0]
    overview = next(frame.value for frame in app.dataframe if "first_target_hits" in frame.value)
    assert int(overview.iloc[0]["first_target_hits"]) == expected["first_target_hits"]
    for view in PAGES[1:]:
        find(app.radio,"研究頁面").set_value(view).run()
        assert not app.exception and not app.error
    assert app.get("download_button")

archive_bytes=export_zip(data["links"], data["history"], data["tests"], data["tables"],data["initial"],data["rounds"],data["course"])
with ZipFile(io.BytesIO(archive_bytes)) as archive:
    excel=load_workbook(io.BytesIO(archive.read("research.xlsx")),read_only=True,data_only=True)
    for name in ("acquisition","target_curve","category_practice","pos_practice","category_delayed","pos_delayed","associations"):
        rows=list(csv.DictReader(io.StringIO(archive.read(name+".csv").decode("utf-8-sig"))))
        headers,*records=excel[name].values
        assert len(rows)==len(records)==len(data["tables"][name])
        for csv_row,xls_row,ui_row in zip(rows,records,data["tables"][name]):
            for field,value in zip(headers,xls_row):
                if type(value) in (int,float):
                    assert abs(float(csv_row[field])-value)<1e-10
                    assert abs(ui_row[field]-value)<1e-10
                elif value is None:
                    assert csv_row[field]=="" and ui_row[field] is None
                else:
                    assert str(value)==csv_row[field] and value==ui_row[field]
    assert sum(1 for _ in excel["daily_rounds"].values)-1==stored["sessions"]
    assert "SYN_01" not in archive.read("practice.csv").decode("utf-8-sig")
    excel.close()

print(json.dumps({"synthetic":True,"gui_pages":5,"reconciled_export_tables":7,
                  "events":stored["events"],"sessions":stored["sessions"],"scheduled":len(data["tests"])}))
