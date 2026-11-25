"""Developer CLI for the ingestion pipeline.

Usage (from ``backend/``)::

    python -m rag.cli chunk path/to/LFT.pdf            # dry run, no AWS/Pinecone
    python -m rag.cli chunk path/to/LFT.pdf --jsonl out.jsonl
    python -m rag.cli create-index dof-ai-legislacion  # one-off Pinecone setup
    python -m rag.cli ingest path/to/LFT.pdf --source-url https://www.diputados.gob.mx/LeyesBiblio/pdf/LFT.pdf
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from rag.chunker import ChunkerConfig, LegalChunker
from rag.config import RagSettings, get_pinecone_api_key
from rag.models import SectionType
from rag.service import DocumentSource, build_chunks


def _source(args: argparse.Namespace) -> DocumentSource:
    path = Path(args.file)
    return DocumentSource(
        filename=path.name,
        data=path.read_bytes(),
        source_key=str(path),
        source_url=getattr(args, "source_url", None),
        law_name=getattr(args, "law_name", None),
    )


def cmd_chunk(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    chunks = build_chunks(_source(args), LegalChunker(ChunkerConfig(max_chunk_chars=args.max_chars)))
    law = chunks[0].law
    kinds = Counter(c.section_type.value for c in chunks)
    print(f"{law.law_name} [{law.law_slug}] publicada {law.publication_date} · última reforma {law.last_reform_date}")
    print(f"{len(chunks)} chunks ({dict(kinds)}) in {time.perf_counter() - started:.2f}s")
    print(f"split articles: {sorted({c.article_label for c in chunks if c.part_count > 1})}")
    print(f"repealed: {sum(c.is_repealed for c in chunks)}")
    for c in chunks[: args.show]:
        print(f"\n--- {c.id}  {c.citation}\n    {c.hierarchy_path}\n{c.text[:400]}")
    if args.jsonl:
        with open(args.jsonl, "w", encoding="utf-8") as fh:
            for c in chunks:
                fh.write(json.dumps(c.to_metadata() | {"id": c.id}, ensure_ascii=False) + "\n")
        print(f"\nwrote {args.jsonl}")
    articles = [c for c in chunks if c.section_type is SectionType.ARTICULO]
    return 0 if articles else 1


def cmd_create_index(args: argparse.Namespace) -> int:
    from pinecone import Pinecone, ServerlessSpec

    settings = RagSettings.from_env()
    pc = Pinecone(api_key=get_pinecone_api_key(settings))
    if pc.has_index(args.name):
        print(f"index {args.name} already exists: {pc.describe_index(args.name).host}")
        return 0
    model = pc.create_index(
        name=args.name,
        dimension=settings.embedding_dimensions,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region=args.region),
    )
    print(f"created {args.name}; set PINECONE_INDEX_HOST={model.host}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from rag.handler import _get_service

    result = _get_service().ingest(_source(args))
    print(result.model_dump_json(indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rag.cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("chunk", help="Parse a law and print its structural chunks (no network).")
    p.add_argument("file")
    p.add_argument("--law-name")
    p.add_argument("--show", type=int, default=3, help="Number of chunks to print.")
    p.add_argument("--max-chars", type=int, default=8000)
    p.add_argument("--jsonl", help="Write all chunks (metadata form) to this file.")
    p.set_defaults(func=cmd_chunk)

    p = sub.add_parser("create-index", help="Create the Pinecone serverless index.")
    p.add_argument("name")
    p.add_argument("--region", default="us-east-1", help="Pinecone free tier only offers aws/us-east-1.")
    p.set_defaults(func=cmd_create_index)

    p = sub.add_parser("ingest", help="Embed with Bedrock and upsert into Pinecone.")
    p.add_argument("file")
    p.add_argument("--law-name")
    p.add_argument("--source-url")
    p.set_defaults(func=cmd_ingest)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
