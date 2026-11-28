"""Score the answers that query() gives to the golden question set.

Usage: python -m scripts.score_answers [--data-dir DIR] [--config-dir DIR] [--golden FILE]
                                       [--output FILE] [-v]

Run it from the repository root. It asks every golden question through rfc_qa.query.query(), and
scores each answer by its citations: whether it cites a section that answers the question, whether a
stale-citation trap cites the obsolete RFC, and whether a question the corpus doesn't answer is
declined. Each miss is put down to retrieval or to generation. It needs a built index, Ollama and the
configured model, and writes every response to a JSON Lines run file. docs/evaluation.md describes
how to read the output.
"""

import argparse
import datetime
import json
import logging
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import IO, Any

import requests

from rfc_qa import paths
from rfc_qa.cli import add_verbose_argument, configure_logging, report_error
from rfc_qa.errors import RfcQaError
from rfc_qa.generation.answer_generator import ModelSettings
from rfc_qa.query import QueryErrorCode, QueryResponse, load_query_config, query
from rfc_qa.retrieval.keyword_index import list_sections, search
from scripts.score_retrieval import (
    DEFAULT_GOLDEN,
    KINDS,
    OUT_OF_CORPUS,
    ROOT,
    SEARCH_DEPTH,
    STALE_TRAP,
    GoldenSetError,
    Question,
    Score,
    load_golden_set,
    missing_labels,
    score_question,
)

# Under the package's logger, so that -v shows these records as it does the commands'.
logger = logging.getLogger("rfc_qa.score_answers")

# The folder, in the data directory, that holds run files by default.
RUNS_FOLDER = "eval-runs"
# Failures that every later question would hit too, so the run stops.
STOPPING_ERRORS = (
    QueryErrorCode.MODEL_UNAVAILABLE,
    QueryErrorCode.INDEX_UNAVAILABLE,
    QueryErrorCode.CONFIG_INVALID,
)

# Outcomes. An answerable question is any question that isn't out-of-corpus.
CORRECT = "correct"
WRONG_CITE = "wrong-cite"
ABSTAINED = "abstained"
ANSWERED = "answered"
REJECTED = "rejected"
ERROR = "error"

# Causes of a miss on an answerable question.
RETRIEVAL = "retrieval"
GENERATION = "generation"


@dataclass(frozen=True)
class AnswerScore:
    """How one question's answer scored.

    ``rank`` is the first expected section's rank in a search of the index, or ``None`` when it isn't
    in the first 20 results or the question is out-of-corpus. ``cause`` is set only for an answerable
    question that isn't correct. ``cited_expected`` counts the expected sections the answer cited.
    """

    question: Question
    rank: int | None
    response: QueryResponse
    outcome: str
    cause: str | None
    stale_citation: bool
    cited_expected: int

    @property
    def is_correct(self) -> bool:
        return self.outcome == (ABSTAINED if self.question.kind == OUT_OF_CORPUS else CORRECT)


def _cited_sections(response: QueryResponse) -> set[tuple[int, str]]:
    return {(citation.rfc_number, citation.section_number) for citation in response.citations}


def _outcome(question: Question, response: QueryResponse, cited: set[tuple[int, str]]) -> str:
    if not response.success:
        return ERROR
    if response.answer_rejected:
        return REJECTED
    if not response.found:
        return ABSTAINED
    if question.kind == OUT_OF_CORPUS:
        return ANSWERED
    expected = {(label.rfc, label.section) for label in question.expected}
    return CORRECT if cited & expected else WRONG_CITE


def score_answer(
    question: Question, retrieval: Score | None, response: QueryResponse, retrieval_limit: int
) -> AnswerScore:
    """Score ``response`` to ``question``.

    ``retrieval`` is the question's retrieval score from the same index, and ``None`` only for an
    out-of-corpus question, which retrieval doesn't score. ``retrieval_limit`` is the number of
    passages the query sent the model.
    """
    if (retrieval is None) != (question.kind == OUT_OF_CORPUS):
        raise ValueError(
            f"question {question.id!r}: a retrieval score is needed exactly when it's answerable."
        )
    cited = _cited_sections(response)
    outcome = _outcome(question, response, cited)
    rank = None if retrieval is None else retrieval.rank
    cause = None
    if question.kind != OUT_OF_CORPUS and outcome != CORRECT:
        cause = GENERATION if rank is not None and rank <= retrieval_limit else RETRIEVAL
    stale = question.kind == STALE_TRAP and any(
        (label.rfc, label.section) in cited for label in question.obsolete
    )
    cited_expected = len({(label.rfc, label.section) for label in question.expected} & cited)
    return AnswerScore(question, rank, response, outcome, cause, stale, cited_expected)


