"""Production wiring: Bedrock (ChatBedrockConverse) + Pinecone retriever + DOF MCP client."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain_aws import ChatBedrockConverse

from agent.config import AgentSettings
from agent.graph import build_graph
from agent.mcp_client import McpDofTools
from agent.nodes import AgentDeps
from rag.retrieval import PineconeRetriever


def build_chat_model(model_id: str, settings: AgentSettings, max_tokens: int) -> ChatBedrockConverse:
    """A deterministic Bedrock Converse chat model (Claude or Amazon Nova, chosen by ``model_id``)."""
    return ChatBedrockConverse(model=model_id, region_name=settings.aws_region, temperature=0.0, max_tokens=max_tokens)


def build_default_deps(settings: AgentSettings | None = None) -> AgentDeps:
    """Wire real dependencies from the environment. Fails fast if no Bedrock model is configured."""
    cfg = settings or AgentSettings.from_env()
    if not cfg.chat_model_id:
        raise RuntimeError("Set BEDROCK_CHAT_MODEL_ID (and optionally BEDROCK_FAST_MODEL_ID).")
    zone = ZoneInfo(cfg.timezone)
    return AgentDeps(
        fast_llm=build_chat_model(cfg.fast_model_id or cfg.chat_model_id, cfg, max_tokens=1024),
        main_llm=build_chat_model(cfg.chat_model_id, cfg, max_tokens=cfg.max_answer_tokens),
        retriever=PineconeRetriever.from_settings(),
        dof_tools=McpDofTools(cfg.mcp_server_url),
        settings=cfg,
        today=lambda: datetime.now(zone).date(),
    )


def build_default_agent(settings: AgentSettings | None = None) -> Any:
    """Compiled graph with production dependencies."""
    return build_graph(build_default_deps(settings))
