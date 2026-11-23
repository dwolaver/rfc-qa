# Proposal

## Why

Nothing measures retrieval yet, and step 3 of the roadmap is about to change it: embeddings, hybrid
search and then status-aware ranking. Without a fixed set of questions and expected answers, step 3
can't show what it improved or what it broke. Earlier changes also left several questions for this
step to answer: whether porter stemming hurts, whether chunks need overlap, and how often an obsolete
RFC outranks the one that replaced it. Keyword search already does this. For "TLS 1.3 session
resumption", RFC 7525 ranks just behind RFC 9325, which obsoletes it, and RFC 8446 ranks just behind
RFC 9846.

This change is the first of step 2's four changes:

1. **This change:** the golden set's format, a first set of about 13 questions, and retrieval
   scoring.
2. Grow the set to about 40 to 60 questions, including questions from the repository owner.
3. Score answers from `query()`, with Ollama, run locally on demand.
4. Record the baseline at v0.2.0 in a committed report.

## What Changes

- **Golden set:** `eval/golden.toml`, in TOML like the configuration files, with one entry per
  question. An entry has an ID, a kind, the question, and the RFC sections that answer it. Labels
  name an RFC and a section, not a chunk ID, so they stay valid when the chunk size changes.
  - **Several answers:** any one of the expected sections counts as a hit, because the same answer
    can appear in more than one place.
  - **Traps:** a stale-citation trap also lists the obsolete sections that a good search ranks below
    the current ones.
  - **Evidence:** each label carries a short quote from the section, and each obsolete label names
    the RFC whose `Obsoletes:` header replaces it. The quotes make the owner's review quick, and the
    headers settle which RFC is current.
- **Kinds:** five, so that results can be read by kind:
  - `direct`: one section answers it.
  - `multi-section`: the answer needs more than one section.
  - `stale-trap`: an obsolete RFC also matches, but the current one answers it.
  - `version-specific`: the question asks about an earlier version, such as TLS 1.2 or RFC 2616, so
    the obsolete RFC is the right answer. Each expected section names the RFC that replaced it, so
    the reviewer can see that the old RFC is intended.
  - `out-of-corpus`: no RFC in the corpus answers it.

  `stale-trap` and `version-specific` pull in opposite directions. Step 3's status-aware ranking
  should improve the first without hurting the second, and keeping them apart shows whether it does.
- **First set:** about 13 questions, drafted from the RFC text and accepted by the repository owner
  in review: 4 direct, 2 multi-section, 3 stale-trap, 2 version-specific and 2 out-of-corpus.
- **Retrieval scoring:** `scripts/score_retrieval.py` runs keyword search for each question against
  a built index, and prints a result per question and totals: hit@1, hit@5, mean reciprocal rank and
  the trap rate, with hit@1 and hit@5 also given for each kind. It's a developer tool, not an
  installed command.
  - **Label check:** before scoring, it checks that every labeled section exists in the index, and
    stops with an error naming the question and section if one doesn't.
  - **Out-of-corpus questions:** search always returns something, so they are skipped and counted.
    Answer scoring in change 3 covers them.
- **Checks in CI:** a test checks the golden set's structure without the RFC text, which CI doesn't
  have. It checks unique IDs, known kinds, RFC numbers that are in the packaged corpus, and that
  every trap lists obsolete sections.
- **Guide:** `docs/evaluation.md` explains the format, how to add a question and how to run the
  scoring, so the owner can add questions in change 2. The README links to it.

## Capabilities

### New Capabilities

- `retrieval-evaluation`: the golden question set, its format and checks, and the scoring of keyword
  search against it.

### Modified Capabilities

None. The new read-only function for listing an index's sections, described in the design, changes
no existing requirement.

## Impact

- **New files:**
  - `eval/golden.toml`;
  - `scripts/score_retrieval.py`;
  - `docs/evaluation.md`;
  - tests in `tests/scripts/test_score_retrieval.py`.
- **Code:** `retrieval/keyword_index.py` gains a read-only function that lists the sections in an
  index, so that all SQL stays in that module.
- **Packaging:** none. `eval/` and `scripts/` aren't installed with the package.
- **Dependencies:** none. TOML is read with `tomllib`.
- **Documentation:** the README links to the new guide, and `CHANGELOG.md` gets an entry.
- **`ARCHITECTURE.md`:** it doesn't describe evaluation yet, and is regenerated at the next release.
