import io
import unittest
from zipfile import ZipFile

from delayed_metrics import associations, delayed_links, first_per_word, retention_by_category
from research_ui import export_zip


def event(key, day, attempt, correct, hit):
    return {"student_code":"PRIVATE_STUDENT","course_id":"C","course_version":"v1","word_id":"W1",
            "practice_date": day,"received_at":day+"T12:00:00+08:00","session_id":day,
            "submission_id":key,"event_id":key,"word_attempt":str(attempt),
            "question_type":"context_cloze","action":"answer","stage":"cloze",
            "correct_server":correct,"target_hit":hit,"selected":"PRIVATE_VALUE","elapsed_session_ms":"2000"}


class DelayedMetricsTests(unittest.TestCase):
    def test_initial_cost_uses_first_graded_cloze_across_days(self):
        wrong=event("first","2026-11-01",1,False,False)
        alternative=event("alt","2026-11-02",1,True,False)
        target=event("target","2026-11-03",1,True,True)
        value=first_per_word([target,wrong,alternative])["PRIVATE_STUDENT","W1"]
        self.assertEqual(value["initial_event"], "first")
        self.assertFalse(value["initial_target_hit"])
        self.assertFalse(value["initial_acceptable"])
        self.assertEqual(value["retrievals_to_first_correct"], 2)
        self.assertEqual(value["errors_before_first_correct"], 1)
        self.assertEqual(value["first_correct_event"], "alt")
        self.assertEqual(value["later_practice_days"],2)
        unknown=first_per_word([wrong | {"word_attempt":"2"}])["PRIVATE_STUDENT","W1"]
        self.assertIsNone(unknown["initial_event"])
        self.assertIsNone(unknown["retrievals_to_first_correct"])

    def test_retention_exposure_and_export_keep_only_traceable_denominators(self):
        tests=[{"student_code":"PRIVATE_STUDENT","course_id":"C","course_version":"v1",
                "end_date":"2026-11-01","test_date":"2026-11-09","submitted_at":"2026-11-09T14:00:00+08:00",
                "status":"submitted","delay_days":8}]
        row={"student_code":"PRIVATE_STUDENT","course_id":"C","course_version":"v1","word_id":"W1",
             "target_hit":False,"correct_server":True,"actual_answer":"PRIVATE_VALUE","target_word":"甲",
             "answer_type":"accepted_alternative","is_makeup":False,"delay_days":8,"category":"topic"}
        earlier=event("early","2026-11-02",1,False,False)
        later=event("late","2026-11-09",2,True,True)|{"received_at":"2026-11-09T17:00:00+08:00"}
        links=delayed_links(tests,[row],[earlier,later])
        self.assertEqual(links[0]["interim_practice_event_ids"],["early"])
        self.assertEqual(links[0]["boundary_time_uncertain_event_ids"],["late"])
        self.assertIsNone(links[0]["first_correct_event"])
        self.assertEqual(links[0]["prior_retrievals"],1)
        rates=retention_by_category(links)
        self.assertEqual((rates[0]["target_retention"],rates[0]["acceptable_accuracy"]),(0,1))
        self.assertTrue(all(item["correlation"] is None for item in associations(links)))
        with ZipFile(io.BytesIO(export_zip(links,[earlier],tests))) as archive:
            practice=archive.read("practice.csv")
            self.assertIn(b"delayed.csv",str(archive.namelist()).encode())
            contents=b"".join(archive.read(name) for name in archive.namelist())
            self.assertNotIn(b"PRIVATE_STUDENT",contents)
            self.assertNotIn(b"PRIVATE_VALUE",contents)
            self.assertNotIn(b"2026-11-09",contents)
            code=practice.decode("utf-8-sig").splitlines()[1].split(",")[4]
            self.assertIn(code.encode(),archive.read("delayed.csv"))
