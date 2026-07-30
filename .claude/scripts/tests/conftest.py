"""Shared pytest config for .claude/scripts/tests.

Redirects the gh name-index cache (iterate_cross_pricing.load_or_refresh_name_index)
to a per-session temp file so tests never read from or write fake-repo entries
into the production `.runs/gh-name-index.json` cache. Test modules that are run
directly (python3 <file>.py, no pytest) set the same env var at import time.
"""

import os
import tempfile

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolate_name_index_cache():
    prior = os.environ.get("ITERATE_CROSS_NAME_INDEX_CACHE")
    with tempfile.TemporaryDirectory() as td:
        os.environ["ITERATE_CROSS_NAME_INDEX_CACHE"] = os.path.join(td, "gh-name-index.json")
        yield
    if prior is None:
        os.environ.pop("ITERATE_CROSS_NAME_INDEX_CACHE", None)
    else:
        os.environ["ITERATE_CROSS_NAME_INDEX_CACHE"] = prior
