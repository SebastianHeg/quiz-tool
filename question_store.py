"""
question_store.py
Data layer for questions and per-question progress, backed by separate JSON files.
"""

import json
import random
import os
import tempfile
import fcntl
from contextlib import contextmanager
from threading import RLock
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

FIELDS_PATH = Path(__file__).resolve().parent / "sets"
_progress_lock = RLock()


def field_path(field: str) -> Path:
    if not isinstance(field, str) or not field or field in {".", ".."} or "/" in field or "\\" in field:
        raise ValueError("Invalid field")
    path = (FIELDS_PATH / field).resolve()
    if path.parent != FIELDS_PATH.resolve() or not path.is_dir():
        raise ValueError("Unknown field")
    return path


@contextmanager
def progress_transaction(field):
    with _progress_lock:
        with open(field_path(field) / ".progress.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_questions(field) -> dict:
    """Load questions from the questions.json file."""
    path = field_path(field) / "questions.json"
    if not path.exists():
        raise ValueError("Missing question bank")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        raise ValueError("Invalid question bank")
    questions = data["questions"]
    if any(not isinstance(q, dict) for q in questions):
        raise ValueError("Invalid question schema")
    ids = [q.get("id") for q in questions]
    if any(type(qid) is not int or qid <= 0 for qid in ids) or len(ids) != len(set(ids)):
        raise ValueError("Question IDs must be unique positive integers")
    if any(not all(isinstance(q.get(k), str) for k in ("topic", "question", "answer")) for q in questions):
        raise ValueError("Invalid question schema")
    return data


def load_progress(field: str) -> dict:
    """Load progress data keyed by question ID."""
    path = field_path(field) / "progress.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def load_sets(field: str) -> dict:
    path = field_path(field) / "sets.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def load_examens(field: str) -> dict:
    path = field_path(field) / "examens.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def load_system_prompt(field: str) -> str:
    """Load system prompt."""
    path = field_path(field) / "system-prompt.txt"
    if not path.exists():
        raise ValueError("Missing grading instructions")
    return path.read_text(encoding="utf-8")

def save_progress(field: str, progress: dict) -> None:
    """Save progress data to progress.json."""
    path = field_path(field) / "progress.json"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
            temporary = f.name
            json.dump(progress, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def get_all_questions(field: str) -> tuple[list[dict], dict]:
    """Return the question bank and separately keyed progress."""
    store = load_questions(field)
    progress = load_progress(field)
    questions = store["questions"]

    return questions, progress

def get_filtered_questions(field: str, filter: str, topic: str) -> list[dict]:
    questions, _ = get_all_questions(field)
    if filter:
        sets = load_sets(field)
        examens = load_examens(field)
        groups = {**sets, **examens}
        if filter not in groups:
            raise ValueError("Unknown question set")
        by_id = {q["id"]: q for q in questions}
        ids = groups[filter]
        if any(qid not in by_id for qid in ids):
            raise ValueError("Question set contains unknown IDs")
        questions = [by_id[qid] for qid in ids]

    if topic:
        questions = [q for q in questions if q["topic"] == topic]

    return questions


def get_question_by_id(field: str, qid: str) -> Optional[dict]:
    questions, _ = get_all_questions(field)
    if isinstance(qid, bool) or not isinstance(qid, (str, int)):
        raise ValueError("Invalid question ID")
    try:
        numeric_id = int(qid)
    except (TypeError, ValueError):
        raise ValueError("Invalid question ID") from None
    return next((q for q in questions if q["id"] == numeric_id), None)


def get_next_question(field: str, filter: Optional[str] = None, topic: Optional[str] = None) -> Optional[dict]:
    """
    Choose a random unattempted question, otherwise a random question among
    those with the lowest lifetime success rate.
    Optionally filter by topic.
    """
    questions = get_filtered_questions(field, filter, topic)
    progress = load_progress(field)

    if topic:
        questions = [q for q in questions if q["topic"] == topic]
    if not questions:
        return None

    unattempted = [
        q for q in questions
        if progress.get(str(q["id"]), {}).get("attempts", 0) == 0
    ]
    if unattempted:
        return random.choice(unattempted)

    lowest = min(_success_rate(progress[str(q["id"])]) for q in questions)
    return random.choice([q for q in questions if _success_rate(progress[str(q["id"])]) == lowest])


def record_attempt(field: str, qid: str, correct: bool, score: float) -> dict:
    """Persist one attempt and return the updated progress block."""
    with progress_transaction(field):
        progress = load_progress(field)
        q_id = str(qid)

        if q_id not in progress:
            progress[q_id] = _default_progress()

        p = progress[q_id]
        p["best_streak"] = max(p.get("best_streak", 0), p.get("streak", 0))
        p["attempts"] += 1
        if correct:
            p["correct"] += 1
            p["streak"] = p.get("streak", 0) + 1
            p["best_streak"] = max(p.get("best_streak", 0), p["streak"])
        else:
            p["streak"] = 0
        p["last_result"] = "correct" if correct else "incorrect"
        p["last_score"] = score
        p["last_attempt"] = datetime.now(timezone.utc).isoformat()

        save_progress(field, progress)
        return p


def get_fields() -> list[str]:
    all_fields = []
    for path in FIELDS_PATH.iterdir():
        if not path.is_dir():
            continue
        try:
            bank = load_questions(path.name)
            load_system_prompt(path.name)
            if bank.get("questions"):
                all_fields.append(path.name)
        except (ValueError, OSError):
            continue
    return sorted(all_fields)


def get_sets(field: str) -> list[dict]:
    sets = load_sets(field)

    return [
        {
            "name": name,
            "questions_count": len(questions),
        }
        for name, questions in sets.items()
    ]

def get_examens(field: str) -> list[dict]:
    sets = load_examens(field)

    return [
        {
            "name": name,
            "questions_count": len(questions),
        }
        for name, questions in sets.items()
    ]


def get_topics(field: str) -> list[str]:
    questions, _ = get_all_questions(field)
    return sorted({q["topic"] for q in questions})


def get_set_stats(field: str, set: str) -> dict:
    questions = get_filtered_questions(field, set, "")
    ids = [q["id"] for q in questions]
    return {**get_stats(field, ids), "questions": question_details(field, questions)}


def get_examen_stats(field: str, examen: str) -> dict:
    questions = get_filtered_questions(field, examen, "")
    ids = [q["id"] for q in questions]
    return {**get_stats(field, ids), "questions": question_details(field, questions)}


def get_topic_stats(field: str, topic: str) -> dict:
    questions = get_filtered_questions(field, "", topic)
    ids = [q["id"] for q in questions]
    return {**get_stats(field, ids), "questions": question_details(field, questions)}


def get_stats(field: str, ids: Optional[list[int]] = None) -> dict:
    questions, progress = get_all_questions(field)
    if (ids == None):
        ids = [q["id"] for q in questions]

    total_questions = len(ids)

    attempted_questions = 0
    correct_questions = 0
    total_attempts = 0
    total_correct = 0
    total_score = 0
    total_streak = 0

    for question_id in ids:
        p = progress.get(str(question_id))

        if p is None or p.get("attempts", 0) == 0:
            continue

        attempted_questions += 1

        attempts = p.get("attempts", 0)
        correct = p.get("correct", 0)

        total_attempts += attempts
        total_correct += correct

        total_score += p.get("last_score", 0)
        total_streak += p.get("streak", 0)

        if p.get("last_result") == "correct":
            correct_questions += 1

    incorrect_questions = attempted_questions - correct_questions

    return {
        "total": total_questions,
        "attempted": attempted_questions,
        "unattempted_questions": (
            total_questions - attempted_questions
        ),
        "total_correct": correct_questions,
        "correct_attempts": total_correct,
        "best_streak": max((progress.get(str(qid), {}).get("best_streak", progress.get(str(qid), {}).get("streak", 0)) for qid in ids), default=0),
        "incorrect_questions": incorrect_questions,
        "completion_percent": (
            attempted_questions / total_questions * 100
            if total_questions else 0
        ),
        "success_rate": (
            total_correct / total_attempts * 100
            if total_attempts else 0
        ),
        "average_score": (
            total_score / attempted_questions
            if attempted_questions else 0
        ),
        "average_streak": (
            total_streak / attempted_questions
            if attempted_questions else 0
        ),
        "total_attempts": total_attempts,
        "overall_rate": round(total_correct / total_attempts * 100, 1) if total_attempts else 0,
    }



# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _success_rate(progress: dict) -> float:
    if progress["attempts"] == 0:
        return 1.0
    return progress["correct"] / progress["attempts"]


def _default_progress() -> dict:
    """Return a fresh progress object for a new question."""
    return {
        "attempts": 0,
        "correct": 0,
        "streak": 0,
        "last_result": None,
        "last_score": 0,
        "last_attempt": None,
    }

def question_details(field, questions):
    progress = load_progress(field)
    return [{"id": q["id"], "question": q["question"], **_default_progress(), **progress.get(str(q["id"]), {})} for q in questions]


def get_field_stats(field):
    questions, _ = get_all_questions(field)
    topics = []
    for topic in sorted({q["topic"] for q in questions}):
        stats = get_topic_stats(field, topic)
        topics.append({"name": topic, "total": stats["total"], "attempted": stats["attempted"], "correct": stats["total_correct"]})
    return {**get_stats(field), "topics": topics}
