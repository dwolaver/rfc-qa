"""Score keyword retrieval against the golden question set.

Usage: python scripts/score_retrieval.py [--data-dir DIR] [--golden FILE] [-v]

The golden set, eval/golden.toml, lists questions and the RFC sections that answer them. This script
checks the set's structure, checks that every labeled section is in the index, then searches the
index with each question and reports where the first expected section ranks. It needs a built index
but no model. docs/evaluation.md describes the format and how to read the output.
"""

import argparse
import logging
import os
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from rfc_qa import paths
from rfc_qa.cli import add_verbose_argument, configure_logging, report_error
from rfc_qa.errors import RfcQaError
from rfc_qa.retrieval.keyword_index import SearchResult, list_sections, search

# Under the package's logger, so that -v shows these records as it does the commands'.
logger = logging.getLogger("rfc_qa.score_retrieval")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_GOLDEN = os.path.join(ROOT, "eval", "golden.toml")

DIRECT = "direct"
MULTI_SECTION = "multi-section"
STALE_TRAP = "stale-trap"
VERSION_SPECIFIC = "version-specific"
OUT_OF_CORPUS = "out-of-corpus"
KINDS = (DIRECT, MULTI_SECTION, STALE_TRAP, VERSION_SPECIFIC, OUT_OF_CORPUS)

# How many results each question's search returns. A rank deeper than this is reported as not found.
SEARCH_DEPTH = 20
# hit@k is reported for these k. 5 is the number of passages a query sends the model.
HIT_KS = (1, 5)
# How many of each question's results -v shows.
_LOGGED_RESULTS = 5

_QUESTION_KEYS = {"id", "kind", "question", "expected", "obsolete"}
_EXPECTED_KEYS = {"rfc", "section", "quote", "replaced_by"}
_OBSOLETE_KEYS = {"rfc", "section", "replaced_by"}


class GoldenSetError(Exception):
    """A problem with the golden set or its labels, ready to show."""


@dataclass(frozen=True)
class Label:
    """An RFC section named by a question. ``replaced_by`` is the newest RFC that obsoletes ``rfc``."""

    rfc: int
    section: str
    quote: str | None = None
    replaced_by: int | None = None


@dataclass(frozen=True)
class Question:
    id: str
    kind: str
    question: str
    expected: tuple[Label, ...]
    obsolete: tuple[Label, ...]


def _is_rfc_number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _parse_label(raw: object, where: str, allowed: set[str]) -> Label:
    if not isinstance(raw, dict):
        raise GoldenSetError(f'{where} must be a table, such as {{ rfc = 9110, section = "15.5.5" }}.')
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise GoldenSetError(f"{where} has unknown fields: {', '.join(unknown)}.")
    rfc = raw.get("rfc")
    if not _is_rfc_number(rfc):
        raise GoldenSetError(f"{where} needs an RFC number in 'rfc'.")
    section = raw.get("section")
    if not isinstance(section, str) or not section.strip():
        raise GoldenSetError(f"{where} needs a section number in 'section', as a string such as \"3.4\".")
    quote = raw.get("quote")
    if quote is not None and (not isinstance(quote, str) or not quote.strip()):
        raise GoldenSetError(f"{where} has an empty 'quote'.")
    replaced_by = raw.get("replaced_by")
    if replaced_by is not None:
        if not _is_rfc_number(replaced_by):
            raise GoldenSetError(f"{where} needs an RFC number in 'replaced_by'.")
        if replaced_by == rfc:
            raise GoldenSetError(f"{where} can't be replaced by its own RFC.")
    assert isinstance(rfc, int)
    return Label(rfc, section, quote, replaced_by)


def _parse_labels(raw: dict[str, Any], key: str, where: str, allowed: set[str]) -> tuple[Label, ...]:
    entries = raw.get(key, [])
    if not isinstance(entries, list):
        raise GoldenSetError(f"{where}: '{key}' must be a list of sections.")
    return tuple(_parse_label(entry, f"{where}: {key} {i + 1}", allowed) for i, entry in enumerate(entries))


def _check_kind_rules(question: Question, where: str) -> None:
    if question.kind == OUT_OF_CORPUS:
        if question.expected:
            raise GoldenSetError(f"{where}: an {OUT_OF_CORPUS} question has no expected sections.")
    elif not question.expected:
        raise GoldenSetError(f"{where}: needs at least one expected section.")
    for label in question.expected:
        if label.quote is None:
            raise GoldenSetError(
                f"{where}: expected section RFC {label.rfc} {label.section} needs a 'quote'."
            )
    if question.kind == STALE_TRAP and not question.obsolete:
        raise GoldenSetError(f"{where}: a {STALE_TRAP} question needs at least one obsolete section.")
    if question.kind != STALE_TRAP and question.obsolete:
        raise GoldenSetError(f"{where}: only a {STALE_TRAP} question lists obsolete sections.")
    for label in question.obsolete:
        if label.replaced_by is None:
            raise GoldenSetError(
                f"{where}: obsolete section RFC {label.rfc} {label.section} needs 'replaced_by'."
            )
    for label in question.expected:
        if question.kind == VERSION_SPECIFIC and label.replaced_by is None:
            raise GoldenSetError(
                f"{where}: expected section RFC {label.rfc} {label.section} of a {VERSION_SPECIFIC} "
                "question needs 'replaced_by'."
            )
        if question.kind != VERSION_SPECIFIC and label.replaced_by is not None:
            raise GoldenSetError(
                f"{where}: only a {VERSION_SPECIFIC} question's expected sections have 'replaced_by'."
            )


