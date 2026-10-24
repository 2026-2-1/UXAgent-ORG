"""Routing tests without any network calls or paid API credentials."""

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from omegaconf import OmegaConf

from src.simulated_web_agent.agent import gpt


def completion(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message={"content": content}, finish_reason="stop")]
    )


class LocalChatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = patch.multiple(gpt, provider="local", embedding_provider=None)
        self.settings.start()
        self.addCleanup(self.settings.stop)

    async def test_small_large_and_json_contract(self):
        messages = [{"role": "user", "content": "Return JSON."}]
        for model, router in [("small", gpt.chat_router), ("large", gpt.slow_chat_router)]:
            for json_mode in [False, True]:
                with self.subTest(model=model, json_mode=json_mode):
                    with patch.object(router, "acompletion", new_callable=AsyncMock) as call:
                        call.return_value = completion('```json\n{"ok": true}\n```')
                        result = await gpt.async_chat(
                            messages, model=model, json_mode=json_mode,
                            max_tokens=48, enable_thinking=True, log=False,
                        )
                        self.assertIsInstance(result, str)
                        self.assertEqual(call.call_args.kwargs["model"], "local")
                        self.assertEqual(call.call_args.kwargs["messages"], messages)
                        self.assertEqual(call.call_args.kwargs["max_tokens"], 48)
                        if json_mode:
                            self.assertEqual(json.loads(result), {"ok": True})
                            self.assertEqual(
                                call.call_args.kwargs["response_format"],
                                {"type": "json_object"},
                            )
                        else:
                            self.assertNotIn("response_format", call.call_args.kwargs)

    async def test_invalid_json_is_rejected(self):
        with patch.object(gpt.chat_router, "acompletion", new_callable=AsyncMock) as call:
            call.return_value = completion("invalid JSON")
            # Bypass retry delay when testing an intentionally invalid response.
            with self.assertRaisesRegex(Exception, "Invalid JSON in response"):
                await gpt.async_chat.__wrapped__([], json_mode=True, log=False)

    async def test_non_text_is_rejected(self):
        with patch.object(gpt.chat_router, "acompletion", new_callable=AsyncMock) as call:
            call.return_value = completion(None)
            with self.assertRaisesRegex(ValueError, "non-text"):
                await gpt.async_chat.__wrapped__([], log=False)

    async def test_truncated_json_reports_token_cap_without_retrying(self):
        response = completion('{"observations": ["incomplete')
        response.choices[0].finish_reason = "length"
        response.usage = SimpleNamespace(completion_tokens=512)
        with patch.object(gpt.chat_router, "acompletion", new_callable=AsyncMock) as call:
            call.return_value = response
            with self.assertRaisesRegex(gpt.ChatOutputTruncatedError, "completion_tokens=512"):
                await gpt.async_chat([], json_mode=True, max_tokens=64000, log=False)
            call.assert_awaited_once()

    async def test_existing_providers_keep_routing_and_thinking(self):
        for provider in ["openai", "aws", "anthropic"]:
            for model, router in [("small", gpt.chat_router), ("large", gpt.slow_chat_router)]:
                for thinking in [False, True]:
                    with self.subTest(provider=provider, model=model, thinking=thinking):
                        with patch.object(gpt, "provider", provider):
                            with patch.object(router, "acompletion", new_callable=AsyncMock) as call:
                                call.return_value = completion('{"ok": true}')
                                result = await gpt.async_chat(
                                    [], model=model, json_mode=True,
                                    enable_thinking=thinking, log=False,
                                )
                                self.assertEqual(json.loads(result), {"ok": True})
                                self.assertEqual(
                                    call.call_args.kwargs["model"],
                                    provider + ("_thinking" if thinking else ""),
                                )
                                self.assertEqual(
                                    "response_format" in call.call_args.kwargs,
                                    provider == "openai",
                                )

    async def test_missing_or_unsupported_embedding_never_calls_api(self):
        with patch.object(gpt.embed_router, "aembedding", new_callable=AsyncMock) as call:
            with self.assertRaisesRegex(RuntimeError, "No embedding provider configured"):
                await gpt.embed_text(["memory"])
            with patch.object(gpt, "embedding_provider", "unknown"):
                with self.assertRaisesRegex(ValueError, "Unsupported embedding provider"):
                    await gpt.embed_text(["memory"])
            call.assert_not_awaited()

    async def test_explicit_embedding_provider_is_independent_of_chat(self):
        for chat, embedding, expected in [
            ("local", "aws", "aws"), ("local", "openai", "openai"),
            ("openai", "aws", "aws"), ("aws", "openai", "openai"),
        ]:
            with self.subTest(chat=chat, embedding=embedding):
                with patch.multiple(gpt, provider=chat, embedding_provider=embedding):
                    with patch.object(gpt.embed_router, "aembedding", new_callable=AsyncMock) as call:
                        call.return_value = SimpleNamespace(data=[{"index": 0, "embedding": [0.1, 0.2]}])
                        self.assertEqual(await gpt.embed_text(["memory"]), [[0.1, 0.2]])
                        call.assert_awaited_once_with(model=expected, input=["memory"])


class LocalSettingsTests(unittest.TestCase):
    def test_url_model_and_key_from_environment(self):
        for url in ["http://127.0.0.1:9000/", "http://127.0.0.1:9000/v1/"]:
            with self.subTest(url=url):
                with patch.dict(os.environ, {
                    "LOCAL_LLM_BASE_URL": url, "LOCAL_LLM_MODEL": "custom-qwen",
                    "LOCAL_LLM_API_KEY": "test-local-key",
                }):
                    params = gpt._local_deployment()["litellm_params"]
                    self.assertEqual(params["api_base"], "http://127.0.0.1:9000/v1")
                    self.assertEqual(params["model"], "openai/custom-qwen")
                    self.assertEqual(params["api_key"], "test-local-key")

    def test_default_local_settings_never_inherit_openai_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "must-not-be-used"}, clear=True):
            params = gpt._local_deployment()["litellm_params"]
            self.assertEqual(params["api_base"], "http://127.0.0.1:8000/v1")
            self.assertEqual(params["model"], "openai/persona-qwen")
            self.assertEqual(params["api_key"], "local-no-key")

    def test_configure_applies_independent_providers(self):
        with patch.multiple(gpt, provider="openai", embedding_provider=None):
            gpt.configure(OmegaConf.create({"llm_provider": "local", "embedding_provider": "aws"}))
            self.assertEqual(gpt.provider, "local")
            self.assertEqual(gpt.embedding_provider, "aws")

    def test_sync_local_chat_routes_without_anthropic_thinking(self):
        with patch.object(gpt, "provider", "local"):
            with patch.object(gpt.chat_router, "completion", new_callable=Mock) as call:
                call.return_value = completion('{"ok": true}')
                result = gpt.chat([], json_mode=True, enable_thinking=True)
                self.assertEqual(json.loads(result), {"ok": True})
                self.assertEqual(call.call_args.kwargs["model"], "local")
                self.assertNotIn("thinking", call.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
