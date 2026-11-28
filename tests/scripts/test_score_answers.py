import json
import os
import re
import subprocess
import textwrap
from typing import ClassVar

import pytest
import requests

from rfc_qa import paths
from rfc_qa import query as rfc_query
from rfc_qa.chunk import Chunk
from rfc_qa.errors import ModelResponseError, ModelUnavailableError
from rfc_qa.generation import answer_generator
from rfc_qa.query import Citation, QueryErrorCode, QueryResponse
from rfc_qa.retrieval.keyword_index import build_index, search
from scripts import score_answers
from scripts.score_answers import (
    ABSTAINED,
    ANSWERED,
    CORRECT,
    ERROR,
    GENERATION,
    REJECTED,
    RETRIEVAL,
    WRONG_CITE,
    commit_state,
    format_report,
    main,
    score_answer,
    summarize,
)
from scripts.score_retrieval import SEARCH_DEPTH, Label, Question, Score
from tests.conftest import write_toml

LIMIT = 5

DIRECT = Question(
    "status-404", "direct", "What does a 404 mean?", (Label(9110, "15.5.5", "The 404 (Not Found)"),), ()
)
MULTI = Question(
    "conditional",
    "multi-section",
    "How do the conditional headers differ?",
    (Label(9110, "13.1.1", "q"), Label(9110, "13.1.2", "q"), Label(9110, "13.1.3", "q")),
    (),
)
TRAP = Question(
    "tls13-resumption",
    "stale-trap",
    "How does a TLS 1.3 client resume a session?",
    (Label(9846, "2.2", "PSKs"),),
    (Label(8446, "2.2", replaced_by=9846),),
)
VERSION = Question(
    "tls12-hello",
    "version-specific",
    "In TLS 1.2, what does the client send first?",
    (Label(5246, "7.4.1.2", "ClientHello", replaced_by=9846),),
    (),
)
OOC = Question("quic", "out-of-corpus", "How does QUIC multiplex streams?", (), ())


def _citation(rfc, section):
    return Citation(f"rfc{rfc}-s{section}-p0", rfc, "Title", section, "Section title")


def _answered(*sections):
    return QueryResponse(
        success=True, answer="An answer.", found=True, citations=[_citation(r, s) for r, s in sections]
    )


NOT_FOUND = QueryResponse(success=True, answer="The indexed RFCs don't answer this question.", found=False)
REJECTED_RESPONSE = QueryResponse(
    success=True, answer="The indexed RFCs don't answer this question.", found=False, answer_rejected=True
)
FAILED = QueryResponse(
    success=False,
    error_code=QueryErrorCode.MODEL_INVALID_RESPONSE,
    error_string="The model's output isn't valid JSON.",
)


def _score(question, response, rank=1):
    retrieval = None if question.kind == "out-of-corpus" else Score(question, rank)
    return score_answer(question, retrieval, response, LIMIT)


# --- Outcomes for answerable questions ---


def test_citing_an_expected_section_is_correct():
    score = _score(DIRECT, _answered((9110, "15.5.5")))
    assert (score.outcome, score.cause, score.cited_expected) == (CORRECT, None, 1)


def test_a_subsection_citation_does_not_match():
    score = _score(DIRECT, _answered((9110, "15.5")))
    assert (score.outcome, score.cited_expected) == (WRONG_CITE, 0)


def test_an_answer_citing_no_expected_section_is_a_wrong_cite():
    assert _score(DIRECT, _answered((7231, "6.5.4"))).outcome == WRONG_CITE


def test_not_found_on_an_answerable_question_is_abstained():
    assert _score(DIRECT, NOT_FOUND).outcome == ABSTAINED


def test_a_rejected_answer_is_rejected_not_abstained():
    assert _score(DIRECT, REJECTED_RESPONSE).outcome == REJECTED


def test_a_failed_query_is_an_error():
    assert _score(DIRECT, FAILED).outcome == ERROR


def test_version_specific_is_correct_when_it_cites_the_obsolete_rfc():
    assert _score(VERSION, _answered((5246, "7.4.1.2"))).outcome == CORRECT


# --- Outcomes for out-of-corpus questions ---


def test_out_of_corpus_not_found_is_a_correct_abstention():
    score = _score(OOC, NOT_FOUND)
    assert (score.outcome, score.is_correct, score.cause, score.rank) == (ABSTAINED, True, None, None)


