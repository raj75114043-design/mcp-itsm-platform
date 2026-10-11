from itsm_mcp.eval.run import contract_check


def test_tool_contract_unchanged():
    res = contract_check()
    assert res["passed"], res
