import os
import textwrap

import pytest

from rfc_qa import paths
from rfc_qa.chunk import Chunk
from rfc_qa.retrieval.keyword_index import SearchResult, build_index
from scripts.score_retrieval import (
    DEFAULT_GOLDEN,
    SEARCH_DEPTH,
    GoldenSetError,
    Label,
    Question,
    load_golden_set,
    main,
    rfcs_outside,
    score_question,
    summarize,
)

VALID = """
[[question]]
id       = "status-404"
kind     = "direct"
question = "What does a 404 response mean?"
expected = [{ rfc = 9110, section = "15.5.5", quote = "The 404 (Not Found) status code" }]

[[question]]
id       = "conditional-requests"
kind     = "multi-section"
question = "How do If-Match and If-None-Match differ?"
expected = [
    { rfc = 9110, section = "13.1.1", quote = "If-Match" },
    { rfc = 9110, section = "13.1.2", quote = "If-None-Match" },
]

[[question]]
id       = "tls13-resumption"
kind     = "stale-trap"
question = "How does a TLS 1.3 client resume an earlier session?"
expected = [{ rfc = 9846, section = "2.2", quote = "PSKs can also be established" }]
obsolete = [{ rfc = 8446, section = "2.2", replaced_by = 9846 }]

[[question]]
id       = "tls12-client-hello"
kind     = "version-specific"
question = "In TLS 1.2, what does the client send first?"
expected = [{ rfc = 5246, section = "7.4.1.2", replaced_by = 9846, quote = "ClientHello" }]

[[question]]
id       = "quic-streams"
kind     = "out-of-corpus"
question = "How does QUIC multiplex streams?"
"""


def _write(tmp_path, text):
    path = tmp_path / "golden.toml"
    path.write_text(textwrap.dedent(text))
    return str(path)


def _with(question):
    """A file holding one question, given as the body of a [[question]] table."""
    return "[[question]]\n" + textwrap.dedent(question)


# --- Loading and structure (task 2.1) ---


def test_valid_set_loads(tmp_path):
    questions = load_golden_set(_write(tmp_path, VALID))
    assert [q.kind for q in questions] == [
        "direct",
        "multi-section",
        "stale-trap",
        "version-specific",
        "out-of-corpus",
    ]
    assert questions[2] == Question(
        "tls13-resumption",
        "stale-trap",
        "How does a TLS 1.3 client resume an earlier session?",
        (Label(9846, "2.2", "PSKs can also be established"),),
        (Label(8446, "2.2", None, 9846),),
    )
    assert questions[4].expected == ()


def _head(kind, question="Q?"):
    return f'id = "a"\nkind = "{kind}"\nquestion = "{question}"\n'


def _expected(fields='rfc = 2, section = "1", quote = "x"'):
    return f"expected = [{{ {fields} }}]\n"


def _obsolete(fields='rfc = 1, section = "1", replaced_by = 2'):
    return f"obsolete = [{{ {fields} }}]\n"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            _head("lookup") + _expected(),
            "question 'a': 'kind' must be one of direct, multi-section, stale-trap, version-specific, "
            "out-of-corpus, not 'lookup'.",
        ),
        ('kind = "direct"\nquestion = "Q?"\n' + _expected(), "question 1 needs an 'id'."),
        (_head("direct", "  ") + _expected(), "question 'a' needs the question text in 'question'."),
        (_head("direct"), "question 'a': needs at least one expected section."),
        (
            _head("out-of-corpus") + _expected(),
            "question 'a': an out-of-corpus question has no expected sections.",
        ),
        (
            _head("direct") + _expected('rfc = 2, section = "1"'),
            "question 'a': expected section RFC 2 1 needs a 'quote'.",
        ),
        (
            _head("direct") + _expected('rfc = 2, section = "1", quote = " "'),
            "question 'a': expected 1 has an empty 'quote'.",
        ),
        (
            _head("direct") + _expected('rfc = 2, section = 1.2, quote = "x"'),
            "question 'a': expected 1 needs a section number in 'section', as a string such as \"3.4\".",
        ),
        (
            _head("direct") + _expected('rfc = "2", section = "1", quote = "x"'),
            "question 'a': expected 1 needs an RFC number in 'rfc'.",
        ),
        (
            _head("stale-trap") + _expected(),
            "question 'a': a stale-trap question needs at least one obsolete section.",
        ),
        (
            _head("direct") + _expected() + _obsolete(),
            "question 'a': only a stale-trap question lists obsolete sections.",
        ),
        (
            _head("stale-trap") + _expected() + _obsolete('rfc = 1, section = "1"'),
            "question 'a': obsolete section RFC 1 1 needs 'replaced_by'.",
        ),
        (
            _head("version-specific") + _expected(),
            "question 'a': expected section RFC 2 1 of a version-specific question needs 'replaced_by'.",
        ),
        (
            _head("direct") + _expected('rfc = 1, section = "1", quote = "x", replaced_by = 2'),
            "question 'a': only a version-specific question's expected sections have 'replaced_by'.",
        ),
        (
            _head("version-specific") + _expected('rfc = 1, section = "1", quote = "x", replaced_by = 1'),
            "question 'a': expected 1 can't be replaced by its own RFC.",
        ),
        (
            _head("direct") + _expected() + 'notes = "x"\n',
            "question 'a' has unknown fields: notes.",
        ),
        (
            _head("direct") + _expected('rfc = 2, section = "1", quote = "x", title = "y"'),
            "question 'a': expected 1 has unknown fields: title.",
        ),
    ],
)
def test_each_structure_rule_names_the_question(tmp_path, body, message):
    path = _write(tmp_path, _with(body))
    with pytest.raises(GoldenSetError) as excinfo:
        load_golden_set(path)
    assert str(excinfo.value) == f"Golden set {path!r}: {message}"


