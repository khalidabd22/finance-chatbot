"""Offline tests - no API keys or internet needed (uses the 'mock' provider and fake models)."""
import json

import pandas as pd
import pytest
from langchain_core.messages import AIMessage

from bots import FinanceBot
from core.config import BASE_DIR, get_settings
from core.context import build_context
from core.data_loader import load_bytes, load_pasted, load_path
from core.errors import DataLoadError, LLMError
from core.llm import LLMRouter


@pytest.fixture
def mock_router():
    return LLMRouter(get_settings(provider_order="mock"))


# ---------------------------------------------------------------- data loading
def test_all_samples_load():
    for f in (BASE_DIR / "sample_data").glob("*.csv"):
        ds = load_path(f)
        assert ds.df is not None and len(ds.df) > 0


def test_csv_semicolon_and_encoding():
    raw = "name;amount\nCafé;10\nTea;5\n".encode("cp1252")
    ds = load_bytes(raw, "x.csv")
    assert list(ds.df.columns) == ["name", "amount"] and len(ds.df) == 2


def test_json_records_and_nested():
    ds = load_bytes(json.dumps({"records": [{"a": 1}, {"a": 2}]}).encode(), "d.json")
    assert len(ds.df) == 2


@pytest.mark.parametrize("raw,name", [(b"", "a.csv"), (b"abc", "a.exe"), (b"{bad json", "a.json")])
def test_bad_files_raise_friendly(raw, name):
    with pytest.raises(DataLoadError) as e:
        load_bytes(raw, name)
    assert e.value.user_message


def test_pasted_auto_detect():
    assert load_pasted("a,b\n1,2\n3,4").kind == "table"
    assert load_pasted('[{"x": 1}]').kind == "table"
    assert load_pasted("Hello this is a policy note.").kind == "text"
    with pytest.raises(DataLoadError):
        load_pasted("   ")


def test_context_picks_relevant_rows():
    df = pd.DataFrame({"item": [f"thing{i}" for i in range(100)] + ["special-widget"], "v": range(101)})
    ds = load_pasted(df.to_csv(index=False))
    ctx = build_context([ds], "tell me about special-widget", max_chars=5000)
    assert "special-widget" in ctx


# ---------------------------------------------------------------- llm router
class _Boom:
    def invoke(self, _):
        raise RuntimeError("401 API key not valid")


def test_router_falls_back(monkeypatch):
    router = LLMRouter(get_settings(provider_order="gemini,mock", max_retries=0))
    router._models["gemini"] = _Boom()
    reply = router.chat([AIMessage(content="hi")])
    assert reply.provider == "Offline demo"


def test_router_all_fail_gives_friendly_error():
    router = LLMRouter(get_settings(provider_order="gemini", max_retries=0, gemini_api_key=""))
    router.settings.gemini_api_key = ""
    with pytest.raises(LLMError) as e:
        router.chat([AIMessage(content="hi")])
    assert "GEMINI_API_KEY" in e.value.user_message


def test_list_content_from_gemini_is_flattened():
    class Parts:
        def invoke(self, _):
            return AIMessage(content=[{"type": "text", "text": "Hello "}, {"type": "text", "text": "World"}])

    router = LLMRouter(get_settings(provider_order="gemini", max_retries=0))
    router._models["gemini"] = Parts()
    assert router.chat([AIMessage(content="x")]).text == "Hello World"


# ---------------------------------------------------------------- bot
@pytest.mark.parametrize("bot_cls", [FinanceBot])
def test_each_bot_answers_with_mock(bot_cls, mock_router):
    bot = bot_cls()
    reply = bot.respond("hello", [], bot.load_samples(), mock_router)
    assert not reply.is_error and reply.text


def test_finance_summary_numbers():
    bot = FinanceBot()
    facts = bot.extra_context("summary", bot.load_samples())
    assert "Income=142,000.00" in facts
    assert "Net savings" in facts
