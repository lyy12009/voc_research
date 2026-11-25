"""Shared calculations for the research dashboard and exports."""
from collections import defaultdict
from statistics import median

from research_metrics import answers, grouped, integer


def index_pos(words):
    return {(row["course_id"], row["course_version"], row["word_id"]): row.get("part_of_speech")
            for row in words}


def attach_pos(rows, index):
    return [r | {"part_of_speech": index.get((r["course_id"], r["course_version"], r["word_id"] or ""))}
            for r in rows]


def grouped_scores(rows, field, delayed=False):
    eligible = rows if delayed else answers(rows)
    fields = (field, "is_makeup") if delayed else (field, "question_type")
    result = []
    for group, records in grouped(eligible, fields).items():
        row = dict(zip(fields, group))
        row[field] = row[field] or "未標註"
        count = len(records)
        correct = sum(r["correct_server"] for r in records)
        row.update(items=count, students=len({r["student_code"] for r in records}),
                   words=len({(r["course_id"], r["course_version"], r["word_id"]) for r in records}),
                   correct=correct, accuracy=correct/count, error_rate=(count-correct)/count)
        if delayed:
            row.update(target_hits=sum(r["target_hit"] for r in records),
                       target_retention=sum(r["target_hit"] for r in records)/count)
        result.append(row)
    return result


def acquisition_summary(records):
    initial = [row for row in records if type(row.get("initial_target_hit")) is bool]
    hits = sum(row["initial_target_hit"] for row in initial)
    accepted_initial = [row for row in records if type(row.get("initial_acceptable")) is bool]
    acceptable = sum(row["initial_acceptable"] for row in accepted_initial)
    reliable = [row for row in records if row["target_status"] in ("hit","right_censored")]
    risk = len(reliable)
    remaining = 1.0
    counts = defaultdict(lambda: [0, 0])
    for row in reliable:
        if row["target_status"] == "hit":
            counts[row["retrievals_to_first_target"]][0] += 1
        else:
            counts[row["observed_retrievals"]][1] += 1
    curve = []
    for attempt, (events, censored) in sorted(counts.items()):
        remaining *= 1-events/risk
        curve.append({"retrieval":attempt,"at_risk":risk,"hits":events,"censored":censored,
                      "cumulative_target_hit":1-remaining})
        risk -= events+censored
    accepted = [row["retrievals_to_first_correct"] for row in records if row.get("retrievals_to_first_correct")]
    return {"first_target_hits":hits,"first_acceptable":acceptable,"first_assessable":len(initial),
            "first_target_rate":hits/len(initial) if initial else None,
            "first_acceptable_assessable":len(accepted_initial),
            "first_acceptable_rate":acceptable/len(accepted_initial) if accepted_initial else None,
            "target_hit_items":sum(row["target_status"] == "hit" for row in records),
            "right_censored_items":sum(row["target_status"] == "right_censored" for row in records),
            "insufficient_items":sum(row["target_status"]=="insufficient" for row in records),
            "no_graded_attempt_items":sum(row["target_status"]=="no_attempt" for row in records),
            "median_retrievals_to_target":next((r["retrieval"] for r in curve if r["cumulative_target_hit"]>=.5),None),
            "accepted_hit_items":len(accepted),
            "median_accepted_retrievals_among_hits":median(accepted) if accepted else None}, curve


def daily_rounds(sessions, events, words, complete_scope=True):
    expected = defaultdict(set)
    for row in words:
        expected[row["course_id"],row["course_version"]].add(row["word_id"])
    per_session = grouped(answers(events,"context_cloze"), ("session_id",))
    output = []
    for session in sessions:
        sid = session["session_id"]
        target = expected[session["course_id"],session["course_version"]]
        results = []
        for (submission,), rows in grouped(per_session.get((sid,),[]),("submission_id",)).items():
            attempts = {integer(row.get("word_attempt")) for row in rows}
            if (complete_scope and target and submission and len(rows)==len(target)
                    and {r["word_id"] for r in rows}==target and len(attempts)==1
                    and None not in attempts and all(r["correct_server"] for r in rows)):
                results.append(next(iter(attempts)))
        output.append({"student_code":session["student_code"],"course_id":session["course_id"],
                       "course_version":session["course_version"],"session_id":sid,
                       "practice_date":session["practice_date"],"completed":bool(session["completed_at"]),
                       "first_all_correct_round":min(results) if results else None})
    return output
