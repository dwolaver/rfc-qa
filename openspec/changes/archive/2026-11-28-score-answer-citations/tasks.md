# Tasks

## 1. Marking a rejected answer

- [x] 1.1 On the branch `score-answer-citations`, add `answer_rejected: bool = False` to `GenerationResult` in `generation/answer_generator.py`, set true when the model's output says found but the result isn't answered: no valid citation, or a blank answer. Test each scenario in the `answer-generation` delta: no valid citations, a blank answer with a valid citation, the model reporting no answer, and an answered question. Verify with `pytest tests/generation/`
- [x] 1.2 Add `answer_rejected: bool = False` to `QueryResponse` in `query.py`, and pass it through from the generation result when `query()` returns not found. Failure responses, a search that finds no passages and answered queries keep it false. Document the field in the class docstring. Test, with `generate_answer` replaced as the existing tests do, that a rejected answer gives `success` true, `found` false, the not-found message, no citations and `answer_rejected` true, and that the other outcomes keep it false. Verify with `pytest tests/test_query.py`, and that `rfc-query` prints the same output as before for a rejected answer

## 2. Scoring answers

- [x] 2.1 Create `scripts/score_answers.py` with the outcome rules from the design, as functions over a question, its retrieval `Score` and a `QueryResponse`: the outcome for answerable and `out-of-corpus` questions, the cause from the rank and the retrieval limit, the stale-citation flag, and the cited count. Import the golden-set loader, `score_question` and the kind constants from `scripts.score_retrieval`, so labels match exactly as retrieval scoring matches them. Test with hand-made responses for each scenario in the `answer-evaluation` spec, including a subsection citation that doesn't match, a trap answer that cites both an expected and an obsolete section, and a cited count of `2/3`. Verify with `pytest tests/scripts/test_score_answers.py`
- [x] 2.2 Add the totals and the report: the per-question table, the share `correct` overall and by kind, the misses by cause, stale citations, correct abstentions, abstentions on answerable questions, and rejected answers and errors. Test the totals and the printed report for a small set of hand-made scores covering every outcome. Verify with `pytest tests/scripts/test_score_answers.py`

## 3. Running a scored run

- [x] 3.1 Add the run file: a writer that writes the run line, then one line per question as it finishes, flushing each, with the fields listed in the design. Read the commit and the working tree's state with `git`, and record them as unknown when `git` fails. The default path is `eval-runs/answers-<UTC timestamp>.jsonl` in the data directory, with its directory created. Test that a written file parses line by line with the expected fields, and that a failing `git` records the commit as unknown. Verify with `pytest tests/scripts/test_score_answers.py`
- [x] 3.2 Add `main(argv)`, run as `python -m scripts.score_answers`, with `--data-dir`, `--config-dir`, `--golden`, `--output` and `-v`. Before the first question it loads the golden set, runs the label check against the index, loads the query configuration as `query()` does, and asks Ollama's model list for the configured model and its digest. Then, for each question, it ranks a search of the first 20 results, calls `query()`, scores the response, writes its line and prints its row. It continues past `MODEL_INVALID_RESPONSE`, and stops with status 1 on `MODEL_UNAVAILABLE`, `INDEX_UNAVAILABLE` or `CONFIG_INVALID`. Test against a small index built with `build_index`, with the model call and the model list replaced: exit 0 with the expected report and run file, exit 1 with no question asked for a missing label, an unreachable Ollama and a missing model, an `error` row that doesn't stop the run, and a stop with status 1 that keeps the earlier questions in the run file. Also test that the scorer's first `retrieval.limit` search results are the passages `query()` sent. Verify with `pytest tests/scripts/test_score_answers.py` and `pre-commit run --all-files`
- [x] 3.3 Run `python -m scripts.score_answers` against the local index and `llama3.2`. Verify that it asks all 40 questions, exits 0, prints the report and writes a run file whose lines parse. Keep the report for the pull request description

## 4. Documentation

- [x] 4.1 Add an answer scoring section to `docs/evaluation.md`: that it needs Ollama and the configured model and isn't run in CI, the command, its flags and where the run file goes, each outcome and cause, how to read the totals, including that `correct` means cited correctly rather than answered correctly, and that the scores vary a little between runs, so a change is read question by question with the run's model and commit beside it. Replace the sentence that calls scoring answers a later step. Verify that the documented command runs as written, and that `pytest tests/test_docs.py` passes
- [x] 4.2 Add an entry under `[Unreleased]` in `CHANGELOG.md`. Under Added: a script that scores the answers `query()` gives to the golden questions, by whether they cite an expected section, cite an obsolete one on a trap, or decline a question the corpus doesn't answer, and that saves each run. Also under Added: `QueryResponse.answer_rejected`, which says that a not-found result came from an answer the service rejected rather than from the model declining. Verify with `pytest tests/test_docs.py`, which checks the changelog's structure

## 5. Integration

- [x] 5.1 Run `pytest`, with and without `RFC_QA_INSTALL_TESTS=1`, and `pre-commit run --all-files`. Verify that all pass, and that the built wheel contains no file from `eval/` or `scripts/`

## Workflow follow-up

- Open a pull request from `score-answer-citations`, with the report from 3.3 in its description. The `test`, `quality` and `secrets` checks must pass, and `archive-check` is expected to fail until the archive.
- After apply, the repository owner reviews the code and CI runs on the pull request. Any changes are made on this branch, in the active change, before the archive, and the checks must pass again.
- Archive the change on this branch as the last step, which creates the `answer-evaluation` spec, updates `answer-generation` and `query-interface`, and makes the change complete.
- The repository owner merges once CI still passes, so that the code, spec and archive land as one commit on `main`.
