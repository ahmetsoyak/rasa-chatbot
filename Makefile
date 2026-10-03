.DEFAULT_GOAL := help

.PHONY: help validate test-actions test-core test-core-e2e train run-actions run-bot frontend-check frontend-dev clean-local

help:
	@echo "Available targets: validate, test-actions, test-core, test-core-e2e, train, run-actions, run-bot, frontend-check, frontend-dev, clean-local"

validate:
	cd server && ../.venv310/bin/rasa data validate --config rasa/config.yml --domain rasa/domain.yml --data rasa/data

test-actions:
	.venv-test/bin/python -m pytest tests/test_actions.py -q

test-core:
	cd server && ../.venv310/bin/rasa test core --stories ../tests/test_stories.yml -m models/eco-travel.tar.gz --out ../results/core

test-core-e2e:
	cd server && ../.venv310/bin/rasa test core --stories ../tests/test_stories.yml -m models/eco-travel.tar.gz --e2e --out ../results/core_e2e

train:
	cd server && ../.venv310/bin/rasa train --config rasa/config.yml --domain rasa/domain.yml --data rasa/data --out models --fixed-model-name eco-travel

run-actions:
	cd server && ../.venv310/bin/rasa run actions --port 5055

run-bot:
	cd server && ../.venv310/bin/rasa run --credentials rasa/credentials.yml --endpoints rasa/endpoints.yml --enable-api --cors "*" -m models/eco-travel.tar.gz --port 5005

frontend-check:
	cd frontend && npm run lint && npm run build

frontend-dev:
	cd frontend && npm run dev -- --port 5173

# Removes ignored, reproducible local artefacts only. It never deletes source,
# cache data, environment files, or committed project material.
clean-local:
	git clean -Xdf -e .env
