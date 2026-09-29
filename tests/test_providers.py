import json

import httpx
import pytest

from app.config import Settings
from app.providers import build_provider
from app.providers.mock import MockProvider
from app.providers.openai_compat import OpenAICompatProvider, ProviderError


class TestMockProvider:
    def test_returns_final_action_with_canned_sql(self):
        p = MockProvider({"有多少个用户": "SELECT COUNT(*) FROM users"})
        out = p.chat([
            {"role": "system", "content": "schema..."},
            {"role": "user", "content": "请问一共有多少个用户？"},
        ])
        act = json.loads(out)
        assert act["action"] == "final"
        assert act["sql"] == "SELECT COUNT(*) FROM users"

    def test_unknown_question_returns_final_with_empty_sql(self):
        p = MockProvider({})
        out = p.chat([{"role": "user", "content": "完全无关的问题"}])
        act = json.loads(out)
        assert act["action"] == "final"
        assert act["sql"] == ""


class TestOpenAICompatProvider:
    def _provider(self, handler, base_url="http://llm.test/v1/"):
        return OpenAICompatProvider(
            base_url, "sk-test", "test-model", retry_sleep=0.0,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    def test_happy_path_sends_openai_shape(self):
        seen = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["url"] = str(req.url)
            seen["auth"] = req.headers.get("Authorization")
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

        p = self._provider(handler)
        out = p.chat([{"role": "user", "content": "q"}], temperature=0.7)
        assert out == "hi"
        assert seen["url"] == "http://llm.test/v1/chat/completions"
        assert seen["auth"] == "Bearer sk-test"
        assert seen["body"]["model"] == "test-model"
        assert seen["body"]["temperature"] == 0.7

    def test_http_error_raises_provider_error(self):
        p = self._provider(lambda req: httpx.Response(401, json={"error": "bad key"}))
        with pytest.raises(ProviderError):
            p.chat([{"role": "user", "content": "q"}])

    def test_malformed_response_raises_provider_error(self):
        p = self._provider(lambda req: httpx.Response(200, json={"nope": 1}))
        with pytest.raises(ProviderError):
            p.chat([{"role": "user", "content": "q"}])

    def test_retries_on_timeout_then_succeeds(self):
        calls = {"n": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ReadTimeout("timed out", request=req)
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        p = self._provider(handler)
        assert p.chat([{"role": "user", "content": "q"}]) == "ok"
        assert calls["n"] == 2

    def test_retries_on_500_and_429_then_succeeds(self):
        codes = [500, 429]
        calls = {"n": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] <= len(codes):
                return httpx.Response(codes[calls["n"] - 1], json={})
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        p = self._provider(handler)
        assert p.chat([{"role": "user", "content": "q"}]) == "ok"
        assert calls["n"] == 3

    def test_no_retry_on_401(self):
        calls = {"n": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(401, json={"error": "bad key"})

        p = self._provider(handler)
        with pytest.raises(ProviderError):
            p.chat([{"role": "user", "content": "q"}])
        assert calls["n"] == 1

    def test_exhausted_retries_raise(self):
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=req)

        p = self._provider(handler)
        with pytest.raises(ProviderError, match="重试"):
            p.chat([{"role": "user", "content": "q"}])


class TestBuildProvider:
    def test_mock_loads_canned_from_eval_set(self, tmp_path):
        eval_file = tmp_path / "eval.json"
        eval_file.write_text(
            json.dumps([{"question": "多少订单", "gold_sql": "SELECT COUNT(*) FROM orders"}], ensure_ascii=False),
            encoding="utf-8",
        )
        s = Settings(llm_provider="mock", eval_set_path=str(eval_file))
        p = build_provider(s)
        assert isinstance(p, MockProvider)
        assert p.canned.get("多少订单") == "SELECT COUNT(*) FROM orders"

    def test_openai_compat_uses_settings(self):
        s = Settings(llm_provider="openai_compat", llm_base_url="http://x/v1", llm_model="m1", llm_api_key="k")
        p = build_provider(s)
        assert isinstance(p, OpenAICompatProvider)
        assert p.model == "m1"

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError):
            build_provider(Settings(llm_provider="nope"))
