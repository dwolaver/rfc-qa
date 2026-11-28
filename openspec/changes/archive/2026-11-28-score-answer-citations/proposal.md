# Proposal

## Why

Retrieval scoring shows whether a correct passage reaches the model, but not what the model does
with it. Nothing yet measures whether an answer cites the right section, cites an obsolete RFC on a
stale-citation trap, or declines a question the corpus doesn't answer. Step 3 is about to change
retrieval, and without these scores it can't show whether a better rank becomes a better answer.

This change is the third of step 2's changes. The plan in `add-golden-question-set` had a single
change score answers. It's now split in two:

1. **This change:** score each answer's citations and abstention against the labels the golden set
   already has. It needs no new labels and no judge model.
2. **Next:** score answer correctness, with a short list of key facts for each question and a judge
   model checked against hand grades.
3. **Then:** record the v0.2.0 baseline, with all three kinds of score, in a committed report.

Scoring needs one change to the library. When the model says it found an answer, but none of its
citations names a passage it was sent, `query()` reports the question as not found. The scorer can't
tell that from a real abstention, so an out-of-corpus question would count as correctly declined
when the model tried to answer it. Other callers can't tell the two apart either.

## What Changes

- **Answer scoring:** a new script, `scripts/score_answers.py`, calls `query()` with each golden
  question and scores the response by its citations and whether it answered:
  - an answerable question is correct when it cites at least one expected section;
  - a `stale-trap` answer that cites one of the question's obsolete sections is a stale citation;
  - an `out-of-corpus` question is correct when the response is not found;
  - each miss on an answerable question is a retrieval miss when no expected section was in the
    passages sent to the model, and a generation miss when one was.
- **Saved runs:** each run writes every response to a JSON Lines file, with the model, its digest,
  the commit and the time, so a run can be read and graded later. The next change grades answers
  from these files.
- **Rejected answers marked:** `QueryResponse` gets a new field that is true when the model said it
  found an answer but the service rejected it, because no citation named a passage it was sent or
  the answer was empty. The response is still not found, so existing callers see no change.
- **Retrieval scoring unchanged:** `score_retrieval.py` still needs no model and still gives the same
  result on every run. The answer scorer reuses its golden-set loading and label matching.

## Capabilities

### New Capabilities

- `answer-evaluation`: scores the answers that `query()` returns against the golden question set,
  and saves each run. The next change adds answer correctness here.

### Modified Capabilities

- `answer-generation`: reports when the model's answer was rejected, rather than only reporting it
  as not found.
- `query-interface`: the response carries whether a not-found result came from a rejected answer.

## Impact

- **Code:** a new field on `GenerationResult` and `QueryResponse` in `rfc_qa`, and the new script with
  its tests. `score_retrieval.py` doesn't change.
- **API:** `QueryResponse` gains a field with a default, which is backward compatible.
- **Running it:** the scorer needs Ollama and the configured model, so it runs locally on demand
  and not in CI. Its tests replace the model call, as the generation tests do.
- **Documentation:** `docs/evaluation.md` describes running and reading the answer scores, and
  `CHANGELOG.md` gets an entry.