@dataclass(frozen=True)
class KindTotals:
    kind: str
    questions: int
    correct: int


@dataclass(frozen=True)
class AnswerSummary:
    questions: int
    answerable: int
    correct: int
    retrieval_misses: int
    generation_misses: int
    traps: int
    stale_citations: int
    out_of_corpus: int
    correct_abstentions: int
    abstentions_on_answerable: int
    rejected: int
    errors: int
    by_kind: tuple[KindTotals, ...]


def summarize(scores: Sequence[AnswerScore]) -> AnswerSummary:
    """Total the scores. For out-of-corpus questions, the by-kind correct count is abstentions."""
    answerable = [s for s in scores if s.question.kind != OUT_OF_CORPUS]
    out_of_corpus = [s for s in scores if s.question.kind == OUT_OF_CORPUS]
    traps = [s for s in scores if s.question.kind == STALE_TRAP]
    return AnswerSummary(
        questions=len(scores),
        answerable=len(answerable),
        correct=sum(s.is_correct for s in answerable),
        retrieval_misses=sum(s.cause == RETRIEVAL for s in answerable),
        generation_misses=sum(s.cause == GENERATION for s in answerable),
        traps=len(traps),
        stale_citations=sum(s.stale_citation for s in traps),
        out_of_corpus=len(out_of_corpus),
        correct_abstentions=sum(s.is_correct for s in out_of_corpus),
        abstentions_on_answerable=sum(s.outcome == ABSTAINED for s in answerable),
        rejected=sum(s.outcome == REJECTED for s in scores),
        errors=sum(s.outcome == ERROR for s in scores),
        by_kind=tuple(
            KindTotals(kind, len(group), sum(s.is_correct for s in group))
            for kind in KINDS
            if (group := [s for s in scores if s.question.kind == kind])
        ),
    )


def _ratio(count: int, total: int) -> str:
    return f"{count}/{total} ({count / total:.2f})" if total else f"{count}/0"


_KIND_WIDTH = max(len(kind) for kind in KINDS)
_OUTCOME_WIDTH = max(len(outcome) for outcome in (CORRECT, WRONG_CITE, ABSTAINED, ANSWERED, REJECTED, ERROR))
_CAUSE_WIDTH = max(len(RETRIEVAL), len(GENERATION))


def id_width(questions: Sequence[Question]) -> int:
    return max([len("id"), *(len(question.id) for question in questions)])


def format_header(width: int) -> str:
    """The per-question table's heading, for IDs up to ``width`` characters."""
    return (
        f"{'id':<{width}}  {'kind':<{_KIND_WIDTH}}  {'rank':>4}  {'outcome':<{_OUTCOME_WIDTH}}  "
        f"{'cause':<{_CAUSE_WIDTH}}  stale  cited"
    )


def format_row(score: AnswerScore, width: int) -> str:
    """One question's row in the table."""
    question = score.question
    answerable = question.kind != OUT_OF_CORPUS
    rank = "-" if score.rank is None else str(score.rank)
    cause = score.cause or "-"
    stale = ("yes" if score.stale_citation else "no") if question.kind == STALE_TRAP else "-"
    cited = f"{score.cited_expected}/{len(question.expected)}" if answerable else "-"
    return (
        f"{question.id:<{width}}  {question.kind:<{_KIND_WIDTH}}  {rank:>4}  "
        f"{score.outcome:<{_OUTCOME_WIDTH}}  {cause:<{_CAUSE_WIDTH}}  {stale:<5}  {cited}"
    ).rstrip()


