# Spec Delta

## ADDED Requirements

### Requirement: Choose the replacing RFC

The RFC that a label names as replacing an obsolete RFC SHALL be chosen from the RFCs in the corpus
whose `Obsoletes:` header names the obsolete RFC. Of those, the label SHALL name the one with the
latest publication date, as given by the month and year on its first page. When more than one share
that latest month, the label SHALL name the lowest-numbered of them. An RFC that obsoletes only a
later replacement of the obsolete RFC SHALL NOT be named.

#### Scenario: Replaced more than once

- **WHEN** RFC 5246 is named in the `Obsoletes:` headers of RFC 8446 and of RFC 9846, which is newer
- **THEN** a label on an RFC 5246 section names RFC 9846

#### Scenario: Several replacements, one newest

- **WHEN** RFC 4366 is named in the `Obsoletes:` headers of RFC 5246, published in August 2008, and
  of RFC 6066, published in January 2011
- **THEN** a label on an RFC 4366 section names RFC 6066

#### Scenario: Replaced by RFCs published together

- **WHEN** RFC 2616 is named in the `Obsoletes:` headers of RFCs 7230 to 7235, all published in June
  2014
- **THEN** a label on an RFC 2616 section names RFC 7230

#### Scenario: Obsoleted through a later replacement

- **WHEN** RFC 2616 is named only by RFCs 7230 to 7235, and RFC 9110 obsoletes RFC 7231
- **THEN** a label on an RFC 2616 section doesn't name RFC 9110
