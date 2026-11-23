# Tasks

## 1. Listing an index's sections

- [x] 1.1 On the branch `add-golden-question-set`, add `list_sections(path) -> set[tuple[int, str]]` to `retrieval/keyword_index.py`, as in the design: read-only, opened like `search`, and raising `IndexUnavailableError` for a missing or unreadable index. Test that it returns each `(rfc_number, section_number)` once for an index built from fixture chunks, with two chunks from one section, and that a missing index raises with the message naming `rfc-ingest`. Verify with `pytest tests/retrieval/`

## 2. Golden set format and structure check

- [x] 2.1 Create `scripts/score_retrieval.py` with `load_golden_set(path)`, which reads the file with `tomllib` and checks every structure rule in the spec: unique IDs, the five known kinds, at least one expected section except for `out-of-corpus`, none for `out-of-corpus`, a non-empty quote on every expected section, obsolete sections only and always on `stale-trap`, a `replaced_by` on every obsolete section, a `replaced_by` on every expected section of a `version-specific` question and on no expected section of another kind, and string section numbers. Each failure raises an error naming the question's ID. Test each rule with a small invalid file written under `tmp_path`, and test that a valid file loads. Verify with `pytest tests/scripts/test_score_retrieval.py`
- [x] 2.2 Create `eval/golden.toml` with the banner comment from the design, describing the fields and the five kinds, and with one placeholder question of each of the five kinds so the structure test has something to read until 4.1 replaces them. Add a test that loads `eval/golden.toml` and checks that every RFC number in it is in the packaged `corpus.toml`, read with `paths.read_toml`. Verify that it passes, and that it fails naming the question and RFC when a placeholder's RFC is changed to one not in the corpus, then changed back

## 3. Scoring

- [x] 3.1 Add `score_question(question, results)` and `summarize(scores)` to the script, with a search depth of 20: rank by chunk position, exact section matching, the trap rule from the design, and out-of-corpus questions skipped and counted. Test with hand-made `SearchResult` lists for each spec scenario: rank 2, a subsection that doesn't match, not found in 20, the totals for ranks 1, 3 and not found, a trap caught, a trap caught with no expected result, a trap avoided, the totals by kind for `stale-trap` and `version-specific`, and two skipped questions. Verify with `pytest tests/scripts/test_score_retrieval.py`
- [x] 3.2 Add `main(argv)`, with `--data-dir`, `--golden` (default `eval/golden.toml` at the repository root) and `-v`. It resolves the index with `resolve_data_dir` and `INDEX_FILE`, runs the label check with `list_sections` before any search, prints the table, the totals and the totals by kind from the design, logs each question's top results at `-v`, and reports errors with `report_error`. Test against a small index built with `build_index`: exit 0 with the expected table, exit 0 when every question is not found, exit 1 naming the question and section for a label missing from the index with no scores printed, and exit 1 naming `rfc-ingest` when there's no index. Verify with `pytest tests/scripts/test_score_retrieval.py` and `pre-commit run --all-files`

## 4. The first questions

- [x] 4.1 Draft about 13 questions in `eval/golden.toml`, replacing the placeholders: 4 `direct`, 2 `multi-section`, 3 `stale-trap`, 2 `version-specific` and 2 `out-of-corpus`, spread across HTTP, TLS and TCP. Follow the drafting rules in the design: user wording, not the section's title; every answering section in the top 20 results added as expected; each quote copied from the RFC text in the data directory; each `replaced_by`, on a trap's obsolete section or a version-specific question's expected section, the newest RFC in the corpus whose own `Obsoletes:` header names the obsolete RFC; each version-specific question naming the earlier version it asks about. Verify that `pytest tests/scripts/test_score_retrieval.py` passes, that `python scripts/score_retrieval.py` against the local index passes the label check and prints a score for every question, and that `grep -F` finds each quote in its RFC's text file
- [x] 4.2 Ask the repository owner to review each question, its labels and quotes, and make any changes they ask for. Verify with the owner's acceptance, then run `python scripts/score_retrieval.py` again and keep its output for the pull request description

## 5. Documentation

- [x] 5.1 Write `docs/evaluation.md`, as in the design: what the golden set is for, its format and five kinds, including how `stale-trap` and `version-specific` differ, how to find and quote a section, how to check an `Obsoletes:` header and find the newest RFC that names the obsolete one, how to run the script and read its output, and that the traps need re-checking when `corpus.toml` changes. It links back to the README before its first section. Add it to the README's list of documents. Verify that the documented command runs as written, and that `pytest tests/test_docs.py` passes
- [x] 5.2 Add an entry under `[Unreleased]` in `CHANGELOG.md`, in the Added category: a golden question set with stale-citation traps and questions about earlier versions, and a script that scores keyword retrieval against it with hit@1, hit@5, mean reciprocal rank and trap rate. Verify with `pytest tests/test_docs.py`, which checks the changelog's structure

## 6. Integration

- [x] 6.1 Run `pytest`, with and without `RFC_QA_INSTALL_TESTS=1`, and `pre-commit run --all-files`. Verify that all pass, and that the built wheel contains no file from `eval/` or `scripts/`

## Workflow follow-up

- Open a pull request from `add-golden-question-set`, with the scoring output from 4.2 in its description. The `test`, `quality` and `secrets` checks must pass, and `archive-check` is expected to fail until the archive.
- The repository owner reviews the code and the questions while CI runs on the pull request. Any changes are made on this branch, in the active change, before the archive, and the checks must pass again.
- Archive the change on this branch as the last step, which creates the `retrieval-evaluation` spec, makes the change complete and turns `archive-check` green.
- The repository owner merges once CI still passes, so that the code, spec and archive land as one commit on `main`.
