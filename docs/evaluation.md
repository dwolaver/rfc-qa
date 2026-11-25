# Evaluation

[Back to README](../README.md)

The golden question set, [`eval/golden.toml`](../eval/golden.toml), is a fixed list of questions,
each labeled with the RFC sections that answer it. `scripts/score_retrieval.py` searches the index
with each question and reports where the first correct section ranks. Each change to retrieval runs
it before and after, so the change can show what it improved and what it made worse.

Scoring reads only the index. It needs no model, and gives the same result on every run against the
same index.

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
and counted, because a search always returns its closest matches. Scoring answers, including
whether the model says it can't answer, is a later step.

With about a dozen questions, one question moves hit@1 by almost 10 points, so read a change's
effect question by question as well as in the totals.

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
