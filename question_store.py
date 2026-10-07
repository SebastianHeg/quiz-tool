"""Question banks, adaptive selection, and shared progress stored as JSON."""

import fcntl
import json
import os
import random
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

FIELDS_PATH = Path(__file__).resolve().parent / "sets"
REQUIRED_QUESTION_FIELDS = ("topic", "question", "answer")
_progress_lock = RLock()


def field_path(field: str) -> Path:
    """Resolve a subject restricted to a direct child of the storage root."""
    if not isinstance(field, str) or not field:
        raise ValueError("Invalid field")
    if field in {".", ".."} or "/" in field or "\\" in field:
        raise ValueError("Invalid field")

    path = (FIELDS_PATH / field).resolve()
    if path.parent != FIELDS_PATH.resolve() or not path.is_dir():
        raise ValueError("Unknown field")
    return path


def _load_json(field: str, filename: str, *, required: bool = False) -> dict:
    path = field_path(field) / filename
    if not path.exists():
        if required:
            raise ValueError("Missing question bank")
        return {}
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def load_questions(field: str) -> dict:
    bank = _load_json(field, "questions.json", required=True)
    if not isinstance(bank, dict) or not isinstance(bank.get("questions"), list):
        raise ValueError("Invalid question bank")
    _validate_questions(bank["questions"])
    return bank


def _validate_questions(questions: list[dict]) -> None:
    seen_ids = set()
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError("Invalid question schema")
        question_id = question.get("id")
        if type(question_id) is not int or question_id <= 0 or question_id in seen_ids:
            raise ValueError("Question IDs must be unique positive integers")
        seen_ids.add(question_id)
        if any(not isinstance(question.get(key), str) for key in REQUIRED_QUESTION_FIELDS):
            raise ValueError("Invalid question schema")


def load_progress(field: str) -> dict:
    return _load_json(field, "progress.json")


def load_sets(field: str) -> dict:
    return _load_json(field, "sets.json")


def load_examens(field: str) -> dict:
    return _load_json(field, "examens.json")


def load_system_prompt(field: str) -> str:
    path = field_path(field) / "system-prompt.txt"
    if not path.exists():
        raise ValueError("Missing grading instructions")
    return path.read_text(encoding="utf-8")


