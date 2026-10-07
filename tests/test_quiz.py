import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

import assessor
import question_store
from app import app

PROCESS_UPDATE_SCRIPT = """
import sys
from pathlib import Path
import question_store

question_store.FIELDS_PATH = Path(sys.argv[1])
for _ in range(10):
    question_store.record_attempt("test", 1, True, 1)
"""


class QuizTests(unittest.TestCase):
    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.storage_root = Path(temporary_directory.name)
        field_directory = self.storage_root / "test"
        field_directory.mkdir()
        questions = [
            {"id": question_id, "topic": "Topic", "question": f"Q{question_id}", "answer": "A"}
            for question_id in (1, 2)
        ]
        self._write_json(field_directory / "questions.json", {"questions": questions})
        self._write_json(field_directory / "sets.json", {"Exam / special": [1]})
        (field_directory / "system-prompt.txt").write_text("Grade fairly", encoding="utf-8")

        storage_patch = patch.object(question_store, "FIELDS_PATH", self.storage_root)
        storage_patch.start()
        self.addCleanup(storage_patch.stop)
        self.client = app.test_client()

    @staticmethod
    def _write_json(path, data):
        path.write_text(json.dumps(data), encoding="utf-8")

    def _submit_answer(self):
        return self.client.post(
            "/api/assess", json={"field": "test", "id": 1, "answer": "A"}
        )

    def test_invalid_requests(self):
        invalid_bodies = [
            [],
            {},
            {"field": "../test", "id": 1, "answer": "A"},
            {"field": "test", "id": "bad", "answer": "A"},
            {"field": "test", "id": 1, "answer": []},
        ]
        for body in invalid_bodies:
            with self.subTest(body=body):
                response = self.client.post("/api/assess", json=body)
                self.assertEqual(response.status_code, 400)
        response = self.client.get("/api/fields/test/question?filter=missing")
        self.assertEqual(response.status_code, 400)
        with self.assertRaises(ValueError):
            question_store.field_path(str(self.storage_root / "test"))

    def test_grading_and_stats(self):
        assessment = assessor.Assessment(
            is_sks=False, correct=True, result="correct",
            sks_punkte=0, score=1, feedback="Good",
        )
        with patch.object(assessor, "assess", return_value=assessment):
            for _ in range(3):
                self.assertEqual(self._submit_answer().status_code, 200)

        stats = self.client.get("/api/fields/test/stats").json
        self.assertEqual(stats["success_rate"], 100)
        self.assertEqual(stats["correct_attempts"], 3)
        self.assertEqual(stats["total_correct"], 1)
        self.assertEqual(stats["best_streak"], 3)
        self.assertEqual(stats["topics"][0]["correct"], 1)

        details = self.client.get("/api/fields/test/topics/Topic/stats").json
        self.assertEqual(len(details["questions"]), 2)
        self.assertEqual(question_store.get_next_question("test")["id"], 2)
        self.assertNotIn("answer", self.client.get("/api/fields/test/question").json)
        self.assertEqual(question_store.get_set_stats("test", "Exam / special")["total"], 1)
        response = self.client.get("/api/fields/test/sets/Exam%20%2F%20special/stats")
        self.assertEqual(response.json["total"], 1)

    def test_failure_and_reveal_do_not_record_progress(self):
        failure = assessor.AssessmentError("Invalid grade")
        with patch.object(assessor, "assess", side_effect=failure):
            self.assertEqual(self._submit_answer().status_code, 502)
        response = self.client.post(
            "/api/reveal-answer", json={"field": "test", "id": 1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(question_store.load_progress("test"), {})

    def test_concurrent_updates(self):
        def record_correct_answer(_):
            return question_store.record_attempt("test", 1, True, 1)

        with ThreadPoolExecutor(max_workers=8) as workers:
            list(workers.map(record_correct_answer, range(40)))
        self.assertEqual(question_store.load_progress("test")["1"]["attempts"], 40)

    def test_process_updates(self):
        command = [sys.executable, "-c", PROCESS_UPDATE_SCRIPT, str(self.storage_root)]
        workers = [subprocess.Popen(command) for _ in range(3)]
        for worker in workers:
            self.addCleanup(self._stop_process, worker)
        for worker in workers:
            self.assertEqual(worker.wait(timeout=10), 0)
        self.assertEqual(question_store.load_progress("test")["1"]["attempts"], 30)

    @staticmethod
    def _stop_process(process):
        if process.poll() is None:
            process.kill()
            process.wait()

    def test_client_is_lazy(self):
        self.assertIsNone(assessor.client)

    def test_parser(self):
        general_grade = {
            "score": 0.5, "result": "partially_correct", "feedback": "Contains {braces}"
        }
        result = assessor._parse_response(f"```json\n{json.dumps(general_grade)}\n```")
        self.assertEqual(result.score, 0.5)
        sks_grade = {"score": 1, "correct": "true", "sks_punkte": 2, "feedback": "Good"}
        self.assertTrue(assessor._parse_response(json.dumps(sks_grade)).is_sks)
        invalid_responses = [
            "not JSON", "{}",
            json.dumps({**general_grade, "score": 70}),
            json.dumps({**general_grade, "result": "unknown"}),
        ]
        for raw in invalid_responses:
            with self.subTest(raw=raw), self.assertRaises(assessor.AssessmentError):
                assessor._parse_response(raw)

    def test_local_backend_receives_instructions(self):
        model = Mock()
        model.chat_session.return_value = nullcontext()
        with patch.object(assessor, "_get_gpt4all_model", return_value=model):
            assessor._call_gpt4all("Grade fairly", "Question")
        model.chat_session.assert_called_once_with(system_prompt="Grade fairly")

    def test_invalid_banks_not_advertised(self):
        invalid_field = self.storage_root / "bad"
        invalid_field.mkdir()
        self._write_json(invalid_field / "questions.json", [])
        self.assertEqual(question_store.get_fields(), ["test"])


if __name__ == "__main__":
    unittest.main()