def test_duplicate_ids_are_rejected(tmp_path):
    question = 'id = "a"\nkind = "out-of-corpus"\nquestion = "Q?"\n'
    path = _write(tmp_path, _with(question) + "\n" + _with(question))
    with pytest.raises(GoldenSetError, match=r"question 'a' appears more than once\.$"):
        load_golden_set(path)


def test_a_file_with_no_questions_is_rejected(tmp_path):
    path = _write(tmp_path, "# nothing yet\n")
    with pytest.raises(GoldenSetError, match=r"no \[\[question\]\] tables\.$"):
        load_golden_set(path)


def test_malformed_toml_names_the_file_and_line(tmp_path):
    path = _write(tmp_path, "[[question]]\nid = \n")
    with pytest.raises(GoldenSetError) as excinfo:
        load_golden_set(path)
    assert str(excinfo.value).startswith(f"Failed to read golden set {path!r}: ")
    assert "line 2" in str(excinfo.value)


def test_missing_file(tmp_path):
    path = str(tmp_path / "missing.toml")
    with pytest.raises(GoldenSetError, match=r"^Failed to read golden set "):
        load_golden_set(path)


def test_rfcs_outside_the_corpus_are_named(tmp_path):
    questions = load_golden_set(_write(tmp_path, VALID))
    assert rfcs_outside(questions, {9110, 9846, 8446, 5246}) == []
    assert rfcs_outside(questions, {9110, 9846, 5246}) == [
        "question 'tls13-resumption': RFC 8446 isn't in the corpus."
    ]


# --- The repository's golden set (task 2.2) ---


def _corpus_numbers():
    corpus = paths.read_toml(paths.packaged_config_dir() / paths.CORPUS_FILE)
    return {entry["number"] for entry in corpus["rfcs"]}


def test_the_golden_set_has_a_valid_structure():
    questions = load_golden_set(DEFAULT_GOLDEN)
    assert questions


def test_the_golden_set_names_only_rfcs_in_the_corpus():
    assert rfcs_outside(load_golden_set(DEFAULT_GOLDEN), _corpus_numbers()) == []


# --- Scoring (task 3.1) ---


def _result(rfc, section, part=0):
    chunk = Chunk(f"rfc{rfc}-s{section}-p{part}", rfc, f"RFC {rfc}", "http", section, "Title", "Text.")
    return SearchResult(chunk, 1.0)


def _question(kind="direct", expected=((9110, "15.5"),), obsolete=(), qid="q"):
    replaced = 9999 if kind == "version-specific" else None
    return Question(
        qid,
        kind,
        "Q?",
        tuple(Label(rfc, section, "quote", replaced) for rfc, section in expected),
        tuple(Label(rfc, section, None, 9999) for rfc, section in obsolete),
    )


def test_correct_section_ranked_second():
    score = score_question(_question(), [_result(9110, "8.6"), _result(9110, "15.5")])
    assert score.rank == 2


