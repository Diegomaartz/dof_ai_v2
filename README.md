# DOF-AI v2

Agentic legal RAG platform for Mexican legislation and the *Diario Oficial de la Federación* (DOF), built on LangGraph, MCP, Pinecone and Amazon Bedrock.

See [CLAUDE.md](CLAUDE.md) for architecture and rules.

## Structure

| Folder | Purpose |
|---|---|
| `infra/` | Terraform (S3, Lambda, ECR, ECS Fargate, IAM) |
| `mcp-server/` | FastMCP server with real-time dof.gob.mx tools |
| `backend/` | Django + DRF API, LangGraph agent (`agent/`), legal chunking & Pinecone ingestion (`rag/`) |
| `frontend/` | React + Vite + TypeScript + Tailwind chat UI with citation viewer |
| `.github/workflows/` | CI/CD (Terraform + Docker builds) |

## Roadmap

- [ ] Scaffold backend (Django + DRF)
- [ ] Structural legal chunker + Pinecone ingestion
- [ ] FastMCP DOF server
- [ ] LangGraph agent with grounding verification
- [ ] SSE streaming endpoint
- [ ] React frontend with citation viewer
- [ ] Terraform infra + GitHub Actions
