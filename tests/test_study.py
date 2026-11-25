import unittest

from delayed_metrics import associations, first_per_word
from study_analysis import acquisition_summary, daily_rounds, grouped_scores
from test_delayed import event


class StudyFormulaTests(unittest.TestCase):
    def test_target_acceptable_and_right_censoring_are_distinct(self):
        alt=event("alt","2026-09-01",1,True,False)
        wrong=event("wrong","2026-09-01",2,False,False)
        hit=event("hit","2026-09-01",3,True,True)
        censored=alt | {"student_code":"censored"}
        missing=wrong | {"student_code":"missing"}
        records=first_per_word([hit,wrong,alt,censored,missing])
        first=records["PRIVATE_STUDENT","W1"]
        self.assertEqual((first["retrievals_to_first_correct"],first["retrievals_to_first_target"]),(1,3))
        self.assertEqual(records["censored","W1"]["target_status"],"right_censored")
        self.assertIsNone(records["censored","W1"]["retrievals_to_first_target"])
        self.assertEqual(records["missing","W1"]["target_status"],"insufficient")
        stats,curve=acquisition_summary(list(records.values()))
        self.assertEqual(stats["first_target_rate"],0)
        self.assertEqual(stats["first_acceptable_rate"],1)
        self.assertEqual(stats["median_retrievals_to_target"],3)
        self.assertEqual(curve[0],{"retrieval":1,"at_risk":2,"hits":0,"censored":1,"cumulative_target_hit":0})
        self.assertEqual(curve[1]["at_risk"],1)

    def test_daily_all_correct_uses_one_submission_and_all_expected_words(self):
        one=event("one","2026-09-01",1,True,False) | {"mode":"practice"}
        two=one | {"word_id":"W2","event_id":"two","correct_server":False}
        three=one | {"event_id":"three","word_attempt":"2","submission_id":"second"}
        four=three | {"word_id":"W2","event_id":"four"}
        completed=one | {"completed_at":"some time"}
        open_session=completed | {"completed_at":None}
        expected=[one,two]
        self.assertIsNone(daily_rounds([open_session],[one,two,three],expected)[0]["first_all_correct_round"])
        self.assertEqual(daily_rounds([completed],[one,two,three,four],expected)[0]["first_all_correct_round"],2)
        self.assertIsNone(daily_rounds([completed],[three,four],expected,False)[0]["first_all_correct_round"])

    def test_pos_denominators_keep_unknown_and_delayed_alternate(self):
        row=event("one","2026-09-01",1,True,False) | {"mode":"practice"}
        totals=grouped_scores([row|{"part_of_speech":None},row|{"part_of_speech":"動詞","correct_server":False}],"part_of_speech")
        self.assertEqual(totals[0]["part_of_speech"],"未標註")
        self.assertEqual(totals[1]["error_rate"],1)
        delayed=row | {"part_of_speech":"動詞","is_makeup":True}
        result=grouped_scores([delayed],"part_of_speech",True)[0]
        self.assertEqual((result["accuracy"],result["target_retention"]),(1,0))

    def test_retention_correlation_matches_hand_calculation_and_splits_makeup(self):
        rows = [{"is_makeup":False,"prior_retrievals":x,"target_hit":bool(y),"correct_server":True}
                for x,y in ((1,0),(2,0),(3,1))]
        rows.append({"is_makeup":True,"prior_retrievals":20,"target_hit":True,"correct_server":True})
        results = {(r["is_makeup"],r["outcome"],r["measure"]):r for r in associations(rows)}
        main = results[False,"target_hit","prior_retrievals"]
        self.assertEqual(main["paired_items"],3)
        self.assertAlmostEqual(main["correlation"],(3**.5)/2)
        self.assertIsNone(results[False,"correct_server","prior_retrievals"]["correlation"])
        self.assertEqual(results[True,"target_hit","prior_retrievals"]["paired_items"],1)
        self.assertIsNone(results[True,"target_hit","prior_retrievals"]["correlation"])