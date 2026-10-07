import concurrent.futures
import json
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import assessor
import question_store as store
from app import app


class QuizTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        field = self.root / 'test'
        field.mkdir()
        questions = [{'id': i, 'topic': 'Topic', 'question': f'Q{i}', 'answer': 'A'} for i in (1, 2)]
        (field / 'questions.json').write_text(json.dumps({'questions': questions}))
        (field / 'system-prompt.txt').write_text('Grade fairly')
        (field / 'sets.json').write_text(json.dumps({'Exam / special': [1]}))
        patcher = patch.object(store, 'FIELDS_PATH', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = app.test_client()

    def test_invalid_requests(self):
        for body in ([], {}, {'field': '../test', 'id': 1, 'answer': 'A'}, {'field': 'test', 'id': 'bad', 'answer': 'A'}, {'field': 'test', 'id': 1, 'answer': []}):
            self.assertEqual(self.client.post('/api/assess', json=body).status_code, 400)
        self.assertEqual(self.client.get('/api/fields/test/question?filter=missing').status_code, 400)
        with self.assertRaises(ValueError):
            store.field_path(str(self.root / 'test'))

    def test_grading_and_stats(self):
        with patch.object(assessor, 'assess', return_value=assessor.Assessment(False, True, 'correct', 0, 1, 'Good')):
            for _ in range(3):
                self.assertEqual(self.client.post('/api/assess', json={'field': 'test', 'id': 1, 'answer': 'A'}).status_code, 200)
        stats = self.client.get('/api/fields/test/stats').json
        self.assertEqual(stats['success_rate'], 100)
        self.assertEqual(stats['correct_attempts'], 3)
        self.assertEqual(stats['total_correct'], 1)
        self.assertEqual(stats['best_streak'], 3)
        self.assertEqual(stats['topics'][0]['correct'], 1)
        details = self.client.get('/api/fields/test/topics/Topic/stats').json
        self.assertEqual(len(details['questions']), 2)
        self.assertEqual(store.get_next_question('test')['id'], 2)
        self.assertNotIn('answer', self.client.get('/api/fields/test/question').json)
        self.assertEqual(store.get_set_stats('test', 'Exam / special')['total'], 1)
        self.assertEqual(self.client.get('/api/fields/test/sets/Exam%20%2F%20special/stats').json['total'], 1)

    def test_failure_and_reveal_do_not_record_progress(self):
        with patch.object(assessor, 'assess', side_effect=assessor.AssessmentError('Invalid grade')):
            self.assertEqual(self.client.post('/api/assess', json={'field': 'test', 'id': 1, 'answer': 'A'}).status_code, 502)
        self.assertEqual(self.client.post('/api/reveal-answer', json={'field': 'test', 'id': 1}).status_code, 200)
        self.assertEqual(store.load_progress('test'), {})

    def test_concurrent_updates(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: store.record_attempt('test', 1, True, 1), range(40)))
        self.assertEqual(store.load_progress('test')['1']['attempts'], 40)

    def test_process_updates(self):
        code = "import sys; from pathlib import Path; import question_store as s; s.FIELDS_PATH=Path(sys.argv[1]); [s.record_attempt('test', 1, True, 1) for _ in range(10)]"
        workers = [subprocess.Popen([sys.executable, '-c', code, str(self.root)]) for _ in range(3)]
        for worker in workers:
            self.assertEqual(worker.wait(timeout=10), 0)
        self.assertEqual(store.load_progress('test')['1']['attempts'], 30)

    def test_client_is_lazy(self):
        self.assertIsNone(assessor.client)

    def test_parser(self):
        result = assessor._parse_response('```json\n{"score":0.5,"result":"partially_correct","feedback":"Contains {braces}"}\n```')
        self.assertEqual(result.score, .5)
        result = assessor._parse_response('{"score":1,"correct":"true","sks_punkte":2,"feedback":"Good"}')
        self.assertTrue(result.is_sks)
        for raw in ('not JSON', '{}', '{"score":70,"result":"correct","feedback":"x"}', '{"score":1,"result":"unknown","feedback":"x"}'):
            with self.assertRaises(assessor.AssessmentError):
                assessor._parse_response(raw)

    def test_local_backend_receives_instructions(self):
        model = Mock()
        model.chat_session.return_value.__enter__ = Mock()
        model.chat_session.return_value.__exit__ = Mock(return_value=False)
        with patch.object(assessor, '_get_gpt4all_model', return_value=model):
            assessor._call_gpt4all('Grade fairly', 'Question')
        model.chat_session.assert_called_once_with(system_prompt='Grade fairly')

    def test_invalid_banks_not_advertised(self):
        folder = self.root / 'bad'
        folder.mkdir()
        (folder / 'questions.json').write_text('[]')
        self.assertEqual(store.get_fields(), ['test'])


if __name__ == '__main__':
    unittest.main()
