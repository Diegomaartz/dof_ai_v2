# DOF-AI v2: Agentic Legal Intelligence Platform on AWS

**DOF-AI v2** is an agentic Retrieval-Augmented Generation (RAG) system designed to query, analyze, and synthesize Mexican federal legislation and daily publications from the *Diario Oficial de la Federación* (DOF).

Built with a cost-optimized, serverless-first AWS architecture, it combines historical vector search with real-time Model Context Protocol (MCP) tools and a self-correcting LangGraph workflow to prevent legal hallucinations.

See [CLAUDE.md](CLAUDE.md) for architectural rules and conventions.

---

## Architecture Overview

```text
[React SPA (S3)] ---> [Django + LangGraph API (ECS Fargate)]
                             |                  |
                (Historical Laws)        (Daily Gazette)
                             v                  v
                    [Pinecone Vector DB]  [FastMCP Server (Lambda)]
                             ^                  |
                             |                  v
            [Ingestion Lambda + Bedrock]  [dof.gob.mx]
                             ^
                             |
                  [Raw Legal Docs (S3)]
```

## Core Stack

- **Orchestration & AI:** Python, LangGraph, Amazon Bedrock (Claude Sonnet/Haiku or Amazon Nova, plus Titan Embeddings v2).
- **Tooling Protocol:** Model Context Protocol (FastMCP Python SDK).
- **Vector Database:** Pinecone (Serverless).
- **Backend & Frontend:** Django REST Framework (DRF), React (Vite + TypeScript + Tailwind).
- **Cloud & DevOps:** AWS (Bedrock, ECS Fargate, Lambda, S3, ECR, IAM), Terraform, GitHub Actions.

## Repository Structure

| Folder | Purpose |
|---|---|
| `infra/` | Terraform (S3, Lambda, ECR, ECS Fargate, IAM) |
| `mcp-server/` | FastMCP server with real-time dof.gob.mx tools |
| `backend/` | Django + DRF API, LangGraph agent (`agent/`), legal chunking & Pinecone ingestion (`rag/`) |
| `frontend/` | React + Vite + TypeScript + Tailwind chat UI with citation viewer |
| `.github/workflows/` | CI/CD (Terraform + Docker builds) |

---

## Development Roadmap (4 Phases)

### Phase 1: Event-Driven Legal RAG & Structural Chunking

**Goal:** Build an automated ingestion pipeline tailored to the hierarchical structure of Mexican laws.

**Key Deliverables:**
- Structural legal parser in `/backend/rag` that splits documents by TÍTULO, CAPÍTULO, ARTÍCULO, and TRANSITORIOS instead of arbitrary token windows.
- Metadata enrichment (`law_name`, `article_number`, `publication_date`, `source_url`).
- Embedding generation using `amazon.titan-embed-text-v2:0` via boto3.
- AWS Lambda function triggered by `s3:ObjectCreated:*` events to process and upsert vectors into Pinecone.

**Acceptance Criteria:** Uploading a `.pdf` or `.txt` law to S3 automatically indexes intact articles into Pinecone within 30 seconds without cutting mid-article.

### Phase 2: Real-Time DOF Integration via MCP Server

**Goal:** Equip the system with standardized, real-time access to daily *Diario Oficial de la Federación* publications.

**Key Deliverables:**
- Standalone MCP server in `/mcp-server` built with FastMCP using stateless HTTP transport (deployable on AWS Lambda).
- Three LLM-documented tools:
  - `get_dof_today()`: Fetches and parses the current day's DOF summary.
  - `search_dof_by_date(date_str)`: Queries historical editions by date (`DD-MM-YYYY`).
  - `extract_decree_text(url)`: Extracts clean text from specific decrees or agreements.
- pytest unit test suite mocking HTTP responses from dof.gob.mx.

**Acceptance Criteria:** MCP Inspector or a local Python client successfully discovers and executes all three tools returning structured JSON payloads.

### Phase 3: Self-RAG Agent in LangGraph & Django API

**Goal:** Replace linear chains with a cyclical, self-evaluating agentic workflow exposed via a streaming REST API.

**Key Deliverables:**
- LangGraph state machine in `/backend/agent` powered by `ChatBedrockConverse`:
  - `router_node`: Classifies intent (Historical Law RAG vs. Daily DOF MCP vs. Hybrid).
  - `retrieve_node` / `mcp_node`: Executes parallel or sequential context gathering.
  - `grade_documents_node`: Evaluates retrieved chunks for relevance; triggers query rewriting (`transform_query_node`) if context is insufficient (max 2 retries).
  - `generate_node`: Synthesizes formal legal answers in Spanish with mandatory inline citations.
- Django REST Framework endpoint (`/api/v2/chat/`) supporting Server-Sent Events (SSE) streaming and returning structured source metadata.
- React frontend in `/frontend` displaying streamed answers and an interactive "Fuentes Verificadas" source citation drawer.

**Acceptance Criteria:** Out-of-scope or unsupported queries trigger a graceful refusal ("No se encontró sustento legal en las fuentes consultadas"), and valid queries cite exact article numbers.

### Phase 4: Infrastructure as Code (Terraform) & CI/CD

**Goal:** Automate cloud provisioning and continuous deployment with zero manual console configuration.

**Key Deliverables:**
- Modular Terraform configuration in `/infra` provisioning:
  - S3 buckets (raw legal documents with Lambda event notifications + static website hosting for React).
  - AWS Lambda functions (ingestion worker + MCP server) and Amazon ECR repositories.
  - ECS Fargate cluster, task definition, and service (configured on public subnets without NAT Gateways to minimize cost).
  - Least-privilege IAM roles allowing ECS and Lambda to invoke Amazon Bedrock and access S3.
- GitHub Actions workflow (`.github/workflows/deploy.yml`) running pytest, `terraform plan/apply`, Docker image builds to ECR, and rolling ECS/S3 updates on push to `main`.

**Acceptance Criteria:** A single `git push` to `main` validates tests, updates AWS infrastructure, and deploys the latest backend and frontend containers automatically.

---

## Architecture Decision Records (ADRs)

- **ADR-001 (Pinecone over OpenSearch Serverless):** Selected Pinecone Serverless Free Tier to avoid AWS OpenSearch Serverless minimum baseline costs (~$350 USD/month) while preserving metadata filtering capabilities.
- **ADR-002 (Structural Chunking over Fixed-Size Splitting):** Mexican legal interpretation depends on complete articles and transitional provisions; regex-based hierarchical splitting prevents semantic fragmentation.
- **ADR-003 (MCP over Hardcoded Scrapers):** Decoupling DOF web scraping into an MCP server allows the scraping tools to be reused across other internal agents or IDE clients without modifying backend orchestration logic.
