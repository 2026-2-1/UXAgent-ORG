# DIS01 embeddings through a Windows SSH tunnel

Chat and embeddings are separate routes. The Qwen chat address/model stays
unchanged. The UXAgent backend and Vite proxy now use **8081**, matching the
user's requested backend port. Model SSH tunnels remain on 8000 (chat) and 8100
(embeddings). The dashboard backend was started with the current code; launching
the dashboard does not start a participant experiment.

## Configuration

`conf/base.yaml` selects `embedding_provider: local` by default via OmegaConf.
The CLI, persona generation, and experiment entry points already call
`gpt.configure(cfg)`; that function sets the embedding provider independently
of chat. Embedding Router settings are loaded at module import, after `.env`.
Restart the Python backend after changing code or environment variables.

| Variable | Default | Purpose |
| --- | --- | --- |
| `EMBEDDING_PROVIDER` | `local` in base.yaml | `local`, explicit `openai`, or explicit `aws` |
| `LOCAL_EMBEDDING_BASE_URL` | `http://127.0.0.1:8100/v1` | OpenAI-compatible API base; `/v1` appended if absent |
| `LOCAL_EMBEDDING_MODEL` | `persona-qwen-embedding` | Server model ID |
| `LOCAL_EMBEDDING_API_KEY` | optional | Dedicated server key; no cloud/chat key inherited |
| `LOCAL_EMBEDDING_DIMENSIONS` | `1024` | Expected output dimension; validation only, not a server request parameter |
| `LOCAL_EMBEDDING_TIMEOUT` | `60` | HTTP timeout in seconds |

An explicitly unset/empty embedding provider raises an error. There is no
automatic fallback to the chat provider or a paid provider. Empty input returns
an empty list without a request. Explicit cloud routes retain their previous
models: OpenAI `text-embedding-3-small`, AWS `cohere.embed-english-v3`.

## SSH topology

DIS01's embedding server stays bound to `127.0.0.1:8100`. The final SSH endpoint
must be DIS01, with ABRM02 as the jump host. In another PowerShell terminal,
replace these account/host placeholders with your actual SSH aliases/addresses:

```powershell
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -J YOUR_USER@ABRM02 -L 127.0.0.1:8100:127.0.0.1:8100 YOUR_USER@DIS01
```

Keep this terminal open. Ending the SSH command closes the forwarding listener.
A tunnel ending at ABRM02 with remote target `127.0.0.1:8100` reaches ABRM02's
loopback, not DIS01's. No server binding or external exposure is needed.

## PowerShell verification

Keep the existing chat environment variables and the existing backend on 8081.
These commands only configure/test the embedding route:

```powershell
Set-Location C:\Users\nkm03\Downloads\uxagent\UXAgent-ORG
$env:EMBEDDING_PROVIDER = "local"
$env:LOCAL_EMBEDDING_BASE_URL = "http://127.0.0.1:8100/v1"
$env:LOCAL_EMBEDDING_MODEL = "persona-qwen-embedding"
# Optional, if this server requires authentication:
# $env:LOCAL_EMBEDDING_API_KEY = "your-embedding-server-key"

curl.exe --max-time 10 http://127.0.0.1:8100/health
$embeddingBody = @{model="persona-qwen-embedding"; input=@("sentence one", "sentence two")} | ConvertTo-Json
$embeddingResponse = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8100/v1/embeddings -ContentType "application/json" -Body $embeddingBody
$embeddingResponse.data | ForEach-Object { "index=$($_.index) dimensions=$($_.embedding.Count)" }

.\.venv\Scripts\python.exe -X utf8 -u -m scripts.check_local_embeddings --memory --chat
.\.venv\Scripts\python.exe -u -m unittest discover -s tests -p "test_*.py" -v
```

The real-server check tests raw POST, health, `embed_text()` count/dimensions and
input order, then (with `--memory`) actual memory update/retrieval, and (with
`--chat`) the existing small/large chat routes. Memory importance still requires
the real Qwen chat server. The check limits only test importance responses to
256 tokens; it does not mock any model response or change production defaults.

Batch and single inference can differ slightly on a GPU. Order verification
compares cosine directions/nearest matches rather than requiring bitwise equality.
Production responses are validated for cardinality, indices, numeric/finite
values and dimensions, then reordered by `data[].index` and returned as floats.
No vectors are generated or substituted by the client.

## Memory and browser checks

`Memory.update()` still embeds new content, evaluates importance using chat,
and appends vectors. Per-piece values are committed only after both operations
succeed. `retrieve()` embeds the query and retains the original dot-product,
recency, importance and kind-weight scoring. Stored/new/query dimension mismatch
errors explain the dimensions and need to re-embed old memories.

