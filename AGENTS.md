# AGENTS.md — Adaptive Multi-LLM Router Web Application

This file defines the working rules for AI coding agents and human contributors working in this repository. Follow it alongside `context.md` and the current source code.

## 1. Project Purpose

Build a web application that gives users one interface for interacting with multiple large language models (LLMs). The backend should select a suitable model based on the request, model capabilities, availability, cost, latency, and configured preferences.

The system is also a research prototype. Routing approaches must be measurable and compared against baselines; do not present an untested design or hypothesis as a proven result.

### Core principle

**Decision layer ≠ generation layer.**

- **Hard-constraint filter:** deterministic application code removes models that cannot satisfy mandatory requirements.
- **Jev decision layer:** an experimental component that may provide structured suitability signals. Verify its actual API, supported inputs, outputs, authentication and limitations from authoritative documentation before implementing it.
- **Routing policy:** application-owned logic that validates decision signals and makes the final selection under constraints.
- **Generation layer:** the selected LLM produces the user-facing answer.

Jev is not the answer generator and must not bypass hard constraints. Keep a rule-based fallback available if Jev is unavailable or returns invalid output.

## 2. Source of Truth and Repository Inspection

Before changing code:

1. Inspect the existing repository, package manifests, environment examples, tests and README.
2. Read `context.md` for project-specific product and architecture context.
3. Preserve working patterns and conventions already established in the codebase.
4. Do not assume a directory, package, endpoint, provider, database or integration exists until verified.
5. If documentation and code conflict, report the conflict and favor the behavior verified in source/tests; do not silently rewrite unrelated architecture.
6. Make focused changes. Avoid large rewrites unless explicitly requested.

Do not overwrite existing user work or generated files without checking their purpose.

## 3. Intended Technology Stack

Use the following as the target stack, not as proof that every dependency is already installed.

### Web frontend
- Next.js
- React
- TypeScript
- Tailwind CSS
- A consistent, accessible component system
- TanStack Query for server state where useful
- Zustand only if shared client state genuinely needs it

### Backend
- Python
- FastAPI
- Pydantic
- Uvicorn
- `httpx` for asynchronous HTTP calls where appropriate
- LiteLLM for supported provider abstraction

### Data and infrastructure
- PostgreSQL for persistent application data and experiment/routing records
- Redis for cache, rate limits and short-lived state
- Docker for repeatable local development/deployment
- Ollama for suitable local model development
- vLLM for suitable self-hosted model serving

Do not add all optional tools at once. Check the existing repository and add only dependencies required for the current milestone.

### Supported model categories
The design should be able to accommodate:
- Commercial/hosted APIs: OpenAI, Google Gemini and Anthropic Claude.
- Open-weight model families: Llama, Qwen, Mistral and Gemma.
- Local/self-hosted inference through Ollama or vLLM where compatible.

A model being open-weight does not automatically mean every distribution, hosted endpoint or usage is free. Store provider/model-specific pricing, license notes, capabilities and deployment mode as metadata where relevant. Do not hard-code claims that a model is free.

## 4. Architecture and Request Flow

Keep the main request path understandable and testable:

```text
Browser
  ↓ HTTPS
Next.js Web App
  ↓ authenticated API request / streaming
FastAPI Backend
  ↓
Input Validation + Authentication + Rate Limiting
  ↓
Query Analysis
  ↓
Cache Lookup (when configured)
  ↓
Model Registry
  ↓
Deterministic Hard-Constraint Filter
  ↓
Candidate Models
  ↓
Jev Decision Layer (experimental, if configured)
  ↓
Routing Policy
  ↓
LiteLLM / Provider Adapter
  ↓
Selected Hosted or Self-Hosted Model
  ↓
Normalized Response / Stream
  ↓
Web UI + Metrics/Feedback
```

Important invariants:
- Apply hard constraints before the decision layer.
- Validate Jev output against a strict schema and registered candidate IDs.
- Never select a model that failed a hard constraint.
- Keep final selection in the application routing policy.
- Use the rule-based router when Jev is disabled, unavailable or invalid.
- If no candidate is compatible, return a clear controlled error; do not silently violate requirements.
- Normalize provider responses at the backend boundary.
- Keep provider-specific details out of frontend components.

## 5. Frontend Guidelines

Build a polished, responsive web app rather than a generic chat mockup.

Expected product areas, subject to current project scope:
- Chat workspace
- Conversation history
- Model/routing transparency panel
- Settings and user preferences
- Feedback controls
- Optional model/provider status and usage information

### UX requirements
- Make loading, streaming, empty, success, error and retry states explicit.
- Display useful errors without exposing stack traces, secrets or raw provider internals.
- Show the selected model and relevant routing explanation when available.
- Label estimates as estimates; do not imply cost or latency is exact unless it is measured.
- Do not fabricate routing confidence, model availability, cost or latency.
- Keep the chat usable on narrow and wide screens.
- Support keyboard navigation, visible focus, semantic HTML, readable contrast and accessible labels.
- Use optimistic UI only where failures can be reconciled safely.
- Avoid unnecessary animations and heavy dependencies.

