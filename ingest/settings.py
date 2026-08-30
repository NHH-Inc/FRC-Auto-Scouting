"""Load host-only configuration before any service module reads environment variables.

``ingest/.env`` is deliberately ignored by Git because it holds the managed Postgres password,
TBA key and (eventually) the Sheets credential path. Loading it here rather than in ``run.ps1``
means direct ``uvicorn ingest.main:app`` launches behave exactly like the helper script.
"""

from pathlib import Path

from dotenv import load_dotenv


ENV_PATH = Path(__file__).with_name(".env")
# Respect explicit environment variables from a CI runner or service manager. They are safer
# than silently replacing a deployed secret with a developer's local file.
load_dotenv(ENV_PATH, override=False)
