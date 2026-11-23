# Design

## Context

- **Search:** `keyword_index.search(path, query_text, limit)` returns `SearchResult(chunk, score)`,
  best first. Each `Chunk` carries `rfc_number` and `section_number`, so a result can be matched to
  a section label with no change to search. A section can produce several chunks, such as
  `rfc9325-s3.4-p0` and `rfc9325-s3.4-p1`, and both can appear in one result list.
- **Retrieval boundary:** a reviewed key decision keeps all SQL in `keyword_index.py`. No public
  function lists the sections in an index.
- **Passages the model sees:** `query.toml` sets `retrieval.limit = 5`.
- **Which RFC is current:** an RFC's text is never updated after publication, so RFC 8446 doesn't say
  that RFC 9846 obsoletes it. Only the newer RFC's `Obsoletes:` header records the link. The
  downloaded corpus has 36 such headers, and some run onto a second line, such as RFC 9110's and
  RFC 9293's. An RFC can be obsoleted more than once: RFC 5246 is obsoleted by RFC 8446, and both
  are obsoleted by RFC 9846, whose header names each of them.
- **Scripts:** `scripts/update_architecture.py` is the existing developer tool. It's checked by ruff
  and mypy in strict mode, is tested in `tests/scripts/` through `pytest.ini`'s `pythonpath = .`,
  and isn't installed. The shared command-line helpers are in `rfc_qa.cli` (`report_error`,
  `add_verbose_argument`, `configure_logging`) and `rfc_qa.paths` (`resolve_data_dir`, `INDEX_FILE`).
- **CI:** it has the repository but no RFC text or index, so anything that needs the corpus runs
  locally.

## Goals / Non-Goals

**Goals:**

- A format that the later changes in step 2 reuse without changing: growing the set, answer scoring
  and the baseline report.
- Retrieval numbers that are the same on every run against the same index.
- Labels that the repository owner can review quickly and trust.

**Non-Goals:**

- **No answer scoring:** `query()`, Ollama and out-of-corpus refusals are change 3.
- **No recorded baseline:** the output is printed. A committed report is change 4.
- **No CI scoring:** CI has no index, and building one there needs the network.
- **No changes to search:** stemming, weights and chunking stay as they are, so the first numbers
  describe the current system.
- **No status in `corpus.toml`:** the golden set records which sections are obsolete for its own
  questions, and status-aware retrieval is step 3.

## Decisions

### The golden set is TOML, with one table per question

`eval/golden.toml` opens with a banner comment that describes the format, as the configuration files
do. Each question is a `[[question]]` table:

```toml
[[question]]
id       = "tls13-resumption"
kind     = "stale-trap"
question = "How does a TLS 1.3 client resume an earlier session?"
expected = [
    { rfc = 9846, section = "2.2", quote = "PSKs can also be established in a previous connection and then used to establish a new connection" },
    { rfc = 9325, section = "3.4", quote = "Session resumption drastically reduces the number of full TLS handshakes" },
]
obsolete = [
    { rfc = 8446, section = "2.2", replaced_by = 9846 },
    { rfc = 7525, section = "3.4", replaced_by = 9325 },
]
```

- **`id`:** a short, stable slug, so a result can be followed across runs and changes.
- **`section`:** a string, because section numbers like `15.5.5` and `A.1` aren't numbers. It's
  written exactly as the index records it.
- **`quote`:** a field, not a comment, so the structure check can require it.
- **`replaced_by`:** the newest RFC in the corpus whose `Obsoletes:` header names the obsolete RFC.
  RFC 5246 is named by both 8446 and 9846, so its `replaced_by` is 9846. The reviewer can check it
  against that one header.

A `version-specific` question carries `replaced_by` on its expected sections instead, and has no
`obsolete` list:

```toml
[[question]]
id       = "tls12-client-hello"
kind     = "version-specific"
question = "In TLS 1.2, what does the client send in its first handshake message?"
expected = [
    { rfc = 5246, section = "7.4.1.2", replaced_by = 9846, quote = "..." },
]
```

Alternatives:

