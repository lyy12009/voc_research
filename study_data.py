"""Bounded research loading and one source of truth for dashboard/export tables."""
from collections import defaultdict

from delayed_metrics import associations, delayed_links, first_per_word, retention_by_category
from research_metrics import category_stats, course_stats
from study_analysis import acquisition_summary, attach_pos, daily_rounds, grouped_scores, index_pos


def partitioned(load, filters, students, keys):
    data = load(filters)
    if not data.get("overflow"):
        return data
    if filters.get("student") or not students:
        return {"overflow": True}
    output = {key: [] for key in keys}
    for student in students:
        rows = load(filters | {"student":student})
        if rows.get("overflow"):
            return {"overflow":True}
        for key in keys:
            output[key].extend(rows[key])
            if len(output[key])>200_000:
                return {"overflow":True}
    if "words" in output:
        output["words"] = list({(r["course_id"],r["course_version"],r["word_id"]):r
                                for r in output["words"]}.values())
    return output


def build_study(store, query):
    metadata = store.study_metadata(query)
    if metadata.get("overflow"):
        return {"overflow":True}
    students = metadata["students"]
    daily = partitioned(store.research, query, students, ("sessions","events","words"))
    delayed = partitioned(store.delayed, {"operation":"read","course":query["course"],"student":query["student"]},
                          students, ("tests","answers"))
    history = partitioned(store.delayed, {"operation":"history","student":query["student"]}, students, ("events",))
    if any(r.get("overflow") for r in (daily, delayed, history)):
        return {"overflow":True}
    pos = index_pos(metadata["words"])
    events = attach_pos(daily["events"],pos)
    relevant_versions = {(row["course_id"],row["course_version"])
                         for row in [*daily["sessions"],*delayed["tests"]]}
    words = [r for r in metadata["words"]
             if (not query["student"] or (r["course_id"],r["course_version"]) in relevant_versions)
             and (not query["word"] or query["word"] in (r["word_id"],r["target_word"]))
             and (not query["category"] or query["category"] == r["category"])]
    by_version = defaultdict(set)
    for word in words:
        by_version[word["course_id"],word["course_version"]].add(word["word_id"])
    cohort = {(row["student_code"],word_id) for row in [*daily["sessions"],*delayed["tests"]]
              for word_id in by_version[row["course_id"],row["course_version"]]}
    selected_words = {r["word_id"] for r in words}
    first = first_per_word(history["events"])
    # Assigned or started items with no graded cloze stay visible without a censor time of zero.
    initial = [{"student_code":key[0],"word_id":key[1],**first.get(key,{"target_status":"no_attempt"})}
               for key in sorted(cohort)]
    targets = attach_pos([r for r in delayed["answers"] if
               (not query["word"] or r["word_id"] in selected_words) and
               (not query["category"] or r["category"] == query["category"])], pos)
    links = delayed_links(delayed["tests"], targets, history["events"])
    summary, curve = acquisition_summary(initial)
    complete = not (query["word"] or query["category"])
    tables = {
        "acquisition": [summary], "target_curve": curve,
        "category_practice": category_stats(events),
        "pos_practice": grouped_scores(events,"part_of_speech"),
        "category_delayed": retention_by_category(links),
        "pos_delayed": grouped_scores(links,"part_of_speech",delayed=True),
        "associations": associations(links),
    }
    return {"events":events,"words":words,"history":history["events"],"tests":delayed["tests"],
            "links":links,"initial":initial,"tables":tables,
            "rounds":daily_rounds(daily["sessions"],events,words,complete),
            "course":course_stats(daily["sessions"],events if complete else [])}
