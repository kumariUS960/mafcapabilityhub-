import copy

from src.registry import USERS, discover, load_registry, validate_capability


def names(result):
    return [c["name"] for c in result.allowed]


def test_support_user_can_use_support_tools():
    r = discover("latest incident and server status", USERS["asha"])
    assert "get_incidents" in names(r)
    assert "get_server_status" in names(r)


def test_security_tool_blocked_for_support_user():
    r = discover("any security alerts", USERS["asha"])
    assert names(r) == []
    assert any(n == "check_security_alerts" for n, _ in r.blocked)


def test_security_tool_allowed_for_security_user():
    r = discover("any security alerts", USERS["meera"])
    assert names(r) == ["check_security_alerts"]


def test_data_user_blocked_from_support_tools():
    r = discover("latest incident", USERS["ravi"])
    assert names(r) == []
    assert r.blocked


def test_everyone_group_tool_available_to_all():
    for user in USERS.values():
        assert "search_documents" in names(discover("find the leave policy", user))


def test_disabled_capability_never_runs():
    caps = load_registry()
    for c in caps:
        if c["name"] == "get_incidents":
            c["status"] = "disabled"
    r = discover("latest incident", USERS["asha"], caps)
    assert "get_incidents" not in names(r)
    assert ("get_incidents", "status is disabled") in r.blocked


def test_deprecated_capability_never_runs():
    caps = load_registry()
    for c in caps:
        if c["name"] == "query_sales_data":
            c["status"] = "deprecated"
    r = discover("sales revenue", USERS["ravi"], caps)
    assert names(r) == []


def test_unknown_request_matches_nothing():
    r = discover("what is the weather today", USERS["asha"])
    assert names(r) == [] and r.blocked == []


def test_new_capability_found_without_code_change():
    caps = load_registry()
    caps.append(
        {
            "id": "cap-099", "name": "get_weather", "description": "Check the weather forecast and temperature",
            "keywords": ["weather", "forecast", "rain"], "type": "function", "endpoint": "local://weather",
            "domain": "Weather", "environment": "prod", "allowed_groups": ["Everyone"],
            "classification": "public", "status": "active", "version": "1.0.0", "owner": "platform-team",
            "requires_approval": False,
        }
    )
    r = discover("what is the weather today", USERS["asha"], caps)
    assert names(r) == ["get_weather"]


def test_high_impact_capability_is_flagged_for_approval():
    r = discover("restart the stuck server", USERS["asha"])
    flagged = {c["name"]: c["requires_approval"] for c in r.allowed}
    assert flagged.get("restart_server") is True


def test_validation_accepts_good_capability_and_rejects_bad_one():
    good = copy.deepcopy(load_registry()[0])
    assert validate_capability(good) == []
    bad = dict(good, endpoint="abc", version="one", owner="")
    errors = validate_capability(bad)
    assert len(errors) == 3
