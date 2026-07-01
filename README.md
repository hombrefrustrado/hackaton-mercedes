# AI FinOps Hackathon — Starter Kit

> *"Do more intelligence with less cost."*

This starter kit gives you two running AI providers out of the box — all OpenAI-compatible, no paid keys required. Your job is to build the cost layer on top: a proxy that intercepts every AI call, tracks what it costs, enforces budgets, and helps teams make smarter decisions about which model to use and why.

The challenge is not about picking the best model. It's about picking the **optimal** one — balancing cost, quality, and latency for each type of task.

---

## What is AI FinOps?

**AI FinOps** is the practice of bringing financial accountability to AI API consumption. Every call to a language model costs money — and those costs scale with every request, every token, every team using the system.

The problem: most companies adopting AI have no visibility into any of this. They don't know which team is spending the most, whether cheaper models would do the same job, or when a budget is about to be blown. According to Flexera 2025, 32% of cloud spend is wasted — and generative AI is accelerating that trend.

AI FinOps addresses this by asking four questions:

- **Who** is consuming AI, and how much does each consumer cost?
- **What** is being spent per request — which model, which provider, how many tokens?
- **When** should the system intervene — block a request, trigger an alert, or reroute to a cheaper model?
- **Why** is a given model choice justified — what's the trade-off between cost, quality, and latency?

The goal is not to spend less — it's to spend *wisely*. This hackathon puts you in the role of the team that builds that missing layer.

---

## Prerequisites

| Tool | Version | Install (macOS) | Install (Windows) |
| --- | --- | --- | --- |
| [Docker](https://docs.docker.com/get-docker/) | 24+ | `brew install --cask docker` | [Docker Desktop](https://docs.docker.com/desktop/install/windows-install/) |
| [Task](https://taskfile.dev/installation/) | 3+ | `brew install go-task` | `winget install Task.Task` |
| [jq](https://jqlang.github.io/jq/) | any | `brew install jq` | `winget install jqlang.jq` |

> **Apple Silicon / Linux:** Ollama runs natively in the container — no extra setup needed.  
> **Windows:** Use Docker Desktop with WSL2.

### Groq API Key (Provider C)

Groq is a free cloud AI provider — no credit card required.

1. Go to [console.groq.com](https://console.groq.com) and sign in with your Google account
2. Navigate to [API Keys](https://console.groq.com/keys) and create a new key
3. Copy the example env file and paste your key:

```bash
cp .env.example .env
# Edit .env and replace gsk_your_key_here with your actual key
```

---

## Quickstart

```bash
# 1. Start both provider containers
task start

# 2. Pull the AI models (run once — downloads ~2 GB total)
task pull

# 3. Verify all providers respond (requires GROQ_API_KEY)
task smoke
```

After `task start` you have:

| Provider | Model | OpenAI-compatible base URL | Auth |
| --- | --- | --- | --- |
| Provider A (local) | `llama3.2:3b` | `http://localhost:11434/v1` | None |
| Provider B (local) | `mistral:7b` | `http://localhost:11435/v1` | None |
| Provider C (Groq cloud) | `llama-3.1-8b-instant` | `https://api.groq.com/openai/v1` | `Bearer $GROQ_API_KEY` |

All three providers accept the standard OpenAI `/v1/chat/completions` format.

---

## All Tasks

```bash
task start   # start containers and wait for health checks
task pull    # pull models into both providers (once per machine)
task smoke   # send a test completion to each provider
task stop    # stop containers (keeps downloaded models)
task reset   # stop containers and delete all model data (frees disk)
```

---

## Pricing Reference

Use these prices in your cost-tracking logic:

| Provider | Model | Input (per 1M tokens) | Output (per 1M tokens) |
| --- | --- | --- | --- |
| Provider A (local) | `llama3.2:3b` | $0.06 | $0.06 |
| Provider B (local) | `mistral:7b` | $0.24 | $0.24 |
| Provider C (Groq) | `llama-3.1-8b-instant` | $0.05 | $0.08 |

The price gaps are intentional — routing decisions between them should be non-trivial.

---

## Making a Request

Both providers speak the OpenAI Chat Completions API:

```bash
curl http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3.2:3b",
    "messages": [{"role": "user", "content": "Summarize this in one sentence."}]
  }'
```

The response includes a `usage` object with `prompt_tokens` and `completion_tokens` — use these to compute cost.

---

## What to Build

See [`CHALLENGE.es.md`](CHALLENGE.es.md) for the full spec, scoring rubric, and acceptance criteria.

In short: build a proxy layer that sits in front of these two providers and adds:

1. **Cost visibility** — track token usage and cost per consumer
2. **Budget enforcement** — block or warn when a consumer exceeds their limit
3. **Optimization logic** — define and apply routing rules to reduce cost without unacceptable quality loss

---

## Troubleshooting

**`task pull` is slow** — model downloads are 1–4 GB each. Run it once and they persist in Docker volumes across restarts (`task stop` keeps them; `task reset` deletes them).

**Port conflict on 11434** — if you have Ollama installed locally, stop it first: `ollama stop` or kill the process.

**Container won't start** — make sure Docker Desktop is running, then `task reset && task start`.