- **JSON or JSON Lines:** has no comments, so the banner couldn't explain the format, and the project
  moved its configuration away from JSON for that reason.
- **A Python module:** easy to load, but it's code rather than data, and it's harder for the owner to
  edit when adding questions.

### Questions about earlier versions have their own kind

A question that asks about an earlier version, such as TLS 1.2 or what RFC 2616 said, has the obsolete
RFC as its right answer. It's the reverse of a trap. Step 3's status-aware ranking will push obsolete
RFCs down to fix the traps, and pushed too far it buries these answers. Counted as `direct`, that
loss would hide in the totals while the trap rate improved. As `version-specific`, with hit@1 and
hit@5 reported for each kind, the two can be read side by side.

`replaced_by` is required on its expected sections, so the reviewer sees that the old RFC is
intended, and forbidden on the expected sections of other kinds, where an obsolete answer would be a
labeling mistake. The question has to name the earlier version it asks about. Without that, the
current RFC is the right answer, and the question is a `direct` one or a trap.

Alternative: file these questions as `direct`. It needs no new kind, but hides the trade-off step 3
has to make.

### A result matches a section only exactly

A result from section 15.5.5 doesn't match a label for 15.5. When a parent section and its
subsections all answer a question, the question lists each one as expected. Matching by prefix would
count a large parent section as correct for every subsection under it, so the scores would rise
without retrieval improving.

### Ranks count chunks, not sections

The rank is the position in the result list, and a section's second chunk takes a position too. So
hit@5 means "an expected section is among the 5 passages the model sees", which matches
`retrieval.limit`. Grouping results by section would report a better rank than the model actually
gets.

### Scoring searches 20 results deep

The search limit is 20. That's deep enough to give a rank, and a mean reciprocal rank above zero,
for sections just outside the top 5, which is where step 3 should first show improvement. At rank 20
the reciprocal rank is 0.05, so anything deeper adds little. The depth is a constant in the script
and appears in its output.

### The trap rate counts an obsolete section above every expected one

For a `stale-trap` question, the obsolete rank is the rank of the first result from any obsolete
section, and the expected rank is the rank of the first result from any expected section. The
question is caught by the trap when an obsolete rank exists and either it's smaller than the expected
rank or there is no expected rank. The rate is caught traps over all `stale-trap` questions scored.
A trap where neither appears in the top 20 isn't caught. Its miss already shows in hit@k and MRR.

### Scoring is a script, reusing the package's helpers

`scripts/score_retrieval.py` imports the installed `rfc_qa` package, as a developer's editable
install provides. It takes `--data-dir`, `--golden` (default `eval/golden.toml` at the repository
root) and `-v`. It finds the index with `resolve_data_dir` and `INDEX_FILE`, so it reads the same
index as the commands. It reports errors with `report_error`, so a missing index gives the same
one-line message naming `rfc-ingest` as `rfc-search` does.

The script is split into functions that can be tested without an index:

- `load_golden_set(path)`: reads and checks the structure, and raises with the question's ID.
- `score_question(question, results)`: takes a question and its search results, and returns the
  ranks.
- `summarize(scores)`: returns the totals.

The tests check these with hand-made results. One test builds a small index from fixture chunks with
`build_index`, then runs `main` against it.

Alternative: an installed command such as `rfc-eval`. Users never run it, and it would have to ship
the golden set with the package.

### `keyword_index` gains `list_sections`

`list_sections(path) -> set[tuple[int, str]]` returns every `(rfc_number, section_number)` that has
a chunk in the index. It's read-only and opens the file as `search` does, raising
`IndexUnavailableError` the same way. The script uses it for the label check, before any search.

Alternatives:

- **SQL in the script:** this would break the reviewed decision that all SQL is in
  `keyword_index.py`.
- **Parsing the RFC text with the ingestion code:** this would check the files on disk rather than
  the index being scored, and the two differ after a corpus change until `rfc-ingest` runs again.

### The structure check runs on the real file in the test suite

A test in `tests/scripts/test_score_retrieval.py` calls `load_golden_set` on `eval/golden.toml`, and
checks each RFC number against the packaged `corpus.toml`, read with `paths.read_toml`. It needs no
index, so it runs in CI. Further tests feed `load_golden_set` small invalid files for each rule in
the spec.

