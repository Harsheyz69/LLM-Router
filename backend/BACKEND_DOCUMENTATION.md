# LLM Router Backend Documentation

This document describes the backend as implemented in `backend/app` and tested by
`backend/tests`. It records current behavior, not only the intended architecture in
`context.md`. The backend is an MVP prototype: routing and provider calls are present,
while persistence, authentication, Jev integration, and operational health checking are
not yet implemented.

## 1. Backend at a glance

The backend is an asynchronous FastAPI application. Its main request path is:

```text
HTTP request
  -> request ID middleware and CORS
  -> Pydantic request validation
  -> prompt-length check
  -> query analyzer
  -> in-memory model registry
  -> hard-constraint filter
  -> decision provider (currently rule-based)
  -> selection validation by RoutingPolicy
  -> LiteLLM provider call
  -> normalized JSON response or SSE stream
```

The central invariant is preserved in the routing code: hard constraints are applied
before the decision provider, and a decision provider cannot select a model outside the
filtered candidate set.

## 2. Source layout

```text
backend/
├── app/
│   ├── main.py                 FastAPI app, middleware, routes, error handlers
│   ├── api/
│   │   ├── chat.py             Chat orchestration and SSE formatting
│   │   └── health.py           Liveness/configuration health endpoint
│   ├── core/
│   │   ├── config.py           Environment-backed Settings singleton
│   │   ├── logging.py          Logging setup and secret redaction
│   │   └── middleware.py       Request IDs and request timing
│   ├── providers/
│   │   └── service.py          LiteLLM adapter, retries, normalization
│   ├── registry/
│   │   ├── schemas.py           ModelEntry and registry enums
│   │   └── repository.py        Static model catalog and in-memory registry
│   ├── router/
│   │   ├── analyzer.py          Heuristic task classification and token estimates
│   │   ├── constraints.py       Deterministic hard-constraint filtering
│   │   ├── decision_provider.py Decision-provider interface and result types
│   │   ├── policy.py             Application-owned final selection policy
│   │   └── rule_based_provider.py Weighted baseline router
│   └── schemas/
│       └── api.py               API request, response, and stream schemas
├── tests/                       Unit and API tests
├── .env.example                 Configuration template
├── requirements.txt             Runtime/test/lint dependencies
└── pyproject.toml               Pytest and Ruff configuration
```

## 3. Application startup and configuration

`app.main:create_app()` creates the FastAPI application and includes `/health` and
`/api/v1/chat`. The module-level `app` is the ASGI entry point used by Uvicorn.

The lifespan handler configures logging, logs the environment and whether OpenAI,
Anthropic, and Google credentials are present, logs the Ollama base URL, then logs
shutdown. Credentials themselves are never logged.

Middleware currently consists of:

- `RequestIdMiddleware`: accepts `X-Request-ID` or generates a UUID, stores it in a
  `ContextVar`, adds it to the response, and logs method, path, status, and duration.
- FastAPI `CORSMiddleware`: allows the comma-separated `CORS_ORIGINS` list, all request
  headers, standard CRUD methods, credentials, and exposes `X-Request-ID`.

`Settings` in `app/core/config.py` reads environment variables and an optional `.env`
file. It is cached by `get_settings()` and therefore behaves as a process-wide singleton.
The important settings are:

| Setting | Default | Current use |
| --- | --- | --- |
| `APP_ENV` | `development` | Environment label and docs/ReDoc visibility |
| `APP_DEBUG` | `false` | Logged, but does not change routing or error detail |
| `APP_LOG_LEVEL` | `info` | Validated and used for logging |
| `CORS_ORIGINS` | `http://localhost:3000` | CORS allowlist |
| `MAX_PROMPT_LENGTH` | `32000` | Runtime character limit for chat prompts |
| `REQUEST_TIMEOUT_SECONDS` | `120` | LiteLLM call timeout |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` | empty | Provider availability and credentials |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama availability flag and LiteLLM base URL |
| `JEV_API_KEY`, `JEV_BASE_URL` | unset | Reserved; no implementation consumes them |
| `DATABASE_URL`, `REDIS_URL` | unset | Reserved for future persistence/cache |

`APP_HOST` and `APP_PORT` are defined for deployment configuration but are not used by
`main.py`; the Uvicorn command must supply them if desired.

## 4. API contract

### `GET /health`

Returns a `HealthResponse` containing `status`, version `0.1.0`, environment, UTC
timestamp, and a provider map. The map means “credentials/configuration appear to be
present”, not “the provider was contacted successfully”. Ollama is reported true when
`OLLAMA_BASE_URL` is non-empty; no Ollama health request is made.

Example shape:

```json
{
  "status": "ok",
  "version": "0.1.0",
  "environment": "development",
  "providers": {"openai": false, "anthropic": false, "google": false, "ollama": true},
  "timestamp": "2026-10-15T00:00:00Z"
}
```

### `POST /api/v1/chat`

`ChatRequest` fields:

- `message`: required, 1–100,000 characters at schema level, not blank. The endpoint
  applies the stricter configured `MAX_PROMPT_LENGTH` check.
- `conversation_id`: optional identifier. If absent, a UUID is generated.
- `preferences.priority`: `quality`, `balanced`, `speed`, or `cost`; default `balanced`.
- `preferences.local_only`: excludes commercial API deployments when true.
- `preferences.max_cost_per_request`: optional non-negative USD ceiling.
- `stream`: false by default.

For a non-streaming request, the response contains the generated assistant message,
request/conversation IDs, routing metadata, optional token usage, latency, role, and
creation time. The backend currently sends only the current user message to the model;
conversation IDs are not persisted and previous conversation messages are not loaded.

Routing metadata includes the selected internal model ID, display name, provider, task
category, human-readable reason, candidate count, fallback flag, routing overhead,
estimated cost when pricing is known, and router type.

Errors use a safe `ErrorDetail` shape. Typical status/error-code combinations are:

| Status | Code | Meaning |
| --- | --- | --- |
| 422 | `validation_error` or FastAPI validation response | Invalid body/preferences |
| 422 | `prompt_too_long` | Prompt exceeds `MAX_PROMPT_LENGTH` |
| 503 | `no_models_available` | Registry has no available/enabled models |
| 503 | `no_compatible_model` | Hard constraints reject all available models |
| 503 | `routing_failure` | Policy could not validate a final selection |
| 502 | `provider_error` | Selected and fallback provider calls failed |
| 500 | `internal_error` | Unexpected server exception |

### Streaming behavior

With `stream: true`, the endpoint returns `text/event-stream` using Server-Sent Events.
The event order is:

```text
event: meta       data: {request_id, conversation_id}
event: routing    data: {routing: RoutingInfo}
event: token      data: {text}
event: token      data: {text}
event: done       data: {usage: null, latency_ms: null}
```

Provider failures are sent as a terminal `error` event with a safe message. Streaming
does not use the non-streaming provider fallback path, and the stream adapter does not
retry failed calls. The current implementation does not record usage or measured
stream latency in the `done` event.

## 5. Routing pipeline

`RoutingPolicy.route()` owns the sequence and final selection.

### 5.1 Query analysis

`analyze_query()` in `router/analyzer.py` is a lightweight heuristic, not a trained or
validated classifier. It:

1. Counts regex keyword matches for coding, math, creative, analysis, summarization,
   and translation. The category with the highest score wins; ties follow the pattern
   declaration order. If no pattern matches, the category is `general`.
2. Estimates input tokens as `max(1, len(text) // 4)`.
3. Estimates output tokens using a category multiplier, clamped to 50–4096 tokens.
4. Estimates complexity as low for messages under 50 characters, medium for messages
   under 500 characters or general/conversation tasks, and high otherwise.

The analyzer currently always sets `requires_tools=False` and `requires_vision=False`.
Those fields exist for future multimodal/tool-aware request handling but cannot currently
be activated through the public chat request.

### 5.2 Registry

The registry is created lazily as a process-local singleton. It contains eight static
entries: two OpenAI, two Anthropic, two Google Gemini, and two Ollama models. Entries
include deployment type, modalities, context window, tool/streaming/vision support,
pricing, estimated latency, quality estimate, health status, license label, notes, and
the LiteLLM model string.

At load time, commercial models are marked available only when their provider key is
non-empty. Ollama models are marked available when the base URL is non-empty; the
registry does not check whether Ollama is actually reachable. `get_available()` returns
models that are both available and enabled. Health status starts as `unknown` for
available models and `unhealthy` otherwise. Health updates are in-memory only, and
provider failures do not automatically update health.

### 5.3 Hard constraints

`apply_hard_constraints()` applies pass/fail checks to every model supplied by the
policy. A model is rejected if it is disabled, unavailable, unhealthy, excluded by
`local_only`, lacks required vision/tools, exceeds a known context window, or has a
known estimated cost above the configured budget. Unknown cost is not treated as zero
and is not rejected by the budget check; it is handled as a scoring penalty later.

The filter returns both compatible candidates and `(model_id, reason)` rejection data.
Only candidates are passed to the decision provider.

### 5.4 Decision provider and policy validation

`DecisionProvider` defines an async interface returning scored candidates, a selected ID,
confidence, reason, and provider name. `RuleBasedDecisionProvider` is currently both the
default primary provider and the fallback. There is no Jev implementation or runtime
selection of Jev in this repository.

The baseline score is:

```text
weight_quality * quality
- weight_cost * normalized_cost
- weight_latency * normalized_latency
+ weight_preference * preference_match
```

Weights vary by priority. Unknown quality defaults to `0.5`; unknown cost and latency
each receive a `0.5` penalty component. Cost and latency are normalized against the
maximum known candidate value. Preference matching adds task/provider affinity bonuses
and a local-model bonus when `local_only` is selected. The reported confidence is the
gap between the top two scores relative to the top score; it is a heuristic, not a
calibrated probability.

The policy handles decision-layer failures as follows:

1. Analyzer and registry lookup run.
2. No available models raises `no_models_available`.
3. Empty hard-filter result raises `no_compatible_model`.
4. Decision-provider exceptions or invalid results invoke the fallback provider.
5. A selected ID not present in the filtered candidates is rejected and re-selected by
   the fallback provider.
6. If the fallback still cannot produce a valid candidate, `routing_failure` is raised.

This validation prevents a decision provider from bypassing hard constraints.

## 6. Provider integration

`ProviderService` is the provider boundary. It converts a `ModelEntry` into a LiteLLM
request using `effective_litellm_model`, OpenAI-compatible message dictionaries, the
configured timeout, the provider API key, and an Ollama `api_base` when applicable.

Non-streaming calls use `litellm.acompletion()` and normalize the first choice into a
`ProviderResponse` containing text, internal model ID, provider, optional usage, actual
call latency, and raw provider model name. Retryable errors (rate limit, timeout,
5xx-like text, or connection errors) are retried up to two total attempts. There is no
backoff between attempts. Authentication errors and unclassified errors are not retried.

Streaming calls use LiteLLM with `stream=True` and yield content from each delta. They
classify all failures as `ProviderError` but do not retry. Provider-specific errors are
converted to short, redacted messages before they can leave the service.

For a non-streaming provider failure, `chat.py` chooses the first other hard-filtered
candidate as a provider fallback. It does not re-run the scoring policy. If that call
also fails, the API returns 502. The streaming path has no equivalent model fallback.

## 7. Logging and security behavior

Logging is human-readable in development and JSON-shaped in non-development mode.
Known OpenAI, Google, Anthropic, bearer-token, and `api_key=...` patterns are replaced
with `[REDACTED]`. Prompt and response bodies are not intentionally logged by the
backend. Provider error text is truncated to 200 characters and redacted.

Implemented protections include server-side provider credentials, Pydantic input
validation, safe error handlers, CORS configuration, request IDs, and secret redaction.

Not implemented yet:

- authentication and authorization;
- per-user ownership checks;
- rate limiting;
- database persistence and migrations;
- Redis caching;
- Jev credentials/API adapter;
- provider reachability probes and automatic health updates;
- conversation/history/feedback endpoints;
- request cancellation and explicit disconnect handling;
- production HTTPS/secret-manager integration.

The application currently accepts a client-supplied request ID without format or length
validation, and CORS allows all request headers. These should be reviewed before public
deployment.

## 8. Testing status

Tests cover schema validation, query heuristics, hard constraints, rule-based scoring,
routing fallback/selection validation, API validation/CORS/error behavior, and log
redaction. External provider calls are intended to be mocked.

The checked environment ran 76 tests with 72 passing and 4 failures:

- Three API tests patch `app.providers.service.litellm`, but `service.py` imports
  LiteLLM inside `complete()`/`stream_complete()` rather than exposing a module-level
  attribute, so the patch target does not exist.
- `test_all_filtered_raises_error` expects `no_compatible_model` for disabled and
  unavailable models, but `RoutingPolicy` calls `registry.get_available()` first and
  therefore raises `no_models_available` before the hard-constraint filter runs.

The test run also emitted deprecation warnings for `datetime.utcnow()` and Python/HTTPX
test-client compatibility. These are maintenance items, not routing behavior.

## 9. Running the backend

From `backend/`, create `.env` from `.env.example`, configure at least one intended
provider, and run:

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Development OpenAPI documentation is available at `/docs` and `/redoc` when
`APP_ENV=development`. Run the test suite with:

```powershell
.venv\Scripts\python.exe -m pytest
```

The default Ollama URL makes Ollama entries appear configured even when no Ollama server
is running. A real end-to-end request therefore requires either a reachable Ollama
server or a configured commercial provider key.

## 10. Recommended next implementation steps

1. Make provider calls injectable/module-patchable and fix the test contract around
   registry availability versus hard filtering.
2. Add explicit provider health checks and update registry health after failures.
3. Add authentication, rate limiting, request-size/output limits, and authorization.
4. Add persistence only after defining conversation ownership and retention.
5. Implement and verify a Jev adapter behind `DecisionProvider`; retain the rule-based
   fallback and validate all Jev model IDs against filtered candidates.
6. Add streaming usage/latency accounting, disconnect handling, and compatible fallback
   behavior if required by the product.

