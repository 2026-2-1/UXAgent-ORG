# Windows UXAgent + Qwen over an existing SSH tunnel

Run these commands from `UXAgent-ORG`. Keep the existing SSH tunnel open.
The default chat provider in `conf/base.yaml` is now `local`. Browser settings
and the existing OpenAI, AWS and Anthropic model definitions are unchanged.

## Verified API (2026-10-24, Windows localhost)

The repository does not contain `api_server.py`. These results were obtained by
calling the server, rather than inferring compatibility from `/health`:

| Request | Result |
| --- | --- |
| `GET /health` | 200, `{"status":"ok","model":"persona-qwen"}` |
| `GET /openapi.json`, `/docs`, `/` | 404 |
| `GET /v1/models` | 200, `data[0].id` is `persona-qwen` |
| `POST /v1/chat/completions` | 200, OpenAI chat completion response |
| `POST /v1/embeddings` with `model: persona-qwen` | 404 |

Confirmed chat URL: `http://127.0.0.1:8000/v1/chat/completions`.
Minimal request:

```json
{"model":"persona-qwen","messages":[{"role":"user","content":"Reply with only OK."}],"max_tokens":16}
```

Observed response (generated ID and timestamp omitted):

```json
{"object":"chat.completion","model":"persona-qwen","choices":[{"index":0,"message":{"role":"assistant","content":"OK\n"},"finish_reason":"stop"}],"usage":{"prompt_tokens":17,"completion_tokens":4,"total_tokens":21}}
```

`response_format: {"type":"json_object"}` was also accepted and the test returned
`{"ok":true}`. This confirms the tested request/response subset; it does not
establish support for every OpenAI feature or server-enforced JSON constraints.
`async_chat(json_mode=True)` additionally extracts and validates a JSON object.
Both `small` and `large` select the same server and model, with no separate
thinking route. Their default `max_tokens` remains 64000; the checks below use
smaller limits. Actual context/output capacity depends on server configuration.

## PowerShell

Settings are read when Python imports the module. Set them before starting UXAgent,
or put them in the repository's ignored `.env` file, then restart the process.

```powershell
Set-Location C:\Users\nkm03\Downloads\uxagent\UXAgent-ORG
$env:LLM_PROVIDER = "local"
$env:LOCAL_LLM_BASE_URL = "http://127.0.0.1:8000"
$env:LOCAL_LLM_MODEL = "persona-qwen"
# Only needed if authentication is enabled on the model server:
# $env:LOCAL_LLM_API_KEY = "your-server-key"

curl.exe http://127.0.0.1:8000/health
.\.venv\Scripts\python.exe -m scripts.check_local_qwen --persona
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_gpt_local.py" -v
```

All three chat variables have defaults as shown above; the API key is optional.
The base URL may include `/v1`; the code appends it only if absent.
For an unauthenticated server LiteLLM receives the placeholder `local-no-key`,
never the value of `OPENAI_API_KEY`. No actual OpenAI key is needed for local chat.
With the repository's existing `uv` setup, the equivalent check is
`uv run -m scripts.check_local_qwen --persona`.

The script performs four real chat calls (`small`/`large`, plain/JSON), verifies
the missing-embedding error without calling an embedding API, and optionally
generates one persona through the existing `generate_personas()` path.
The unittest command uses mocks and never calls a model server or paid API.
The smoke check has an overall deadline of 90 seconds per chat case and 180
seconds for persona generation so repeated retries cannot wait indefinitely.

Validation completed on 2026-10-24:

- Actual local server: all four chat combinations passed and returned strings.
- Actual `generate_personas()` call: one persona returned (`Persona: Leo`).
- Unconfigured embeddings: expected error raised without an embedding API call.
- Mock regression suite: 10 tests passed, including existing OpenAI/AWS/Anthropic
  routing, independent embeddings, local environment settings and invalid JSON.
- CLI `--help`, Python compilation and `git diff --check`: passed.
- Cloud providers were tested with mocks only; no cloud API calls were made.
- Full browser/memory experiment: not run; separate embeddings are still needed.

## Start the experiment UI

The UXAgent backend uses port 8081 so it does not conflict with the Qwen tunnel
on port 8000. The Vite UI proxies `/run` and `/progress` to that backend.
Start these in two PowerShell terminals:

```powershell
# Terminal 1, from UXAgent-ORG:
.\.venv\Scripts\python.exe -u -m src.simulated_web_agent.main.app

# Terminal 2, from UXAgent-ORG:
Set-Location experiment-ui
node node_modules/vite/bin/vite.js --configLoader native --host 127.0.0.1 --port 5173 --strictPort
```

Open `http://127.0.0.1:5173/`. The native config loader avoids an esbuild config
loading permission error in the restricted Windows execution environment and
requires the installed Node runtime's TypeScript support (tested with Node 24).
`UXAGENT_API_PORT` can override the backend port; if changed, update the Vite
proxy target to match. Starting the UI does not start a browser experiment.

## Dedicated embeddings

A separate `local` embedding route is now configured by default. It targets
`http://127.0.0.1:8100/v1/embeddings`, model `persona-qwen-embedding`, independently
of the unchanged chat routers. See [local-embeddings.md](local-embeddings.md) for
settings, SSH topology, live checks and full-experiment prerequisites.

An unset embedding provider now raises an error for every chat provider; the
former implicit OpenAI/AWS embedding fallback has been removed. Explicit
`embedding_provider: openai` / `aws` routes remain available.

The earlier validation results in this document describe the chat-only stage.
The embedding check script reports the current live status separately.