### Output is a plain table

```
Retrieval scores for 11 questions, from index.db (search depth 20)

id                    kind           rank  trap
tls13-resumption      stale-trap        1  no
http-404-meaning      direct            1  -
...
tcp-keepalive-idle    multi-section     -  -

hit@1  7/11 (0.64)    hit@5 10/11 (0.91)    MRR 0.74    trap rate 1/3 (0.33)

kind                hit@1          hit@5
direct              3/4 (0.75)     4/4 (1.00)
multi-section       1/2 (0.50)     2/2 (1.00)
stale-trap          2/3 (0.67)     3/3 (1.00)
version-specific    1/2 (0.50)     1/2 (0.50)

Skipped 2 out-of-corpus questions.
```

A `-` in the rank column means not found. Logging (`-v`) shows the top results for each question,
for investigating a miss. Change 4 can add a machine-readable output when it records the baseline.

### How the questions are drafted

- **Coverage:** each question is drafted from the RFC text, spread across the HTTP, TLS and TCP
  families.
- **Wording:** questions are phrased the way a user would ask, not copied from the section's title
  or text. Search weights titles heavily, so copied words would make retrieval look better than it
  is.
- **Completeness:** for each question, the top 20 results are read, and any other section that also
  answers it is added as expected. The new section's quote gets checked too.
- **No abstracts:** an abstract is never labeled, as expected or obsolete, even when it states the
  answer. It summarizes a document rather than answering a question, so leaving it out keeps the
  scores strict.
- **Replacements:** for each trap and each `version-specific` question, `replaced_by` is the newest
  RFC in the corpus whose own `Obsoletes:` header names the obsolete RFC. An RFC that only obsoletes
  a later replacement doesn't count.
- **One replacement:** an RFC obsoleted directly by several RFCs published together, such as RFC 2616
  by RFCs 7230 to 7235, has no single newest replacement, so it isn't labeled until the format has a
  rule for that case.
- **Earlier versions:** each `version-specific` question names the version or RFC it asks about. Its
  expected sections are in the obsolete RFC only. A section of the current RFC that describes the
  earlier version, such as RFC 9113's section 5.3.1 on RFC 7540's priority scheme, isn't expected,
  because the question is answered when the obsolete RFC is retrieved.
- **Out-of-corpus:** these are questions on the same topics that no RFC in the corpus answers, such as
  a protocol that isn't in the manifest. They're realistic misses rather than unrelated questions.

The repository owner reviews each question, its labels and quotes in the pull request, and accepts
or changes them before the change is archived.

### A guide for adding questions

`docs/evaluation.md` covers the format, the five kinds and how `stale-trap` and `version-specific` differ, how to find and quote a section, how to check
an `Obsoletes:` header, and how to run the script. It links back to the README, and the README links
to it, as the documentation spec requires.

## Risks / Trade-offs

- [About 13 questions give noisy totals: one question moves hit@1 by about 10 points, and a kind with
  two questions by 50] → The output is
  per question, so a change can be read question by question. Change 2 grows the set to 40 to 60.
- [Labels miss a section that also answers a question, so a correct result scores as a miss] → The
  drafting reads the top 20 results for other answering sections, and the owner reviews them. A miss
  found later is fixed in the golden set, and the fix is noted in its pull request.
- [Questions drafted while looking at the RFC text share its words] → They're phrased the way a user
  would ask, and the owner's own questions in change 2 balance the set.
- [The corpus or the parser changes section numbers, so labels point at nothing] → The label check
  stops scoring and names each missing section, so nothing is silently scored as a miss.
- [A newer RFC joins the corpus and obsoletes an expected section] → The trap labels, and the
  `replaced_by` of `version-specific` questions, then need updating. `docs/evaluation.md` says to re-check `Obsoletes:` headers when `corpus.toml` changes.
- [The code-quality spec names "the release scripts", and the scoring script isn't one] → The lint
  and type checks already cover all of `scripts/`, so the new script is checked the same way. The
  wording can be widened by a later change to that spec.
