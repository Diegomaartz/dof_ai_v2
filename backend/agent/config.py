"""Agent configuration from environment variables. Bedrock model IDs are never hard-coded."""

from __future__ import annotations

import os
from dataclasses import dataclass

MAX_RETRIES_LIMIT = 2
"""Self-RAG rewrite bound mandated by CLAUDE.md; ``AGENT_MAX_RETRIES`` may lower it, never raise it."""


@dataclass(frozen=True)
class AgentSettings:
    """Runtime settings for the LangGraph agent.

    Attributes:
        chat_model_id: Bedrock model for the final answer (``BEDROCK_CHAT_MODEL_ID``), e.g. a Claude Sonnet
            or Amazon Nova Pro inference profile.
        fast_model_id: Cheaper model for routing, grading and query rewriting (``BEDROCK_FAST_MODEL_ID``);
            defaults to ``chat_model_id``.
        aws_region: Region for Bedrock.
        mcp_server_url: Streamable HTTP endpoint of the DOF MCP server.
        retrieval_top_k: Chunks requested from the vector store per attempt.
        max_retries: Query rewrites allowed before refusing (Self-RAG loop bound).
        max_dof_candidates: Upper bound of DOF notes passed to the grader from one edition.
        max_dof_full_texts: Relevant DOF notes whose full text is fetched for generation.
        dof_text_chars: Characters of each fetched decree text given to the generator.
        grade_excerpt_chars: Characters of each source shown to the grader.
        max_answer_tokens: Output cap for the generator.
        timezone: Timezone defining "today" for DOF questions.
    """

    chat_model_id: str | None = None
    fast_model_id: str | None = None
    aws_region: str | None = None
    mcp_server_url: str = "http://127.0.0.1:8001/mcp"
    retrieval_top_k: int = 6
    max_retries: int = 2
    max_dof_candidates: int = 250
    max_dof_full_texts: int = 2
    dof_text_chars: int = 12_000
    grade_excerpt_chars: int = 1_500
    max_answer_tokens: int = 2_048
    timezone: str = "America/Mexico_City"

    def __post_init__(self) -> None:
        if not 0 <= self.max_retries <= MAX_RETRIES_LIMIT:
            raise ValueError(
                f"max_retries must be between 0 and {MAX_RETRIES_LIMIT} (CLAUDE.md), got {self.max_retries}"
            )

    @classmethod
    def from_env(cls) -> AgentSettings:
        default = cls()
        chat = os.getenv("BEDROCK_CHAT_MODEL_ID") or None
        return cls(
            chat_model_id=chat,
            fast_model_id=os.getenv("BEDROCK_FAST_MODEL_ID") or chat,
            aws_region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
            mcp_server_url=os.getenv("MCP_SERVER_URL", default.mcp_server_url),
            retrieval_top_k=int(os.getenv("AGENT_RETRIEVAL_TOP_K", default.retrieval_top_k)),
            max_retries=int(os.getenv("AGENT_MAX_RETRIES", default.max_retries)),
            max_dof_candidates=int(os.getenv("AGENT_MAX_DOF_CANDIDATES", default.max_dof_candidates)),
            max_dof_full_texts=int(os.getenv("AGENT_MAX_DOF_FULL_TEXTS", default.max_dof_full_texts)),
            dof_text_chars=int(os.getenv("AGENT_DOF_TEXT_CHARS", default.dof_text_chars)),
            grade_excerpt_chars=int(os.getenv("AGENT_GRADE_EXCERPT_CHARS", default.grade_excerpt_chars)),
            max_answer_tokens=int(os.getenv("AGENT_MAX_ANSWER_TOKENS", default.max_answer_tokens)),
            timezone=os.getenv("AGENT_TIMEZONE", default.timezone),
        )
