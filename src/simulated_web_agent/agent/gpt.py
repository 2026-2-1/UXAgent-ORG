import asyncio
import json
import math
import os
import time
from functools import wraps
from pathlib import Path
from typing import Any, Dict, cast

# anthropic import for claude computer use
import anthropic
import yaml
from anthropic.types.beta import (
    BetaContentBlockParam,
    BetaTextBlock,
    BetaTextBlockParam,
    BetaToolUseBlockParam,
)

# client and model for claude compute use tool
from dotenv import load_dotenv

# from litellm import drop_params, token_counter
from litellm.router import Router

from . import context

load_dotenv()  # Load provider settings before constructing the routers.

provider = os.getenv("LLM_PROVIDER", "openai")
embedding_provider = os.getenv("EMBEDDING_PROVIDER") or None


def configure(cfg):
    """Apply chat and embedding settings at every application entry point."""
    global provider, embedding_provider
    provider = cfg.llm_provider
    embedding_provider = cfg.get("embedding_provider", os.getenv("EMBEDDING_PROVIDER"))


def _local_deployment():
    # LiteLLM's OpenAI client appends /chat/completions to api_base.
    base_url = os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    if not base_url.endswith("/v1"):
        base_url += "/v1"
    return {
        "model_name": "local",
        "litellm_params": {
            "model": "openai/" + os.getenv("LOCAL_LLM_MODEL", "persona-qwen"),
            "api_base": base_url,
            # The client requires a nonempty key even when this server has no auth.
            # Never inherit OPENAI_API_KEY for the local endpoint.
            "api_key": os.getenv("LOCAL_LLM_API_KEY") or "local-no-key",
        },
    }

prompt_dir = Path(__file__).parent.absolute() / "shop_prompts"

chat_router = Router(
    model_list=[
        _local_deployment(),
        {
            "model_name": "openai",
            "litellm_params": {
                "model": "openai/gpt-5-mini",
                "reasoning_effort": "minimal",
            },
        },
        {
            "model_name": "aws",
            "litellm_params": {
                "model": "bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0",
                "thinking": {
                    "type": "disabled",
                },
            },
        },
        {
            "model_name": "anthropic",
            "litellm_params": {
                "model": "claude-sonnet-4-20250514",
                "custom_llm_provider": "anthropic",
            },
        },
        {
            "model_name": "openai_thinking",
            "litellm_params": {
                "model": "openai/gpt-5-mini",
                "reasoning_effort": "high",
            },
        },
        {
            "model_name": "aws_thinking",
            "litellm_params": {
                "model": "bedrock/global.anthropic.claude-sonnet-4-5-20250929-v1:0",
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": 32000,
                },
            },
        },
        {
            "model_name": "anthropic_thinking",
            "litellm_params": {
                "model": "claude-sonnet-4-20250514",
                "custom_llm_provider": "anthropic",
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": 32000,
                },
            },
        },
    ]
)

slow_chat_router = Router(
    model_list=[
        _local_deployment(),
        {
            "model_name": "openai",
            "litellm_params": {"model": "openai/gpt-5", "reasoning_effort": "minimal"},
        },
        {
            "model_name": "aws",
            "litellm_params": {
                "model": "bedrock/global.anthropic.claude-sonnet-4-5-20250929-v1:0",
                "thinking": {
                    "type": "disabled",
                },
            },
        },
        {
            "model_name": "anthropic",
            "litellm_params": {
                "model": "claude-sonnet-4-20250514",
                "custom_llm_provider": "anthropic",
            },
        },
        {
            "model_name": "openai_thinking",
            "litellm_params": {"model": "openai/gpt-5", "reasoning_effort": "high"},
        },
        {
            "model_name": "aws_thinking",
            "litellm_params": {
                "model": "bedrock/global.anthropic.claude-sonnet-4-5-20250929-v1:0",
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": 32000,
                },
            },
        },
        {
            "model_name": "anthropic_thinking",
            "litellm_params": {
                "model": "claude-sonnet-4-20250514",
                "custom_llm_provider": "anthropic",
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": 32000,
                },
            },
        },
    ]
)

def _local_embedding_deployment():
    base_url = os.getenv("LOCAL_EMBEDDING_BASE_URL", "http://127.0.0.1:8100/v1").rstrip("/")
    if not base_url.endswith("/v1"):
        base_url += "/v1"
    return {
        "model_name": "local",
        "litellm_params": {
            "model": "openai/" + os.getenv("LOCAL_EMBEDDING_MODEL", "persona-qwen-embedding"),
            "api_base": base_url,
            "api_key": os.getenv("LOCAL_EMBEDDING_API_KEY") or "local-no-key",
        },
    }


_local_embedding = _local_embedding_deployment()
embed_router = Router(
    model_list=[
        _local_embedding,
        {
            "model_name": "openai",
            "litellm_params": {"model": "openai/text-embedding-3-small"},
        },
        {
            "model_name": "aws",
            "litellm_params": {
                "model": "bedrock/cohere.embed-english-v3",
                "input_type": "search_document",
                "truncate": "END",
            },
        },
    ]
)


