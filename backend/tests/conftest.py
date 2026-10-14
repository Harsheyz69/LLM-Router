"""
Shared test fixtures and configuration.
"""

from __future__ import annotations

import os

import pytest

# Ensure tests don't accidentally use real credentials
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("GOOGLE_API_KEY", "")
os.environ.setdefault("APP_ENV", "testing")


@pytest.fixture
def anyio_backend():
    return "asyncio"
