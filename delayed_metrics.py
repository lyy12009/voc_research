"""Traceable measures based on immutable practice events and delayed submissions."""
from datetime import date, datetime
from math import sqrt

from research_metrics import grouped


def first_per_word(events):
    cloze = [e for e in events if e.get("question_type") == "context_cloze"
             and e["action"] == "answer" and type(e.get("correct_server")) is bool]
    result = {}
    for key, records in grouped(cloze, ("student_code", "word_id")).items():
        days = grouped(records, ("practice_date",))
        ordered = []
        complete_prefix = True
        for day in sorted(days):
            same_day = days[day]
            # Different daily sessions can arrive offline out of order.
            if len({row["session_id"] for row in same_day}) != 1:
                complete_prefix = False
                break
            attempts = grouped(same_day, ("word_attempt",))
            for number in range(1, len(same_day) + 1):
                matches = attempts.get((str(number),), [])
                if len(matches) != 1 or not matches[0].get("submission_id"):
                    complete_prefix = False
                    break
                ordered.append(matches[0])
            if not complete_prefix:
                break
        first = ordered[0] if ordered else None
        first_correct = next((index for index, row in enumerate(ordered, 1) if row["correct_server"]), None)
        target = next((index for index, row in enumerate(ordered, 1) if row["target_hit"] is True), None)
        if target and any(type(row["target_hit"]) is not bool for row in ordered[:target]):
            target = None
        reliable_target = bool(ordered) and complete_prefix and all(type(row["target_hit"]) is bool for row in ordered)
        later = [r for r in records if first and r["practice_date"] > first["practice_date"]]
        result[key] = {
            "initial_event": first["event_id"] if first else None,
            "initial_target_hit": first["target_hit"] if first else None,
            "initial_acceptable": first["correct_server"] if first else None,
            "retrievals_to_first_correct": first_correct,
            "retrievals_to_first_target": target,
            "target_status": "hit" if target else "right_censored" if reliable_target else "insufficient",
            "observed_retrievals": len(ordered),
            "first_target_event": ordered[target-1]["event_id"] if target else None,
            "errors_before_first_correct": first_correct - 1 if first_correct else None,
            "first_correct_event": ordered[first_correct-1]["event_id"] if first_correct else None,
            "later_practice_days": len({row["practice_date"] for row in later}) if first else None,
            "later_retrievals": len({(row["session_id"], row["submission_id"]) for row in later
                                     if row.get("submission_id")}) if first else None,
            "later_errors": sum(not row["correct_server"] for row in later) if first else None,
            "later_event_ids": [row["event_id"] for row in later] if first else None,
        }
    return result


def delayed_links(tests, answers, history):
    indexed = grouped(history, ("student_code", "word_id"))
    lookup = {(row["student_code"], row["course_id"]): row for row in tests}
    output = []
    for answer in answers:
        assessment = lookup[answer["student_code"], answer["course_id"]]
        start, finish = assessment["end_date"], assessment["test_date"]
        submitted = datetime.fromisoformat(assessment["submitted_at"])
        known = []
        uncertain = []
        prior = []
        for event in indexed[answer["student_code"], answer["word_id"]]:
            day = event["practice_date"]
            if day < finish or (day == finish and datetime.fromisoformat(event["received_at"]) < submitted):
                prior.append(event)
            if day < start or day > finish:
                continue
            if event["practice_date"] == start:
                uncertain.append(event["event_id"])
            elif event["practice_date"] < finish or datetime.fromisoformat(event["received_at"]) < submitted:
                known.append(event["event_id"])
            elif event["practice_date"] == finish:
                uncertain.append(event["event_id"])
        practice = [event for event in prior if event["question_type"] == "context_cloze"
                    and event.get("submission_id") and type(event.get("correct_server")) is bool]
        days = sorted({date.fromisoformat(event["practice_date"]) for event in practice})
        gaps = [(second - first).days for first, second in zip(days, days[1:])]
        elapsed_by_session = {}
        for event in practice:
            raw = event.get("elapsed_session_ms") or ""
            if raw.isascii() and raw.isdecimal() and len(raw) <= 12:
                sid = event["session_id"]
                elapsed_by_session[sid] = max(int(raw), elapsed_by_session.get(sid, 0))
        initial = first_per_word(prior).get((answer["student_code"], answer["word_id"]), {})
        output.append(answer | initial | {
            "end_date": start, "interim_practice_event_ids": known,
            "boundary_time_uncertain_event_ids": uncertain,
            "prior_retrievals": len({(event["session_id"], event["submission_id"]) for event in practice}),
            "prior_practice_days": len(days),
            "prior_average_gap_days": sum(gaps) / len(gaps) if gaps else None,
            "prior_observed_session_elapsed_seconds": sum(elapsed_by_session.values()) / 1000 if elapsed_by_session else None,
        })
    return output


def retention_by_category(answers):
    result = []
    for (category, makeup), rows in grouped(answers, ("category", "is_makeup")).items():
        result.append({"category": category, "is_makeup": makeup, "answered_items": len(rows),
                       "target_hits":sum(row["target_hit"] for row in rows),
                       "acceptable_hits":sum(row["correct_server"] for row in rows),
                       "target_retention": sum(row["target_hit"] for row in rows) / len(rows),
                       "acceptable_accuracy": sum(row["correct_server"] for row in rows) / len(rows)})
    return result

def associations(rows):
    measures = ("prior_retrievals", "prior_practice_days", "prior_average_gap_days",
                "prior_observed_session_elapsed_seconds", "initial_acceptable",
                "errors_before_first_correct", "retrievals_to_first_correct", "retrievals_to_first_target")
    output = []
    for (makeup,), group in grouped(rows, ("is_makeup",)).items():
        for outcome in ("target_hit", "correct_server"):
            for measure in measures:
                pairs = [(float(row[measure]), float(row[outcome])) for row in group if row.get(measure) is not None]
                if not pairs:
                    continue
                xs, ys = zip(*pairs)
                dx, dy = [x-sum(xs)/len(xs) for x in xs], [y-sum(ys)/len(ys) for y in ys]
                scale = sqrt(sum(x*x for x in dx)*sum(y*y for y in dy))
                output.append({"is_makeup":makeup,"outcome":outcome,"measure":measure,"paired_items":len(pairs),
                    "correlation":sum(x*y for x,y in zip(dx,dy))/scale if len(pairs)>=3 and scale else None})
    return output
