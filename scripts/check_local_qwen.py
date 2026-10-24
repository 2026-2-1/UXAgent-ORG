"""Run from the repository root: python -m scripts.check_local_qwen --persona."""

import argparse
import asyncio
import json
from functools import partial

from src.simulated_web_agent.agent import gpt
from src.simulated_web_agent.main.persona import _load_cfg, generate_personas


async def check(include_persona=False, timeout=90):
    gpt.configure(_load_cfg())
    if gpt.provider != "local":
        raise RuntimeError("This check requires LLM_PROVIDER=local; it only tests local chat.")

    for model in ["small", "large"]:
        for json_mode in [False, True]:
            prompt = 'Return only the JSON object {"ok":true}.' if json_mode else "Reply with only OK."
            print(f"Checking {model}, json_mode={json_mode}...", flush=True)
            result = await asyncio.wait_for(
                gpt.async_chat(
                    [{"role": "user", "content": prompt}],
                    model=model, json_mode=json_mode, max_tokens=64, timeout=timeout, log=False,
                ),
                timeout=timeout + 30,
            )
            if not isinstance(result, str) or not result.strip():
                raise AssertionError("Expected nonempty string from chat server")
            if json_mode and json.loads(result) != {"ok": True}:
                raise AssertionError(f"Unexpected JSON output: {result}")
            print(f"PASS {model}, json_mode={json_mode}: {result.strip()}", flush=True)

    if not gpt.embedding_provider:
        try:
            await gpt.embed_text(["embedding configuration check"])
        except RuntimeError as error:
            print(f"EXPECTED embedding block: {error}")
        else:
            raise AssertionError("Unconfigured local embeddings must fail")
    else:
        print("Embedding provider configured; embedding API is not called by this check.")

    if include_persona:
        print("Checking persona generation (180-second total deadline)...", flush=True)
        personas = await asyncio.wait_for(
            generate_personas(
                demographics=[{"name": "Age", "choices": [{"name": "28", "weight": 1}]}],
                general_intent="Compare keyboards before buying one.",
                n=1, max_concurrency=1,
                chat_fn=partial(gpt.async_chat, max_tokens=384, timeout=150, log=False),
                example_text=(
                    "Persona: Mina\nBackground: A graduate student.\n"
                    "Demographics:\nAge: 28\nShopping Habits: Compares prices carefully."
                ),
            ),
            timeout=180,
        )
        if len(personas) != 1 or not personas[0]["persona"].strip():
            raise AssertionError("Persona generation returned no persona")
        print("PASS persona generation:")
        print(json.dumps(personas[0], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persona", action="store_true", help="Also generate one short persona.")
    parser.add_argument("--timeout", type=float, default=90, help="HTTP timeout in seconds (default: 90).")
    args = parser.parse_args()
    asyncio.run(check(args.persona, args.timeout))
