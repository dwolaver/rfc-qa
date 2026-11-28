# Spec Delta

## Purpose

Measures the answers the service returns for the golden question set: whether they cite the
sections that answer each question, avoid obsolete ones, and decline questions the corpus doesn't
answer. Each run is saved so that it can be compared and graded later.

## ADDED Requirements

### Requirement: Score each golden question through the query interface

Answer scoring SHALL ask every question in the golden set through the service's query entry point,
with the configuration and data directory it would use for a user. It SHALL check the golden set and
its labels against the index first, as retrieval scoring does, and score nothing if either check
fails.

#### Scenario: Every question is asked

- **WHEN** answer scoring runs against a valid golden set and index
- **THEN** each question in the set, including `out-of-corpus` questions, is answered through the query entry point once

#### Scenario: Missing label stops the run

- **WHEN** an expected or obsolete section has no chunk in the index
- **THEN** answer scoring reports each missing section with its question, asks no question, and exits with status 1

### Requirement: Score an answerable question by its citations

For a question that isn't `out-of-corpus`, answer scoring SHALL give the outcome `correct` when a
citation matches an expected section, `wrong-cite` when the answer cites none, `abstained` when the
response is not found, `rejected` when the model's answer was rejected, and `error` when the query
failed. A citation SHALL match a section only when its RFC number and section number are the same.

#### Scenario: Correct citation

- **WHEN** the answer cites a section listed in the question's expected sections
- **THEN** the outcome is `correct`

#### Scenario: Answer that cites no expected section

- **WHEN** the response is found but none of its citations is an expected section
- **THEN** the outcome is `wrong-cite`

#### Scenario: Rejected answer on an answerable question

- **WHEN** the response is not found and marks the model's answer as rejected
- **THEN** the outcome is `rejected`, not `abstained`

### Requirement: Score an out-of-corpus question by whether it answered

For an `out-of-corpus` question, answer scoring SHALL give the outcome `abstained` when the response
is not found and the answer wasn't rejected, `answered` when the response is found, `rejected` when
the model's answer was rejected, and `error` when the query failed. Only `abstained` SHALL count as
correct.

#### Scenario: Correct abstention

- **WHEN** an `out-of-corpus` question's response is not found and its answer wasn't rejected
- **THEN** the outcome is `abstained`, which counts as correct

#### Scenario: Rejected answer is not an abstention

- **WHEN** an `out-of-corpus` question's response is not found and marks the model's answer as rejected
- **THEN** the outcome is `rejected`, which doesn't count as correct

### Requirement: Attribute each miss to retrieval or generation

For an answerable question whose outcome isn't `correct`, answer scoring SHALL give the cause
`retrieval` when no expected section ranked within the configured retrieval limit in a search of the
index with the question, and `generation` when one did. It SHALL read the limit from the query
configuration rather than assume it.

#### Scenario: Correct section never reached the model

- **WHEN** an answerable question misses and its first expected section ranks below the retrieval limit, or not at all in the first 20 results
- **THEN** its cause is `retrieval`

#### Scenario: Correct section reached the model

- **WHEN** an answerable question misses and an expected section ranks within the retrieval limit
- **THEN** its cause is `generation`

### Requirement: Flag stale citations on traps

For a `stale-trap` question, answer scoring SHALL mark a stale citation when the answer cites any of
the question's obsolete sections, whatever the question's outcome.

#### Scenario: Trap answer cites the obsolete RFC

- **WHEN** a `stale-trap` answer cites one of the question's obsolete sections
- **THEN** the question is marked as a stale citation, even if it also cites an expected section

### Requirement: Report the answer scores

Answer scoring SHALL report, for each question, its ID, kind, retrieval rank, outcome, cause, stale
citation and the number of its expected sections it cited out of those listed. It SHALL then report
the share of answerable questions `correct`, overall and by kind; the misses by cause; stale
citations out of `stale-trap` questions; correct abstentions out of `out-of-corpus` questions;
abstentions out of answerable questions; and rejected answers and errors out of all questions.

#### Scenario: Report after a run

- **WHEN** answer scoring finishes every question
- **THEN** it prints the per-question table followed by the totals and the totals by kind

#### Scenario: Cited count for a multi-section question

- **WHEN** a question lists three expected sections and its answer cites two of them
- **THEN** its row shows the cited count as `2/3`

### Requirement: Save each run

Answer scoring SHALL write each run to a JSON Lines file, one line at a time as each question
finishes. The first line SHALL record the model and its digest, the Ollama address, the retrieval
limit, the commit and whether the working tree had changes, the golden set and the start time. Each
later line SHALL record one question's ID, kind, retrieval rank, full response and scores.

#### Scenario: Default run file

- **WHEN** answer scoring runs without `--output`
- **THEN** it writes the run to a new timestamped file under `eval-runs` in the data directory, and prints its path

#### Scenario: Named run file

- **WHEN** answer scoring runs with `--output FILE`
- **THEN** it writes the run to `FILE`

#### Scenario: Commit unknown

- **WHEN** the commit can't be read because `git` isn't available or the directory isn't a repository
- **THEN** the run records the commit as unknown and goes on

### Requirement: Run answer scoring locally against the model

Answer scoring SHALL choose the index's data directory as the commands do, and the query
configuration as the query entry point does. Before the first question it SHALL confirm that Ollama
is reachable and has the configured model, and exit with status 1 if not. It SHALL NOT be part of the
automated checks, and SHALL exit with status 0 once it has scored every question, whatever the
results.

#### Scenario: Model not available

- **WHEN** Ollama can't be reached, or doesn't have the configured model, when answer scoring starts
- **THEN** it reports the problem, asks no question, and exits with status 1

#### Scenario: Scored run

- **WHEN** every question has been asked and scored
- **THEN** answer scoring exits with status 0, however many questions it got wrong

### Requirement: Stop a run that can't continue

During a run, a query that fails because the model's output was invalid SHALL be recorded as an
`error` outcome, and the run SHALL go on. A query that fails because the model, the index or the
configuration became unavailable SHALL stop the run with status 1, keeping the questions already
saved.

#### Scenario: One invalid model response

- **WHEN** one query fails with `MODEL_INVALID_RESPONSE`
- **THEN** that question's outcome is `error`, and the remaining questions are asked

#### Scenario: Ollama stops during a run

- **WHEN** a query fails with `MODEL_UNAVAILABLE` partway through a run
- **THEN** answer scoring stops, exits with status 1, and the run file keeps every question answered before it
