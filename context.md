# Adaptive Multi-LLM Router — Web Application Context

> **Purpose:** This file is the working source of truth for AI coding assistants and developers building the web application for the Adaptive Multi-LLM Router project. Read it before making architectural or product changes. Update it whenever the agreed design changes.

## 1. Project Summary

**Working project name:** Adaptive Multi-LLM Router  
**Product type:** Web application + routing backend + research prototype  
**Primary goal:** Let users submit a prompt through one interface while the backend chooses a suitable large language model (LLM) based on capability requirements, quality estimates, cost, latency, availability, and policy constraints.

The system should support two broad categories of models:

1. **Commercial/hosted models**, such as OpenAI, Google Gemini, and Anthropic Claude.
2. **Open-weight or open-source models**, such as selected Llama, Qwen, Mistral, and Gemma models, served through a compatible hosted endpoint or self-hosted infrastructure such as Ollama or vLLM.

Do not state that every open-weight model or hosted service is free. Model licensing, availability, usage limits, and hosting costs differ and must be represented accurately in the model registry.

### Core design principle

> **Deterministic constraints → decision signals → routing policy → generation.**

The decision layer is not the answer generator. The selected LLM generates the answer. The routing policy remains responsible for enforcing application requirements and selecting the final model.

Jev is an experimental decision-layer component in this architecture. The project must evaluate its usefulness rather than assume that it is automatically better than simpler routing methods.

---

## 2. Product Goals

### MVP goals

- Provide a clean, responsive web chat interface.
- Allow users to submit prompts without choosing a provider manually.
- Send requests to a centralized FastAPI backend.
- Filter out models that cannot satisfy mandatory query requirements.
- Use a pluggable decision layer, with Jev as the intended experimental integration.
- Apply an application-controlled routing policy before generation.
- Route to commercial and open-weight models through a unified provider layer where supported.
- Return streamed answers when the chosen provider and backend path support streaming.
- Show a clear, optional explanation of the routing decision.
- Handle provider timeouts, rate limits, unavailable models, and decision-layer failure gracefully.
- Record enough metrics to evaluate quality, cost, latency, and routing overhead.
- Keep provider credentials and Jev credentials on the server, never in browser code.

### Later goals

- Semantic response caching.
- User-specific preferences and personalization.
- Anonymous pairwise answer comparison for collecting preference signals.
- Routing analytics and an admin/experiment dashboard.
- Adaptive routing or contextual-bandit experiments.
- More providers, local inference deployments, multimodal routing, and production-grade observability.

### Non-goals for the first MVP

- Calling every available model for every prompt.
- Building a model-training platform.
- Implementing complex autonomous agents unrelated to model selection.
- Deploying Kubernetes, Kafka, or many microservices before a working end-to-end path exists.
- Promising that routing always improves quality or reduces cost before benchmarks confirm it.
- Requiring users to paste their own provider API keys.

---

## 3. Recommended Technology Stack

### Web frontend

- **Next.js App Router**
- **React + TypeScript**
- **Tailwind CSS**
- Optional: **shadcn/ui** for accessible UI primitives
- **TanStack Query** for server state and request lifecycle where useful
- **Zustand** only for small pieces of client UI state if necessary
- `fetch` with streaming support for responses; use SSE or a well-defined streaming HTTP protocol supported by the backend
- Markdown renderer for assistant answers, with safe handling of code blocks and links

Next.js is the recommended default for a polished web app. If the existing repository already uses Vite/React, do not rewrite it without an explicit reason; preserve the current framework and apply this document's product/API requirements.

### Backend

- Python
- FastAPI
- Pydantic
- httpx / async HTTP clients
- Uvicorn
- LiteLLM as a possible common interface to supported providers
- A provider-adapter interface for integrations that LiteLLM does not directly cover

### Storage and cache

- **PostgreSQL** for durable application data, conversations, model metadata, routing events, and feedback.
- **Redis** for exact-response cache, routing-decision cache, rate limits, and short-lived state.
- Semantic cache/vector search is a later phase, not a requirement for the first working version.

