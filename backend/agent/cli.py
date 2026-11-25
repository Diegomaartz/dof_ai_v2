"""Ask the agent a question from the terminal (real Bedrock + Pinecone + MCP; configure ``.env``).

python -m agent.cli "¿Cuál es la duración máxima de la jornada diurna?"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from agent.factory import build_default_agent
from agent.graph import initial_state


async def _run(question: str) -> int:
    graph = build_default_agent()
    final: dict[str, Any] = {}
    async for mode, chunk in graph.astream(initial_state(question), stream_mode=["updates", "values"]):
        if mode == "updates":
            for node, update in chunk.items():
                details = {k: update[k] for k in ("route", "dof_date", "query", "retries", "sufficient") if k in update}
                print(f"· {node} {details}", file=sys.stderr)
        else:
            final = chunk
    print("\n" + final.get("answer", ""))
    for source in final.get("cited_sources", []):
        print(f"  - {source.citation} {source.url or ''}")
    for error in final.get("errors", []):
        print(f"  ! {error}", file=sys.stderr)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Consulta al agente DOF-AI.")
    parser.add_argument("question")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(asyncio.run(_run(args.question)))


if __name__ == "__main__":
    main()
