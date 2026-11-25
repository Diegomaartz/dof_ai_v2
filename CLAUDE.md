# CLAUDE.md — DOF-AI v2

Persistent context and architectural rules for this repository. Read this before making changes. The phased roadmap and acceptance criteria live in [README.md](README.md).

## Project

DOF-AI v2 is an agentic legal intelligence platform for querying, retrieving and synthesizing Mexican legislation and daily publications of the *Diario Oficial de la Federación* (DOF).

v1 was a linear LangChain pipeline. v2 is a **stateful, self-correcting LangGraph agent** whose core goal is **zero legal hallucinations**: every answer must be grounded in retrieved articles or real-time DOF summaries.

## Non-negotiable rules

### Legal grounding
- Answers must be built **only** from retrieved content (Pinecone chunks or MCP DOF tool results). Never answer legal questions from model prior knowledge.
- Every claim must cite its source inline using the format **`[Ley X, Art. Y, DOF DD/MM/YYYY]`** (law name, article number, publication/reform date).
- If retrieval returns nothing relevant, the agent must refuse explicitly with: **"No se encontró sustento legal en las fuentes consultadas"** — never guess.
- The graph must include a Self-RAG verification step: grade retrieved docs for relevance and rewrite the query when context is insufficient (**max 2 retries**), then refuse if grounding still fails.
- Chunking of legal texts is **structural** (by Libro / Título / Capítulo / Artículo, keeping fractions and TRANSITORIOS intact), never naive fixed-size splitting. Chunk metadata must carry at least `law_name`, `article_number`, hierarchy path, `publication_date` and `source_url` so citations can be produced.

### Cost (AWS Free Tier / pay-per-use)
- **Do NOT provision:** NAT Gateways, OpenSearch Serverless, always-on EC2 instances, or any other resource with a fixed hourly cost.
- Fargate tasks run in **default VPC public subnets** with strict Security Groups (least-privilege ingress, no open admin ports).
- Prefer Lambda, S3, and on-demand Bedrock calls. Pinecone stays on the Serverless free tier.
- When adding infrastructure, state its expected monthly cost in the PR / commit description.

### Infrastructure
- All AWS resources are defined in Terraform under `infra/`. No manual console changes.
- IAM follows least privilege; one role per workload (ingestion Lambda, MCP Lambda, ECS task).
- Never hardcode AWS credentials or API keys. Workloads use IAM roles; local development uses environment variables documented in `.env.example`.
- Secrets (Pinecone API key, Django secret key, etc.) never go in code, Terraform state outputs, or the repo. Use AWS Secrets Manager / SSM Parameter Store in the cloud.

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Agent | LangGraph + `langchain-aws` (`ChatBedrockConverse`) — Claude (Sonnet/Haiku) or Amazon Nova on Bedrock |
| Tools | Model Context Protocol via official Python `mcp` SDK (`FastMCP`), stateless HTTP transport, for real-time dof.gob.mx scraping/queries |
| RAG | Pinecone Serverless + Bedrock embeddings `amazon.titan-embed-text-v2:0` |
| Backend | Django 5 + Django REST Framework, streaming responses via SSE |
| Frontend | React + Vite + TypeScript + Tailwind CSS |
| AWS | Bedrock, Lambda (ingestion & MCP server), S3 (raw legal docs + frontend hosting), ECR, ECS Fargate (Django) |
| IaC / CI-CD | Terraform + GitHub Actions |

Bedrock model IDs must be configurable via environment variables, never hard-coded, so models can be swapped (Claude ↔ Nova, Sonnet ↔ Haiku) without code changes.

## Monorepo structure

