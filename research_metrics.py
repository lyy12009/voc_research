
"""Research units for the current practice protocol."""
from collections import defaultdict
from datetime import date

CATEGORIES = {"textbook": "教材基本生詞", "topic": "主題生詞", "supplement": "教師臨時補充生詞",
              "unknown": "類別未記錄"}
STAGES = {"meaning_match": "詞義配對", "context_cloze": "句子填空"}

def answers(events, question=None):
    return [row for row in events if row.get("action") == "answer" and row.get("mode") == "practice"
            and row.get("question_type") in STAGES and type(row.get("correct_server")) is bool
            and (question is None or row["question_type"] == question)]


def first_try(row):
    flag = row.get("first_attempt")
    attempt = str(row.get("word_attempt") or "")
    return flag in (True, "true") or (flag is None and attempt == "1")


def rate(rows):
    return sum(not row["correct_server"] for row in rows) / len(rows) if rows else None


def grouped(rows, fields):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(key) for key in fields)].append(row)
    return groups


def category_stats(events):
    groups = grouped(answers(events), ("category", "question_type"))
    output = []
    for (category, question), rows in sorted(groups.items()):
        first = [row for row in rows if first_try(row)]
        output.append({"類別": CATEGORIES.get(category, category), "題型": STAGES[question], "判分作答數": len(rows),
                       "錯誤率": rate(rows), "可確認首次作答數": len(first), "首次錯誤率": rate(first)})
    return output


def integer(value):
    token = "" if value is None else str(value)
    return int(token) if token.isascii() and token.isdecimal() and len(token) <= 12 else None


def retrieval_stats(events):
    fields = ("student_code", "course_id", "course_version", "word_id")
    output = []
    for key, rows in grouped(answers(events, "context_cloze"), fields).items():
        if not key[-1]:
            continue
        days = sorted({date.fromisoformat(row["practice_date"]) for row in rows})
        observed = {(row["session_id"], row["submission_id"]) for row in rows if row.get("submission_id")}
        costs = []
        initial_day_rows = [row for row in rows if row["practice_date"] == days[0].isoformat()]
        initial_marked = [row for row in initial_day_rows if first_try(row)]
        for daily in grouped(rows, ("session_id",)).values():
            by_attempt = defaultdict(list)
            for row in daily:
                attempt = integer(row.get("word_attempt"))
                if attempt and row.get("submission_id"):
                    by_attempt[attempt].append(row)
            for index in range(1, len(by_attempt) + 1):
                records = by_attempt[index]
                if len(records) != 1 or (index == 1 and not first_try(records[0])):
                    break
                if records[0]["correct_server"]:
                    costs.append(index)
                    break
        output.append(dict(zip(fields, key)) | {
            "查詢期最早填空日的首次作答錯誤": not initial_marked[0]["correct_server"] if len(initial_marked) == 1 else None,
            "有紀錄的填空提交數": len(observed) if observed else None, "有填空紀錄天數": len(days),
            "相鄰練習日間隔": ", ".join(str((b-a).days) for a,b in zip(days,days[1:])) or None,
            "可計首次答對成本的日場次": len(costs),
            "首次答對前平均錯誤數": sum(n-1 for n in costs)/len(costs) if costs else None,
            "首次答對平均作答數": sum(costs)/len(costs) if costs else None,
        })
    return output


def course_stats(sessions, events):
    latest = {}
    for event in events:
        elapsed = integer(event.get("elapsed_session_ms"))
        if elapsed is not None and event.get("mode") == "practice":
            sid = event["session_id"]
            latest[sid] = max(elapsed, latest.get(sid, 0))
    fields = ("student_code", "course_id")
    output = []
    for key, rows in grouped(sessions, fields).items():
        spans = [latest[row["session_id"]] for row in rows if row["session_id"] in latest]
        output.append(dict(zip(fields, key)) | {
            "已開始日數": len(rows), "已完成日數": sum(bool(row["completed_at"]) for row in rows),
            "未完成日數": sum(not row["completed_at"] for row in rows),
            "有事件時間的日場次": len(spans), "觀測工作階段經過秒數合計": sum(spans) / 1000 if spans else None,
        })
    return output