def test_out_of_corpus_answer_is_answered():
    score = _score(OOC, _answered((9110, "15.5.5")))
    assert (score.outcome, score.is_correct) == (ANSWERED, False)


def test_out_of_corpus_rejected_answer_is_not_an_abstention():
    score = _score(OOC, REJECTED_RESPONSE)
    assert (score.outcome, score.is_correct) == (REJECTED, False)


def test_out_of_corpus_failed_query_is_an_error():
    assert _score(OOC, FAILED).outcome == ERROR


def test_a_retrieval_score_is_needed_exactly_for_answerable_questions():
    with pytest.raises(ValueError, match="status-404"):
        score_answer(DIRECT, None, NOT_FOUND, LIMIT)
    with pytest.raises(ValueError, match="quic"):
        score_answer(OOC, Score(OOC, None), NOT_FOUND, LIMIT)


# --- Causes ---


@pytest.mark.parametrize("rank", [LIMIT + 1, 20, None])
def test_a_miss_whose_section_never_reached_the_model_is_retrieval(rank):
    assert _score(DIRECT, NOT_FOUND, rank=rank).cause == RETRIEVAL


@pytest.mark.parametrize("rank", [1, LIMIT])
def test_a_miss_whose_section_reached_the_model_is_generation(rank):
    assert _score(DIRECT, _answered((7231, "6.5.4")), rank=rank).cause == GENERATION


def test_the_cause_uses_the_limit_given():
    retrieval = Score(DIRECT, 4)
    assert score_answer(DIRECT, retrieval, NOT_FOUND, 3).cause == RETRIEVAL
    assert score_answer(DIRECT, retrieval, NOT_FOUND, 4).cause == GENERATION


def test_errors_and_rejections_get_a_cause_too():
    assert _score(DIRECT, FAILED, rank=None).cause == RETRIEVAL
    assert _score(DIRECT, REJECTED_RESPONSE, rank=2).cause == GENERATION


# --- Stale citations and cited counts ---


def test_a_trap_answer_citing_the_obsolete_section_is_stale():
    score = _score(TRAP, _answered((8446, "2.2")))
    assert (score.outcome, score.stale_citation) == (WRONG_CITE, True)


def test_a_trap_answer_citing_both_is_correct_and_stale():
    score = _score(TRAP, _answered((9846, "2.2"), (8446, "2.2")))
    assert (score.outcome, score.stale_citation) == (CORRECT, True)


def test_a_trap_answer_citing_only_the_current_rfc_is_not_stale():
    assert _score(TRAP, _answered((9846, "2.2"))).stale_citation is False


def test_only_traps_are_marked_stale():
    assert _score(VERSION, _answered((5246, "7.4.1.2"))).stale_citation is False


def test_cited_count_for_a_multi_section_question():
    score = _score(MULTI, _answered((9110, "13.1.1"), (9110, "13.1.3"), (9110, "8.6")))
    assert (score.outcome, score.cited_expected) == (CORRECT, 2)


# --- Totals and report ---


def _scores():
    return [
        _score(DIRECT, _answered((9110, "15.5.5")), rank=1),
        _score(MULTI, _answered((9110, "13.1.1"), (9110, "13.1.2")), rank=2),
        _score(TRAP, _answered((8446, "2.2")), rank=3),
        _score(VERSION, NOT_FOUND, rank=None),
        _score(OOC, NOT_FOUND),
        _score(Question("ooc-2", "out-of-corpus", "How does BGP pick routes?", (), ()), REJECTED_RESPONSE),
        _score(Question("direct-2", "direct", "q", (Label(9110, "8.6", "q"),), ()), FAILED, rank=7),
    ]


def test_totals():
    summary = summarize(_scores())
    assert (summary.questions, summary.answerable, summary.correct) == (7, 5, 2)
    assert (summary.retrieval_misses, summary.generation_misses) == (2, 1)
    assert (summary.traps, summary.stale_citations) == (1, 1)
    assert (summary.out_of_corpus, summary.correct_abstentions) == (2, 1)
    assert summary.abstentions_on_answerable == 1
    assert (summary.rejected, summary.errors) == (1, 1)
    assert [(t.kind, t.questions, t.correct) for t in summary.by_kind] == [
        ("direct", 2, 1),
        ("multi-section", 1, 1),
        ("stale-trap", 1, 0),
        ("version-specific", 1, 0),
        ("out-of-corpus", 2, 1),
    ]


def test_totals_of_nothing():
    summary = summarize([])
    assert (summary.questions, summary.correct, summary.by_kind) == (0, 0, ())


