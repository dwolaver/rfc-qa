# Changelog

[Back to README](README.md)

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html). Each change adds its entry under
[Unreleased], and a release turns that section into the version's, as described in
[Releasing](docs/releasing.md).

## [Unreleased]

### Added

- A golden question set, `eval/golden.toml`, of questions labeled with the RFC sections that answer
  them. It includes questions an obsolete RFC also matches, and questions about earlier versions
  such as TLS 1.2.
- `scripts/score_retrieval.py`, which scores keyword search against the golden set with hit@1,
  hit@5, mean reciprocal rank and the rate at which an obsolete RFC outranks the current one, in
  total and for each kind of question. [Evaluation](docs/evaluation.md) explains the format, how to
  add a question and how to read the scores.
- More questions in the golden set, including more stale-trap questions. When several RFCs
  obsolete the same RFC, a label's `replaced_by` names the one with the latest publication date,
  and the lowest-numbered when they share a month, as [Evaluation](docs/evaluation.md) describes.
- `scripts/score_answers.py`, which asks each golden question through `query()` and scores the answer
  by its citations: whether it cites a section that answers the question, whether a stale-citation
  trap cites the obsolete RFC, and whether a question the corpus doesn't answer is declined. Each miss
  is put down to retrieval or to generation, and each run is saved as JSON Lines. It needs Ollama, and
  runs locally on demand.
- `QueryResponse.answer_rejected`, which is true when a not-found result came from an answer the
  service rejected, because it cited no passage the model was sent or was blank, rather than from the
  model declining.

### Changed

- With `-v`, `rfc-query` logs a rejected answer as rejected. It used to say that the model found no
  answer.

## [0.2.0] - 2026-11-21

### Added

- The `rfc-ingest`, `rfc-query` and `rfc-search` commands, installed with the project, in place of
  running `ingest.py`, `query.py` and `keyword_index.py` from the repository root.
- `--config-dir` and `RFC_QA_CONFIG_DIR` to choose the configuration directory, and `OLLAMA_BASE_URL`
  to override the Ollama address.
- `--data-dir` and `RFC_QA_DATA_DIR` to choose the data directory, for every command and for
  `query(..., data_dir=...)`.
- The commands work from a regular install, outside a checkout: the default configuration is
  installed with the package. `platformdirs` is a new runtime dependency.
- `-v` and `-vv` on every command, to show the library's progress and details on standard error.
  The library logs through `logging` and stays silent unless the program configures it.
- A comment in each configuration file describing every section and setting, with its unit or
  allowed values.
- ruff, mypy and a pre-commit hook, run in CI as the `quality` check.
- Secret scanning with gitleaks, in the pre-commit hook and in CI as the `secrets` check.
- Install tests, which build a wheel and run the commands from a fresh virtual environment.
- The MIT license, and an account in the README of how the project was built.
- `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md` and guides in `docs/`, linked from a shorter
  README, with a test that checks the links between them.

### Changed

- The project is named `rfc-qa` in its documents, matching the package and the commands, in place of
  "Document Q&A Service".
- The code is in the `rfc_qa` package, with subpackages for ingestion, retrieval and generation, in
  the `src/` layout. The package is only imported as installed.
- The configuration files are TOML: `corpus.toml`, `ingest.toml` and `query.toml`.
- The default data directory is the user data directory for `rfc-qa`, such as
  `~/.local/share/rfc-qa` on Linux, and the index is always `index.db` in it.
- Failures raise one family of errors from `rfc_qa.errors`, all subclasses of `RfcQaError`, and the
  commands report each one once, as one line on standard error with exit status 1.
  `download_rfc`, `build_index`, `search` and `read_metadata` raise instead of returning `False` or
  `None`, and `query()` raises `TypeError` for a query that isn't a string.
- The package and the scripts are type-checked strictly, and the lint rules also cover outdated
  syntax, logging calls, long lines, simpler constructs, ruff's own checks and pytest's conventions.
- Architecture updates start from the release tag, so they still work after a squash merge.
- The tests mirror the package's layout, and run with bare `pytest`.
- OpenSpec is updated to 2.1.

### Fixed

- When Ollama answers with JSON that isn't an object, such as a list, `query()` returns
  `MODEL_INVALID_RESPONSE` instead of raising an uncaught `AttributeError`.

### Removed

- The JSON configuration files, which are no longer read.
- `index_path` in the query configuration, and `data/` at the repository root as the default data
  directory.

## [0.1.0] - 2026-11-08

### Added

- An RFC downloader that checks each download and writes it atomically.
- Ingestion of a curated corpus of HTTP, TLS and TCP RFCs into sections and chunks, with a SQLite
  FTS5 keyword index.
- Answers to questions from a local model served by Ollama, with citations checked against the
  retrieved passages.
- `ARCHITECTURE.md`, generated from the code by a pinned model.
- CI that runs the tests on every pull request, and a check that a pull request's OpenSpec change
  is archived before it merges.

[Unreleased]: https://github.com/dwolaver/rfc-qa/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/dwolaver/rfc-qa/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/dwolaver/rfc-qa/releases/tag/v0.1.0