def test_rank_counts_chunks_not_sections():
    results = [_result(9110, "8.6", 0), _result(9110, "8.6", 1), _result(9110, "15.5")]
    assert score_question(_question(), results).rank == 3


def test_a_subsection_does_not_match():
    assert score_question(_question(), [_result(9110, "15.5.5")]).rank is None


def test_another_rfc_with_the_same_section_does_not_match():
    assert score_question(_question(), [_result(7231, "15.5")]).rank is None


def test_any_expected_section_counts():
    question = _question(expected=((9325, "3.4"), (9846, "2.2")))
    assert score_question(question, [_result(9110, "1"), _result(9846, "2.2")]).rank == 2


def test_not_found_in_the_first_20():
    results = [_result(9110, str(i)) for i in range(1, 21)] + [_result(9110, "15.5")]
    score = score_question(_question(), results)
    assert score.rank is None
    assert score.reciprocal_rank == 0.0


def test_found_at_20():
    results = [_result(9110, str(i)) for i in range(1, 20)] + [_result(9110, "15.5")]
    assert score_question(_question(), results).rank == SEARCH_DEPTH


def test_totals():
    questions = [_question(qid=str(i)) for i in range(3)]
    scores = [
        score_question(questions[0], [_result(9110, "15.5")]),
        score_question(questions[1], [_result(9110, "1"), _result(9110, "2"), _result(9110, "15.5")]),
        score_question(questions[2], [_result(9110, "1")]),
    ]
    summary = summarize(scores)
    assert summary.scored == 3
    assert summary.hits == {1: 1, 5: 2}
    assert summary.mean_reciprocal_rank == pytest.approx((1 + 1 / 3 + 0) / 3)


TRAP = _question("stale-trap", expected=((9846, "2.2"),), obsolete=((8446, "2.2"),))


def test_trap_caught():
    score = score_question(TRAP, [_result(8446, "2.2"), _result(9846, "2.2")])
    assert (score.rank, score.obsolete_rank, score.trap_caught) == (2, 1, True)


def test_trap_caught_with_no_expected_result():
    score = score_question(TRAP, [_result(9110, "1"), _result(8446, "2.2")])
    assert (score.rank, score.obsolete_rank, score.trap_caught) == (None, 2, True)


def test_trap_avoided():
    score = score_question(TRAP, [_result(9846, "2.2"), _result(8446, "2.2")])
    assert score.trap_caught is False


def test_trap_with_neither_in_the_results_is_not_caught():
    assert score_question(TRAP, [_result(9110, "1")]).trap_caught is False


def test_obsolete_rank_only_counts_for_traps():
    question = _question(expected=((9110, "1"),))
    assert score_question(question, [_result(9110, "1")]).trap_caught is False


def test_trap_rate():
    caught = score_question(TRAP, [_result(8446, "2.2"), _result(9846, "2.2")])
    avoided = score_question(TRAP, [_result(9846, "2.2")])
    direct = score_question(_question(), [_result(9110, "15.5")])
    summary = summarize([caught, avoided, direct])
    assert (summary.traps, summary.traps_caught) == (2, 1)


def test_totals_by_kind():
    version = _question("version-specific", expected=((5246, "7.4.1.2"),))
    scores = [
        score_question(TRAP, [_result(9846, "2.2")]),
        score_question(TRAP, [_result(9110, "1"), _result(9846, "2.2")]),
        score_question(version, [_result(5246, "7.4.1.2")]),
        score_question(version, [_result(9110, "1")]),
    ]
    by_kind = {totals.kind: totals for totals in summarize(scores).by_kind}
    assert list(by_kind) == ["stale-trap", "version-specific"]
    assert (by_kind["stale-trap"].scored, by_kind["stale-trap"].hits) == (2, {1: 1, 5: 2})
    assert (by_kind["version-specific"].scored, by_kind["version-specific"].hits) == (2, {1: 1, 5: 1})


def test_skipped_questions_are_counted_and_left_out_of_totals():
    summary = summarize([score_question(_question(), [_result(9110, "15.5")])], skipped=2)
    assert (summary.skipped, summary.scored, summary.hits) == (2, 1, {1: 1, 5: 1})


def test_out_of_corpus_questions_are_not_scored():
    with pytest.raises(ValueError, match="out-of-corpus"):
        score_question(_question("out-of-corpus", expected=()), [])