def test_report():
    scores = _scores()
    assert format_report(scores, summarize(scores)) == textwrap.dedent("""\
        id                kind              rank  outcome     cause       stale  cited
        status-404        direct               1  correct     -           -      1/1
        conditional       multi-section        2  correct     -           -      2/3
        tls13-resumption  stale-trap           3  wrong-cite  generation  yes    0/1
        tls12-hello       version-specific     -  abstained   retrieval   -      0/1
        quic              out-of-corpus        -  abstained   -           -      -
        ooc-2             out-of-corpus        -  rejected    -           -      -
        direct-2          direct               7  error       retrieval   -      0/1

        cited correctly  2/5 (0.40)    misses: retrieval 2, generation 1
        stale citations  1/1 (1.00)
        abstained        1/2 (0.50) of out-of-corpus, 1/5 (0.20) of answerable
        rejected         1/7 (0.14)    errors 1/7 (0.14)

        kind              correct
        direct            1/2 (0.50)
        multi-section     1/1 (1.00)
        stale-trap        0/1 (0.00)
        version-specific  0/1 (0.00)
        out-of-corpus     1/2 (0.50)

        For out-of-corpus questions, correct means the query declined to answer.""")


# --- The command (tasks 3.1 and 3.2) ---

INDEX_CHUNKS = [
    Chunk(
        "rfc9110-s15.5.5-p0", 9110, "HTTP Semantics", "http", "15.5.5", "404 Not Found", "No representation."
    ),
    Chunk("rfc9110-s8.6-p0", 9110, "HTTP Semantics", "http", "8.6", "Content-Length", "Body size in octets."),
    Chunk("rfc8446-s2.2-p0", 8446, "TLS 1.3", "tls", "2.2", "Resumption", "Session tickets resume sessions."),
    Chunk(
        "rfc9846-s2.2-p0", 9846, "TLS 1.3", "tls", "2.2", "Pre-Shared Key", "A ticket can resume a session."
    ),
]
CHUNKS_BY_ID = {chunk.chunk_id: chunk for chunk in INDEX_CHUNKS}

GOLDEN = """
[[question]]
id       = "not-found"
kind     = "direct"
question = "What does 404 not found mean?"
expected = [{ rfc = 9110, section = "15.5.5", quote = "No representation." }]

[[question]]
id       = "resumption"
kind     = "stale-trap"
question = "How is a session resumption done?"
expected = [{ rfc = 9846, section = "2.2", quote = "A ticket can resume a session." }]
obsolete = [{ rfc = 8446, section = "2.2", replaced_by = 9846 }]

[[question]]
id       = "quic"
kind     = "out-of-corpus"
question = "How does QUIC multiplex streams?"
"""

CONFIG = {
    "retrieval": {"limit": 3},
    "llm": {
        "model": "llama3.2",
        "base_url": "http://localhost:11434",
        "num_ctx": 8192,
        "max_answer_tokens": 512,
        "timeout_seconds": 120,
    },
}
DIGEST = "a80c4f17acd55265feec403c7aef86be0c25983ab279d83f3bcd3abbcb5b8b72"
MODEL_LIST = {"models": [{"name": "llama3.2:latest", "model": "llama3.2:latest", "digest": DIGEST}]}