@contextmanager
def progress_transaction(field: str):
    """Lock the entire read-modify-write operation across threads and processes."""
    with _progress_lock:
        with (field_path(field) / ".progress.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def save_progress(field: str, progress: dict) -> None:
    """Replace progress atomically; callers must lock read-modify-write operations."""
    destination = field_path(field) / "progress.json"
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent, delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(progress, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def get_all_questions(field: str) -> tuple[list[dict], dict]:
    return load_questions(field)["questions"], load_progress(field)


def get_filtered_questions(
    field: str, group_name: str | None = None, topic: str | None = None
) -> list[dict]:
    questions = load_questions(field)["questions"]
    if group_name:
        groups = {**load_sets(field), **load_examens(field)}
        if group_name not in groups:
            raise ValueError("Unknown question set")
        questions_by_id = {question["id"]: question for question in questions}
        question_ids = groups[group_name]
        if any(question_id not in questions_by_id for question_id in question_ids):
            raise ValueError("Question set contains unknown IDs")
        questions = [questions_by_id[question_id] for question_id in question_ids]
    if topic:
        questions = [question for question in questions if question["topic"] == topic]
    return questions


def get_question_by_id(field: str, question_id: str | int) -> dict | None:
    if isinstance(question_id, bool) or not isinstance(question_id, (str, int)):
        raise ValueError("Invalid question ID")
    try:
        numeric_id = int(question_id)
    except ValueError:
        raise ValueError("Invalid question ID") from None
    questions = load_questions(field)["questions"]
    return next((question for question in questions if question["id"] == numeric_id), None)


def get_next_question(
    field: str, group_name: str | None = None, topic: str | None = None
) -> dict | None:
    """Prioritize unanswered questions, then randomize among the weakest questions."""
    questions = get_filtered_questions(field, group_name, topic)
    if not questions:
        return None
    progress = load_progress(field)
    unattempted = [
        question for question in questions
        if progress.get(str(question["id"]), {}).get("attempts", 0) == 0
    ]
    if unattempted:
        return random.choice(unattempted)

    def success_rate(question: dict) -> float:
        entry = progress[str(question["id"])]
        return entry["correct"] / entry["attempts"]

    lowest_rate = min(map(success_rate, questions))
    weakest_questions = [question for question in questions if success_rate(question) == lowest_rate]
    return random.choice(weakest_questions)


def record_attempt(field: str, question_id: str | int, correct: bool, score: float) -> dict:
    with progress_transaction(field):
        progress = load_progress(field)
        entry = progress.setdefault(str(question_id), _default_progress())
        _update_attempt(entry, correct, score)
        save_progress(field, progress)
        return entry


def _update_attempt(entry: dict, correct: bool, score: float) -> None:
    previous_streak = entry.get("streak", 0)
    entry["attempts"] += 1
    entry["correct"] += int(correct)
    entry["streak"] = previous_streak + 1 if correct else 0
    entry["best_streak"] = max(
        entry.get("best_streak", 0), previous_streak, entry["streak"]
    )
    entry["last_result"] = "correct" if correct else "incorrect"
    entry["last_score"] = score
    entry["last_attempt"] = datetime.now(timezone.utc).isoformat()


def _default_progress() -> dict:
    return {
        "attempts": 0,
        "correct": 0,
        "streak": 0,
        "last_result": None,
        "last_score": 0,
        "last_attempt": None,
    }


def get_fields() -> list[str]:
    fields = []
    for path in FIELDS_PATH.iterdir():
        if not path.is_dir():
            continue
        try:
            bank = load_questions(path.name)
            load_system_prompt(path.name)
        except (ValueError, OSError):
            continue
        if bank["questions"]:
            fields.append(path.name)
    return sorted(fields)


def _group_summaries(groups: dict) -> list[dict]:
    return [
        {"name": name, "questions_count": len(question_ids)}
        for name, question_ids in groups.items()
    ]


def get_sets(field: str) -> list[dict]:
    return _group_summaries(load_sets(field))


def get_examens(field: str) -> list[dict]:
    return _group_summaries(load_examens(field))


def get_topics(field: str) -> list[str]:
    questions = load_questions(field)["questions"]
    return sorted({question["topic"] for question in questions})


def get_set_stats(field: str, set_name: str) -> dict:
    return _filtered_stats(field, group_name=set_name)


def get_examen_stats(field: str, exam_name: str) -> dict:
    return _filtered_stats(field, group_name=exam_name)


def get_topic_stats(field: str, topic: str) -> dict:
    return _filtered_stats(field, topic=topic)


def _filtered_stats(
    field: str, group_name: str | None = None, topic: str | None = None
) -> dict:
    questions = get_filtered_questions(field, group_name, topic)
    progress = load_progress(field)
    question_ids = [question["id"] for question in questions]
    stats = _calculate_stats(question_ids, progress)
    stats["questions"] = _question_details(questions, progress)
    return stats


def get_stats(field: str, ids: list[int] | None = None) -> dict:
    questions, progress = get_all_questions(field)
    question_ids = ids if ids is not None else [question["id"] for question in questions]
    return _calculate_stats(question_ids, progress)


def _average(total: float, count: int) -> float:
    return total / count if count else 0


def _calculate_stats(question_ids: list[int], progress: dict) -> dict:
    """Distinguish latest correct questions from cumulative correct attempts."""
    entries = [progress.get(str(question_id), {}) for question_id in question_ids]
    attempted = [entry for entry in entries if entry.get("attempts", 0) > 0]
    total_questions = len(question_ids)
    attempted_count = len(attempted)
    correct_questions = sum(entry.get("last_result") == "correct" for entry in attempted)
    total_attempts = sum(entry.get("attempts", 0) for entry in attempted)
    correct_attempts = sum(entry.get("correct", 0) for entry in attempted)
    total_score = sum(entry.get("last_score", 0) for entry in attempted)
    total_streak = sum(entry.get("streak", 0) for entry in attempted)
    best_streak = max(
        (entry.get("best_streak", entry.get("streak", 0)) for entry in entries),
        default=0,
    )
    success_rate = _average(correct_attempts, total_attempts) * 100
    return {
        "total": total_questions,
        "attempted": attempted_count,
        "unattempted_questions": total_questions - attempted_count,
        "total_correct": correct_questions,
        "correct_attempts": correct_attempts,
        "best_streak": best_streak,
        "incorrect_questions": attempted_count - correct_questions,
        "completion_percent": _average(attempted_count, total_questions) * 100,
        "success_rate": success_rate,
        "average_score": _average(total_score, attempted_count),
        "average_streak": _average(total_streak, attempted_count),
        "total_attempts": total_attempts,
        "overall_rate": round(success_rate, 1),
    }


def _question_details(questions: list[dict], progress: dict) -> list[dict]:
    return [
        {
            "id": question["id"],
            "question": question["question"],
            **_default_progress(),
            **progress.get(str(question["id"]), {}),
        }
        for question in questions
    ]


def get_field_stats(field: str) -> dict:
    questions, progress = get_all_questions(field)
    stats = _calculate_stats([question["id"] for question in questions], progress)
    topics = []
    for topic in sorted({question["topic"] for question in questions}):
        topic_ids = [question["id"] for question in questions if question["topic"] == topic]
        topic_stats = _calculate_stats(topic_ids, progress)
        topics.append({
            "name": topic,
            "total": topic_stats["total"],
            "attempted": topic_stats["attempted"],
            "correct": topic_stats["total_correct"],
        })
    stats["topics"] = topics
    return stats