def _parse_question(raw: object, index: int) -> Question:
    where = f"question {index}"
    if not isinstance(raw, dict):
        raise GoldenSetError(f"{where} must be a [[question]] table.")
    question_id = raw.get("id")
    if not isinstance(question_id, str) or not question_id.strip():
        raise GoldenSetError(f"{where} needs an 'id'.")
    where = f"question {question_id!r}"
    unknown = sorted(set(raw) - _QUESTION_KEYS)
    if unknown:
        raise GoldenSetError(f"{where} has unknown fields: {', '.join(unknown)}.")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise GoldenSetError(f"{where}: 'kind' must be one of {', '.join(KINDS)}, not {kind!r}.")
    text = raw.get("question")
    if not isinstance(text, str) or not text.strip():
        raise GoldenSetError(f"{where} needs the question text in 'question'.")
    assert isinstance(kind, str)
    question = Question(
        question_id,
        kind,
        text,
        _parse_labels(raw, "expected", where, _EXPECTED_KEYS),
        _parse_labels(raw, "obsolete", where, _OBSOLETE_KEYS),
    )
    _check_kind_rules(question, where)
    return question


def load_golden_set(path: str) -> list[Question]:
    """Read the golden set at ``path`` and check its structure.

    Raises :class:`GoldenSetError` naming the file, and the question when there is one.
    """
    try:
        with open(path, "rb") as file:
            document = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise GoldenSetError(f"Failed to read golden set {path!r}: {exc}") from exc
    raw_questions = document.get("question")
    unknown = sorted(set(document) - {"question"})
    try:
        if unknown:
            raise GoldenSetError(f"unknown top-level fields: {', '.join(unknown)}.")
        if not isinstance(raw_questions, list) or not raw_questions:
            raise GoldenSetError("no [[question]] tables.")
        questions = [_parse_question(raw, i + 1) for i, raw in enumerate(raw_questions)]
        seen: set[str] = set()
        for question in questions:
            if question.id in seen:
                raise GoldenSetError(f"question {question.id!r} appears more than once.")
            seen.add(question.id)
    except GoldenSetError as exc:
        raise GoldenSetError(f"Golden set {path!r}: {exc}") from None
    return questions


def rfcs_outside(questions: list[Question], corpus: set[int]) -> list[str]:
    """Return a message for each label whose RFC, or replacing RFC, isn't in ``corpus``."""
    return [
        f"question {question.id!r}: RFC {number} isn't in the corpus."
        for question in questions
        for label in (*question.expected, *question.obsolete)
        for number in (label.rfc, label.replaced_by)
        if number is not None and number not in corpus
    ]


@dataclass(frozen=True)
class Score:
    """Where a question's first expected and first obsolete results ranked, counting from 1."""

    question: Question
    rank: int | None
    obsolete_rank: int | None = None

    def hit(self, k: int) -> bool:
        return self.rank is not None and self.rank <= k

    @property
    def reciprocal_rank(self) -> float:
        return 0.0 if self.rank is None else 1.0 / self.rank

    @property
    def trap_caught(self) -> bool:
        """A stale-trap question whose obsolete result ranks above every expected result."""
        if self.question.kind != STALE_TRAP or self.obsolete_rank is None:
            return False
        return self.rank is None or self.obsolete_rank < self.rank


def _first_rank(labels: Sequence[Label], results: Sequence[SearchResult]) -> int | None:
    sections = {(label.rfc, label.section) for label in labels}
    for position, result in enumerate(results[:SEARCH_DEPTH], start=1):
        if (result.chunk.rfc_number, result.chunk.section_number) in sections:
            return position
    return None


def score_question(question: Question, results: Sequence[SearchResult]) -> Score:
    """Rank ``results``, best first, against the question's labels. Only exact sections match."""
    if question.kind == OUT_OF_CORPUS:
        raise ValueError(f"question {question.id!r} is {OUT_OF_CORPUS}, which retrieval doesn't score.")
    return Score(question, _first_rank(question.expected, results), _first_rank(question.obsolete, results))


@dataclass(frozen=True)
class KindTotals:
    kind: str
    scored: int
    hits: dict[int, int]


@dataclass(frozen=True)
class Summary:
    scored: int
    hits: dict[int, int]
    mean_reciprocal_rank: float
    traps: int
    traps_caught: int
    by_kind: tuple[KindTotals, ...]
    skipped: int