anthropic_client = anthropic.Anthropic()
anthropic_model = "claude-sonnet-4-20250514"


class ChatOutputTruncatedError(RuntimeError):
    """A token-limited response cannot satisfy a complete JSON contract."""


def async_retry(times=10):
    def func_wrapper(f):
        @wraps(f)
        async def wrapper(*args, **kwargs):
            wait = 1
            max_wait = 5
            last_exc = None
            for _ in range(times):
                # noinspection PyBroadException
                try:
                    return await f(*args, **kwargs)
                except ChatOutputTruncatedError:
                    # Repeating the same oversized request cannot fix the server's cap.
                    raise
                except Exception as exc:
                    last_exc = exc
                    print("got exc", exc)
                    await asyncio.sleep(wait)
                    wait = min(wait * 2, max_wait)
                    pass
            if last_exc:
                raise last_exc

        return wrapper

    return func_wrapper


def retry(times=10):
    def func_wrapper(f):
        def wrapper(*args, **kwargs):
            wait = 1
            max_wait = 5
            last_exc = None
            for _ in range(times):
                # noinspection PyBroadException
                try:
                    return f(*args, **kwargs)
                except Exception as exc:
                    print("got exc", exc)
                    last_exc = exc
                    # await asyncio.sleep(wait)
                    time.sleep(wait)
                    wait = min(wait * 2, max_wait)
                    pass
            if last_exc:
                raise last_exc

        return wrapper

    return func_wrapper


def _extract_json_string(text: str) -> str:
    import regex

    # Improved pattern to match JSON objects. Note: This is still not foolproof for deeply nested or complex JSON.
    json_pattern = r"\{(?:[^{}]*|(?R))*\}"
    matches = regex.findall(json_pattern, text, regex.DOTALL)
    if matches:
        return matches[0]
    else:
        raise Exception("No JSON object found in the response")


@async_retry()
async def async_chat(
    messages,
    model="small",
    json_mode=False,
    log=True,
    max_tokens=64000,
    enable_thinking=None,
    **kwargs,
):
    """
    Async chat completion that returns the string LLM output.

    For model and provider information, check the head of /src/simulated_web_agent/agent/gpt.py.

    To add your own preferred LLM for chat completion, simply add the model into each of the liteLLM routers,
    and change the provider global variable to your custom provider.

    Args:
        model: "small" or "large"; both use LOCAL_LLM_MODEL for provider "local"
        json_mode: whether the result should be in json deserializable
        log: whether to log the output
        max_tokens: the maximum number of tokens
        enable_thinking: whether to enable thinking, if supported (supported by bedrock and anthropic, not supported by openai)

    Returns:
        A single string object outputted by the LLM.
    """

    if context.api_call_manager.get() and log:
        context.api_call_manager.get().request.append(messages)

    router = chat_router if model == "small" else slow_chat_router
    call_kwargs: Dict[str, Any] = dict(**kwargs)
    if enable_thinking and provider != "local":
        router_model = provider + "_thinking"
    else:
        router_model = provider
    if json_mode and provider in {"openai", "local"}:
        call_kwargs["response_format"] = {"type": "json_object"}
    response = await router.acompletion(
        model=router_model,
        messages=messages,
        max_tokens=max_tokens,
        drop_params=True,  # do not forward unused params, such as thinking for openai
        **call_kwargs,
        tools=None,
    )
    content = response.choices[0].message.get("content", "")
    if not isinstance(content, str):
        raise ValueError("Chat server returned non-text message content")

    finish_reason = response.choices[0].finish_reason
    if json_mode and finish_reason == "length":
        tokens = getattr(getattr(response, "usage", None), "completion_tokens", "unknown")
        raise ChatOutputTruncatedError(
            f"Chat JSON response was truncated: provider={provider}, "
            f"finish_reason=length, requested max_tokens={max_tokens}, "
            f"completion_tokens={tokens}. Check the model server's generation "
            "limit/max_new_tokens. Partial JSON is not accepted."
        )
    if finish_reason != "stop":
        print("finish_reason:", finish_reason)
        print("content:", content)
        print("response:", response)
    # tokens_used = token_counter(model="openai/gpt-5-mini", text=content)
    # print("Output tokens:", tokens_used)

    if context.api_call_manager.get() and log:
        context.api_call_manager.get().response.append(content)

    if json_mode:
        # Extract JSON substring from the content
        try:
            json_str = _extract_json_string(content)
            _ = json.loads(json_str)
            return json_str
        except Exception as e:
            print(e)
            print(content)
            raise Exception("Invalid JSON in response") from e
    return content