### Component boundaries
- Keep page components focused on layout and composition.
- Put API calls in a shared typed API/client layer, not directly throughout UI components.
- Separate chat rendering, message composition, routing metadata, settings and feedback into reusable components.
- Keep secrets and privileged logic entirely out of client bundles.

## 6. Backend and API Guidelines

- Use Pydantic request/response models for API boundaries.
- Use explicit types and clear error responses.
- Keep routing, provider calls, model registry, cache, persistence and evaluation logic in separate modules.
- Use asynchronous I/O for network-bound operations where appropriate.
- Configure connect/read/overall timeouts.
- Retry only when appropriate, with bounded attempts and backoff. Avoid retry storms and duplicate billable requests.
- Implement provider-aware fallback only to a compatible candidate.
- Add request/correlation IDs to help trace a request across routing and generation.
- Document endpoints through FastAPI/OpenAPI.
- Do not report success until the provider or local model has actually returned a successful result.
- Avoid logging full prompts/responses by default; redact sensitive information and make retention intentional.

Proposed endpoints may include health, chat, conversation history, settings, routing metadata and feedback. Verify the existing API before adding or renaming endpoints. Keep endpoint names and schemas consistent across frontend, backend and tests.

## 7. Streaming

If streaming is implemented:
- Use the repository's chosen transport consistently (for example SSE or streaming HTTP).
- Define and document event names and payload schemas.
- Include request IDs and a clear terminal success/error event.
- Handle user cancellation, network disconnect and partial responses.
- Prevent duplicate message creation on reconnect.
- Keep the UI able to distinguish “generating”, “complete” and “failed”.
- Do not assume that a disconnected client means the backend generation stopped.

## 8. Model Registry and Routing

A model entry should represent only verified/configured information. Depending on the provider, useful metadata includes:
- stable internal model ID
- provider and external model name
- deployment mode (hosted/local/self-hosted)
- modalities and supported tools
- context limit
- input/output pricing or an explicit unknown value
- availability/health
- measured or estimated latency
- version and metadata update time
- relevant license/deployment notes

### Routing policy
- Hard constraints are pass/fail filters, not weighted preferences.
- Soft objectives may consider suitability/quality, cost, latency, availability and user preferences.
- Mark unknown pricing/latency as unknown; never assume unknown cost is zero.
- Treat Jev scores/confidence as signals, not ground truth.
- When confidence is low or scores are close, use a documented policy such as a compatible fallback or limited top-K evaluation only when enabled and budgeted.
- Do not call every model for every request by default.
- Record enough metadata to reproduce experiments without unnecessarily storing sensitive content.

## 9. Commercial and Open-Weight Models

Treat hosted APIs and local/self-hosted inference as different deployment paths.

- Hosted commercial models require server-side provider credentials and are subject to provider pricing, quotas and terms.
- Open-weight models may still require significant hardware, have license conditions, or incur hosting costs.
- Local inference must be optional and capability-aware; not every workstation can run every model.
- Ollama and vLLM are serving options, not model families.
- Check provider/model compatibility in the current LiteLLM and serving documentation before adding integrations.
- Do not download large model weights automatically as part of ordinary app startup.
- Do not claim offline capability unless the chosen model, runtime and all required app paths truly work offline.

## 10. Security and Privacy — Non-Negotiable

- Never place provider API keys, Jev credentials, database passwords or secret tokens in frontend code, `NEXT_PUBLIC_*` variables, committed files or browser storage.
- Keep credentials on the server, loaded from environment configuration or a secret manager.
- Commit `.env.example` with placeholder values only; never commit `.env`.
- Validate and limit user input, request size, output size and execution time.
- Apply authentication and server-side authorization to user-specific data.
- Never trust a client-supplied user ID as proof of identity.
- Use parameterized database access/ORM patterns.
- Configure CORS narrowly for known application origins.
- Rate-limit public or expensive endpoints.
- Avoid logging secrets, auth tokens or sensitive prompts unnecessarily.
- Treat user prompts and model output as untrusted data. Do not allow prompt injection to change routing policy or reveal system secrets.
- Sanitize rendered Markdown/HTML to prevent XSS.
- Do not expose raw provider errors, stack traces or internal configuration to the client.
- If BYOK is ever added, design secure encryption, isolation, rotation and deletion before shipping it. BYOK is not required for the MVP.

## 11. Caching

Caching is optional until the core request flow works.

- Start with exact-response and/or routing-decision caching only when needed.
- Revalidate model availability and hard constraints even when a routing decision is cached.
- Include relevant model, prompt, router and policy versions in cache keys/metadata.
- Use TTL and invalidation.
- Do not reuse stale or user-specific responses across users.
- Be conservative with time-sensitive, personalized or rapidly changing questions.
- Cache successful responses only; do not cache provider failures as successful answers.
- Track cache hits, misses, stale-result safeguards and latency impact.

Semantic caching and vector infrastructure are later enhancements, not MVP prerequisites.

