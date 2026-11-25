
import unittest

from research_metrics import category_stats, course_stats, retrieval_stats


SESSION = {"student_code": "PRIVATE-STUDENT", "practice_date": "2026-11-01", "course_id": "L1",
           "course_version": "v1", "session_id": "PRIVATE-SESSION", "completed_at": None}
EVENT = SESSION | {"event_id": "PRIVATE-EVENT", "word_id": "W1", "verified_word_id": "W1", "category": "topic",
                   "action": "answer", "mode": "practice", "question_type": "context_cloze",
                   "correct_server": False, "first_attempt": "true", "word_attempt": "1",
                   "submission_id": "round-1", "selected": "PRIVATE-TEXT",
                   "client_time": "2026-11-01T12:00:00", "elapsed_session_ms": "1500"}
CLEAN = EVENT | {"event_id": "event-two", "correct_server": True, "first_attempt": "false",
                 "word_attempt": "2", "submission_id": "round-2", "elapsed_session_ms": "9500"}


class ResearchMetricsTests(unittest.TestCase):
    def test_category_only_pools_server_scores_within_a_question_type(self):
        rows = category_stats([EVENT, CLEAN, EVENT | {"question_type": "meaning_match"},
                               EVENT | {"mode": "delayed"}, EVENT | {"correct_server": None}])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["錯誤率"], 0.5)
        self.assertEqual(rows[0]["首次錯誤率"], 1)
        self.assertEqual(rows[1]["判分作答數"], 1)

    def test_cost_excludes_incomplete_sequences_and_intervals_use_observed_days(self):
        missing = CLEAN | {"practice_date": "2026-11-04", "session_id": "next", "word_attempt": "3"}
        item = retrieval_stats([EVENT, CLEAN, missing])[0]
        self.assertEqual(item["有紀錄的填空提交數"], 3)
        self.assertEqual(item["相鄰練習日間隔"], "3")
        self.assertEqual(item["可計首次答對成本的日場次"], 1)
        self.assertEqual(item["首次答對平均作答數"], 2)
        self.assertEqual(item["首次答對前平均錯誤數"], 1)
        self.assertIsNone(retrieval_stats([missing])[0]["首次答對平均作答數"])

    def test_course_uses_largest_elapsed_value_per_session(self):
        values = course_stats([SESSION], [EVENT, CLEAN])[0]
        self.assertEqual(values["未完成日數"], 1)
        self.assertEqual(values["觀測工作階段經過秒數合計"], 9.5)
