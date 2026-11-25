# Proposal

## Why

The first golden set has 13 questions. With that few, one question moves hit@1 by almost 10 points,
and most kinds have two or three questions, so step 3 can't read a change by kind yet. This change
is the second of step 2's four changes: it grows the set with the repository owner's own questions.

The owner's questions also reached a case the format left open. RFC 2616 is obsoleted by six RFCs,
7230 to 7235, all published in June 2014, so "the newest RFC whose `Obsoletes:` header names it"
is a tie. RFC 7230 is obsoleted the same way, by RFCs 9110 and 9112. Three questions are waiting on
the rule: one names RFC 2616, and two traps leave RFC 2616's matching sections unlabeled until it's
decided.

## What Changes

- **More questions:** the repository owner adds questions to `eval/golden.toml`, and each one is
  checked before it's accepted. The checks are the drafting rules: a quote from one line of the
  section, every answering section in the top 20 results, a kind that fits, and a `replaced_by` from
  the `Obsoletes:` headers. The set grows toward 40, and the owner decides when it's complete.
- **The replacing RFC, defined:** `replaced_by` is the RFC with the latest publication date, the
  month and year on its first page, among the RFCs in the corpus that obsolete the RFC. When more than
  one shares that month, it's the lowest-numbered of them. RFC 2616's sections are replaced by RFC
  7230, and RFC 7230's by RFC 9110. The guide and the golden set's banner describe the rule.
- **Labels the rule unblocks:** RFC 2616's sections that also match the two HTTP/1.1 traps are added
  as obsolete, and so is RFC 7230's `https` section in the HTTP encryption trap.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `retrieval-evaluation`: adds a requirement that defines the replacing RFC: the latest publication
  date, with the lowest number breaking a tie.

## Impact

- **Data:** `eval/golden.toml` gains questions and labels, and its banner describes the tie-break.
- **Code:** none. `replaced_by` isn't used in scoring, and the structure check doesn't read
  `Obsoletes:` headers, so the rule is applied when drafting and checked in review.
- **Documentation:** `docs/evaluation.md` describes the tie-break, and `CHANGELOG.md` gets an entry.
- **Scores:** the totals change with each question, so the pull request gives the scores before and
  after.
