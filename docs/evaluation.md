# Evaluation

[Back to README](../README.md)

The golden question set, [`eval/golden.toml`](../eval/golden.toml), is a fixed list of questions,
each labeled with the RFC sections that answer it. Two scripts score against it:

- `scripts/score_retrieval.py` searches the index with each question and reports where the first
  correct section ranks. Each change to retrieval runs it before and after, so the change can show
  what it improved and what it made worse. It reads only the index, needs no model, and gives the
  same result on every run against the same index.
- `scripts/score_answers.py` asks each question through `query()` and scores the answer by the
  sections it cites, as described in [Scoring answers](#scoring-answers). It needs Ollama.

## Running the scores

Build the index first, as described in [Building the index](usage.md#building-the-index). Then, from
the repository root, with the project installed for development as in
[CONTRIBUTING.md](../CONTRIBUTING.md):

```
python scripts/score_retrieval.py
```

It reads `index.db` in the data directory, chosen as the commands choose it: `--data-dir`, then
`RFC_QA_DATA_DIR`, then the default. `--golden` names another question file, and `-v` shows the top
five results for each question on standard error.

The script first checks that every labeled section has a chunk in the index. If one doesn't, it
names each missing section and its question, and scores nothing. It exits with status 1 for that, for
a problem in the golden set, or for a missing index, and with status 0 once it has scored, whatever
the scores.

## Reading the output

```
id                        kind              rank  trap
api-error-details         direct              11  -
tls-application-protocol  direct               -  -
http2-flow-control        stale-trap           2  yes
...

hit@1  2/11 (0.18)    hit@5  7/11 (0.64)    MRR 0.35    trap rate 3/3 (1.00)
```

- **rank:** the position of the first result from an expected section, in the first 20 results. `-`
  means none of the 20 was from an expected section. Ranks count passages, so a second passage from
  one section takes a position.
- **hit@1 and hit@5:** the share of questions ranked first, and ranked in the first five. Five is the
  number of passages a query sends the model, so hit@5 is the share of questions where the model
  sees a correct passage.
- **MRR:** the mean reciprocal rank, the average of 1 / rank, counting a question not found as 0.
  It rewards moving a section from rank 10 to rank 2, which hit@5 alone only partly shows.
- **trap:** for a `stale-trap` question, `yes` when a passage from an obsolete RFC ranks above every
  passage from the current one. The **trap rate** is the share of traps caught this way, so lower
  is better.

A table after the totals gives hit@1 and hit@5 for each kind. `out-of-corpus` questions are skipped
and counted, because a search always returns its closest matches. Whether the model declines to
answer them is measured by [scoring answers](#scoring-answers).

With about a dozen questions, one question moves hit@1 by almost 10 points, so read a change's
effect question by question as well as in the totals.

## Scoring answers

Answer scoring asks every golden question through `query()`, as a user's question would be asked,
and scores each answer by its citations and by whether it answered at all. It doesn't judge the
answer's text: an answer that cites the right section can still say something wrong.

It needs the index, Ollama and the configured model, so it runs locally on demand and isn't part of
CI. From the repository root, with the project installed for development:

```
python -m scripts.score_answers
```

It runs as a module, with `-m`, because it reuses the retrieval scorer's code. `--data-dir`,
`--golden` and `-v` work as they do for retrieval scoring, and `--config-dir` chooses the query
configuration as `rfc-query` does. A run of 40 questions takes under a minute once the model is
loaded.

Before the first question it checks the golden set, checks every label against the index, and asks
Ollama for the configured model. If any of these fails, it asks nothing and exits with status 1. A
query whose model output is invalid is scored as an `error`, and the run goes on. If Ollama, the
index or the configuration stops working partway, the run stops with status 1. Otherwise it exits
with status 0, whatever the scores.

### The run file

Each run is saved as JSON Lines, one line as each question finishes, so an interrupted run keeps
what it finished. By default it's a new file in `eval-runs/` in the data directory, outside the
repository, named by the time it started, such as `answers-20261128T144235Z.jsonl`. `--output`
names another file.

The first line describes the run: the model and its digest, the Ollama address, the number of
passages per query, the commit and whether the working tree had changes, the golden set and the
index. Each later line is one question, with its retrieval rank, the full response and its scores.

### Reading the output

```
id                        kind              rank  outcome     cause       stale  cited
tcp-data-in-syn           direct               1  correct     -           -      1/4
http-header-format        direct               4  abstained   generation  -      0/1
tls13-resumption          stale-trap           5  wrong-cite  generation  yes    0/3
dns-over-https            out-of-corpus        -  answered    -           -      -
...

cited correctly  15/33 (0.45)    misses: retrieval 16, generation 2
stale citations  4/9 (0.44)
abstained        1/7 (0.14) of out-of-corpus, 4/33 (0.12) of answerable
rejected         1/40 (0.03)    errors 0/40 (0.00)
```

- **rank:** the rank of the first expected section in a search of the first 20 results, as
  retrieval scoring reports it. It's `-` when none was found, and for `out-of-corpus` questions.
- **outcome:** for a question the corpus answers:
  - `correct`: the answer cites at least one expected section.
  - `wrong-cite`: it answered, but cites no expected section.
  - `abstained`: the query said the indexed RFCs don't answer it.
  - `rejected`: the model said it found an answer, but none of its citations named a passage it was
    sent, or the answer was blank, so the query reported it as not found.
  - `error`: the query failed.

  For an `out-of-corpus` question, `abstained` is the correct outcome, and `answered` means it gave
  an answer anyway. `rejected` isn't counted as declining: the model tried to answer.
- **cause:** for a question the corpus answers that isn't `correct`, `retrieval` when no expected
  section was among the passages sent to the model, and `generation` when one was but the model
  didn't cite it. The number of passages comes from `retrieval.limit` in the query configuration.
- **stale:** for a `stale-trap` question, `yes` when the answer cites one of the question's obsolete
  sections, even if it also cites a current one.
- **cited:** how many of the question's expected sections the answer cites. A `multi-section`
  question needs only one to count as correct, so this shows how much of the answer was covered.

The totals give the share of answerable questions cited correctly, and their misses by cause; stale
citations out of the traps; correct abstentions out of the `out-of-corpus` questions, and
abstentions out of the answerable ones, where declining is a miss; and rejected answers and errors
out of every question. A table by kind follows.

"Cited correctly" is not "answered correctly". A later step checks each answer's facts.

The model runs at temperature 0, but its answers can still vary a little between runs. Compare runs
question by question, with each run file's model, digest and commit beside it, rather than reading a
small change in a total as an effect.

## The kinds of question

| Kind | What it tests | Expected sections | Obsolete sections |
| --- | --- | --- | --- |
| `direct` | One topic, answered in one place | One or more | None |
| `multi-section` | An answer that needs more than one section | Two or more | None |
| `stale-trap` | A question an obsolete RFC also matches, though the current RFC answers it | In the current RFC | Each with `replaced_by` |
| `version-specific` | A question about an earlier version, such as TLS 1.2, so the obsolete RFC answers it | In the obsolete RFC, each with `replaced_by` | None |
| `out-of-corpus` | A question no RFC in the corpus answers | None | None |

`stale-trap` and `version-specific` pull in opposite directions. Ranking obsolete RFCs lower lowers
the trap rate, but pushed too far, it buries the answers to `version-specific` questions. Their
hit@k lines in the table by kind show both effects.

A `version-specific` question has to name the earlier version it asks about, such as "In TLS 1.2"
or "in RFC 7540". Without that, the current RFC is the right answer, and the question is a `direct`
question or a trap.

## Adding a question

Each question is a `[[question]]` table. The banner at the top of `eval/golden.toml` describes the
fields. For example:

```toml
[[question]]
id       = "http2-flow-control"
kind     = "stale-trap"
question = "How does HTTP/2 flow control stop a sender from overwhelming the receiver?"
expected = [
    { rfc = 9113, section = "5.2.1", quote = "HTTP/2 stream flow control aims to allow a variety of flow-control" },
]
obsolete = [
    { rfc = 7540, section = "5.2.1", replaced_by = 9113 },
]
```

1. **Word the question as a user would ask it.** Avoid copying the section's title or its wording.
   Search weights titles heavily, so copied words make retrieval look better than it is.
2. **Find the sections that answer it.** Search with the question, and read the first 20 results:

   ```
   rfc-search "How does HTTP/2 flow control stop a sender from overwhelming the receiver?" --limit 20
   ```

   Every section that answers the question goes in `expected`, because any one of them counts as a
   correct result. Leave out abstracts, which summarize a document rather than answer a question.
   A result matches only its exact section, so when a section and its subsections both answer,
   list each one.
3. **Quote each expected section.** Copy a phrase from one line of the RFC's text file, in the
   `rfcs/` folder of the data directory, so the reviewer can find it with `grep -F`. RFC text wraps at
   about 72 characters and often has two spaces after a full stop, so a quote that crosses a line
   won't be found.
4. **Check which RFC is current.** An RFC's text never says that a later RFC replaced it. Only the
   newer RFC records it, in its `Obsoletes:` header near the top:

   ```
   head -12 rfc9113.txt
   ```

   The header can run onto a second line, as RFC 9110's does, so read all of it. `replaced_by` is
   the newest RFC in the corpus whose header names the obsolete RFC, judged by the month and year
   on its first page rather than by its number. RFC 4366, for example, is named by RFC 5246, from
   August 2008, and by RFC 6066, from January 2011, so its `replaced_by` is 6066. When more than one
   RFC shares the latest month, `replaced_by` is the lowest-numbered: RFC 2616 is named by RFCs 7230
   to 7235, all from June 2014, so its `replaced_by` is 7230, and RFC 7230 is named by RFCs 9110 and
   9112, both from June 2022, so its `replaced_by` is 9110.

   `replaced_by` names an RFC that replaced the whole document, not the RFC a section moved to. RFC
   2616's status codes moved to RFC 7231, but their `replaced_by` is still 7230. Section numbers can
   change between an RFC and its replacement, as RFC 8446's section 4.6.1 became RFC 9846's section
   4.7.1, so check each one.
5. **Run the checks.** `pytest tests/scripts/test_score_retrieval.py` checks the file's structure,
   and that every RFC it names is in the corpus. `python scripts/score_retrieval.py` checks that
   every section is in the index, then scores it.

The repository owner reviews each new question, its labels and quotes, in the pull request that
adds it.

## When the corpus changes

When `corpus.toml` gains an RFC, check its `Obsoletes:` header against the golden set. An RFC that
obsoletes an expected section turns that question into a trap, or changes a `replaced_by`. After
rebuilding the index, run the script: a parser or chunking change that renumbers a section shows up
as a missing label, rather than as a silent miss.