The offline tests use controlled fixtures only, including a temporary HTTP server
on an OS-assigned loopback port. They verify real LiteLLM HTTP serialization,
reversed response indices, malformed vectors, API failures, memory append/retrieve
and chat/cloud routing. These tests do not prove remote DIS01 connectivity.

The previously observed Windows CP949 failure is fixed by reading browser
scripts as UTF-8. Experiment output/error files also use UTF-8. Errors are saved
under the run's `error.txt` rather than the nonexistent `policy.run_path`.

Only after the actual embedding, memory, and chat checks succeed, trial one
participant with a maximum of three steps. Keep the dashboard's saved 20-person
preset separate from this trial. Check the new `runs/<timestamp>/` directory for
`error.txt`, `action_trace.json`, `memory_trace.json` and screenshots. A progress
counter or HTTP 200 alone does not establish successful agent execution.

## Observed validation in this session (2026-10-24)

- Offline regression tests: 22 passed, including HTTP serialization, input-order
  restoration, malformed responses, memory update/retrieval and cloud chat routes.
- Real Chromium preflight under Windows' CP949 default: passed script loading,
  parser execution and Korean page observation. Report:
  `runs/local-ui/encoding-preflight.json`.
- Initially localhost:8100 refused connections. After the user opened the SSH
  tunnel, Codex also observed successful POST and health responses, model
  `persona-qwen-embedding`, and two 1024-dimensional vectors.
- Real LiteLLM calls also returned a 2x1024 batch and two 1x1024 single responses.
  The initial component-wise order check was too strict for batch/single GPU
  numerical differences (observed maximum component difference about 0.00031).
  The check now uses cosine nearest matches. Its live rerun remains incomplete.
- Subsequent checks again refused localhost:8100 connections (WinError 10061).
  Existing chat requests to localhost:8000/v1/chat/completions timed out for both
  small and large. No chat router/address/model was changed.
- Latest failure log: `runs/local-ui/embedding-check.log`. Actual combined
  memory/chat integration and the three-step participant trial were not completed;
  they require the embedding and chat tunnels/services to remain available.

These results establish the client implementation and partial live connectivity,
not a completed remote memory/browser integration.

## Latest results after the server restart

The earlier connection failures above were superseded by these real Windows
checks after the user restarted both services and kept both SSH tunnels open:

- Both `/health` endpoints on 8000 and 8100: HTTP 200, expected model IDs.
- Raw chat POST, async small/large chat, and JSON chat: passed. The chat recheck
  used a 90-second HTTP timeout and 120-second overall async deadline. Report:
  `runs/local-ui/chat-restart-check.json`.
- Raw embedding POST, float output shape `(2, 1024)`, and input-order verification:
  passed. Batch/single cosine matches were approximately 0.999998 for each input.
- Real `memory.update()` stored both vectors; real `memory.retrieve()` embedded
  the query and returned two stored memories. Real chat supplied importance scores.
  Report: `runs/local-ui/embedding-integration-check.json`.
- Offline regression suite after fixes: **24 tests passed**.
- One-participant, maximum-three-step Decathlon trial: attempted. Normal sandbox
  execution denied website access; an approved run outside that restriction
  successfully loaded the real website. It then failed in `Agent.perceive()`:
  the chat request asked for `max_tokens=64000`, but the actual response ended
  with `finish_reason=length`, `completion_tokens=512`, and incomplete JSON.
  Latest trace: `runs/2026-10-24_20-44-13_dc11/error.txt`; summary:
  `runs/local-ui/one-participant-trial.json`. No agent action completed.

The remaining browser-trial blocker is the chat server's observed output limit.
Inspect its `api_server.py` generation settings/max_new_tokens and ensure the
requested output budget is honored. The server source is not in this repository,
so it was not modified. The exhaustive perception prompt was preserved; no
partial JSON, fake memory, or external model response was substituted.

Truncated JSON now raises `ChatOutputTruncatedError` immediately instead of
repeating the same request ten times. Experiment cleanup also cancels/awaits its
background reasoning task. Anthropic Router entries explicitly name their
existing provider so model-name detection differences do not prevent local
startup; their model IDs and the local Qwen routes are unchanged.

Repeat checks from Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -X utf8 -u -m scripts.check_local_qwen --timeout 90
.\.venv\Scripts\python.exe -X utf8 -u -m scripts.check_local_embeddings --memory --chat
# After correcting the remote chat generation limit:
.\.venv\Scripts\python.exe -X utf8 -u -m scripts.check_browser_trial --max-steps 3
```