@retry()
def chat(
    messages, model="small", enable_thinking=None, json_mode=False, **kwargs
) -> str:
    """
    Returns LLM text completion given list of formatted messages.

    Args:
        model: set to "small" to use the lightweight version of the chat model.
        messages: List of previous messages
        enable_thinking: Whether to enable thinking or not. Pass in an integer for custom thinking budget.
        json_mode: Whether to enable JSON mode or not.

    Returns:
        String output of the LLM model
    """

    router = chat_router if model == "small" else slow_chat_router
    call_kwargs: Dict[str, Any] = dict(**kwargs)
    if enable_thinking and provider != "local":
        call_kwargs["thinking"] = {
            "type": "enabled",
            "budget_tokens": enable_thinking
            if isinstance(enable_thinking, int)
            else 1024,
        }
    if json_mode and provider in {"openai", "local"}:
        call_kwargs["response_format"] = {"type": "json_object"}

    try:
        response = router.completion(
            model=provider,
            messages=messages,
            drop_params=True,  # do not forward unused params, such as thinking for openai
            **call_kwargs,
        )
        return response.choices[0].message["content"]
    except Exception as e:
        print(messages)
        print(e)
        raise e


async def embed_text(texts: list[str]) -> list[list[float]]:
    """Return validated float vectors in input order, using only the embedding provider."""
    if not isinstance(texts, list) or any(not isinstance(text, str) for text in texts):
        raise TypeError("embed_text expects a list of strings")
    if not texts:
        return []
    selected_provider = embedding_provider
    if not selected_provider:
        raise RuntimeError(
            "No embedding provider configured. Set embedding_provider / "
            "EMBEDDING_PROVIDER explicitly to local, openai or aws. "
            "No chat-provider or paid-API fallback is performed."
        )
    if selected_provider not in {"local", "openai", "aws"}:
        raise ValueError(
            f"Unsupported embedding provider: {selected_provider!r}. "
            "Available embedding routes: local, openai, aws."
        )

    call_kwargs = {}
    expected_dimension = None
    description = f"provider={selected_provider}"
    if selected_provider == "local":
        params = _local_embedding["litellm_params"]
        description += f", base_url={params['api_base']}, model={params['model']}"
        expected_dimension = int(os.getenv("LOCAL_EMBEDDING_DIMENSIONS", "1024"))
        if expected_dimension <= 0:
            raise ValueError("LOCAL_EMBEDDING_DIMENSIONS must be positive")
        call_kwargs = {
            "timeout": float(os.getenv("LOCAL_EMBEDDING_TIMEOUT", "60")),
            "num_retries": 0,
            # Prevent the OpenAI SDK's base64 default; server returns float arrays.
            "encoding_format": "float",
        }
    try:
        response = await embed_router.aembedding(
            model=selected_provider, input=texts, **call_kwargs
        )
    except Exception as exc:
        hint = (
            " Check the Windows SSH tunnel's final destination is DIS01, not ABRM02; "
            "keep the UXAgent backend port 8081 separate."
            if selected_provider == "local" else " Check this provider's credentials and service."
        )
        raise RuntimeError(
            f"Embedding request failed ({description}): {type(exc).__name__}: {exc}.{hint}"
        ) from exc

    try:
        data = response.data
        if len(data) != len(texts):
            raise ValueError(f"expected {len(texts)} vectors, received {len(data)}")
        ordered = {}
        for row in data:
            index = row.get("index")
            if type(index) is not int or not 0 <= index < len(texts) or index in ordered:
                raise ValueError(f"missing, duplicate or invalid data[].index: {index!r}")
            vector = row.get("embedding")
            if not isinstance(vector, list) or not vector:
                raise ValueError(f"embedding at index {index} must be a nonempty array")
            if expected_dimension is None:
                expected_dimension = len(vector)
            if len(vector) != expected_dimension:
                raise ValueError(
                    f"embedding dimension mismatch at index {index}: "
                    f"expected {expected_dimension}, received {len(vector)}"
                )
            if any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) for value in vector
            ):
                raise ValueError(f"embedding at index {index} contains non-finite/non-numeric values")
            ordered[index] = [float(value) for value in vector]
        return [ordered[index] for index in range(len(texts))]
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid embedding response ({description}): {exc}") from exc


def chat_anthropic_computer_use(
    messages,
    system: BetaTextBlockParam,
    model=anthropic_model,
    screen_width: int = 1024,
    screen_height: int = 768,
) -> (list[BetaToolUseBlockParam], list[Dict, Any]):
    """
    Given a system block and JSON messages, return the tool use block generated by the computer use tool
    """
    response = anthropic_client.beta.messages.create(
        model=model,
        max_tokens=1024,
        tools=[
            {
                "type": "computer_20250124",
                "name": "computer",
                "display_width_px": screen_width,
                "display_height_px": screen_height,
                "display_number": 1,
            },
            {
                "name": "web_browser",
                "description": "High-level browser controls",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "switch_tab",
                                "forward",
                                "back",
                                "new_tab",
                                "goto_url",
                                "close_tab",
                                "terminate",
                            ],
                        },
                        "tab_index": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "Zero-based index for switch_tab and close_tab",
                        },
                        "url": {
                            "type": "string",
                            "description": "URL input, only required for goto_url and new_tab",
                        },
                    },
                    "required": ["action"],
                },
            },
        ],
        system=[system],
        messages=messages,
        betas=["computer-use-2025-01-24"],
    )

    return response


def load_prompt(prompt_name):
    p = prompt_dir / f"{prompt_name}.txt"
    return open(p, "r", encoding="utf-8").read()