## 12. Data and Database

- Use migrations for schema changes.
- Keep database access behind a repository/service boundary where practical.
- Enforce user ownership in every query involving private conversations or settings.
- Store only what the product and research actually need.
- Separate operational logs/metrics from sensitive conversation content.
- Define retention/deletion behavior for conversation and feedback data.
- Store experiment metadata such as router version, policy version, candidate set, selected model, latency and estimated/actual cost when available.

## 13. Testing Requirements

Add or update tests for every meaningful behavior change.

### Backend tests
- request validation
- hard-constraint filtering
- routing-policy decisions
- invalid Jev output
- Jev unavailable → rule-based fallback
- no compatible candidate
- provider timeout/rate limit/failure
- provider fallback compatibility
- secret redaction and authorization
- cache invalidation/TTL behavior
- streaming termination and disconnect handling where supported

### Frontend tests
- chat submission
- streaming/loading states
- empty/error/retry states
- routing metadata display
- responsive and accessible interactions
- authentication and conversation isolation

### Integration
- Keep tests deterministic; mock external provider APIs.
- Do not require paid provider calls for ordinary unit-test runs.
- Provide an explicit opt-in smoke test for real provider credentials.
- Never use real secrets in test fixtures.

Run the relevant formatter, linter, type checker and tests after changes. Report commands run and any failures honestly.

## 14. Research and Evaluation Integrity

The project evaluates routing; it must not invent results.

Compare, where implemented:
1. Fixed single-model baseline
2. Rule-based router
3. Conventional ML router, if developed
4. Jev-based router
5. Jev plus preference feedback, if developed
6. Adaptive/contextual approach, as future work

Measure appropriate combinations of:
- answer/task quality
- cost per request
- end-to-end latency
- routing overhead
- time to first token
- fallback/error rate
- cache hit rate
- human preference agreement
- model-count scalability

Keep hypotheses, design choices, measured results and future work clearly separate. Do not claim Jev is superior without reproducible evidence. Ensure comparisons use consistent datasets, budgets and evaluation conditions.

## 15. MVP Priority Order

Prioritize a working end-to-end vertical slice:

1. Inspect repository and document current state.
2. Establish frontend/backend run instructions and environment configuration.
3. Implement FastAPI health endpoint and typed API contract.
4. Implement a small verified model registry.
5. Implement deterministic hard-constraint filtering.
6. Implement a rule-based fallback router.
7. Integrate LiteLLM with one working provider first.
8. Verify one complete request from browser to model and back.
9. Add a second provider and provider-aware fallback.
10. Integrate Jev after verifying its current interface and capabilities.
11. Implement the application-owned routing policy.
12. Build the chat UI and streaming.
13. Add routing transparency and useful error states.
14. Add persistence only for concrete requirements.
15. Add Redis caching after the request path works.
16. Add evaluation scripts and repeatable experiments.
17. Harden authentication, limits, logging and deployment.

Do not start with Kubernetes, Kafka, multiple microservices, sophisticated semantic caching, contextual bandits or dozens of providers. Add them only when a demonstrated requirement justifies the complexity.

## 16. Coding Standards

- Prefer small, readable, single-purpose modules.
- Use TypeScript strict typing and Python type hints.
- Avoid `any`, broad exception swallowing and unexplained magic constants.
- Keep configuration centralized and validate it at startup.
- Avoid duplicate provider-specific logic.
- Use clear names and concise comments that explain non-obvious decisions.
- Do not introduce abstractions that have only one trivial use unless they improve a meaningful boundary.
- Keep dependencies minimal and justify new packages.
- Preserve backward compatibility for API changes where practical; update all consumers and tests together.
- Never leave fake success data or placeholder model outputs in production paths.
- Mark incomplete functionality clearly rather than pretending it works.

## 17. Agent Workflow for Each Task

For each implementation task:

1. State the intended outcome briefly.
2. Inspect relevant files before editing.
3. Identify assumptions and affected interfaces.
4. Make the smallest complete change.
5. Add/update tests.
6. Run appropriate checks.
7. Review the diff for secrets, unrelated changes, incorrect claims and dead code.
8. Summarize changed files, behavior, test commands/results and any remaining limitation.

If blocked by missing credentials or an undocumented Jev interface, implement a clean adapter boundary and a tested mock/rule-based fallback. Do not fabricate credentials, endpoints or API behavior.

## 18. Definition of Done

A change is complete only when:
- behavior matches the requested task
- frontend/backend contracts agree
- validation and error handling are present
- relevant tests/checks are run and reported
- no secrets are committed or exposed
- documentation/config examples are updated where needed
- unsupported claims and fake results are absent
- remaining limitations are stated clearly

## 19. First End-to-End Success Criterion

A user submits a prompt in the web app; the backend validates it, filters incompatible models, selects a compatible candidate using the active router, calls the configured hosted or self-hosted model, and returns/streams the actual answer with honest routing metadata and recoverable errors.

Build and verify this path before expanding the system.
