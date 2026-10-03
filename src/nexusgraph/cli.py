"""Command-line interface.

    nexusgraph bootstrap     generate + ingest the synthetic dataset
    nexusgraph serve         run the FastAPI server (UI + API)
    nexusgraph mcp           run the MCP server over stdio
    nexusgraph status        show store counts
"""

from __future__ import annotations

import argparse
import sys

from nexusgraph.config import get_settings
from nexusgraph.observability.logging import configure_logging, get_logger


def _cmd_bootstrap(args: argparse.Namespace) -> int:
    from nexusgraph.runtime import bootstrap

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    report = bootstrap(settings, seed=args.seed, regenerate=not args.no_regenerate)
    print(report.summary())
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    uvicorn.run(
        "nexusgraph.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        log_level=settings.log_level.lower(),
    )
    return 0


def _cmd_mcp(_args: argparse.Namespace) -> int:
    from nexusgraph.mcp_server.server import run_stdio

    configure_logging("WARNING", False)
    run_stdio()
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    from nexusgraph.runtime import build_runtime

    settings = get_settings()
    runtime = build_runtime(settings)
    print(f"profile={settings.profile}")
    print(f"entities:      {runtime.entities.count()}")
    print(f"documents:     {runtime.documents.document_count()}")
    print(f"chunks:        {runtime.documents.chunk_count()}")
    print(f"rdf triples:   {runtime.graph.count()}")
    print(f"vector index:  {runtime.vector_index.count()}")
    print(f"bootstrapped:  {runtime.is_bootstrapped()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nexusgraph",
        description="GraphRAG + Knowledge Graph Agent over synthetic life-sciences data",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    boot = sub.add_parser("bootstrap", help="generate + ingest the synthetic dataset")
    boot.add_argument("--seed", type=int, default=42)
    boot.add_argument("--no-regenerate", action="store_true",
                      help="reuse the existing generated dataset if present")
    boot.set_defaults(func=_cmd_bootstrap)

    serve = sub.add_parser("serve", help="run the API + UI server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=_cmd_serve)

    mcp = sub.add_parser("mcp", help="run the MCP server over stdio")
    mcp.set_defaults(func=_cmd_mcp)

    status = sub.add_parser("status", help="show store counts")
    status.set_defaults(func=_cmd_status)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:  # pragma: no cover
        return 130
    except Exception as exc:
        logger = get_logger("cli")
        logger.error("command failed: %s", exc, exc_info=True)
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
