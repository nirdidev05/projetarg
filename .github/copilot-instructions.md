# Copilot instructions for projetarg

## Project overview
This repository is a multi-part argumentation and discussion-analysis project:

- Part 1: ABA / ABA+ argumentation framework logic in `aba.py`, with a Streamlit UI in `app.py`.
- Part 2: Kialo discussion export parsing and relation-analysis tooling in `part2_kialo.py` and `part2_relations.py`.
- Part 3: exploratory analysis in `part3.ipynb` for h-categorizer sampling and projected heat-map / convex-hull stability.

The README is the main source of domain intent and usage examples. When changing behavior, prefer preserving the documented formats and examples rather than inventing new conventions.

## Build, test, and validation commands
The project is Python-based and expects a local virtual environment. Use the repo venv rather than a global pytest install.

- Create or refresh dependencies:
  - `.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt -r .\requirements-part2.txt`
- Run the full test suite:
  - `.\.venv\Scripts\python.exe -m pytest -q`
- Run a single test file:
  - `.\.venv\Scripts\python.exe -m pytest -q test_aba.py`
  - `.\.venv\Scripts\python.exe -m pytest -q test_part2.py`
- Run a single test or keyword subset:
  - `.\.venv\Scripts\python.exe -m pytest -q test_aba.py -k reverse`
  - `.\.venv\Scripts\python.exe -m pytest -q test_part2.py -k discovery`
- Start the Streamlit app for Part 1:
  - `.\.venv\Scripts\streamlit run app.py`

There is no dedicated lint config or CI workflow in this repo. Validation is driven primarily by pytest, with the notebook and app behavior checked through the existing tests and the README examples.

## High-level architecture

### Part 1: ABA engine
`aba.py` is the core implementation. It contains:

- parsing of the ABA text format (`L:`, `A:`, `C(x):`, `[rN]: ...`, `PREF:`)
- validation (`ABAError` on malformed framework syntax)
- flat / non-circular / atomic conversions
- argument generation and attack generation
- preference-aware normal and reverse attacks
- helper functions such as `weighted_h_categorizer`

The logic is intentionally structured around the formal ABA / ABA+ definitions used in the project documentation. Changes here affect both the notebook and the Streamlit app, so keep behavior consistent with the documented examples and tests.

### Part 2: Kialo dataset pipeline
`part2_kialo.py` focuses on:

- fetching discussion listings from the Kialo API
- validating the listing structure and export metadata
- downloading official exports
- parsing discussion trees and relation labels
- recording failures instead of silently dropping invalid data

`part2_relations.py` focuses on:

- constructing candidate parent/child pairs and discussion splits
- feature extraction and evaluation metrics
- TF-IDF and logistic-regression baselines
- leakage-aware splits so that whole discussions stay together

This part is more data-science and ETL-oriented than the ABA engine; tests validate exact parser behavior and ranking/metric semantics.

### Part 3: h-categorizer experiment
`part3.ipynb` is a numerical experiment notebook. It samples intrinsic weights for argumentation frameworks, projects them into two dimensions, and compares heat maps and convex hull areas across framework shapes and sample sizes.

If you modify the experiment or re-run it, keep the fixed-seed reference sample and projection strategy consistent with the notebook logic; otherwise the comparisons become hard to interpret.

## Project conventions and non-obvious patterns

- Follow the README’s ABA text format exactly. The parser is strict and intentionally rejects malformed syntax.
- In `ABAFramework.from_text`, lines beginning with `%` are comments, and `##` section headers are ignored.
- Preserve exact string output for rules and arguments where tests assert specific representations (for example, `[r1]: ...` and argument IDs).
- Keep the “normal vs reverse” attack semantics aligned with the README and the tests; the preference logic is central to the project and not a generically optional feature.
- For Part 2, assume discussion-level leakage is important: keep train/test splits by whole `discussion_id`, not by individual rows, and avoid silently dropping malformed exports.
- In notebook-style analysis work, prefer reproducible seeds and deterministic sampling to maintain comparability across runs.
- Do not treat the README and tests as optional documentation; they define the intended behavior more strongly than the file names alone.

## Editing guidance

- Prefer surgical, local changes. This repo has small, clearly bounded modules; broad refactors are usually unnecessary.
- When changing parser or algorithmic behavior, validate with the nearest relevant pytest targets first, then widen only if needed.
- If you modify the notebooks or data-processing code, check the associated tests and keep outputs deterministic when they are part of the project artifacts.
- When adding new behavior, add or update tests in the same area rather than relying only on manual notebook checks.
