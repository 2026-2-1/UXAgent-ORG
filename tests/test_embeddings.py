"""Offline fixtures only: no remote inference or cloud API calls."""

import asyncio
import copy
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import numpy as np
from litellm.router import Router
from omegaconf import OmegaConf

from src.simulated_web_agent.agent import gpt, memory


def fixture_vector(value, dimension=1024):
    return [value] * dimension


class EmbeddingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = patch.multiple(gpt, provider="local", embedding_provider="local")
        self.settings.start()
        self.addCleanup(self.settings.stop)
        env = patch.dict(os.environ, {"LOCAL_EMBEDDING_DIMENSIONS": "1024"})
        env.start()
        self.addCleanup(env.stop)

    async def test_reordered_indices_restore_input_order_and_float_type(self):
        with patch.object(gpt.embed_router, "aembedding", new_callable=AsyncMock) as call:
            call.return_value = SimpleNamespace(data=[
                {"index": 1, "embedding": fixture_vector(2)},
                {"index": 0, "embedding": fixture_vector(1)},
            ])
            result = await gpt.embed_text(["first", "second"])
            self.assertEqual(result, [fixture_vector(1.0), fixture_vector(2.0)])
            self.assertTrue(all(type(value) is float for row in result for value in row))
            self.assertEqual(call.call_args.kwargs["input"], ["first", "second"])
            self.assertEqual(call.call_args.kwargs["encoding_format"], "float")

    async def test_invalid_response_count_dimension_indices_and_values(self):
        rows = [{"index": 0, "embedding": fixture_vector(1)}]
        cases = [
            ([], "expected 1 vectors"),
            ([{"index": 0, "embedding": [1.0, 2.0]}], "dimension mismatch"),
            ([{"index": None, "embedding": fixture_vector(1)}], "index"),
            ([{"index": 1, "embedding": fixture_vector(1)}], "index"),
            ([{"index": 0, "embedding": fixture_vector(float("nan"))}], "non-finite"),
            ([{"index": 0, "embedding": fixture_vector("invalid")}], "non-numeric"),
            ([{"index": 0, "embedding": fixture_vector(True)}], "non-numeric"),
        ]
        for data, message in cases:
            with self.subTest(message=message):
                with patch.object(gpt.embed_router, "aembedding", new_callable=AsyncMock) as call:
                    call.return_value = SimpleNamespace(data=data)
                    with self.assertRaisesRegex(ValueError, message):
                        await gpt.embed_text(["text"])
        with patch.object(gpt.embed_router, "aembedding", new_callable=AsyncMock) as call:
            call.return_value = SimpleNamespace(data=rows * 2)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                await gpt.embed_text(["first", "second"])

    async def test_no_paid_fallback_even_when_chat_uses_cloud(self):
        for chat in ["local", "openai", "aws", "anthropic"]:
            with patch.multiple(gpt, provider=chat, embedding_provider=None):
                with patch.object(gpt.embed_router, "aembedding", new_callable=AsyncMock) as call:
                    with self.assertRaisesRegex(RuntimeError, "No embedding provider configured"):
                        await gpt.embed_text(["memory"])
                    call.assert_not_awaited()

    async def test_connection_failure_has_tunnel_context_and_original_cause(self):
        with patch.object(gpt.embed_router, "aembedding", new_callable=AsyncMock) as call:
            call.side_effect = ConnectionError("connection refused")
            with self.assertRaisesRegex(RuntimeError, "DIS01.*ABRM02") as caught:
                await gpt.embed_text(["text"])
            self.assertIsInstance(caught.exception.__cause__, ConnectionError)
            self.assertIn("connection refused", str(caught.exception))

    async def test_empty_input_skips_network_and_non_strings_fail(self):
        with patch.object(gpt.embed_router, "aembedding", new_callable=AsyncMock) as call:
            self.assertEqual(await gpt.embed_text([]), [])
            with self.assertRaises(TypeError):
                await gpt.embed_text([123])
            call.assert_not_awaited()

    async def test_real_litellm_http_serialization_against_loopback_fixture(self):
        """Test HTTP compatibility, not the inaccessible DIS01 service."""
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append((self.path, body))
                data = [{"object": "embedding", "index": index, "embedding": fixture_vector(index + 1)}
                        for index in reversed(range(len(body["input"])))]
                encoded = json.dumps({"object": "list", "model": body["model"], "data": data,
                                      "usage": {"prompt_tokens": 2, "total_tokens": 2}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        deployment = copy.deepcopy(gpt._local_embedding)
        deployment["litellm_params"]["api_base"] = f"http://127.0.0.1:{server.server_port}/v1"
        router = Router(model_list=[deployment], num_retries=0)
        try:
            with patch.multiple(gpt, embed_router=router, _local_embedding=deployment):
                result = await gpt.embed_text(["sentence one", "sentence two"])
            self.assertEqual(received[0][0], "/v1/embeddings")
            self.assertEqual(received[0][1]["input"], ["sentence one", "sentence two"])
            self.assertEqual(received[0][1]["model"], deployment["litellm_params"]["model"].removeprefix("openai/"))
            self.assertEqual(result, [fixture_vector(1.0), fixture_vector(2.0)])
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()


class SettingsTests(unittest.TestCase):
    def test_embedding_env_is_separate_from_chat_and_cloud_keys(self):
        with patch.dict(os.environ, {
            "LOCAL_EMBEDDING_BASE_URL": "http://127.0.0.1:9999/",
            "LOCAL_EMBEDDING_MODEL": "different-embedding-model",
            "LOCAL_EMBEDDING_API_KEY": "embedding-test-key",
            "LOCAL_LLM_API_KEY": "chat-only", "OPENAI_API_KEY": "cloud-only",
        }):
            params = gpt._local_embedding_deployment()["litellm_params"]
            self.assertEqual(params["api_base"], "http://127.0.0.1:9999/v1")
            self.assertEqual(params["model"], "openai/different-embedding-model")
            self.assertEqual(params["api_key"], "embedding-test-key")
        with patch.dict(os.environ, {}, clear=True):
            params = gpt._local_embedding_deployment()["litellm_params"]
            self.assertEqual(params["api_base"], "http://127.0.0.1:8100/v1")
            self.assertEqual(params["api_key"], "local-no-key")

    def test_base_config_selects_local_embedding_independently(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "anthropic", "EMBEDDING_PROVIDER": "local"}):
            cfg = OmegaConf.load("conf/base.yaml")
            with patch.multiple(gpt, provider="local", embedding_provider=None):
                gpt.configure(cfg)
                self.assertEqual(gpt.provider, "anthropic")
                self.assertEqual(gpt.embedding_provider, "local")


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        agent = SimpleNamespace(persona="A hiker", intent="Find a backpack", current_plan=None)
        self.memory = memory.Memory(agent)

    async def add(self, text):
        piece = memory.Thought(text, self.memory)
        await self.memory.add_memory_piece(piece)
        return piece

    async def test_update_append_and_retrieve_use_existing_similarity_flow(self):
        first = await self.add("hiking backpack")
        second = await self.add("unrelated item")
        # Controlled test fixtures, never used by production code.
        vector_a, vector_b = fixture_vector(0.01), fixture_vector(-0.01)
        with patch.object(memory, "embed_text", new_callable=AsyncMock) as embed:
            with patch.object(memory, "async_chat", new_callable=AsyncMock, return_value='{"score": 5}'):
                embed.return_value = [vector_a, vector_b]
                await self.memory.update()
                self.assertEqual(self.memory.embeddings.shape, (2, 1024))
                np.testing.assert_array_equal(first.embedding, vector_a)
                np.testing.assert_array_equal(second.embedding, vector_b)
                embed.return_value = [vector_a]
                found = await self.memory.retrieve("backpack", n=1)
                self.assertIs(found[0], first)
                embed.assert_awaited_with(["backpack"])
                third = await self.add("another backpack")
                await self.memory.update()
                self.assertEqual(self.memory.embeddings.shape, (3, 1024))
                np.testing.assert_array_equal(third.embedding, vector_a)

    async def test_update_dimension_failure_does_not_commit_piece_embeddings(self):
        old = await self.add("old memory")
        self.memory.embeddings = np.array([[0.2, 0.3]])
        self.memory.importance = np.array([0.5])
        new = await self.add("new memory")
        with patch.object(memory, "embed_text", new_callable=AsyncMock, return_value=[fixture_vector(0.1)]):
            with patch.object(memory, "async_chat", new_callable=AsyncMock, return_value='{"score": 5}'):
                with self.assertRaisesRegex(ValueError, "stored=2, received=1024"):
                    await self.memory.update()
        self.assertEqual(new.embedding.size, 0)
        self.assertEqual(self.memory.embeddings.shape, (1, 2))
        self.assertEqual(new.importance, -1)

    async def test_retrieve_reports_stored_and_query_dimension_mismatch(self):
        await self.add("memory")
        self.memory.embeddings = np.array([[0.2, 0.3]])
        self.memory.importance = np.array([0.5])
        with patch.object(memory, "embed_text", new_callable=AsyncMock, return_value=[fixture_vector(0.1)]):
            with self.assertRaisesRegex(ValueError, "memory.retrieve.*stored=2, received=1024"):
                await self.memory.retrieve("query", trigger_update=False)

    async def test_api_failure_keeps_pending_memory_and_surfaces_cause(self):
        piece = await self.add("pending memory")
        with patch.object(memory, "embed_text", new_callable=AsyncMock, side_effect=RuntimeError("DIS01 unavailable")):
            with patch.object(memory, "async_chat", new_callable=AsyncMock, return_value='{"score": 5}'):
                with self.assertRaisesRegex(RuntimeError, "DIS01 unavailable"):
                    await self.memory.update()
        self.assertEqual(self.memory.embeddings.size, 0)
        self.assertEqual(piece.embedding.size, 0)
        self.assertEqual(piece.importance, -1)


if __name__ == "__main__":
    unittest.main()