```text
dof-ai-v2/
├── CLAUDE.md               # This file
├── README.md               # Roadmap and technical documentation
├── infra/                  # Terraform (S3, Lambda, ECR, ECS Fargate, IAM)
├── mcp-server/             # Standalone FastMCP server with real-time dof.gob.mx tools
├── backend/                # Django + DRF + LangGraph agent + legal chunking pipeline
│   ├── core/               # Django settings, ASGI/WSGI config
│   ├── agent/              # LangGraph state machine, nodes, prompts, MCP client
│   └── rag/                # Structural legal chunker + Pinecone ingestion service
├── frontend/               # React SPA: legal chat + source citation viewer
└── .github/workflows/      # CI/CD (Terraform + Docker builds)
```

### Boundaries
- `mcp-server/` is independent: it must not import from `backend/`. The backend talks to it only through the MCP protocol.
- `backend/agent/` owns graph state, nodes and prompts; `backend/rag/` owns chunking, embedding and Pinecone access. The agent uses RAG through a service interface, not by calling Pinecone directly.
- The frontend consumes only the DRF API (`/api/v2/chat/`, including the SSE stream) and renders citations returned by the backend; it never calls Bedrock, Pinecone or the MCP server directly.

## MVP contracts

- **MCP tools** (exactly three, LLM-documented, returning structured JSON):
  - `get_dof_today()` — current day's DOF summary.
  - `search_dof_by_date(date_str)` — historical edition by date, format `DD-MM-YYYY`.
  - `extract_decree_text(url)` — clean text of a specific decree or agreement.
- **Graph nodes:** `router_node` (Historical Law RAG vs. Daily DOF MCP vs. Hybrid) → `retrieve_node` / `mcp_node` → `grade_documents_node` → `transform_query_node` (loop, max 2 retries) → `generate_node`.
- **Ingestion:** `s3:ObjectCreated:*` on the raw-docs bucket triggers the ingestion Lambda (PDF/TXT → structural chunks → Titan v2 embeddings → Pinecone upsert).
- **UI:** streaming chat plus a collapsible **"Fuentes Verificadas"** panel showing exact excerpts and DOF links.

## Conventions
- Python: PEP 8, type hints everywhere, Pydantic / TypedDict models for agent state and tool I/O. Document functions and tools in clear technical English.
- Prompts live in `backend/agent/prompts/` as versioned files, not inline strings scattered across nodes.
- Language: LLM-facing prompts, legal answers and UI copy are in accurate, formal **Mexican Spanish**; code, comments and identifiers are in English.
- Tests (pytest) are required before a task is considered complete: the chunker (article boundary detection on real law samples), MCP tools (mocked dof.gob.mx HTTP responses), LangGraph routing transitions and nodes (mocked Bedrock/Pinecone/MCP), and API endpoints. Never call real AWS, Pinecone or dof.gob.mx from unit tests.

## Architecture Decision Records

- **ADR-001 — Pinecone over OpenSearch Serverless:** Pinecone Serverless free tier avoids OpenSearch Serverless baseline costs (~$350 USD/month) while preserving metadata filtering.
- **ADR-002 — Structural over fixed-size chunking:** Mexican legal interpretation depends on complete articles and transitional provisions; regex-based hierarchical splitting prevents semantic fragmentation.
- **ADR-003 — MCP over hardcoded scrapers:** Decoupling DOF scraping into an MCP server lets other agents or IDE clients reuse the tools without changing backend orchestration.

## Commands

### Backend / RAG ingestion (`backend/`)

```bash
py -3.11 -m venv .venv                                   # repo root; Lambda runtime is 3.11
.venv/Scripts/python -m pip install -e "backend[dev]"    # Linux/macOS: .venv/bin/python
cd backend
python -m pytest                                         # unit tests (no network)
ruff check . && ruff format --check . && mypy            # lint, format, strict types
python -m rag.cli chunk path/to/LFT.pdf                  # dry-run the structural chunker
python -m rag.cli create-index dof-ai-legislacion        # one-off Pinecone index (1024-d, cosine)
python -m rag.cli ingest path/to/LFT.pdf --source-url <url>  # real Bedrock + Pinecone run (.env)
python -m agent.cli "¿Cuál es la duración máxima de la jornada diurna?"  # real agent run: Bedrock + Pinecone + MCP server
```

