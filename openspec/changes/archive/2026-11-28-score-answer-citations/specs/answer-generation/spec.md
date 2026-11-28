# Spec Delta

## ADDED Requirements

### Requirement: Mark a rejected answer

When the model reports that it found an answer, but the service returns not found because no
citation names a passage that was sent or the answer is blank, the service SHALL mark the answer as
rejected. Every other outcome, including the model reporting no answer, SHALL NOT be marked as
rejected. A rejected answer SHALL otherwise be reported exactly as not found.

#### Scenario: Answer with no valid citations

- **WHEN** the model reports an answer but none of its citations are valid
- **THEN** the response is not found, with the standard not-found message and no citations, and marks the answer as rejected

#### Scenario: Blank answer

- **WHEN** the model reports that it found an answer, with a valid citation, but the answer is empty or only whitespace
- **THEN** the response is not found and marks the answer as rejected

#### Scenario: Model reports no answer

- **WHEN** the model reports that the passages don't answer the question
- **THEN** the response is not found and doesn't mark the answer as rejected

#### Scenario: Answered question

- **WHEN** the model's answer is returned with at least one valid citation
- **THEN** the response doesn't mark the answer as rejected