### Model serving

- Commercial APIs: selected OpenAI, Gemini, and Claude models, based on credentials, access, cost, and API compatibility.
- Open-weight models: selected Llama, Qwen, Mistral, and Gemma models, subject to license and runtime constraints.
- **Ollama** may be used for local development or lightweight self-hosting.
- **vLLM** may be used for GPU-backed model serving when appropriate.
- The registry must distinguish between a model's weights, its license, the serving endpoint, and the real cost of running it.

### Quality and deployment tools

- Git / GitHub
- Docker for reproducible backend deployment
- Pytest for backend tests
- Playwright or equivalent for web end-to-end tests
- OpenAPI docs generated by FastAPI
- Prometheus, Grafana, and OpenTelemetry later, when observability needs justify them

### Authentication

Authentication provider is an implementation decision. Keep authentication behind a small, replaceable integration. A demo can begin with restricted development access, but any public multi-user deployment must enforce authentication and server-side authorization.

---

## 4. High-Level Architecture

```text
┌───────────────────────────────────────────────┐
│                 Web Client                    │
│ Next.js / React / TypeScript / Tailwind        │
│ Chat · History · Settings · Routing Details    │
└──────────────────────────┬────────────────────┘
                           │ HTTPS + stream
                           ▼
┌───────────────────────────────────────────────┐
│                  FastAPI                      │
│ Auth · Validation · Chat API · Stream         │
└──────────────────────────┬────────────────────┘
                           ▼
┌───────────────────────────────────────────────┐
│                 Request Flow                  │
│ Exact Cache → Query Analyzer → Model Registry │
│ → Hard Constraint Filter → Candidate Pool     │
└──────────────────────────┬────────────────────┘
                           ▼
┌───────────────────────────────────────────────┐
│               Decision Layer                  │
│ Jev adapter or rule-based fallback            │
│ Structured scores/signals + confidence         │
└──────────────────────────┬────────────────────┘
                           ▼
┌───────────────────────────────────────────────┐
│                Routing Policy                 │
│ Constraints + quality + cost + latency        │
│ + availability + preferences                  │
└──────────────────────────┬────────────────────┘
                           ▼
┌───────────────────────────────────────────────┐
│             Provider Abstraction              │
│ LiteLLM and/or provider adapters              │
└──────────────────────────┬────────────────────┘
                           ▼
       ┌───────────────────┴──────────────────┐
       ▼                                      ▼
┌─────────────────────┐            ┌─────────────────────┐
│ Commercial/hosted   │            │ Open-weight models  │
│ OpenAI/Gemini/Claude│            │ Llama/Qwen/Mistral/ │
│                     │            │ Gemma via API,      │
│                     │            │ Ollama or vLLM      │
└─────────────────────┘            └─────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────┐
│ PostgreSQL · Redis · Metrics · Feedback        │
└───────────────────────────────────────────────┘
```

### Component responsibilities

1. **Web client:** renders chat and app UI; never calls provider APIs directly.
2. **FastAPI:** authenticates requests, validates input, streams responses, and orchestrates the backend flow.
3. **Query analyzer:** derives task and constraint features; does not independently override routing policy.
4. **Model registry:** authoritative metadata for model identity, capabilities, pricing, endpoint type, availability, limits, license notes, and measured performance.
5. **Hard constraint filter:** deterministic code removing incompatible models.
6. **Decision layer:** Jev adapter where verified/available, otherwise a rule-based fallback; returns validated structured signals.
7. **Routing policy:** selects the final model under hard constraints and soft objectives.
8. **Provider abstraction:** converts common requests to provider-compatible calls and normalizes responses.
9. **Evaluation/feedback:** records measurements and optional user preference signals for research.
10. **Redis/PostgreSQL:** short-lived cache/state and durable storage, respectively.

---

## 5. Routing Design

### Request lifecycle

