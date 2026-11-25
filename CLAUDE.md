# CLAUDE.md — DOF-AI v2

Persistent context and architectural rules for this repository. Read this before making changes.

## Project

DOF-AI v2 is an agentic legal intelligence platform for querying, retrieving and synthesizing Mexican legislation and daily publications of the *Diario Oficial de la Federación* (DOF).

v1 was a linear LangChain pipeline. v2 is a **stateful, self-correcting LangGraph agent** whose core goal is **zero legal hallucinations**: every answer must be grounded in retrieved articles or real-time DOF summaries.

## Non-negotiable rules

### Legal grounding
- Answers must be built **only** from retrieved content (Pinecone chunks or MCP DOF tool results). Never answer legal questions from model prior knowledge.
- Every claim must cite its source precisely: **law name, article number, and publication date** (DOF date for publications/reforms).
- If retrieval returns nothing relevant, the agent must say so explicitly instead of guessing.
- The graph must include a verification/self-correction step (e.g. grade retrieved docs, check the draft answer against sources, re-retrieve or rewrite the query when grounding fails).
- Chunking of legal texts is **structural** (by Libro / Título / Capítulo / Artículo, keeping fractions and transitory articles intact), never naive fixed-size splitting. Chunk metadata must carry the law, article number, hierarchy path and publication/reform date so citations can be produced.

### Cost (AWS Free Tier / pay-per-use)
- **Do NOT provision:** NAT Gateways, OpenSearch Serverless, always-on EC2 instances, or any other resource with a fixed hourly cost.
- Fargate tasks run in **default VPC public subnets** with strict Security Groups (least-privilege ingress, no open admin ports).
- Prefer Lambda, S3, and on-demand Bedrock calls. Pinecone stays on the Serverless free tier.
- When adding infrastructure, state its expected monthly cost in the PR / commit description.

### Infrastructure
- All AWS resources are defined in Terraform under `infra/`. No manual console changes.
- IAM follows least privilege; one role per workload (ingestion Lambda, MCP Lambda, ECS task).
- Secrets (Pinecone API key, Django secret key, etc.) never go in code, Terraform state outputs, or the repo. Use environment variables locally and AWS Secrets Manager / SSM Parameter Store in the cloud.

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Agent | LangGraph + `langchain-aws` (`ChatBedrockConverse`) — Claude (Sonnet/Haiku) or Amazon Nova on Bedrock |
| Tools | Model Context Protocol via official Python `mcp` SDK (`FastMCP`) for real-time dof.gob.mx scraping/queries |
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
- The frontend consumes only the DRF API (including the SSE stream) and renders citations returned by the backend; it never calls Bedrock, Pinecone or the MCP server directly.

## Conventions
- Python: type hints everywhere, Pydantic / TypedDict models for agent state and tool I/O.
- Prompts live in `backend/agent/prompts/` as versioned files, not inline strings scattered across nodes.
- Tests: unit tests for the chunker (article boundary detection on real law samples), graph nodes (with mocked Bedrock/Pinecone/MCP), and API endpoints. Never call real AWS or Pinecone from unit tests.
- User-facing content (answers, UI copy) is in Spanish; code, comments and identifiers are in English.

## Commands

_To be filled in as each package is scaffolded (install, run locally, test, lint, terraform plan/apply)._
