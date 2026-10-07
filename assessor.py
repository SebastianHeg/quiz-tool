"""Semantic answer grading through OpenAI or a cached local GPT4All model."""

import json
import math
import os
from dataclasses import dataclass
from threading import RLock

from dotenv import load_dotenv

load_dotenv()
BACKEND = os.environ.get("ASSESSOR_BACKEND", "gpt4all").lower()
GPT4ALL_MODEL = os.environ.get("GPT4ALL_MODEL", "mistral-7b-instruct-v0.1.Q4_0.gguf")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
CORRECT_RESULTS = {"fully_correct", "correct", "mostly_correct"}
PARTIAL_RESULTS = {"partially_correct", "minimally_correct"}
VALID_RESULTS = CORRECT_RESULTS | PARTIAL_RESULTS | {"incorrect"}
TRUE_VALUES = {"true", "1", "yes", "correct", "richtig"}
FALSE_VALUES = {"false", "0", "no", "incorrect", "falsch"}
MAX_OUTPUT_TOKENS = 512

client = None
_gpt4all_instance = None
_model_lock = RLock()


class AssessmentError(RuntimeError):
    """The grading service failed or returned an unusable assessment."""


@dataclass
class Assessment:
    is_sks: bool
    correct: bool
    result: str
    sks_punkte: int
    score: float
    feedback: str


def assess(system_prompt: str, question: str, answer: str, student_answer: str) -> Assessment:
    prompt = _build_prompt(question, answer, student_answer)
    try:
        raw = _call_backend(system_prompt, prompt)
    except Exception as exc:
        raise AssessmentError("Grading service unavailable") from exc
    return _parse_response(raw)


def _call_backend(system_prompt: str, prompt: str) -> str:
    if BACKEND == "openai":
        return _call_openai(system_prompt, prompt)
    if BACKEND == "gpt4all":
        return _call_gpt4all(system_prompt, prompt)
    raise AssessmentError("Unknown grading backend")


def _call_gpt4all(system_prompt: str, prompt: str) -> str:
    with _model_lock:
        model = _get_gpt4all_model()
        with model.chat_session(system_prompt=system_prompt):
            return model.generate(prompt, max_tokens=MAX_OUTPUT_TOKENS)


def _call_openai(system_prompt: str, prompt: str) -> str:
    global client
    if client is None:
        from openai import OpenAI
        client = OpenAI(timeout=60, max_retries=1)
    response = client.responses.create(
        model=OPENAI_MODEL,
        temperature=0,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    return response.output_text


def _build_prompt(question: str, answer: str, student_answer: str) -> str:
    return (
        f"Frage: {question}\n"
        f"Musterlösung: {answer}\n"
        f"Schülerantwort: {student_answer}\n"
    )


def _parse_response(raw: str) -> Assessment:
    """Normalize a valid grade; malformed output must never update progress."""
    try:
        data = _extract_json_object(raw)
        score = _validate_score(data["score"])
        feedback = data["feedback"]
        if not isinstance(feedback, str):
            raise ValueError("Feedback must be text")
        if "sks_punkte" in data:
            return _parse_sks_assessment(data, score, feedback)
        return _parse_general_assessment(data, score, feedback)
    except (KeyError, TypeError, ValueError):
        raise AssessmentError("Grading service returned an invalid assessment") from None


def _extract_json_object(raw: str) -> dict:
    """Allow markdown fences or prose around the model's JSON object."""
    if not isinstance(raw, str):
        raise ValueError("Model response must be text")
    decoder = json.JSONDecoder()
    for index, character in enumerate(raw):
        if character != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate
    raise ValueError("No JSON object in model response")


def _validate_score(score: float) -> float:
    if type(score) not in (int, float):
        raise ValueError("Score must be numeric")
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("Score must be between zero and one")
    return float(score)


def _parse_boolean(value: bool | str) -> bool:
    if type(value) is bool:
        return value
    if isinstance(value, str):
        normalized = value.lower()
        if normalized in TRUE_VALUES:
            return True
        if normalized in FALSE_VALUES:
            return False
    raise ValueError("Invalid correctness value")


def _parse_sks_assessment(data: dict, score: float, feedback: str) -> Assessment:
    points = data["sks_punkte"]
    if type(points) is not int or points not in (0, 1, 2):
        raise ValueError("SKS points must be zero, one, or two")
    return Assessment(
        is_sks=True,
        correct=_parse_boolean(data["correct"]),
        result="",
        sks_punkte=points,
        score=score,
        feedback=feedback,
    )


def _parse_general_assessment(data: dict, score: float, feedback: str) -> Assessment:
    result = data["result"]
    if result not in VALID_RESULTS:
        raise ValueError("Unknown assessment result")
    return Assessment(
        is_sks=False,
        correct=result in CORRECT_RESULTS,
        result=result,
        sks_punkte=0,
        score=score,
        feedback=feedback,
    )


def _get_gpt4all_model():
    global _gpt4all_instance
    if _gpt4all_instance is None:
        from gpt4all import GPT4All
        _gpt4all_instance = GPT4All(GPT4ALL_MODEL)
    return _gpt4all_instance
