"""Real-server check: python -m scripts.check_local_embeddings --memory --chat."""

import argparse
import asyncio
import json
import os
import traceback
import urllib.request
from functools import partial
from types import SimpleNamespace

import numpy as np

from src.simulated_web_agent.agent import gpt, memory
from src.simulated_web_agent.main.persona import _load_cfg


def request_json(url, body=None):
    headers = {"Content-Type": "application/json"}
    key = os.getenv("LOCAL_EMBEDDING_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(
        url, data=json.dumps(body).encode() if body is not None else None, headers=headers
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


async def check(include_memory=False, include_chat=False):
    gpt.configure(_load_cfg())
    if gpt.embedding_provider != "local":
        raise RuntimeError("This check requires EMBEDDING_PROVIDER=local")
    params = gpt._local_embedding["litellm_params"]
    base = params["api_base"]
    model_id = params["model"].split("/", 1)[1]
    sentences = ["I need a lightweight hiking backpack.", "Tomorrow's forecast predicts heavy snow."]
    print(f"Embedding URL: {base}/embeddings; model: {model_id}", flush=True)
    errors = []
    raw = None
    for label, url, body in [
        ("a: raw POST", base + "/embeddings", {"model": model_id, "input": sentences}),
        ("b: health", base.removesuffix("/v1") + "/health", None),
    ]:
        try:
            value = await asyncio.to_thread(request_json, url, body)
            if body:
                raw = value
                print(f"PASS {label}: indices/dimensions=" + str([
                    (row.get("index"), len(row.get("embedding", []))) for row in value["data"]
                ]), flush=True)
            else:
                if value.get("status") != "ok":
                    raise AssertionError(f"Unexpected health status: {value}")
                print(f"PASS {label}: {value}", flush=True)
        except Exception as exc:
            errors.append(label)
            print(f"FAIL {label}: {type(exc).__name__}: {exc}", flush=True)

    if not errors:
        print("Checking c: embed_text count, dimensions, float type and input order...", flush=True)
        batch = await asyncio.wait_for(gpt.embed_text(sentences), timeout=70)
        assert len(batch) == 2 and all(len(row) == 1024 for row in batch)
        assert all(type(value) is float for row in batch for value in row)
        ordered_raw = sorted(raw["data"], key=lambda row: row["index"])
        raw_vectors = np.asarray([row["embedding"] for row in ordered_raw])
        vectors = np.asarray(batch)
        # GPU batch/single inference may differ slightly (e.g. bfloat16).
        # Compare directions and nearest matches rather than exact components.
        raw_cosine = np.sum(vectors * raw_vectors, axis=1) / (
            np.linalg.norm(vectors, axis=1) * np.linalg.norm(raw_vectors, axis=1)
        )
        assert np.all(raw_cosine > 0.995), raw_cosine
        singles = []
        for sentence in sentences:
            single = await asyncio.wait_for(gpt.embed_text([sentence]), timeout=70)
            singles.append(single[0])
        singles = np.asarray(singles)
        cosine = (vectors @ singles.T) / (
            np.linalg.norm(vectors, axis=1)[:, None] * np.linalg.norm(singles, axis=1)[None, :]
        )
        assert np.all(np.diag(cosine) > 0.995), cosine
        assert np.array_equal(np.argmax(cosine, axis=1), np.arange(2)), cosine
        print(f"PASS c: (2, 1024), floats, input order verified; cosine={cosine.tolist()}", flush=True)

        if include_memory:
            agent = SimpleNamespace(persona="A cautious beginner hiker", intent="Compare backpacks", current_plan=None)
            store = memory.Memory(agent)
            for sentence in sentences:
                await store.add_memory_piece(memory.Thought(sentence, store))
            original_chat = memory.async_chat
            # Still calls the real chat server; only limits test duration and output.
            memory.async_chat = partial(gpt.async_chat, max_tokens=256, timeout=90)
            try:
                print("Checking d: memory.update (real embeddings and real chat importance)...", flush=True)
                await asyncio.wait_for(store.update(), timeout=120)
                assert store.embeddings.shape == (2, 1024)
                for index, piece in enumerate(store.memories):
                    np.testing.assert_array_equal(piece.embedding, store.embeddings[index])
                print("PASS d: memory.update stored both 1024-dimensional vectors", flush=True)
                found = await asyncio.wait_for(store.retrieve(sentences[0], n=2), timeout=70)
                assert len(found) == 2 and all(piece in store.memories for piece in found)
                print("PASS d: memory.retrieve embedded the question and returned stored memories", flush=True)
            except Exception as exc:
                errors.append("memory.update/retrieve")
                print(f"FAIL d: {type(exc).__name__}: {exc}", flush=True)
                traceback.print_exc()
            finally:
                memory.async_chat = original_chat
    else:
        print("SKIP c/d: raw API/health checks failed; remote embedding integration is unverified", flush=True)

    if include_chat:
        for size in ["small", "large"]:
            print(f"Checking e: real chat {size}...", flush=True)
            try:
                text = await asyncio.wait_for(gpt.async_chat(
                    [{"role": "user", "content": 'Return only the JSON object {"ok":true}.'}],
                    model=size, json_mode=True, max_tokens=64, timeout=90, log=False,
                ), timeout=120)
                assert json.loads(text) == {"ok": True}
                print(f"PASS e: {size} chat JSON response", flush=True)
            except Exception as exc:
                errors.append(f"chat {size}")
                print(f"FAIL e: {size}: {type(exc).__name__}: {exc}", flush=True)
    if errors:
        raise RuntimeError("Failed checks: " + ", ".join(errors))


async def main(args):
    try:
        await check(args.memory, args.chat)
    except Exception:
        # Print the failed stage before LiteLLM's background logger shuts down.
        traceback.print_exc()
        raise
    finally:
        from litellm.litellm_core_utils.logging_worker import GLOBAL_LOGGING_WORKER

        await asyncio.sleep(1)  # Allow completed-request callbacks to drain first.
        await GLOBAL_LOGGING_WORKER.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--chat", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args))