```text
1. Receive prompt and request options.
2. Authenticate and authorize request.
3. Validate body, size, conversation ownership, and idempotency key.
4. Check exact response cache if cache policy allows.
5. Analyze task, modality, context needs, and constraints.
6. Load currently eligible model metadata.
7. Apply deterministic hard constraints.
8. Build a manageable candidate pool.
9. Ask Jev for structured decision signals, if configured and available.
10. Validate Jev output; otherwise invoke a rule-based fallback.
11. Apply final routing policy.
12. Call the chosen provider/model through the provider abstraction.
13. Stream normalized answer events to the browser.
14. Store successful response and routing telemetry as appropriate.
15. Return a request ID and final status for reconnect/reconciliation.
```

### Hard constraints

Use deterministic code for requirements such as:

- supported modality (text, image, audio, etc.)
- context window sufficient for the request
- tools/function calling required by a request
- provider/model enabled and healthy
- budget ceiling if configured as a hard limit
- required deployment/privacy boundary, such as local-only inference

Do not ask Jev to decide whether hard constraints may be ignored.

### Decision layer and Jev

Jev is an intended experimental component. Do not assume its undocumented interface, SDK, output format, latency, or pricing. Before implementing the real adapter, verify the current official integration documentation, model/API availability, credential requirements, and output contract.

Keep Jev behind an interface such as:

```python
class DecisionProvider:
    async def decide(self, query_features, candidates) -> DecisionResult:
        ...
```

An initial implementation may use a `RuleBasedDecisionProvider` so the whole application works before Jev credentials/API access are configured. A `JevDecisionProvider` can then implement the same interface.

Validate all returned candidate IDs against the current registry and filtered candidate set. Treat malformed, unknown, non-finite, or out-of-range scores as invalid. Do not accept a Jev result that bypasses hard filters.

### Routing policy

A conceptual scoring function is:

```text
score(model) = quality_weight * quality
             - cost_weight * normalized_cost
             - latency_weight * normalized_latency
             + preference_weight * preference_match
```

This is a starting abstraction, not a proven optimal formula. Hard constraints must be applied before this soft score. Document and test tie-breaking rules. Model availability and provider limits must influence the final choice.

### Confidence and exploration

- High confidence: normally call one selected model.
- Low confidence: optionally evaluate a limited top-K set or collect preference feedback when the request budget and latency policy allow it.
- Do not call every model by default. Multi-model execution increases cost and latency.
- If scores are close, use measured quality/cost/latency, availability, user preference, or a controlled exploration policy.

### Fallback behavior

- Jev unavailable or invalid → rule-based router.
- Selected model unavailable → another eligible candidate.
- Provider timeout → bounded retry, then fallback where safe.
- Provider rate limit → provider-aware reroute or controlled backoff.
- Redis unavailable → bypass cache if safe.
- No compatible candidate → return a clear user-facing error; do not silently violate mandatory constraints.

---

## 6. Model Registry Requirements

Keep model metadata in configuration/database records rather than scattering model-specific conditionals through the code.

Suggested fields:

```json
{
  "model_id": "provider-or-runtime/model-name",
  "display_name": "Human-readable model name",
  "provider": "openai | google | anthropic | ollama | vllm | other",
  "deployment_type": "commercial_api | hosted_open_model | self_hosted",
  "license_label": "record verified license here",
  "modalities": ["text"],
  "context_window": null,
  "supports_tools": false,
  "supports_streaming": true,
  "input_cost_per_unit": null,
  "output_cost_per_unit": null,
  "cost_unit": "provider-defined unit",
  "estimated_latency_ms": null,
  "quality_estimate": null,
  "available": true,
  "health_status": "unknown",
  "enabled": true,
  "metadata_version": 1
}
```

Null/unknown pricing must not be treated as zero. The registry should record the pricing unit and timestamp/source. For self-hosted models, consider infrastructure/runtime costs rather than assuming that inference is cost-free.

The exact set of supported models should be configuration-driven and limited to models for which the project has verified credentials, licensing/usage terms, capability metadata, and a working endpoint.

---

## 7. Web Application Pages and UX

### 7.1 Chat workspace — MVP priority