- Lambda entry point: `rag.handler.lambda_handler` (package `backend/rag` + `backend/requirements-ingestion.txt`).
- Vector IDs are `<law_slug>#art-<label>` / `<law_slug>#tr<block>-<label>`; the slug defaults to the file stem (`LFT.pdf` → `lft`) or the `x-amz-meta-law-id` S3 metadata. Re-uploading a law replaces its vectors and prunes stale IDs.
- S3 object metadata: `source-url` is **required**; `law-name` and `publication-date` (`YYYY-MM-DD`) are required when the law header cannot be parsed; `law-id` is optional. Ingestion refuses (`IncompleteLawMetadataError`, before any Bedrock/Pinecone call) rather than index chunks that cannot be cited.
- Agent: `agent.graph.build_graph(AgentDeps)` compiles the graph; `agent.factory.build_default_agent()` wires Bedrock (`BEDROCK_CHAT_MODEL_ID` for answers, `BEDROCK_FAST_MODEL_ID` for routing/grading/rewriting), `rag.retrieval.PineconeRetriever` and `agent.mcp_client.McpDofTools` (`MCP_SERVER_URL`). Tests inject fakes through `AgentDeps` (`tests/agent/conftest.py`).
- Grounding is enforced in code, not only in prompts: `generate_node` replaces with the refusal message any answer that cites a source that was not retrieved, cites nothing, or has a claim line (sentence/paragraph/list item) without its own citation (`agent.citations.check_citations`; headings, `:` intros and verbatim quotes of a source are exempt). When grading is still insufficient after the 2 rewrites it refuses without calling the LLM. Law citations come verbatim from ingestion metadata; DOF notes cite `[<título abreviado>, DOF DD/MM/YYYY]`.
- Retrieved text is untrusted data: each source is wrapped in `<fuente>…</fuente>` (tags inside the text are neutralized) and the prompts declare its content is never instructions. Repealed articles are flagged `DEROGADO` to the grader and generator.
- Answer tokens stream from the `generate_node` node (`graph.astream(..., stream_mode="messages")`, `metadata["langgraph_node"]`). The grounding check runs after the stream ends, so clients must replace the streamed text when the final state says `refused`.

### MCP server (`mcp-server/`)

```bash
cd mcp-server
py -3.11 -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"   # own venv: independent package
.venv/Scripts/python -m pytest                           # unit tests (mocked SIDOF HTTP, no network)
.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check . && .venv/Scripts/mypy
.venv/Scripts/python -m dof_mcp --port 8001              # local server at http://127.0.0.1:8001/mcp (MCP Inspector: Streamable HTTP)
```

- mcp SDK 2.x: FastMCP is now `mcp.server.mcpserver.MCPServer`; `mcp.server.fastmcp` no longer exists.
- Lambda entry point: `dof_mcp.handler.lambda_handler` (Mangum; package `mcp-server/dof_mcp` + `mcp-server/requirements-lambda.txt`). A fresh ASGI app is built per invocation because the SDK's session manager can only `run()` once; the `MCPServer` itself is built once per container.
- Data source is the public SIDOF JSON API (`https://sidof.segob.gob.mx/dof/sidof/notas/{DD-MM-YYYY}` and `/notas/nota/{codigo}`), not HTML scraping. Public links use `https://dof.gob.mx` (the `www.` host serves a mismatched TLS certificate).
- SIDOF quirks: a strict `Accept: application/json` gets **406** (send `*/*` too). `existeHtml` is always `"S"`; `existeDoc == "N"` marks scanned image/PDF-only notes with no text. `tipoNota` can be the string `"null"`, and `titulo` may be missing (never substitute a heading for it).
- `extract_decree_text` only derives the note code from dof.gob.mx / SIDOF URLs and calls the fixed SIDOF endpoint. It never fetches the URL it is given (SSRF guard).
- Expected monthly cost: Lambda + Function URL on demand, within the free tier. No fixed-cost resources.
