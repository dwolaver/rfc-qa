# Tasks

## 1. The replacing RFC

- [x] 1.1 On the branch `expand-golden-question-set`, describe the rule from the design in `docs/evaluation.md`, in step 4 of "Adding a question": newest means the latest month and year on the first page, a tie goes to the lowest number, and the whole `Obsoletes:` header is read, including a wrapped second line. Use RFC 4366, RFC 2616 and RFC 7230 as examples, and note that `replaced_by` names the replacing set rather than the section's new home. Add one line for it to the banner of `eval/golden.toml`. Verify that `pytest tests/test_docs.py tests/scripts/test_score_retrieval.py` passes
- [x] 1.2 Add the labels the rule unblocks, from the table in the design: RFC 2616 §6.1.1 as obsolete in `http1-status-codes`, RFC 2616 §5.1.1 and §9 as obsolete in `http-valid-methods`, both with `replaced_by = 7230`, RFC 7230 §2.7.2 as obsolete in `http-encryption` with `replaced_by = 9110`, and `replaced_by = 7230` kept on `rfc2616-purpose`. Read each section to confirm that it matches its question. Verify that `python scripts/score_retrieval.py` passes the label check

## 2. The owner's questions

- [x] 2.1 For each question the repository owner adds to `eval/golden.toml`, apply the checks in the design: a one-line quote that `grep -F` finds in the RFC's text file, every answering section in the top 20 results from `rfc-search --limit 20`, a kind that fits, a `replaced_by` chosen by the spec's rule, a near-miss for `out-of-corpus`, and wording not copied from a section's title. Report each concern to the owner and make only the changes they accept. Verify each question with the owner's acceptance, and that `pytest tests/scripts/test_score_retrieval.py` passes
- [x] 2.2 When the owner says the set is complete, run `python scripts/score_retrieval.py` and keep its output, with the count of questions by kind, for the pull request description. Verify that the label check passes and that every question that isn't `out-of-corpus` has a score

## 3. Documentation

- [x] 3.1 Keep one entry for this change under `[Unreleased]` in `CHANGELOG.md`, in the Added category: more questions in the golden set, written for contributors. Don't list the questions. If the tie-break changes what contributors do, mention it in the entry. Verify with `pytest tests/test_docs.py`

## 4. Integration

- [x] 4.1 Run `pytest` and `pre-commit run --all-files`, and `openspec validate expand-golden-question-set --strict`. Verify that all pass

## Workflow follow-up

- Open a pull request from `expand-golden-question-set`, with the scores from 2.2 and the baseline from the first set of 13 questions on `main`, which no release includes yet, for comparison. The `test`, `quality` and `secrets` checks must pass, and `archive-check` is expected to fail until the archive.
- The repository owner reviews the questions and the rule while CI runs on the pull request. Any changes are made on this branch, in the active change, before the archive, and the checks must pass again.
- Archive the change on this branch as the last step, which adds the requirement to the `retrieval-evaluation` spec, makes the change complete and turns `archive-check` green.
- The repository owner merges once CI still passes, so that the questions, spec and archive land as one commit on `main`.
