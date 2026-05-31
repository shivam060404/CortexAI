from backend.auth.api_keys import api_key_matches, generate_api_key_pair, hash_api_key
from backend.core import graph as graph_module


def test_generated_api_key_is_hashed_for_storage():
    raw_key, stored_value = generate_api_key_pair()

    assert raw_key.startswith("ctx_")
    assert stored_value == hash_api_key(raw_key)
    assert stored_value != raw_key
    assert api_key_matches(raw_key, stored_value)


def test_api_key_matcher_supports_legacy_plaintext_values():
    raw_key, _ = generate_api_key_pair()

    assert api_key_matches(raw_key, raw_key)


def test_cleanup_session_preserves_latest_metrics_snapshot():
    session_id = "metric-session"

    class FakeGuard:
        def metrics(self):
            return {"tokens_used": 321, "tool_calls_count": 7}

    graph_module._session_guards[session_id] = FakeGuard()
    graph_module.cleanup_session(session_id)

    assert graph_module.get_execution_metrics(session_id) == {
        "tokens_used": 321,
        "tool_calls_count": 7,
    }
