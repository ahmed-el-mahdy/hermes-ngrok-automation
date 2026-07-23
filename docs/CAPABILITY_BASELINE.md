# Hermes Capability Baseline

Validated on 2026-07-23 against the running workstation VM.

## Core Platform

- Hermes Agent `v0.19.0` (`v2026.7.20` image pin)
- Open WebUI as the only public dashboard
- ngrok HTTPS entry point to Open WebUI
- Telegram gateway restricted by an explicit user allowlist
- Persistent Hermes data, Open WebUI data, model cache, and shared workspace

## General Assistant Scope

HERMES is a general-purpose personal assistant and execution agent. Its default
scope includes research, software engineering, automation, documents, planning,
learning, communication, and analysis. Domain specialists are loaded only when
the task calls for them. Egyptian real-estate analysis is an optional capability,
not the assistant's primary identity.

## Built-In Tool Families

The current release exposes these verified tool families:

- browser and web research
- terminal and code execution
- files and projects
- persistent memory and session search
- skills and delegation
- tasks and scheduled jobs
- voice output, image understanding, and video handling
- user clarification and approval controls

Document and data support includes Arabic OCR, PDF extraction, DOCX extraction,
spreadsheets, structured HTML parsing, and user-writable Python packages.

## Skill Bundles

Five bundles provide predictable task-oriented skill selection:

| Bundle | Purpose |
| --- | --- |
| `personal-assistant` | Workspace, documents, maps, presentations, and notes |
| `deep-research` | Papers, structured research, citations, and document reading |
| `software-engineering` | Codebase inspection, debugging, tests, pull requests, and simplification |
| `content-studio` | Ideation, editing, design handoff, presentations, and video content |
| `property-analysis` | Optional maps, document review, research, and Egyptian property analysis |

Unsafe or irrelevant optional skills are not installed. Bundled upstream skills
remain subject to Hermes security auditing before use.

## Model Routing

- Primary cloud route: OpenRouter Nemotron free
- Cloud fallbacks: GPT OSS free, OpenRouter free router, then Gemini 2.5 Flash
- Auxiliary low-latency tasks: Gemini 2.5 Flash where a valid Gemini key exists
- Local route: `qwen3-4b-gpu:latest` through Open WebUI's native Ollama API

The local Ollama model is fully loaded in GPU memory and is intended as an
always-available direct model. Hermes cloud routing continues to use the
OpenAI-compatible providers because this Ollama build's compatibility endpoint
does not respond reliably, while its native API does.

## Acceptance Evidence

- Hermes runtime smoke test: 53 of 53 checks passed
- Telegram live validation: 3 of 3 checks passed
- Open WebUI model catalog: 11 of 11 models returned successful responses
- No pytest or smoke-test process remained running after validation

Machine-readable evidence is stored on the VM under:

`~/hermes_workspace/shared/outputs/`

## Deliberately Deferred Integrations

- Playwright MCP is not duplicated because Hermes already has an audited browser
  tool and browser snapshots.
- Google Maps Grounding is deferred until a dedicated Maps-enabled Google Cloud
  key and billing configuration are supplied.
- Apify MCP is deferred until an Apify token is supplied and a real scraping
  workflow needs it.
- An external Qdrant service is deferred while built-in persistent memory and
  session search remain healthy; adding another database would consume VM memory
  without a demonstrated need.

These integrations should be added only when their credentials and use cases are
available, then protected by the same allowlist, timeout, and security-audit
controls as the existing tools.
