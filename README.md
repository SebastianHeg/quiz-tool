# Quiz Trainer

A Flask exam practice app for SKS, SRC, psychology, and custom subjects. Answer in your own words and receive semantic AI grading, feedback, and a reference answer.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000. The development server listens on all interfaces on port 5000. Use a production WSGI server for hosted deployments.

The default backend is GPT4All, which loads a local model on the first assessment and may download the model if needed. An OpenAI API key is not required for local grading.

To use OpenAI, configure the environment or a `.env` file:

```dotenv
ASSESSOR_BACKEND=openai
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-4o-mini
```

| Variable | Default | Purpose |
|---|---|---|
| `ASSESSOR_BACKEND` | `gpt4all` | `gpt4all` or `openai` |
| `GPT4ALL_MODEL` | `mistral-7b-instruct-v0.1.Q4_0.gguf` | Local model filename |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model |

## Architecture and storage

`templates/index.html` contains the browser markup; `static/trainer.css` and `static/trainer.js` contain its styles and behavior. `app.py` exposes JSON endpoints; `question_store.py` handles storage, selection, and statistics; `assessor.py` handles grading. Grading is synchronous. Local inference is serialized because the cached model has shared chat state.

Each subject lives under `sets/<subject>/`:

- `questions.json`: an object containing a `questions` array.
- `system-prompt.txt`: grading instructions, including the JSON response format.
- `sets.json` and optional `examens.json`: objects mapping group names to arrays of question IDs.
- `progress.json`: generated progress keyed by question ID.

Example question bank:

```json
{
  "questions": [
    {
      "id": 1,
      "topic": "Navigation",
      "subtopic": "GPS",
      "question": "Your question",
      "answer": "Reference answer"
    }
  ]
}
```

IDs must be unique positive integers. Existing IDs should remain stable because sets and progress reference them. Only valid subjects with grading instructions appear in the subject list.

Grading instructions must request JSON with `score` from 0 to 1 and `feedback`, plus either `result` (`correct`, `fully_correct`, `mostly_correct`, `partially_correct`, `minimally_correct`, `incorrect`) or SKS fields `correct` and `sks_punkte` (0–2). Invalid model output returns an error without recording an attempt.

Question selection chooses an unanswered question at random, then randomly chooses among questions with the lowest lifetime success rate. There is no time-based spaced repetition. Revealing or skipping an answer does not record an attempt.

Statistics distinguish questions whose latest result was correct (`total_correct`) from all successful attempts (`correct_attempts`). `success_rate` is successful attempts divided by total attempts. The best streak is the longest recorded consecutive correct streak on an individual question. Older progress cannot recover streak records that were already lost.

Progress updates use atomic replacement and thread/process locking on Unix. Progress is shared by everyone using the server; there are no accounts or separate learner histories. Subject paths are restricted to direct directories under `sets/`.

`main.py` is a separate desktop Tkinter trainer with independent logic and an older progress schema. Avoid using it and the web app to write the same progress file concurrently.

## Import utilities and checks

`support/` provides HTML parsing, ID assignment, fuzzy matching of question lists to banks, and coverage analysis. The requirements include Beautiful Soup and RapidFuzz for these utilities.

Run regression tests without calling external AI services:

```bash
.venv/bin/python -m unittest discover -s tests -v
```
