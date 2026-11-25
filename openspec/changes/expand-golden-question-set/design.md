# Design

## Context

The `retrieval-evaluation` spec says each obsolete label names "the RFC whose `Obsoletes:` header
replaces it", and the guide and the golden set's banner say that's the newest such RFC in the
corpus. Neither says what "newest" is measured by, and neither covers a tie. The corpus has two
ties:

- RFC 2616 is named by RFCs 7230, 7231, 7232, 7233, 7234 and 7235, all published in June 2014.
- RFC 7230 is named by RFCs 9110 and 9112, both published in June 2022.

`replaced_by` isn't used in scoring. It shows the reviewer that a label is meant to be obsolete, and
it records which RFC took over, which step 3's status-aware ranking may use. The structure check
can't verify it, because CI has no RFC text, so the rule is applied when drafting and checked in
review.

## Goals / Non-Goals

**Goals:**

- A rule that gives one `replaced_by` for every obsolete RFC in the corpus, that anyone can apply
  from the `Obsoletes:` headers alone.

**Non-Goals:**

- Checking `replaced_by` against the headers automatically. That needs the RFC text, so it would run
  in the scoring script rather than CI, and is a separate change if it's wanted.
- Recording which replacement covers a section's subject. Step 3 can add that if its ranking needs
  it.

## Decisions

### Newest means the latest publication date

The replacing RFC is the one with the latest publication date among the RFCs whose `Obsoletes:`
header names the obsolete RFC. The date is the month and year on the RFC's first page, not its
number, because numbers don't always follow dates: RFC 9147 is dated April 2022 and RFC 9110 June
2022. Only the RFCs in the latest month are candidates, so an older replacement, such as RFC 5246
for RFC 4366, is never named when a newer one, RFC 6066, exists.

An `Obsoletes:` header can wrap onto a second line, as RFC 9110's and RFC 9293's do, so checking a
label means reading the whole header, not only its first line.

### A tie goes to the lowest-numbered RFC

When more than one RFC shares the latest month, `replaced_by` is the lowest number among them:
RFC 7230 for RFC 2616, and RFC 9110 for RFC 7230. A month is as precise as RFC headers are, so RFCs
published together always tie.

The rule needs no judgment, so two people labeling the same section agree, and a reviewer checks it
from the headers as before. RFCs published as a set are numbered in the order the set is read, so
the lowest-numbered one is usually its overview or architecture document, as RFC 7230 is for HTTP/1.1
and RFC 9110 is for HTTP.

Alternatives:

- **The replacement that covers the section's subject,** such as RFC 7231 for RFC 2616's status
  codes. It's more precise, but every label becomes a judgment call, and some sections, like RFC
  2616's introduction, are split across several replacements.
- **A list of every replacing RFC.** It's the most faithful, but it changes the format and the
  structure check, for a field nothing reads yet. It's worth revisiting in the change that checks
  `replaced_by` against the headers automatically: a list of every RFC whose `Obsoletes:` header
  names the obsolete RFC needs no date or tie-break, so that check would only compare the list with
  the headers.

### Labels on RFC 2616 and RFC 7230 are added now

Three questions are waiting on the rule. Their labels are added in this change, checked like any
other label:

| Question | Label | `replaced_by` |
| --- | --- | --- |
| `http1-status-codes` | RFC 2616 §6.1.1, obsolete | 7230 |
| `http-valid-methods` | RFC 2616 §5.1.1 and §9, obsolete | 7230 |
| `http-encryption` | RFC 7230 §2.7.2, obsolete | 9110 |
| `rfc2616-purpose` | RFC 2616 §1.1, expected | 7230 |

### Each new question is checked before it's accepted

The owner writes each question, and each one gets the same checks as the first set's drafting rules,
before it's accepted:

- Each quote is on one line of the RFC text file, so `grep -F` finds it.
- Every section in the top 20 results that answers the question is expected.
- The kind fits. A question that names an RFC is `version-specific` only if that RFC is obsolete and
  answers it. When the current RFC answers it and an obsolete one also matches, it's a `stale-trap`.
- `out-of-corpus` questions are near-misses on the corpus's topics, not unrelated questions.
- The wording isn't copied from the section's title.

## Risks / Trade-offs

- [The lowest-numbered RFC isn't the one that covers the section, as with RFC 2616's status codes
  and RFC 7230 rather than RFC 7231] → `replaced_by` records the replacing set, not the section's new
  home. The guide says so, and step 3 can add a field for the new home if its ranking needs one.
- [Most of the owner's questions turn into traps, because labeling the current RFC often finds an
  obsolete one that also matches] → The pull request reports the count by kind, and the trap rate is
  read next to the stale-trap row's hit@5, since an uncaught trap is often a miss rather than a
  success.
- [A wrong `replaced_by` passes the structure check, as RFC 9113 on an RFC 9846 section did while
  drafting] → Review checks each one against the headers. An automatic check is a non-goal here.