def summarize(scores: Sequence[Score], skipped: int = 0) -> Summary:
    """Total the scores. ``skipped`` is the number of out-of-corpus questions left out."""
    by_kind = tuple(
        KindTotals(kind, len(group), {k: sum(s.hit(k) for s in group) for k in HIT_KS})
        for kind in KINDS
        if (group := [s for s in scores if s.question.kind == kind])
    )
    traps = [s for s in scores if s.question.kind == STALE_TRAP]
    return Summary(
        scored=len(scores),
        hits={k: sum(s.hit(k) for s in scores) for k in HIT_KS},
        mean_reciprocal_rank=sum(s.reciprocal_rank for s in scores) / len(scores) if scores else 0.0,
        traps=len(traps),
        traps_caught=sum(s.trap_caught for s in traps),
        by_kind=by_kind,
        skipped=skipped,
    )


def missing_labels(questions: Sequence[Question], sections: set[tuple[int, str]]) -> list[str]:
    """Return a message for each expected or obsolete section with no chunk in the index."""
    return [
        f"question {question.id!r}: RFC {label.rfc} section {label.section} isn't in the index."
        for question in questions
        for label in (*question.expected, *question.obsolete)
        if (label.rfc, label.section) not in sections
    ]


def _ratio(count: int, total: int) -> str:
    return f"{count}/{total} ({count / total:.2f})" if total else f"{count}/0"


def format_report(scores: Sequence[Score], summary: Summary, index_path: str) -> str:
    """The per-question table, the totals and the totals by kind, as printed."""
    id_width = max([len("id"), *(len(s.question.id) for s in scores)])
    kind_width = max(len(kind) for kind in KINDS)
    lines = [
        f"Retrieval scores for {summary.scored} questions, from {index_path} (search depth {SEARCH_DEPTH})",
        "",
        f"{'id':<{id_width}}  {'kind':<{kind_width}}  {'rank':>4}  trap",
    ]
    for score in scores:
        rank = "-" if score.rank is None else str(score.rank)
        trap = ("yes" if score.trap_caught else "no") if score.question.kind == STALE_TRAP else "-"
        lines.append(
            f"{score.question.id:<{id_width}}  {score.question.kind:<{kind_width}}  {rank:>4}  {trap}"
        )
    hits = "    ".join(f"hit@{k}  {_ratio(summary.hits[k], summary.scored)}" for k in HIT_KS)
    traps = _ratio(summary.traps_caught, summary.traps) if summary.traps else "-"
    lines += ["", f"{hits}    MRR {summary.mean_reciprocal_rank:.2f}    trap rate {traps}"]
    if summary.by_kind:
        header = "".join(f"{f'hit@{k}':<15}" for k in HIT_KS).rstrip()
        lines += ["", f"{'kind':<{kind_width}}  {header}"]
        for totals in summary.by_kind:
            cells = "".join(f"{_ratio(totals.hits[k], totals.scored):<15}" for k in HIT_KS).rstrip()
            lines.append(f"{totals.kind:<{kind_width}}  {cells}")
    lines += ["", f"Skipped {summary.skipped} {OUT_OF_CORPUS} questions."]
    return "\n".join(lines)


def _log_results(question: Question, results: Sequence[SearchResult]) -> None:
    logger.info("%s: %s", question.id, question.question)
    for position, result in enumerate(results[:_LOGGED_RESULTS], start=1):
        chunk = result.chunk
        logger.info(
            "  %d. RFC %d section %s: %s",
            position,
            chunk.rfc_number,
            chunk.section_number,
            chunk.section_title,
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Score retrieval against the golden set: 0 once scored, 1 for a problem with the set or the index."""
    parser = argparse.ArgumentParser(description="Score keyword retrieval against the golden question set.")
    parser.add_argument(
        "--data-dir",
        help=f"Directory holding {paths.INDEX_FILE}. Defaults to ${paths.DATA_DIR_ENV}, then the user data "
        "directory.",
    )
    parser.add_argument(
        "--golden", default=DEFAULT_GOLDEN, help="The golden set. Defaults to eval/golden.toml."
    )
    add_verbose_argument(parser)
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    index_path = paths.resolve_data_dir(args.data_dir).file(paths.INDEX_FILE)
    try:
        questions = load_golden_set(args.golden)
        missing = missing_labels(questions, list_sections(index_path))
        if missing:
            for message in missing:
                report_error(message)
            return report_error("Nothing was scored. Fix the labels, or rebuild the index with rfc-ingest.")
        scores = []
        for question in questions:
            if question.kind == OUT_OF_CORPUS:
                continue
            results = search(index_path, question.question, SEARCH_DEPTH)
            _log_results(question, results)
            scores.append(score_question(question, results))
    except (GoldenSetError, RfcQaError) as exc:
        return report_error(exc)
    skipped = sum(question.kind == OUT_OF_CORPUS for question in questions)
    print(format_report(scores, summarize(scores, skipped), index_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
