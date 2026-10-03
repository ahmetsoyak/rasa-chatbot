---
title: Eco Travel Advisor
emoji: 🌍
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
---

# Eco-Travel Advisor

A Rasa-based conversational assistant that helps travellers compare lower-carbon transport, find accommodation data, and request human support for complex trips.

## Project layout

| Path | Purpose |
| --- | --- |
| `server/rasa/` | Rasa configuration, domain, credentials, and dialogue data |
| `server/actions/` | Rasa custom actions and their data-service layer |
| `frontend/` | React chat interface |
| `server/mock_data/` | Carbon factors, place names, and offset-programme references |
| `tests/` | Unit, dialogue, latency, and UI checks |
| `docker/` | Docker Compose and Hugging Face container configuration |

Generated local directories such as `.venv310/`, `.venv-test/`, `.rasa/`, `frontend/node_modules/`, `models/`, and `results/` are intentionally ignored by Git. They are not part of the submitted source tree.

## Quick start

The project uses two Python environments. Do not mix them:

```bash
# Rasa train/run/test environment
cd server
../.venv310/bin/rasa train --config rasa/config.yml --domain rasa/domain.yml --data rasa/data --out models --fixed-model-name eco-travel
../.venv310/bin/rasa run actions --port 5055
../.venv310/bin/rasa run --credentials rasa/credentials.yml --endpoints rasa/endpoints.yml --enable-api --cors "*" -m models/eco-travel.tar.gz --port 5005

# React interface, in another terminal
cd frontend && npm run dev -- --port 5173
```

Copy `.env.example` to `.env` and provide local values for the documented variables before using live providers. Never commit `.env`.

## Common commands

Use the included Makefile where available:

```bash
make validate
make test-actions
make test-core
make frontend-check
```

See `tests/README.md` for the complete test matrix and `docs/DEPLOYMENT.md` for deployment notes.

## Data and sustainability claims

Accommodation records are fetched from OpenStreetMap and are not presented as eco-certified unless the evidence supports that claim. Proxy indicators are labelled in the interface. Carbon estimates use the documented DESNZ 2026 factors and the Climatiq selector in `server/mock_data/carbon_factors.json`.

## Development notes

- `server/actions/services/` owns API access and data transformations.
- The root `Dockerfile` runs the React frontend, Rasa, and the action server in one non-root Hugging Face Space container.
