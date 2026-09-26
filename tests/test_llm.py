import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.llm.base import LLMError, LLMRefusalError, LLMTruncatedError, LLMUsage
from pipeline.llm.claude import ClaudeProvider
from pipeline.llm.factory import create_provider
from pipeline.llm.schema_tools import to_structured_output_schema
from pipeline.llm.usage_log import append_usage, estimate_cost
from pipeline.schema_validation import SCHEMA_NAMES, load_schema

# --- structured output schema ------------------------------------------------

UNSUPPORTED = {"minLength", "maxLength", "minimum", "maximum", "pattern", "minItems", "maxItems", "$schema"}


def walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_structured_schema_is_api_compatible(name: str) -> None:
    out = to_structured_output_schema(load_schema(name))
    for node in walk(out):
        assert not (UNSUPPORTED & set(node)), node
        assert not isinstance(node.get("type"), list), node
        if node.get("type") == "object" and "properties" in node:
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])


def test_structured_schema_does_not_mutate_input() -> None:
    original = load_schema("research")
    snapshot = json.dumps(original, sort_keys=True)
    to_structured_output_schema(original)
    assert json.dumps(original, sort_keys=True) == snapshot


def test_nullable_type_becomes_any_of() -> None:
    out = to_structured_output_schema({"type": "object", "properties": {"a": {"type": ["string", "null"], "minLength": 1}}})
    assert out["properties"]["a"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}


# --- Claude adapter (no network) --------------------------------------------

class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


class FakeMessages:
    def __init__(self, message):
        self.message = message
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(self.message)


def fake_client(message):
    client = SimpleNamespace(messages=FakeMessages(message), beta=SimpleNamespace(messages=FakeMessages(message)))
    return client


def message(text='{"ok": true}', stop_reason="end_turn", content=None):
    return SimpleNamespace(
        content=content if content is not None else [SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        stop_details=None,
        model="claude-opus-5",
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200,
                              cache_creation_input_tokens=0, cache_read_input_tokens=50),
        _request_id="req_test",
    )


SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def test_claude_sends_structured_output_request() -> None:
    client = fake_client(message())
    p = ClaudeProvider(model="claude-opus-5", effort="high", max_tokens=32000, fallbacks=None, client=client)
    result = p.generate_json(system="SYS", user="USER", schema=SCHEMA)
    call = client.messages.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"]["effort"] == "high"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert call["system"][0]["text"] == "SYS"
    assert call["messages"] == [{"role": "user", "content": "USER"}]
    assert result.data == {"ok": True}
    assert result.usage == LLMUsage(1000, 200, 0, 50)
    assert result.request_id == "req_test"


def test_claude_uses_beta_fallbacks_when_configured() -> None:
    client = fake_client(message())
    p = ClaudeProvider(model="claude-opus-5", effort="high", max_tokens=32000, fallbacks="default", client=client)
    p.generate_json(system="S", user="U", schema=SCHEMA)
    assert client.messages.calls == []
    call = client.beta.messages.calls[0]
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]


def test_claude_reads_text_after_fallback_block() -> None:
    content = [SimpleNamespace(type="fallback"), SimpleNamespace(type="thinking", thinking=""),
               SimpleNamespace(type="text", text='{"ok": false}')]
    p = ClaudeProvider(model="m", effort="high", max_tokens=10, fallbacks=None, client=fake_client(message(content=content)))
    assert p.generate_json(system="S", user="U", schema=SCHEMA).data == {"ok": False}


@pytest.mark.parametrize("stop,exc", [("refusal", LLMRefusalError), ("max_tokens", LLMTruncatedError)])
def test_claude_bad_stop_reasons(stop, exc) -> None:
    p = ClaudeProvider(model="m", effort="high", max_tokens=10, fallbacks=None, client=fake_client(message(stop_reason=stop)))
    with pytest.raises(exc):
        p.generate_json(system="S", user="U", schema=SCHEMA)


def test_claude_invalid_json_raises() -> None:
    p = ClaudeProvider(model="m", effort="high", max_tokens=10, fallbacks=None, client=fake_client(message(text="not json")))
    with pytest.raises(LLMError):
        p.generate_json(system="S", user="U", schema=SCHEMA)


def test_factory_builds_claude_from_config() -> None:
    cfg = {"provider": "claude", "claude": {"model": "claude-opus-5", "effort": "high", "max_tokens": 32000,
                                            "fallbacks": "default", "max_retries": 3}}
    p = create_provider(cfg, client=fake_client(message()))
    assert isinstance(p, ClaudeProvider) and p.model == "claude-opus-5"


def test_factory_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError):
        create_provider({"provider": "nope"})


def test_repository_llm_config_builds_provider() -> None:
    from pipeline.config import load_yaml

    cfg = dict(load_yaml("config/llm.yaml")["llm"], provider="claude")
    p = create_provider(cfg, client=fake_client(message()))
    assert p.model == "claude-opus-5"


# --- usage / cost ------------------------------------------------------------

PRICING = {"claude-opus-5": {"input": 5.0, "output": 25.0, "cache_write": 6.25, "cache_read": 0.5}}


def test_estimate_cost() -> None:
    usage = LLMUsage(input_tokens=1_000_000, output_tokens=100_000, cache_creation_input_tokens=0, cache_read_input_tokens=1_000_000)
    assert estimate_cost("claude-opus-5", usage, PRICING) == pytest.approx(5.0 + 2.5 + 0.5)


def test_estimate_cost_unknown_model_is_none() -> None:
    assert estimate_cost("other", LLMUsage(1, 1), PRICING) is None


def test_append_usage_writes_jsonl(tmp_path: Path) -> None:
    log = tmp_path / "logs" / "llm_usage.jsonl"
    append_usage(log, {"stage": "script", "cost_usd": 0.1})
    append_usage(log, {"stage": "storyboard", "cost_usd": 0.2})
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert [x["stage"] for x in lines] == ["script", "storyboard"]
    assert all("timestamp" in x for x in lines)
