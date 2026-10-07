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
            return model.generate(prompt, max_tokens=512)


def _call_openai(system_prompt: str, prompt: str) -> str:
    global client
    if client is None:
        from openai import OpenAI
        client = OpenAI(timeout=60, max_retries=1)
    return client.responses.create(
        model=OPENAI_MODEL,
        temperature=0,
        input=[{"role": "system", "content": system_prompt},
               {"role": "user", "content": prompt}],
        max_output_tokens=512,
    ).output_text


def _build_prompt(question: str, answer: str, student_answer: str) -> str:
    return f"Frage: {question}\nMusterlösung: {answer}\nSchülerantwort: {student_answer}\n"


def _parse_response(raw: str) -> Assessment:
    """Accept a JSON object with optional surrounding prose; reject invalid grades."""
    decoder = json.JSONDecoder()
    data = None
    if isinstance(raw, str):
        for index, char in enumerate(raw):
            if char != "{":
                continue
            try:
                candidate, _ = decoder.raw_decode(raw[index:])
                if isinstance(candidate, dict):
                    data = candidate
                    break
            except json.JSONDecodeError:
                continue
    try:
        if data is None:
            raise ValueError()
        score = data["score"]
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError()
        feedback = data["feedback"]
        if not isinstance(feedback, str):
            raise ValueError()
        if "sks_punkte" in data:
            points = data["sks_punkte"]
            if type(points) is not int or points not in (0, 1, 2):
                raise ValueError()
            correct = data["correct"]
            if isinstance(correct, str):
                if correct.lower() not in ("true", "false", "1", "0", "yes", "no", "correct", "incorrect", "richtig", "falsch"):
                    raise ValueError()
                correct = correct.lower() in ("true", "1", "yes", "correct", "richtig")
            if type(correct) is not bool:
                raise ValueError()
            return Assessment(True, correct, "", points, float(score), feedback)
        result = data["result"]
        if result not in {"fully_correct", "correct", "mostly_correct", "partially_correct", "minimally_correct", "incorrect"}:
            raise ValueError()
        return Assessment(False, result in {"fully_correct", "correct", "mostly_correct"}, result, 0, float(score), feedback)
    except (KeyError, TypeError, ValueError):
        raise AssessmentError("Grading service returned an invalid assessment") from None


def _get_gpt4all_model():
    global _gpt4all_instance
    if _gpt4all_instance is None:
        from gpt4all import GPT4All
        _gpt4all_instance = GPT4All(GPT4ALL_MODEL)
    return _gpt4all_instance
