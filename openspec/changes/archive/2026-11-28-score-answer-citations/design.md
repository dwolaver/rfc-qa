# Design

## Context

`query()` searches the keyword index, sends the top `retrieval.limit` passages (5 by default) to
the model, and returns a `QueryResponse`. `generate_answer` keeps a citation only when it names a
passage that was sent, and turns a found answer into not found when no citation survives or the
answer is empty. That is the case proposal.md describes, which the response can't yet tell apart
from the model declining.

`scripts/score_retrieval.py` loads and checks the golden set, checks every label against the index,
ranks the first 20 search results against each question's labels, and prints a table by kind. Tests
import it as `scripts.score_retrieval`, which works because `pytest.ini` puts the repository root on
the path and `scripts/` is a namespace package. Its guide promises that retrieval scoring needs no
model and gives the same result on every run.

The golden set has no reference answers. Its labels are sections, so this change scores what
sections say about an answer: which ones it cites, and whether it answered at all.

## Goals / Non-Goals

**Goals:**

- Score every golden question through `query()` itself, so the scores cover the path users take.
- Say, for each answer that misses, whether retrieval or generation lost it.
- Save each run in a form the next change can grade by hand and with a judge.

**Non-Goals:**

- Judging the answer text. That is the next change, with key facts and a judge model.
- Returning a rejected answer's text in the response. The field says an answer was rejected, and the
  log says so too. Adding the text is a later decision if callers need it.
- Running in CI. CI has no Ollama, and the scores vary a little between runs.
- Repeating runs to average out the variation. One run per invocation; the saved metadata lets runs
  be compared.

## Decisions

### `answer_rejected` on the result and the response

`GenerationResult` and `QueryResponse` each get `answer_rejected: bool = False`. It is true when the
model's output said it found an answer, but the service returned not found: no citation named a
passage that was sent, or the answer was blank. `found` stays false, `answer` stays the standard
not-found message, and `citations` stays empty, so existing callers see no change. It is false on
every other response, including failures.

The name covers both reasons, rather than only citations, so that an out-of-corpus question with a
blank "found" answer is not scored as a correct abstention either. Alternatives:

- **`unusable_citations`:** narrower, and leaves the blank-answer case looking like an abstention.
- **A three-way `outcome` enum in place of `found`:** clearer, but it changes a field callers
  already read, which is a breaking change for a scoring need.

The console output doesn't change. `rfc-query` still prints the not-found message. The log record
for a rejected answer changes: it said the model found no answer, which was wrong, so it now says the
answer was rejected, and `-v` shows that.

### A separate script, run as a module

`scripts/score_answers.py` imports the golden-set loader, `missing_labels`, `score_question` and the
kind constants from `scripts.score_retrieval`, so labels are matched exactly as retrieval scoring
matches them. It is run from the repository root as `python -m scripts.score_answers`, because that
import needs the root on the path, as the tests already arrange.

Alternatives:

- **`python scripts/score_answers.py`, like the retrieval scorer:** that puts `scripts/` on the path
  instead of the root, so the import would have to differ between running and testing, or the script
  would edit `sys.path`.
- **Moving the shared code into `rfc_qa`:** evaluation isn't part of the installed library, and the
  golden set isn't installed with it.

### Retrieval rank from a search of its own

For each answerable question the scorer searches the index for the first 20 results and ranks them
with `score_question`, then calls `query()`. Search is deterministic, and `query()` sends the first
`retrieval.limit` results of the same search, so an expected section was among the passages the model
saw exactly when its rank is at most `retrieval.limit`. The limit is read from the query configuration
`query()` uses, not assumed to be 5.

This searches twice per question. A keyword search takes milliseconds next to seconds of generation,
and it keeps `query()` free of evaluation hooks.

### Outcomes

Each question gets one outcome:

```
 answerable question (not out-of-corpus)       out-of-corpus question
 -------------------------------------------   ------------------------------
 correct      cites an expected section        abstained   not found (correct)
 wrong-cite   answered, cites none expected    answered    found, with citations
 abstained    not found                        rejected    answer_rejected
 rejected     answer_rejected                  error       query failed
 error        query failed
```

An answerable question that isn't `correct` also gets a cause: `retrieval` when its rank is above
`retrieval.limit` or it wasn't found, otherwise `generation`. A `stale-trap` answer is marked as a
stale citation when it cites any of the question's obsolete sections, whatever its outcome. A
version-specific question is scored like any other: its expected sections are in the obsolete RFC.

Each answerable question also reports how many of its expected sections it cited, such as `2/3`.
For `multi-section` questions this shows how much of the answer was covered, without a second rule
for what counts as correct.

### Failures during a run

Before the first question, the scorer checks the golden set and its labels against the index, as
retrieval scoring does, loads the query configuration, and asks Ollama's model list for the
configured model and its digest. Any of these failing exits with status 1 before a question is
asked.

During the run, a query that fails with `MODEL_INVALID_RESPONSE` is recorded as an `error` outcome and
the run goes on: it says something about the model. A failure with `MODEL_UNAVAILABLE`,
`INDEX_UNAVAILABLE` or `CONFIG_INVALID` stops the run with status 1, because every later question would
fail the same way. The questions answered so far stay in the saved run.

### Saved runs in JSON Lines

The run file is JSON Lines, written and flushed one line at a time, so an interrupted run keeps what it
finished:

- The first line is the run: the model name and digest, the Ollama address, the retrieval limit, the
  commit and whether the working tree had changes, the golden set's path, and the start time in UTC.
- Each later line is one question: its ID and kind, the retrieval rank, the full response (success,
  found, answer, citations, `answer_rejected`, error code and string, timings), and its outcome, cause,
  stale citation and cited count.

The default path is `eval-runs/answers-<UTC timestamp>.jsonl` in the data directory, outside the
repository, so runs don't land in commits by accident. `--output` names another file. The baseline
change commits one run on purpose.

The commit comes from `git`. When `git` isn't available or the directory isn't a repository, the
run records it as unknown and goes on.

### Tests

The tests replace the model call, as the generation tests do, and use a small index built in a
temporary directory, so they need no Ollama. They cover each outcome and cause, the stale-citation
flag, the cited count, the run file's lines, and the exit status for each failure above.

## Risks / Trade-offs

- [The scores vary a little between runs, even at temperature 0] → The run records the model digest
  and commit, the guide says to read a change question by question, and the baseline is a saved run
  rather than a number to match.
- [Seven out-of-corpus questions give a coarse abstention rate] → The table lists each one. More can
  be added later with the same checks as any question.
- [A citation of an expected section doesn't prove the answer is right] → Correctness is the next
  change. Until then the guide calls this score "cited correctly", not "answered correctly".
- [Search and `query()` could rank differently if `query()` ever changes how it searches] → The rank
  is recorded beside the citations, so a citation of a passage ranked above the limit shows the
  difference. A test checks that the scorer's top results are the passages `query()` sent.
- [A full run takes minutes, and longer on a cold start] → The run prints each question as it finishes,
  and the timings in the run file show where the time went.
