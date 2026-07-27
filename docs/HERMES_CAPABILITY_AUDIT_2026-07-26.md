# Hermes Capability Audit

Date: 2026-07-26

## Scope

This audit compares the live Hermes VM with the v0.19.0 source tree, official
documentation, official optional skill catalog, and selected public GitHub
skill repositories. It is intentionally evidence-based: a listed skill is not
treated as a working capability until its dependencies and runtime path pass a
local test.

## Verified Baseline

- Hermes Agent: v0.19.0 (2026.7.20), upstream commit `3ef6bbd2`
- Live skill inventory before this change: 87 enabled
- Built-in and local tools: 29 schemas
- System prompt before curation: 23.0 KB
- Skills index before curation: 9.3 KB
- Tool schemas before curation: 48.2 KB
- Persistent session store: 131 sessions
- Core tools verified by `hermes doctor`: browser, code execution, cron,
  delegation, files, memory, projects, session search, skills, terminal, todo,
  TTS, video, vision, and web
- Active providers verified by `hermes doctor`: Ollama Cloud, OpenRouter, and
  Gemini; local GPU remains the no-cloud-quota fallback
- Live tool-call validation replaced OpenRouter Nemotron with free
  `inclusionai/ling-3.0-flash:free` and the `openrouter/free` capability
  router; both produced valid tool calls before the local GPU route, but share
  the same OpenRouter account allowance

## High-Value Additions

The durable skill profile installs only these official optional skills:

| Skill | Value |
|---|---|
| `duckduckgo-search` | Key-free text, news, image, and video search fallback |
| `excel-author` | Auditable spreadsheet creation with `openpyxl` |
| `memento-flashcards` | Reusable spaced-repetition learning workflows |
| `code-wiki` | Markdown and Mermaid reference documentation for codebases |
| `one-three-one-rule` | Concise problem/options/recommendation decisions |

These skills complement existing tools instead of duplicating them. They load
on demand through Hermes' progressive-disclosure skill system.

## Disabled Noise And Risk

The curated profile disables skills that are unsafe, irrelevant to the current
host, or guaranteed to fail because their service is not configured:

- `godmode`
- `obliteratus`
- `spotify`
- `apple-productivity`
- `openhue`
- `xurl`
- `yuanbao`
- `polymarket`
- `petdex`
- `heartmula`
- `audiocraft-audio-generation`
- `touchdesigner-mcp`
- `watchers`
- `fitness-nutrition`
- `rest-graphql-debug`

The disabled bundled files remain available for deliberate future review;
disabling removes them from normal discovery and prompt selection without
destructive deletion.

The last three entries above were reviewed from the official optional catalog,
but their installed copies received `DANGEROUS` verdicts from
`hermes skills audit --deep` because they read credentials and make outbound
requests. They were uninstalled from the active profile rather than silently
overriding the scanner. Existing built-in web, cron, API, and health workflows
cover their immediate use cases.

## Personal Knowledge Strategy

Personal-project ingestion is Markdown-first:

1. Curated Markdown dossiers are the highest-confidence retrieval layer.
2. Existing Markdown attachment extracts are indexed directly.
3. Text, DOCX, and embedded PDF text are extracted locally during import.
4. Images remain in the private archive and are OCR'd only when a specific
   question needs a specific image.
5. Raw user turns remain searchable below curated and attachment evidence.
6. Old assistant turns are lowest priority and never override user-authored
   facts.

This keeps imports fast, avoids unnecessary OCR errors, and minimizes the
private text sent into any one model request.

## Public GitHub Sources Reviewed

### NousResearch/hermes-agent

Primary source of truth. The installed v0.19.0 already includes Skills Hub,
GitHub and registry installs, `/learn`, MCP, profiles, projects, webhooks,
checkpoints, curator, journey, security audit, and the native dashboard.

### ZeroPointRepo/awesome-hermes-skills

Useful discovery index for Hermes-specific projects. Its own security notice
says the entries are curated rather than audited and recommends reading source
and pinning a commit. It is not installed as a bundle.

### anthropics/skills

Strong reference implementation of the Agent Skills standard, especially for
document workflows. The current Hermes image already has PDF, DOCX, PPTX, OCR,
and spreadsheet dependencies, so copying the whole repository would add
substantial duplication.

### vercel-labs/agent-skills

High-quality first-party React, web design, React Native, and Vercel guidance.
These are good project-specific additions when a matching frontend project is
active. They are not part of the always-on general assistant profile.

### OpenDataLab/MinerU-Document-Explorer

Powerful local document MCP with deep reading and hybrid retrieval. Full vector
mode downloads roughly 2 GB of models and adds a persistent service. The
current private archive is small enough for the existing SQLite FTS5 index, so
MinerU is deferred until document volume or layout complexity justifies the
resource cost.

### openai/skills

The repository now marks itself deprecated in favor of OpenAI Plugins. It is
not used as a new installation source.

## Supply-Chain Policy

For any future community skill:

1. Prefer the official Hermes catalog when an equivalent exists.
2. Inspect the full `SKILL.md`, scripts, references, and declared dependencies.
3. Pin public GitHub content to a reviewed commit SHA.
4. Run `hermes skills inspect` before installation.
5. Run `hermes skills audit --deep` after installation.
6. Run `hermes security audit` for Python, plugin, and MCP dependencies.
7. Keep secrets only in `/opt/data/.env` or Hermes' secret providers.
8. Disable the skill if its runtime dependency is absent.
9. Validate one real workflow before describing the capability as ready.

## Deferred Integrations

These should be added only when the user wants the corresponding workflow and
provides or authorizes its connection:

- Email and calendar provider
- Home Assistant
- Spotify
- Discord
- X search/posting
- Image or video generation provider
- Heavy local vector document MCP

This avoids prompt noise, failed tool calls, idle services, and unnecessary
credential exposure.
