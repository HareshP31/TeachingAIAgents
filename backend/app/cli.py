from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from app.config import get_settings
from app.agents.analyst import Analyst
from app.agents.auditor import Auditor
from app.db.database import Database
from app.db.migrations import migrate
from app.db.repository import Repository
from app.graphs.ingestion_graph import IngestionService
from app.services.corpus import CorpusImportService
from app.services.embeddings import FakeEmbedder, SentenceTransformerEmbedder
from app.services.evaluation import CorpusEvaluator, write_report
from app.services.llm import LMStudioClient


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    await database.open()
    try:
        await migrate(database)
        repository = Repository(database)
        if args.command == "migrate":
            print("database migrated")
        elif args.command == "always-review":
            await repository.set_always_review(args.enabled == "true")
            print(f"always_review={args.enabled}")
        elif args.command == "ingest":
            fake = settings.app_mode in {"fake", "test"}
            embedder = FakeEmbedder(settings.embedding_dimensions) if fake else SentenceTransformerEmbedder(settings.embedding_model)
            service = IngestionService(repository, embedder, settings)
            paths = sorted(Path(args.path).glob("*.pdf")) if Path(args.path).is_dir() else [Path(args.path)]
            if not paths:
                raise SystemExit("no PDFs found")
            for path in paths:
                result = await service.ingest_path(path)
                print(f"{path.name}: {result}")
        elif args.command == "import-archive":
            fake = settings.app_mode in {"fake", "test"}
            embedder = FakeEmbedder(settings.embedding_dimensions) if fake else SentenceTransformerEmbedder(settings.embedding_model)
            ingestion = IngestionService(repository, embedder, settings)
            result = await CorpusImportService(repository, ingestion, settings).import_archive(Path(args.path))
            print(json.dumps({key: value for key, value in result.items() if key != "manifest"}, default=str))
            if result.get("status") == "partial":
                raise SystemExit(2)
        elif args.command == "corpus-status":
            result = (
                await repository.get_corpus_import(UUID(args.import_id))
                if args.import_id else await repository.list_corpus_imports()
            )
            print(json.dumps(result, default=str))
        elif args.command == "cleanup":
            result = await repository.cleanup(args.kind)
            print(json.dumps(result))
        elif args.command == "eval-corpus":
            fake = settings.app_mode in {"fake", "test"}
            embedder = FakeEmbedder(settings.embedding_dimensions) if fake else SentenceTransformerEmbedder(settings.embedding_model)
            analyst = auditor = None
            if args.full:
                llm = None if fake else LMStudioClient(
                    settings.lm_studio_base_url, settings.lm_studio_api_key,
                    settings.lm_studio_model,
                )
                analyst = Analyst(repository, embedder, settings, llm, fake)
                auditor = Auditor(llm, fake)
            evaluator = CorpusEvaluator(repository, embedder, settings, analyst, auditor)
            report = await evaluator.run(Path(args.cases), full=args.full)
            write_report(report, Path(args.output))
            output = {
                "case_count": report["case_count"],
                "source_hit_rate": report["source_hit_rate"],
                "output": args.output,
            }
            for metric in ("citation_valid_rate", "behavior_pass_rate", "auditor_valid_rate"):
                if metric in report:
                    output[metric] = report[metric]
            print(json.dumps(output))
    finally:
        await database.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Teaching AI Agents operator CLI")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    ingest = commands.add_parser("ingest")
    ingest.add_argument("path")
    archive = commands.add_parser("import-archive")
    archive.add_argument("path")
    status = commands.add_parser("corpus-status")
    status.add_argument("import_id", nargs="?")
    cleanup = commands.add_parser("cleanup")
    cleanup.add_argument("kind", choices=["synthetic", "failed", "stale"])
    evaluation = commands.add_parser("eval-corpus")
    evaluation.add_argument(
        "--cases", default=str(Path(__file__).parent / "evals" / "corpus_cases.yaml"),
    )
    evaluation.add_argument("--output", default="/data/documents/evaluations/latest.json")
    evaluation.add_argument("--full", action="store_true")
    review = commands.add_parser("always-review")
    review.add_argument("enabled", choices=["true", "false"])
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