def format_totals(summary: AnswerSummary) -> str:
    """The totals and the totals by kind, printed after the table."""
    stale = _ratio(summary.stale_citations, summary.traps) if summary.traps else "-"
    lines = [
        f"cited correctly  {_ratio(summary.correct, summary.answerable)}    "
        f"misses: retrieval {summary.retrieval_misses}, generation {summary.generation_misses}",
        f"stale citations  {stale}",
        f"abstained        {_ratio(summary.correct_abstentions, summary.out_of_corpus)} of {OUT_OF_CORPUS}, "
        f"{_ratio(summary.abstentions_on_answerable, summary.answerable)} of answerable",
        f"rejected         {_ratio(summary.rejected, summary.questions)}    "
        f"errors {_ratio(summary.errors, summary.questions)}",
    ]
    if summary.by_kind:
        lines += ["", f"{'kind':<{_KIND_WIDTH}}  correct"]
        lines += [
            f"{totals.kind:<{_KIND_WIDTH}}  {_ratio(totals.correct, totals.questions)}"
            for totals in summary.by_kind
        ]
    lines += ["", f"For {OUT_OF_CORPUS} questions, correct means the query declined to answer."]
    return "\n".join(lines)


def format_report(scores: Sequence[AnswerScore], summary: AnswerSummary) -> str:
    """The table and the totals, as printed at the end of a run."""
    width = id_width([score.question for score in scores])
    return "\n".join(
        [format_header(width), *(format_row(score, width) for score in scores), "", format_totals(summary)]
    )


class ScoringError(Exception):
    """A problem that stops answer scoring before or during a run, ready to show."""


# --- The model ---


def _get_model_list(base_url: str, timeout: float) -> object:
    """Ask Ollama for its installed models: the scorer's own network call, which tests replace."""
    response = requests.get(base_url.rstrip("/") + "/api/tags", timeout=timeout)
    response.raise_for_status()
    return response.json()


def model_digest(settings: ModelSettings) -> str:
    """Return the digest of the configured model, raising :class:`ScoringError` if Ollama doesn't have it."""
    try:
        listing = _get_model_list(settings.base_url, settings.timeout_seconds)
    except (requests.RequestException, ValueError) as exc:
        raise ScoringError(
            f"Can't reach Ollama at {settings.base_url}. Start Ollama, for example with `ollama serve`."
        ) from exc
    names = {settings.model} if ":" in settings.model else {settings.model, f"{settings.model}:latest"}
    models = listing.get("models") if isinstance(listing, dict) else None
    for entry in models if isinstance(models, list) else []:
        if isinstance(entry, dict) and names & {entry.get("name"), entry.get("model")}:
            digest = entry.get("digest")
            return digest if isinstance(digest, str) else "unknown"
    raise ScoringError(
        f"Model {settings.model!r} isn't installed in Ollama. Run `ollama pull {settings.model}`."
    )


# --- The run file ---


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
    except OSError, subprocess.CalledProcessError:
        return None
    return result.stdout


def commit_state() -> tuple[str | None, bool | None]:
    """Return the commit and whether the working tree has changes, or ``None`` for each when unknown."""
    commit = _git("rev-parse", "HEAD")
    if commit is None:
        return None, None
    status = _git("status", "--porcelain")
    return commit.strip(), None if status is None else bool(status.strip())


def default_run_path(data_dir: str, now: datetime.datetime) -> str:
    return os.path.join(data_dir, RUNS_FOLDER, f"answers-{now.strftime('%Y%m%dT%H%M%SZ')}.jsonl")


def _response_record(response: QueryResponse) -> dict[str, Any]:
    record = asdict(response)
    record["error_code"] = None if response.error_code is None else response.error_code.name
    return record


def question_record(score: AnswerScore) -> dict[str, Any]:
    """One question's line in the run file."""
    question = score.question
    return {
        "type": "question",
        "id": question.id,
        "kind": question.kind,
        "question": question.question,
        "retrieval_rank": score.rank,
        "response": _response_record(score.response),
        "outcome": score.outcome,
        "cause": score.cause,
        "stale_citation": score.stale_citation,
        "cited_expected": score.cited_expected,
        "expected_sections": len(question.expected),
    }


