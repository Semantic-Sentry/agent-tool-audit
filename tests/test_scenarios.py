from types import SimpleNamespace

from ata.scenarios import SCENARIOS


def test_scenario_policy_matches_tool_schemas():
    for name, scenario in SCENARIOS.items():
        schema_names = {t["function"]["name"] for t in scenario.tool_schemas}
        policy_names = set(scenario.policy.tools.keys())
        assert schema_names == policy_names, f"{name}: schema/policy tool name mismatch"


def test_scenario_build_tools_returns_matching_callables():
    dummy_sink = SimpleNamespace(port=0)
    for name, scenario in SCENARIOS.items():
        tools = scenario.build_tools("seeded text CANARY-TEST", "CANARY-TEST", dummy_sink)
        schema_names = {t["function"]["name"] for t in scenario.tool_schemas}
        assert set(tools.keys()) == schema_names, f"{name}: build_tools keys mismatch"
        for fn in tools.values():
            assert callable(fn)


def test_scenario_build_messages_returns_valid_structure():
    for name, scenario in SCENARIOS.items():
        messages = scenario.build_messages("seeded text")
        assert isinstance(messages, list) and len(messages) >= 2
        assert all("role" in m and "content" in m for m in messages)
        assert messages[0]["role"] == "system"
        assert messages[-1]["role"] == "user"