def test_no_scores():
    summary = summarize([], skipped=2)
    assert (summary.scored, summary.mean_reciprocal_rank, summary.by_kind) == (0, 0.0, ())


# --- The command line (task 3.2) ---

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

GOLDEN = """
[[question]]
id       = "not-found"
kind     = "direct"
question = "What does 404 not found mean?"
expected = [{ rfc = 9110, section = "15.5.5", quote = "No representation." }]

[[question]]
id       = "body-size"
kind     = "direct"
question = "How is the body size given?"
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


@pytest.fixture
def data_dir(tmp_path):
    directory = tmp_path / "data"
    directory.mkdir()
    build_index(INDEX_CHUNKS, {"embedding_model_name": "test"}, str(directory / paths.INDEX_FILE))
    return str(directory)


def _run(data_dir, golden, *extra):
    return main(["--data-dir", data_dir, "--golden", golden, *extra])


def test_main_prints_the_table_and_totals(data_dir, tmp_path, capsys):
    golden = _write(tmp_path, GOLDEN)
    assert _run(data_dir, golden) == 0
    out, err = capsys.readouterr()
    index = os.path.join(data_dir, paths.INDEX_FILE)
    assert out == textwrap.dedent(f"""\
        Retrieval scores for 3 questions, from {index} (search depth 20)

        id          kind              rank  trap
        not-found   direct               1  -
        body-size   direct               -  -
        resumption  stale-trap           2  yes

        hit@1  1/3 (0.33)    hit@5  2/3 (0.67)    MRR 0.50    trap rate 1/1 (1.00)

        kind              hit@1          hit@5
        direct            1/2 (0.50)     1/2 (0.50)
        stale-trap        0/1 (0.00)     1/1 (1.00)

        Skipped 1 out-of-corpus questions.
        """)
    assert err == ""


def test_main_exits_0_when_nothing_is_found(data_dir, tmp_path, capsys):
    golden = _write(
        tmp_path, _with(_head("direct", "zebra") + _expected('rfc = 9110, section = "8.6", quote = "x"'))
    )
    assert _run(data_dir, golden) == 0
    out = capsys.readouterr().out
    assert "hit@1  0/1 (0.00)    hit@5  0/1 (0.00)    MRR 0.00    trap rate -" in out


def test_main_stops_before_scoring_for_a_label_missing_from_the_index(data_dir, tmp_path, capsys):
    golden = _write(tmp_path, _with(_head("direct") + _expected('rfc = 9110, section = "99.9", quote = "x"')))
    assert _run(data_dir, golden) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err.splitlines() == [
        "question 'a': RFC 9110 section 99.9 isn't in the index.",
        "Nothing was scored. Fix the labels, or rebuild the index with rfc-ingest.",
    ]


def test_main_without_an_index_names_rfc_ingest(tmp_path, capsys):
    golden = _write(tmp_path, GOLDEN)
    assert _run(str(tmp_path / "empty"), golden) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err.splitlines() == [
        f"Index not found: {str(tmp_path / 'empty' / paths.INDEX_FILE)!r}. Run rfc-ingest to build it."
    ]


def test_main_reports_a_bad_golden_set_in_one_line(data_dir, tmp_path, capsys):
    golden = _write(tmp_path, _with(_head("lookup")))
    assert _run(data_dir, golden) == 1
    err = capsys.readouterr().err
    assert len(err.splitlines()) == 1
    assert "'kind' must be one of" in err


def test_main_reads_the_data_directory_from_the_environment(data_dir, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(paths.DATA_DIR_ENV, data_dir)
    assert main(["--golden", _write(tmp_path, GOLDEN)]) == 0
    assert f"from {os.path.join(data_dir, paths.INDEX_FILE)} " in capsys.readouterr().out


def test_v_shows_each_questions_top_results(data_dir, tmp_path, capsys):
    assert _run(data_dir, _write(tmp_path, GOLDEN), "-v") == 0
    err = capsys.readouterr().err.splitlines()
    assert "INFO rfc_qa.score_retrieval: resumption: How is a session resumption done?" in err
    assert "INFO rfc_qa.score_retrieval:   1. RFC 8446 section 2.2: Resumption" in err


def test_without_v_nothing_is_logged(data_dir, tmp_path, capsys):
    assert _run(data_dir, _write(tmp_path, GOLDEN)) == 0
    assert capsys.readouterr().err == ""