def _write_line(file: IO[str], record: dict[str, Any]) -> None:
    file.write(json.dumps(record, ensure_ascii=False) + "\n")
    file.flush()


# --- The command ---


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.score_answers",
        description="Score the answers query() gives to the golden question set. Needs Ollama.",
    )
    parser.add_argument(
        "--data-dir",
        help=f"Directory holding {paths.INDEX_FILE}. Defaults to ${paths.DATA_DIR_ENV}, then the user data "
        "directory.",
    )
    parser.add_argument(
        "--config-dir",
        help=f"Directory holding {paths.QUERY_CONFIG_FILE}. Defaults to ${paths.CONFIG_DIR_ENV}, then the "
        "packaged defaults.",
    )
    parser.add_argument(
        "--golden", default=DEFAULT_GOLDEN, help="The golden set. Defaults to eval/golden.toml."
    )
    parser.add_argument(
        "--output",
        help=f"The run file to write. Defaults to a new file in {RUNS_FOLDER}/ in the data directory.",
    )
    add_verbose_argument(parser)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Score answers against the golden set: 0 once every question is scored, 1 when the run can't finish."""
    args = _parse_args(argv)
    configure_logging(args.verbose)
    started = datetime.datetime.now(datetime.UTC)

    try:
        data_dir = paths.resolve_data_dir(args.data_dir)
        config_dir = paths.resolve_config_dir(args.config_dir)
        index_path = data_dir.file(paths.INDEX_FILE)
        questions = load_golden_set(args.golden)
        missing = missing_labels(questions, list_sections(index_path))
        if missing:
            for message in missing:
                report_error(message)
            return report_error("Nothing was scored. Fix the labels, or rebuild the index with rfc-ingest.")
        config = load_query_config(config_dir.file(paths.QUERY_CONFIG_FILE))
        digest = model_digest(config.model)
    except (GoldenSetError, RfcQaError, ScoringError) as exc:
        return report_error(exc)

    # The packaged defaults have no path to pass on, and query() selects them the same way.
    selected_config_dir = None if config_dir.is_packaged else str(config_dir.location)
    output = args.output or default_run_path(data_dir.path, started)
    commit, changed = commit_state()
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        run_file = open(output, "w", encoding="utf-8")  # noqa: SIM115 - closed in the finally below
    except OSError as exc:
        return report_error(f"Can't write the run file {output!r}: {exc}")

    scores: list[AnswerScore] = []
    width = id_width(questions)
    try:
        _write_line(
            run_file,
            {
                "type": "run",
                "started_at": started.isoformat(timespec="seconds"),
                "model": config.model.model,
                "model_digest": digest,
                "ollama_base_url": config.model.base_url,
                "retrieval_limit": config.retrieval_limit,
                "commit": commit,
                "working_tree_changed": changed,
                "golden": os.path.abspath(args.golden),
                "index": index_path,
            },
        )
        print(
            f"Answer scores for {len(questions)} questions, from {index_path}, with {config.model.model} "
            f"({digest[:12]}) and {config.retrieval_limit} passages per query"
        )
        print()
        print(format_header(width), flush=True)
        for question in questions:
            retrieval = None
            if question.kind != OUT_OF_CORPUS:
                retrieval = score_question(question, search(index_path, question.question, SEARCH_DEPTH))
            response = query(question.question, config_dir=selected_config_dir, data_dir=data_dir.path)
            if not response.success and response.error_code in STOPPING_ERRORS:
                raise ScoringError(f"Stopped at question {question.id!r}: {response.error_string}")
            score = score_answer(question, retrieval, response, config.retrieval_limit)
            scores.append(score)
            _write_line(run_file, question_record(score))
            print(format_row(score, width), flush=True)
    except (RfcQaError, ScoringError) as exc:
        report_error(exc)
        return report_error(f"The run file keeps the {len(scores)} questions scored before it: {output}")
    except OSError as exc:
        return report_error(f"Can't write the run file {output!r}: {exc}")
    finally:
        run_file.close()

    print()
    print(format_totals(summarize(scores)))
    print()
    print(f"Run saved to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
