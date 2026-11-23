# retrieval-evaluation Specification

## Purpose

Measures how well retrieval finds the RFC sections that answer a fixed set of questions, including
questions where an obsolete RFC competes with the one that replaced it, so that each change to
retrieval can be compared with the last.

## Requirements

### Requirement: Keep a golden question set

The repository SHALL hold a golden question set in `eval/golden.toml`, as a TOML document with one
entry per question. Each entry SHALL have an ID that is unique in the set, a kind, the question text,
and its expected sections. The kind SHALL be one of `direct`, `multi-section`, `stale-trap`,
`version-specific` or `out-of-corpus`. The set SHALL NOT be installed with the package.

#### Scenario: Entry fields

- **WHEN** the golden set is read
- **THEN** every entry has an ID, a kind, a question and its expected sections, and no two entries share an ID

#### Scenario: Not installed

- **WHEN** the project is built as a wheel
- **THEN** the wheel doesn't contain the golden set

### Requirement: Label answers by RFC section

Each expected section SHALL name an RFC number and a section number, not a chunk. A question that
isn't `out-of-corpus` SHALL have at least one expected section, and any one of them SHALL count as a
correct result. An `out-of-corpus` question SHALL have none. Each expected section SHALL carry a short
quote from that section, as evidence for review.

#### Scenario: Several correct sections

- **WHEN** a question lists RFC 9325 section 3.4 and RFC 9846 section 2.2 as expected
- **THEN** a result from either section counts as correct

#### Scenario: Labels survive a new chunk size

- **WHEN** the index is rebuilt with a different chunk size, so the chunk IDs change
- **THEN** every label still names the same section, and none needs editing

#### Scenario: Out-of-corpus question with a label

- **WHEN** an `out-of-corpus` question lists an expected section
- **THEN** the structure check fails and names the question

### Requirement: Label the obsolete sections of a trap

A `stale-trap` question SHALL list at least one obsolete section: a section of an RFC that another
RFC in the corpus obsoletes, which also matches the question. Each obsolete section SHALL name the
RFC whose `Obsoletes:` header replaces it. Questions of other kinds SHALL NOT list obsolete sections.

#### Scenario: Trap with its obsolete sections

- **WHEN** a `stale-trap` question lists RFC 7525 section 3.4 as obsolete, replaced by RFC 9325
- **THEN** the structure check accepts it

#### Scenario: Trap without obsolete sections

- **WHEN** a `stale-trap` question lists no obsolete section
- **THEN** the structure check fails and names the question

### Requirement: Label the expected sections of a version-specific question

A `version-specific` question asks about an earlier version, so its expected sections are in obsolete
RFCs. Each of its expected sections SHALL name the RFC whose `Obsoletes:` header replaces that RFC.
Expected sections of other kinds SHALL NOT name a replacing RFC, and a `version-specific` question
SHALL NOT list obsolete sections.

#### Scenario: Question about TLS 1.2

- **WHEN** a `version-specific` question expects RFC 5246 section 7.4.1.2, replaced by RFC 9846
- **THEN** the structure check accepts it

#### Scenario: Version-specific section without its replacement

- **WHEN** an expected section of a `version-specific` question doesn't name the RFC that replaced it
- **THEN** the structure check fails and names the question

#### Scenario: Replacement on another kind

- **WHEN** an expected section of a `direct` question names a replacing RFC
- **THEN** the structure check fails and names the question

### Requirement: Check the golden set's structure in the automated checks

The test suite SHALL check the golden set's structure without the RFC text or a built index: unique
IDs, known kinds, the expected and obsolete sections each kind allows, the replacing RFC each kind
requires or forbids, a quote on every expected section, and RFC numbers that are all in the packaged
corpus manifest.

#### Scenario: RFC outside the corpus

- **WHEN** a label names an RFC that isn't in the packaged corpus manifest
- **THEN** the structure check fails and names the question and the RFC

