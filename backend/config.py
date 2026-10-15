"""Shared settings: the model (gpt-6-luna via Portkey), file paths, and run limits."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
MCP_SERVER_SCRIPT = ROOT / "mcp_server" / "server.py"
MCP_PYTHON = ROOT / ".venv" / "bin" / "python"
AUDIT_PATH = Path(os.getenv("CAMPUS_AUDIT_PATH", ROOT / "output" / "audit_trail.json"))
# Working database (what the MCP server reads and writes) and the untouched
# original it is reset from. Same env overrides as mcp_server/server.py.
WORKING_DB_PATH = Path(os.getenv("CAMPUS_DB_PATH", ROOT / "data" / "campus_customs_new.db"))
ORIGINAL_DB_PATH = Path(os.getenv("CAMPUS_ORIGINAL_DB_PATH", ROOT / "data" / "campus_customs.db"))
APPROVALS_ARCHIVE_DIR = Path(os.getenv("CAMPUS_APPROVALS_ARCHIVE_DIR", ROOT / "output" / "approvals_archive"))

# The assignment requires every AI agent to use gpt-6-luna through Portkey.
MODEL_NAME = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"

# --- Run limits (stop runaway loops and cost) ------------------------------
# One agent run: at most this many model requests and tool calls.
AGENT_REQUEST_LIMIT = 8
AGENT_TOOL_CALLS_LIMIT = 12
AGENT_TOTAL_TOKENS_LIMIT = 60_000
# Whole team run (Boss plus every delegation): shared budget across all agents.
TEAM_REQUEST_LIMIT = 30
TEAM_TOTAL_TOKENS_LIMIT = 200_000
# Longest reply a single model request may produce.
MAX_OUTPUT_TOKENS_PER_REQUEST = 3_000
# Delegation: Boss is depth 0, a specialist it calls is depth 1, and a
# specialist that specialist consults is depth 2. Nothing deeper is allowed.
MAX_DELEGATION_DEPTH = 2
MAX_DELEGATIONS_PER_RUN = 10

MODEL_SETTINGS = ModelSettings(max_tokens=MAX_OUTPUT_TOKENS_PER_REQUEST)

# PORTKEY_API_KEY lives in the shared .env a few folders up (AI code/.env);
# find_dotenv searches parent folders from the working directory until it finds it.
load_dotenv(find_dotenv(usecwd=True))
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")


@lru_cache(maxsize=1)
def get_model() -> OpenAIResponsesModel:
    """The one model every agent uses: gpt-6-luna through Portkey."""
    api_key = os.getenv("PORTKEY_API_KEY")
    if not api_key:
        raise RuntimeError("PORTKEY_API_KEY was not found in the environment or .env")
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=PORTKEY_BASE_URL,
        default_headers={"x-portkey-provider": "openai"},
        timeout=90.0,
    )
    return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))