Main workspace should include:

- conversation list/sidebar
- new chat action
- scrollable message area
- user and assistant message styles
- prompt composer with send/stop controls
- loading/generating state
- copy response action
- code-block formatting
- error and retry states
- responsive behavior for desktop and mobile browser widths

Keep the chat UI focused. Do not overload the first screen with research charts or infrastructure details.

### 7.2 Routing details

Provide an optional expandable **“Why this model?”** section for each response. It may display:

- task category
- eligible candidate count
- selected model
- a human-readable routing reason
- confidence if meaningfully calibrated
- approximate cost/latency only when actual estimates are available
- whether a fallback was used

Do not expose API keys, secret prompts, raw private credentials, hidden chain-of-thought, or sensitive provider configuration. Give a short decision explanation, not internal reasoning traces.

### 7.3 Conversation history

- list conversations belonging to the authenticated user only
- rename/delete conversations if supported
- load earlier messages with authorization checks
- never trust a client-supplied user ID to establish ownership

### 7.4 Settings

Potential settings:

- quality vs cost vs speed preference
- optional “local models only” or privacy preference, but only if configured local models actually exist
- response style preferences
- conversation management

The routing policy must enforce settings server-side. Client-side settings are not security controls.

### 7.5 Model/route selection controls

The product is an automatic router, so the default path should automatically select a model. A future advanced mode can let a user pin a model or compare models, but those are explicit overrides and should be recorded in routing events.

### 7.6 Admin/experiment dashboard — later phase

Potential metrics:

- request count
- model selection distribution
- average route overhead
- time to first token and end-to-end latency
- estimated/actual cost where available
- provider error and fallback rates
- cache hit rate
- benchmark results

Never expose other users' prompts or conversations through aggregate analytics.

---

## 8. Frontend Structure

Suggested Next.js organization:

```text
web/
├── app/
│   ├── (auth)/
│   ├── chat/
│   │   └── [conversationId]/
│   ├── settings/
│   ├── layout.tsx
│   ├── page.tsx
│   └── globals.css
├── components/
│   ├── chat/
│   │   ├── ChatComposer.tsx
│   │   ├── ChatMessage.tsx
│   │   ├── MessageList.tsx
│   │   └── ConversationSidebar.tsx
│   ├── routing/
│   │   └── RoutingDetails.tsx
│   └── ui/
├── hooks/
│   ├── useChat.ts
│   └── useConversations.ts
├── lib/
│   ├── api.ts
│   ├── stream.ts
│   ├── schemas.ts
│   └── utils.ts
├── types/
├── public/
├── tests/
├── package.json
└── .env.example
```

If the repository already has a different structure, adapt incrementally rather than duplicating folders or rewriting unrelated code.

### Frontend rules

- Use TypeScript types for request/response payloads.
- Keep backend calls in a small API client module.
- Keep provider secrets out of all `NEXT_PUBLIC_*` variables.
- `NEXT_PUBLIC_*` variables are public and must contain only non-secret configuration, such as the backend base URL.
- Avoid placing all chat, auth, history, and settings logic in one giant component.
- Handle streaming cancellation and duplicate submissions deliberately.
- Sanitize rendered Markdown and avoid unsafe raw HTML.
- Add accessible labels, focus states, keyboard navigation, and clear empty/loading/error states.

---

## 9. Backend Structure

Suggested structure:

```text
backend/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── chat.py
│   │   ├── conversations.py
│   │   ├── feedback.py
│   │   └── health.py
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   └── logging.py
│   ├── router/
│   │   ├── analyzer.py
│   │   ├── constraints.py
│   │   ├── decision_provider.py
│   │   ├── jev_provider.py
│   │   ├── rule_based_provider.py
│   │   └── policy.py
│   ├── registry/
│   │   ├── schemas.py
│   │   └── repository.py
│   ├── providers/
│   │   ├── base.py
│   │   ├── litellm_client.py
│   │   └── adapters/
│   ├── cache/
│   ├── db/
│   ├── evaluation/
│   └── schemas/
├── tests/
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## 10. Initial API Contract

Exact routes can change with implementation, but keep contracts versionable and documented through FastAPI/OpenAPI.

### `GET /health`

Purpose: liveness/readiness information. Do not return credentials or internal secrets.

### `POST /api/v1/chat`

Example request:

```json
{
  "conversation_id": null,
  "message": "Explain binary search with a Python example.",
  "preferences": {
    "priority": "balanced",
    "local_only": false
  },
  "stream": true
}
```

Illustrative streaming events could include:

```text
event: meta
data: {"request_id":"...","conversation_id":"..."}