@pytest.fixture
def run(tmp_path, monkeypatch):
    """A data and config directory, with the model call and Ollama's model list replaced.

    ``run.answers`` maps a question to what the model returns: a chunk ID it cites, ``None`` for no
    answer, a ``GenerationResult`` to return as it is, or an exception to raise. ``run.sent`` records
    the chunk IDs sent for each question.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    build_index(INDEX_CHUNKS, {"target_chunk_tokens": 1100}, str(data_dir / paths.INDEX_FILE))
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    write_toml(config_dir / paths.QUERY_CONFIG_FILE, CONFIG)
    golden = tmp_path / "golden.toml"
    golden.write_text(GOLDEN)

    class Run:
        answers: ClassVar[dict[str, object]] = {}
        sent: ClassVar[dict[str, list[str]]] = {}
        model_list: ClassVar[object] = MODEL_LIST
        model_list_calls = 0
        output = str(tmp_path / "run.jsonl")
        data_dir = str(tmp_path / "data")
        golden = tmp_path / "golden.toml"

        @classmethod
        def main(cls, *extra):
            return main(
                [
                    "--data-dir",
                    str(data_dir),
                    "--config-dir",
                    str(config_dir),
                    "--golden",
                    str(golden),
                    *extra,
                ]
            )

        @classmethod
        def lines(cls, path=None):
            with open(path or cls.output, encoding="utf-8") as file:
                return [json.loads(line) for line in file]

    Run.answers = {
        "What does 404 not found mean?": "rfc9110-s15.5.5-p0",
        "How is a session resumption done?": "rfc8446-s2.2-p0",
        "How does QUIC multiplex streams?": None,
    }
    Run.sent = {}

    def fake_generate(question, chunks, settings):
        Run.sent[question] = [chunk.chunk_id for chunk in chunks]
        answer = Run.answers[question]
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, answer_generator.GenerationResult):
            return answer
        if answer is None:
            return answer_generator.GenerationResult(found=False, answer=None)
        assert isinstance(answer, str)
        return answer_generator.GenerationResult(
            found=True, answer="An answer.", cited=[CHUNKS_BY_ID[answer]]
        )

    def fake_model_list(base_url, timeout):
        Run.model_list_calls += 1
        if isinstance(Run.model_list, Exception):
            raise Run.model_list
        return Run.model_list

    monkeypatch.setattr(rfc_query, "generate_answer", fake_generate)
    monkeypatch.setattr(score_answers, "_get_model_list", fake_model_list)
    return Run


def test_main_prints_the_report_and_writes_the_run_file(run, capsys):
    assert run.main("--output", run.output) == 0
    out, err = capsys.readouterr()
    index = os.path.join(run.data_dir, paths.INDEX_FILE)
    assert out == textwrap.dedent(f"""\
        Answer scores for 3 questions, from {index}, with llama3.2 (a80c4f17acd5) and 3 passages per query

        id          kind              rank  outcome     cause       stale  cited
        not-found   direct               1  correct     -           -      1/1
        resumption  stale-trap           2  wrong-cite  generation  yes    0/1
        quic        out-of-corpus        -  abstained   -           -      -

        cited correctly  1/2 (0.50)    misses: retrieval 0, generation 1
        stale citations  1/1 (1.00)
        abstained        1/1 (1.00) of out-of-corpus, 0/2 (0.00) of answerable
        rejected         0/3 (0.00)    errors 0/3 (0.00)

        kind              correct
        direct            1/1 (1.00)
        stale-trap        0/1 (0.00)
        out-of-corpus     1/1 (1.00)

        For out-of-corpus questions, correct means the query declined to answer.

        Run saved to {run.output}
        """)
    assert err == ""

    header, *questions = run.lines()
    assert header["type"] == "run"
    assert (header["model"], header["model_digest"], header["retrieval_limit"]) == ("llama3.2", DIGEST, 3)
    assert header["ollama_base_url"] == "http://localhost:11434"
    assert (header["golden"], header["index"]) == (str(run.golden), index)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", header["started_at"])
    assert {"commit", "working_tree_changed"} <= set(header)
    assert [(q["type"], q["id"], q["outcome"]) for q in questions] == [
        ("question", "not-found", "correct"),
        ("question", "resumption", "wrong-cite"),
        ("question", "quic", "abstained"),
    ]
    first = questions[0]
    assert (first["kind"], first["retrieval_rank"], first["cause"], first["cited_expected"]) == (
        "direct",
        1,
        None,
        1,
    )
    assert first["expected_sections"] == 1
    assert first["response"]["found"] is True
    assert first["response"]["answer_rejected"] is False
    assert first["response"]["citations"][0]["chunk_id"] == "rfc9110-s15.5.5-p0"
    assert questions[1]["stale_citation"] is True
    assert questions[2]["retrieval_rank"] is None


def test_the_default_run_file_is_in_the_data_directory(run, capsys):
    assert run.main() == 0
    files = os.listdir(os.path.join(run.data_dir, "eval-runs"))
    assert len(files) == 1
    assert re.fullmatch(r"answers-\d{8}T\d{6}Z\.jsonl", files[0])
    path = os.path.join(run.data_dir, "eval-runs", files[0])
    assert capsys.readouterr().out.endswith(f"Run saved to {path}\n")
    assert len(run.lines(path)) == 4


def test_the_scorers_top_results_are_the_passages_query_sent(run):
    assert run.main("--output", run.output) == 0
    index = os.path.join(run.data_dir, paths.INDEX_FILE)
    for question, sent in run.sent.items():
        assert [result.chunk.chunk_id for result in search(index, question, SEARCH_DEPTH)][:3] == sent


def test_a_rejected_answer_is_recorded(run):
    run.answers["What does 404 not found mean?"] = answer_generator.GenerationResult(
        found=False, answer=None, answer_rejected=True
    )
    assert run.main("--output", run.output) == 0
    first = run.lines()[1]
    assert (first["outcome"], first["response"]["answer_rejected"]) == ("rejected", True)


def test_an_out_of_corpus_question_with_no_passages_is_not_sent_to_the_model(run):
    assert run.main("--output", run.output) == 0
    assert "How does QUIC multiplex streams?" not in run.sent
    assert run.lines()[3]["outcome"] == "abstained"


def test_a_missing_label_stops_before_any_question(run, capsys):
    run.golden.write_text(GOLDEN.replace('section = "15.5.5"', 'section = "99.9"'))
    assert run.main("--output", run.output) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err.splitlines() == [
        "question 'not-found': RFC 9110 section 99.9 isn't in the index.",
        "Nothing was scored. Fix the labels, or rebuild the index with rfc-ingest.",
    ]
    assert (run.sent, run.model_list_calls) == ({}, 0)
    assert not os.path.exists(run.output)


def test_an_unreachable_ollama_stops_before_any_question(run, capsys):
    run.model_list = requests.ConnectionError("refused")
    assert run.main("--output", run.output) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err.splitlines() == [
        "Can't reach Ollama at http://localhost:11434. Start Ollama, for example with `ollama serve`."
    ]
    assert run.sent == {}
    assert not os.path.exists(run.output)


def test_a_missing_model_stops_before_any_question(run, capsys):
    run.model_list = {"models": [{"name": "gemma3:270m", "model": "gemma3:270m", "digest": "e7d3"}]}
    assert run.main("--output", run.output) == 1
    assert capsys.readouterr().err.splitlines() == [
        "Model 'llama3.2' isn't installed in Ollama. Run `ollama pull llama3.2`."
    ]
    assert run.sent == {}


def test_a_missing_index_stops_before_any_question(run, tmp_path, capsys):
    assert main(["--data-dir", str(tmp_path / "empty"), "--golden", str(run.golden)]) == 1
    assert "Run rfc-ingest to build it." in capsys.readouterr().err
    assert run.sent == {}


def test_an_invalid_model_response_is_an_error_and_the_run_goes_on(run, capsys):
    run.answers["What does 404 not found mean?"] = ModelResponseError("The model's output isn't valid JSON.")
    assert run.main("--output", run.output) == 0
    assert "not-found   direct               1  error       generation  -      0/1" in capsys.readouterr().out
    _, first, *rest = run.lines()
    assert first["outcome"] == "error"
    assert first["response"]["error_code"] == "MODEL_INVALID_RESPONSE"
    assert len(rest) == 2


def test_ollama_stopping_during_a_run_keeps_the_earlier_questions(run, capsys):
    run.answers["How is a session resumption done?"] = ModelUnavailableError("Can't reach Ollama.")
    assert run.main("--output", run.output) == 1
    out, err = capsys.readouterr()
    assert "not-found   direct" in out
    assert "resumption" not in out
    assert err.splitlines() == [
        "Stopped at question 'resumption': Can't reach Ollama.",
        f"The run file keeps the 1 questions scored before it: {run.output}",
    ]
    assert [line["type"] for line in run.lines()] == ["run", "question"]
    assert "How does QUIC multiplex streams?" not in run.sent


def test_a_model_with_a_tag_must_match_exactly(run, capsys):
    run.model_list = {"models": [{"name": "llama3.2:1b", "model": "llama3.2:1b", "digest": "x"}]}
    assert run.main("--output", run.output) == 1
    assert "isn't installed in Ollama" in capsys.readouterr().err


def test_commit_state_reads_git():
    commit, changed = commit_state()
    assert commit is not None
    assert re.fullmatch(r"[0-9a-f]{40}", commit)
    assert isinstance(changed, bool)


def test_commit_is_unknown_without_git(run, monkeypatch):
    def no_git(*args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr(subprocess, "run", no_git)
    assert commit_state() == (None, None)
    assert run.main("--output", run.output) == 0
    header = run.lines()[0]
    assert (header["commit"], header["working_tree_changed"]) == (None, None)


def test_commit_is_unknown_outside_a_repository(monkeypatch, tmp_path):
    monkeypatch.setattr(score_answers, "ROOT", str(tmp_path))
    assert commit_state() == (None, None)
