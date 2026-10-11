import logging
import os
import tempfile

import pytest

_tmp = tempfile.mkdtemp()
os.environ.update({"DATABASE_URL": f"sqlite:///{_tmp}/test.db", "LLM_PROVIDER": "none"})
os.environ.pop("MCP_TOKENS", None)
logging.disable(logging.INFO)


@pytest.fixture()
def reg():
    from itsm_mcp.eval.run import fresh_registry
    return fresh_registry(11)
