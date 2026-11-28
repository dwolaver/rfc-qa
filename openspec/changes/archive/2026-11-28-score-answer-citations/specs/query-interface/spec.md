# Spec Delta

## MODIFIED Requirements

### Requirement: Accept a query through the programmatic API

The service SHALL expose a programmatic entry point that accepts a single user query and
returns a structured response object describing the outcome. The entry point SHALL return a
response rather than raising for expected failure conditions: an invalid query string, a
configuration error, an unavailable index and an unavailable or misbehaving model. It SHALL
raise only for caller bugs, such as a query that isn't a string.

#### Scenario: Query returns a structured response

- **WHEN** the entry point is called with a string
- **THEN** it returns a response object carrying a success flag and, depending on the outcome, an answer, whether an answer was found, whether the model's answer was rejected, citations, timings, an integer enumeration error code, and a human-readable error string

#### Scenario: Answered query

- **WHEN** a valid query is answered from the indexed RFCs
- **THEN** the response has `success` true, `found` true, the answer, and at least one citation

#### Scenario: Rejected answer in the response

- **WHEN** the model's answer to a valid query is rejected
- **THEN** the response has `success` true, `found` false, the standard not-found message, no citations, and `answer_rejected` true

#### Scenario: Rejected answer defaults to false

- **WHEN** a response is not a rejected answer, including a failure response
- **THEN** its `answer_rejected` is false

#### Scenario: Error codes unchanged

- **WHEN** a query fails because of the configuration, the index or the model
- **THEN** the response carries `CONFIG_INVALID`, `INDEX_UNAVAILABLE`, `MODEL_UNAVAILABLE` or `MODEL_INVALID_RESPONSE` respectively, with the error's message as its error string
