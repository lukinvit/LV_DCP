# Deployment notes

Docker compose brings up Postgres, Redis, and the API. The API container
is built from `pyproject.toml` and runs `uvicorn app.main:app`.