event: routing
data: {"model":"...","reason":"Suitable for a coding explanation"}

event: token
data: {"text":"Binary search ..."}

event: done
data: {"usage":{},"latency_ms":0}
```

Choose one stable streaming format (SSE or another documented streaming protocol) and implement client/server together. Do not mix multiple formats casually. If streaming is not ready, return a normal JSON response first and add streaming as a later milestone.

### `GET /api/v1/conversations`

Returns only conversations accessible to the authenticated user.

### `GET /api/v1/conversations/{conversation_id}`

Returns messages after server-side ownership checks.

### `DELETE /api/v1/conversations/{conversation_id}`

Deletes or archives a conversation only after authorization.

### `POST /api/v1/feedback`

Example:

```json
{
  "request_id": "...",
  "feedback": "helpful",
  "preferred_candidate": null
}
```

Feedback values must be validated and tied to a real request owned by the user.

### Error format

Use a consistent error schema with a stable code, safe user message, and request ID. Do not send stack traces, raw provider error payloads, or secrets to the browser.

---

## 11. Data Model (Initial)

A relational schema may include:

### Users
- `id`
- authentication subject/provider ID
- `created_at`
- settings/preferences

### Conversations
- `id`
- `user_id`
- `title`
- `created_at`
- `updated_at`

### Messages
- `id`
- `conversation_id`
- `role`
- `content`
- `created_at`
- optional provider usage metadata after privacy review

### Model registry
- `model_id`
- provider/runtime
- deployment type
- capabilities
- pricing/license metadata
- health/availability
- version and update timestamp

### Routing events
- `request_id`
- user/conversation references where applicable
- candidate IDs
- selected model
- decision-layer type/version
- validated decision signals
- policy result
- latency breakdown
- token/cost measurements when available
- fallback status
- timestamp

### Feedback
- `id`
- `request_id`
- `user_id`
- feedback type or preferred candidate
- timestamp

Minimize stored sensitive content. Establish retention rules and avoid logging full prompts by default unless they are necessary for an explicit research experiment and appropriate consent/privacy protections are in place.

---

## 12. Caching Strategy

### MVP

Start with:

1. Exact-response caching only for requests that are safe and eligible.
2. Routing-decision caching only when context, constraints, model-registry version, and policy version match.

Do not cache user-specific or sensitive responses indiscriminately. Cache keys should include relevant versions and request properties. Recheck current hard constraints and model availability before using a cached routing decision.

### Later

Add semantic caching only after testing freshness and false-match risk. Similar wording must not cause incorrect reuse of answers for time-sensitive, user-specific, or materially different requests.

Cache telemetry should record hits/misses and assess impact on latency, cost, and answer quality.

---

## 13. Security and Privacy

Mandatory:

- All provider and Jev credentials stay on the backend/secret manager.
- Browser requests go to this project's backend, not directly to model vendors.
- Use HTTPS in deployed environments.
- Validate payload sizes and content types.
- Apply authentication and per-user authorization for private resources.
- Apply rate limits and bounded concurrency.
- Never trust client-supplied user IDs for authorization.
- Do not log API keys, tokens, or secrets.
- Redact sensitive content from telemetry where possible.
- Restrict CORS to required origins in production.
- Treat user prompt text as untrusted data; it cannot override server policies.
- Avoid rendering untrusted Markdown/HTML unsafely.
- Avoid exposing internal prompts, raw Jev payloads, or sensitive routing configuration to the client.

Do not implement user-provided provider keys in the MVP. If BYOK is added in a later version, it requires encrypted storage, strict access control, key rotation/revocation, and no secret logging.

---

## 14. Reliability and Edge Cases

### Must handle in MVP

- Empty or invalid prompt.
- Prompt too long for every available model.
- No compatible model.
- Malformed Jev output.
- Jev integration unavailable.
- Selected model/provider unavailable.
- Provider timeout.
- Provider rate limit.
- Duplicate send / retry.
- Browser disconnect during streaming.
- User opens or refreshes a conversation they do not own.
- Missing/unknown cost or capability metadata.
- API key or sensitive error leakage.

### Expected behavior

- Show safe, actionable messages.
- Assign request IDs for tracing/reconciliation.
- Use idempotency protection where appropriate.
- Use bounded retries, not infinite retries.
- Fall back only to a model that satisfies mandatory constraints.
- If no valid model remains, tell the user that the current configuration cannot satisfy the request.
- Unknown pricing is unknown, not zero.
- Unknown capability is not automatically considered supported.

---

## 15. Research and Evaluation

The web app is also a research prototype. Keep decision-making and metrics observable enough for experiments.

### Baselines

1. Fixed single model.
2. Rule-based router.
3. Conventional ML router, if enough labeled data exists.
4. Jev-based decision layer + routing policy.
5. Jev + preference feedback, as a later experiment.
6. Adaptive/contextual router, as future work.

### Metrics

- task/answer quality
- cost/request, where measured
- routing overhead
- time to first token
- end-to-end latency
- provider error rate
- fallback rate
- cache hit rate
- human preference agreement
- model distribution
- behavior as model pool size increases

Separate documented facts, hypotheses, design decisions, and measured results. Do not invent scores or imply Jev is superior before evaluation.

### Preference collection — later phase

A controlled optional experiment may show anonymous outputs from two models and ask which answer is preferred. Do not run pairwise model comparisons for every prompt by default. Store only the data necessary for the experiment and document consent and retention behavior.

---

## 16. Performance and Scalability

Start with one FastAPI deployment and a manageable candidate pool. Keep request handling asynchronous where appropriate and use bounded concurrency for provider calls.

Scale later using:

- multiple stateless backend instances behind a load balancer
- shared Redis and PostgreSQL
- per-provider rate limits/quotas
- health-aware model availability
- queues for expensive background evaluation only if needed
- monitoring for request rate, queue depth, latency, errors, and spend

Do not create one router instance per user. Do not assume 10,000 users means 10,000 simultaneous provider calls can be safely launched; enforce concurrency limits and provider quotas.

For local open-weight models, measure available CPU/GPU memory, throughput, model loading time, concurrency, and hosting cost. A model being open-weight does not mean local inference is free or fast.

---

## 17. Suggested Repository Layout

```text
adaptive-llm-router/
├── web/                    # Next.js frontend
├── backend/                # FastAPI routing API
├── research/
│   ├── papers/
│   ├── datasets/
│   ├── experiments/
│   └── results/
├── docs/
│   ├── architecture.md
│   ├── api.md
│   ├── routing-policy.md
│   ├── security.md
│   └── evaluation.md
├── docker-compose.yml      # Optional local backend services
├── README.md
├── context.md              # This file
└── .gitignore
```

If frontend and backend live in separate repositories, retain the same logical separation and keep this file in the primary project repository.

---

## 18. Build Roadmap

### Phase 1 — Web shell

- Initialize/inspect frontend repository.
- Establish styling, responsive layout, and navigation.
- Build chat workspace with local mocked messages.

### Phase 2 — Backend skeleton

- FastAPI app and configuration.
- Health endpoint.
- Pydantic request/response schemas.
- Safe error handling and structured request IDs.

### Phase 3 — Model registry and filters

- Define model metadata schema.
- Register a small, verified set of hosted and open-weight candidates.
- Implement deterministic capability/budget filtering.

### Phase 4 — Working provider call

- Add provider abstraction/LiteLLM where supported.
- Keep all credentials server-side.
- Make one end-to-end request work before adding complex routing.

### Phase 5 — Baseline router

- Implement a rule-based fallback router.
- Add tie-breaking, availability handling, timeout, and rate-limit behavior.

### Phase 6 — Jev adapter

- Verify official integration details and access requirements.
- Implement the adapter behind the decision-provider interface.
- Validate outputs and test fallback.

### Phase 7 — Connect UI and streaming

- Connect browser to FastAPI.
- Add streaming, cancellation, retry, and request reconciliation.
- Add routing details UI.

### Phase 8 — Persistence and cache

- Add PostgreSQL conversations and routing logs.
- Add Redis exact/routing cache when its safety conditions are clear.

### Phase 9 — Evaluation

- Add baseline scripts and measurable cost/latency/quality reporting.
- Run controlled experiments; save reproducible configurations.

### Phase 10 — Hardening and future features

- Authentication, authorization, rate limits, monitoring.
- Preference feedback.
- Semantic cache, additional models, adaptive routing, and scaling when justified.

---

## 19. Definition of Done for the First End-to-End Milestone

The first milestone is complete when:

1. A user can enter a prompt in the browser.
2. The browser sends it to FastAPI.
3. FastAPI validates it and constructs eligible model candidates.
4. The baseline router selects a compatible model (Jev can be added once its integration is verified).
5. The backend calls a configured model without exposing credentials.
6. The response returns safely to the browser.
7. Errors produce useful user-facing messages.
8. Logs include request IDs and routing/provider timings without secrets.
9. Automated tests cover validation, candidate filtering, fallback, and basic provider failure.

Do not wait for Redis, semantic caching, analytics, adaptive learning, or Kubernetes before completing this milestone.

---

## 20. Project References

Use these as research/documentation starting points and verify current pages before citing them in formal work:

- FastAPI: https://fastapi.tiangolo.com/
- Pydantic: https://docs.pydantic.dev/
- Next.js: https://nextjs.org/docs
- Tailwind CSS: https://tailwindcss.com/docs
- LiteLLM: https://docs.litellm.ai/
- Ollama: https://docs.ollama.com/
- vLLM: https://docs.vllm.ai/
- OpenAI API: https://platform.openai.com/docs/
- Gemini API: https://ai.google.dev/gemini-api/docs
- Anthropic API: https://docs.anthropic.com/
- Jev / TypeSafe AI public introduction: https://typesafe.ai/blog/introducing-system-one-models-and-jev
- RouteLLM: https://arxiv.org/abs/2406.18665
- MixLLM: https://aclanthology.org/2025.naacl-long.545/
- Select-then-Route: https://aclanthology.org/2025.emnlp-industry.28/
- LLMRouterBench: https://aclanthology.org/2026.findings-acl.1881/
- FLARE: https://aclanthology.org/2026.acl-long.1018/
- RouterEval: https://aclanthology.org/2025.findings-emnlp.208/
- Intelligent Prompt Routing with User-Controlled Quality-Cost Trade-offs: https://aclanthology.org/2025.emnlp-industry.170/

---

## 21. Rules for Future Coding Assistants

Before editing:

1. Inspect the existing repository and follow its conventions.
2. Read this file and any related architecture/API document.
3. Avoid rewriting working code just to match a preferred framework.
4. Make small, testable changes.
5. Preserve the decision/generation separation.
6. Keep hard constraints deterministic and enforce them again before provider calls.
7. Keep all provider and Jev credentials server-side.
8. Include failure paths and tests with routing changes.
9. Do not invent undocumented Jev API behavior.
10. Do not claim experimental success without measured results.
11. Update this file when architecture, API contracts, or stack decisions change.
12. Prefer a minimal working end-to-end path over premature infrastructure.

## 22. One-Line Mental Model

> **The web app collects the prompt; the backend filters compatible models; the decision layer recommends; the routing policy decides; the selected model generates; the system measures the result.**
