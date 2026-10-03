# Testing the Eco-Travel Advisor

This project relies on Rasa's own train/test tooling rather than a hand-built
held-out NLU test set, since `rasa test nlu` can automatically cross-validate
against `data/nlu.yml` (Rasa performs the train/test split internally).

## Environment note

Rasa 3.6.x requires Python >=3.8,<3.11. Create the venv with a compatible
interpreter, e.g.:

```bash
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run `tests/test_actions.py` (pytest) in a **separate** virtualenv from the
one above — installing pytest 9.x into the same venv as `rasa` upgrades
`packaging` past the `<21.0` ceiling rasa needs, breaking `rasa` imports:

```bash
python3.10 -m venv .venv-test
source .venv-test/bin/activate
pip install -r requirements-dev.txt -r actions/requirements-actions.txt
pytest tests/test_actions.py -v
```

## NLU testing (cross-validation)

Rasa can k-fold cross-validate the NLU pipeline directly against the training
data in `data/nlu.yml` without needing a separate held-out file:

```bash
rasa test nlu --nlu data/nlu.yml --cross-validation
```

This reports intent classification and entity extraction metrics (F1,
precision, recall, and a confusion matrix) averaged across folds.

If you want a genuine held-out test set instead of cross-validation, split
`data/nlu.yml` (e.g. an 80/20 split) into `data/nlu.yml` (train) and a new
`tests/nlu_test_examples.yml` (test) using the same YAML format shown in
`data/nlu.yml`, then run:

```bash
rasa test nlu --nlu tests/nlu_test_examples.yml --model models/<model>.tar.gz
```

## Core / dialogue management testing

Test story coverage (happy path + edge cases: ambiguous input triggering
first-stage fallback, fallback escalating to human handover, direct human
advisor requests, and out-of-scope redirection) lives in
`tests/test_stories.yml` and is run with:

```bash
rasa test core --stories tests/test_stories.yml
```

This produces a `results/` directory with a story-level pass/fail report and
a confusion matrix for predicted vs. expected actions.

## End-to-end / combined test run

To run both NLU and Core tests together against a trained model:

```bash
rasa train
rasa test --stories tests/test_stories.yml --nlu data/nlu.yml
```

## What the edge cases in test_stories.yml cover

- **Happy path**: full multi-turn trip intake via `trip_planning_form`
  through to a ranked recommendation summary.
- **Fallback recovery**: a single low-confidence turn triggers
  `action_default_fallback` (stage 1 re-prompt), and the user's next message
  is understood normally.
- **Fallback escalation**: two consecutive low-confidence turns trigger
  `action_default_fallback` twice, which internally escalates to
  a consent request for `action_human_handover` (stage 2). No advisor package
  is created until the user explicitly confirms.
- **Direct human advisor request**: a clear, high-confidence request for a
  human advisor bypasses fallback entirely and escalates immediately.
- **Out-of-scope redirection**: an out-of-scope message is handled
  gracefully and the user is able to pivot back into trip planning.

## Measured results (this trained model)

- **Core** (`rasa test core --stories tests/test_stories.yml`): 5/5 test
  stories pass, F1 / precision / accuracy all 1.00.
- **NLU** (`rasa test nlu --nlu data/nlu.yml --cross-validation --folds 3`):
  intent accuracy ~0.76, F1 ~0.75 on the held-out folds (up from an initial
  ~0.69/0.68 after expanding training examples per intent and sharpening
  wording on the most-confused intent pairs, e.g. `ask_transport_options` vs
  `ask_carbon_footprint`). Train-set accuracy is 1.00, so there is still a
  meaningful train/test gap — expected given ~20 intents trained from
  scratch (no pretrained embeddings) on a few hundred examples total. See
  `results/nlu/intent_errors.json` and `intent_confusion_matrix.png` for the
  residual error breakdown; `out_of_scope` (a catch-all bucket) accounts for
  the largest single share of remaining errors. Entity extraction (DIET) is
  markedly weaker than intent classification on the same small dataset — a
  known, expected pattern, not a wiring bug.
- Directions for improvement if more time/data were available: (1) collect
  real user utterances rather than synthetic examples, (2) merge or
  restructure semantically overlapping intents, (3) enable the commented
  `LanguageModelFeaturizer` + DistilBERT pipeline in `config.yml` for pretrained
  embeddings, which typically generalises much better on small datasets than
  the sparse CountVectors features used here.

## User-test plan for the report

The brief labels user testing as optional, but testing is worth 15%; include
this small, reproducible study in the report. Recruit 5-8 adults who have
planned a trip in the last year. Do not collect names, emails, exact travel
dates or GPS coordinates. Give each participant the same three tasks: plan a
budget city break, compare a high-emission route with a lower-carbon option,
and request a human advisor then accept or decline the consent prompt.

Record task completion (success/fail), elapsed time, clarification/fallback
count and any critical issue. Afterwards, ask five 1-5 Likert questions:
clarity, trust in carbon information, usefulness of recommendations, ease of
handover consent, and overall ease of use. Report median and range (not just
the mean), a short thematic summary of comments, and one design change made in
response. State plainly that this is a formative convenience sample rather
than a statistically generalisable study.