#### Scenario: Valid set

- **WHEN** the golden set has a valid structure
- **THEN** the structure check passes without network access, RFC text or an index

### Requirement: Check labels against the index before scoring

Before it scores, retrieval scoring SHALL check that every expected and obsolete section has at least
one chunk in the index. If any doesn't, it SHALL score nothing, report each missing section with its
question, and exit with status 1.

#### Scenario: Section missing from the index

- **WHEN** a label names RFC 9110 section 99.9, which has no chunk in the index
- **THEN** retrieval scoring reports the question and the section, scores nothing, and exits with status 1

### Requirement: Score retrieval for each question

Retrieval scoring SHALL search the index with each question that isn't `out-of-corpus`, take the
first 20 results, and find the rank of the first result from an expected section. A result SHALL
match a section only when its RFC number and section number are both the same. It SHALL report, for
each question, its ID, kind and rank, or that no expected section was found.

#### Scenario: Correct section ranked second

- **WHEN** the first result is from another section and the second is from an expected section
- **THEN** the question's rank is 2

#### Scenario: Subsection of an expected section

- **WHEN** the expected section is RFC 9110 section 15.5 and a result is from section 15.5.5
- **THEN** that result doesn't match the expected section

#### Scenario: Not found in the first 20

- **WHEN** no result among the first 20 is from an expected section
- **THEN** the question is reported as not found, with no rank

### Requirement: Report the retrieval totals

Retrieval scoring SHALL report, over the questions it scored: hit@1 and hit@5, the share whose rank
is at most 1 or at most 5; the mean reciprocal rank, the mean of one over each rank, counting a
question not found as zero; and the trap rate, the share of `stale-trap` questions where a result
from an obsolete section ranks above every result from an expected section. It SHALL also report
hit@1 and hit@5 for each kind it scored.

#### Scenario: Totals

- **WHEN** three questions are scored with ranks 1, 3 and not found
- **THEN** hit@1 is 1 of 3, hit@5 is 2 of 3, and the mean reciprocal rank is (1 + 1/3 + 0) / 3

#### Scenario: Trap caught

- **WHEN** a `stale-trap` question's first result from an obsolete section ranks 1 and its first result from an expected section ranks 2
- **THEN** that question counts towards the trap rate

#### Scenario: Totals by kind

- **WHEN** two `stale-trap` questions rank 1 and 2, and two `version-specific` questions rank 1 and not found
- **THEN** the `stale-trap` line shows hit@1 1 of 2 and hit@5 2 of 2, and the `version-specific` line shows hit@1 1 of 2 and hit@5 1 of 2

#### Scenario: Trap avoided

- **WHEN** a `stale-trap` question's first result from an expected section ranks above every result from an obsolete section
- **THEN** that question doesn't count towards the trap rate

### Requirement: Skip out-of-corpus questions in retrieval scoring

Retrieval scoring SHALL NOT search with `out-of-corpus` questions, because a search always returns
its best matches. It SHALL report how many it skipped, and leave them out of every total.

#### Scenario: Skipped questions counted

- **WHEN** the golden set has two `out-of-corpus` questions
- **THEN** retrieval scoring reports that it skipped 2 questions, and its totals don't include them

### Requirement: Run retrieval scoring against a local index

Retrieval scoring SHALL read the index in the data directory, chosen as the commands choose it: a
`--data-dir` flag, then the `RFC_QA_DATA_DIR` environment variable, then the default. It SHALL NOT
need a model, Ollama or network access. It SHALL exit with status 0 once it has scored, whatever the
results, and with status 1 when the index can't be read.

#### Scenario: No index

- **WHEN** retrieval scoring runs and the data directory has no index
- **THEN** it reports that the index is missing, names `rfc-ingest` as the way to build it, and exits with status 1

#### Scenario: Low scores

- **WHEN** retrieval scoring completes and every question is not found
- **THEN** it prints the results and exits with status 0
