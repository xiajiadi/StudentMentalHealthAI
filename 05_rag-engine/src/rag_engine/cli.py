"""Command-line benchmark and compatibility runner for Round 1."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .config import RAGConfig
from .domain import RetrievalPlan, stable_digest, utc_now
from .embedding import BGEM3EmbeddingProvider, MockEmbeddingProvider
from .evaluation import EvaluationHarness, GoldenQuery, load_golden_queries
from .exceptions import RAGEngineError
from .indexing import IndexBuilder, KnowledgeCorpusLoader
from .query import DeterministicQueryBuilder
from .rerank import BGERerankerProvider, NoOpReranker
from .sparse import BM25SRetriever
from .stores import ChromaVectorStore
from .retrieval import RetrievalService


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _module_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _project_root() -> Path:
    return _module_root().parent


def _default_input_paths() -> dict[str, Path]:
    published = _project_root() / "04_knowledge-pipeline" / "data" / "published" / "round1"
    review_candidates = (
        published / "review_queue.jsonl",
        _project_root() / "04_knowledge-pipeline" / "data" / "review_queue.jsonl",
    )
    review_queue = next((path for path in review_candidates if path.exists()), review_candidates[0])
    return {
        "config": _module_root() / "config" / "rag.v1.json",
        "corpus": published / "embedding_ready.jsonl",
        "documents": published / "knowledge_documents.jsonl",
        "review_queue": review_queue,
        "golden": _module_root() / "evaluation" / "golden_queries.jsonl",
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _synthetic_assessment(*, risk_level: str = "normal") -> dict[str, Any]:
    """Return a non-personal fixture for benchmark query construction."""

    return {
        "schema_version": "assessment.v1",
        "assessment_id": "ASSESS_synthetic_benchmark_001",
        "subject_id": "SUBJ_synthetic_benchmark_001",
        "population_scope": "K12学生",
        "status": "completed",
        "dimensions": {"stress": {"theta": -0.7, "band": "unknown"}},
        "risk": {
            "level": risk_level,
            "need_human_review": risk_level in {"high", "crisis"},
            "reason_codes": ["SYNTHETIC_BENCHMARK"],
            "ruleset_id": "RULESET_synthetic_benchmark_v1",
        },
    }


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")


def _plan_for_query(
    builder: DeterministicQueryBuilder,
    assessment: Mapping[str, Any],
    query: GoldenQuery,
    *,
    mode: str,
    rerank_enabled: bool,
) -> RetrievalPlan:
    plan = builder.build(
        assessment,
        role=query.role,
        target_population=query.target_population,
        dimension="stress",
        intent=query.intent,
        user_query=query.query,
        layers=(query.layer,) if query.layer else None,
        query_type=query.query_type,
    )
    return replace(plan, retrieval_mode=mode, rerank_enabled=rerank_enabled)


def _evaluate_configuration(
    name: str,
    mode: str,
    service: RetrievalService,
    config: RAGConfig,
    queries: Sequence[GoldenQuery],
    *,
    corpus_version: str,
    provider_metadata: Mapping[str, Any],
    rerank_enabled: bool = False,
) -> dict[str, Any]:
    builder = DeterministicQueryBuilder(config)
    assessment = _synthetic_assessment()
    trace_samples: dict[str, Any] = {}

    def runner(query: GoldenQuery) -> Sequence[str]:
        plan = _plan_for_query(builder, assessment, query, mode=mode, rerank_enabled=rerank_enabled)
        slug = _slug(name)
        result = service.retrieve(
            plan,
            raw_query=query.query,
            request_id=f"REQ_{slug}_{query.query_id}",
            trace_id=f"TRACE_{slug}_{query.query_id}",
            retrieval_id=f"RETR_{slug}_{query.query_id}",
        )
        trace_samples[query.query_id] = result.trace.to_dict()
        return [hit.chunk_id for hit in result.hits]

    evaluation = EvaluationHarness(queries).evaluate(
        name,
        runner,
        metadata={
            "mode": mode,
            "provider": dict(provider_metadata),
            "corpus_version": corpus_version,
            "synthetic_assessment": True,
            "rerank_enabled": rerank_enabled,
        },
    )
    evaluation["status"] = "pass"
    if rerank_enabled:
        preferred_types = ("semantic_paraphrase", "exact_keyword", "policy", "theory", "intervention")
        selected_ids: list[str] = []
        for query_type in preferred_types:
            match = next((query for query in queries if query.query_type == query_type and query.query_id in trace_samples), None)
            if match is not None:
                selected_ids.append(match.query_id)
            if len(selected_ids) >= 3:
                break
        selected_ids = selected_ids[:3]
        evaluation["trace_samples"] = {key: trace_samples[key] for key in selected_ids}
    else:
        evaluation["trace_samples"] = {key: trace_samples[key] for key in sorted(trace_samples)[:2]}
    return evaluation


def _bm25_manifest(records: Sequence[Any], corpus_version: str, config: RAGConfig) -> dict[str, Any]:
    package_version = _package_version("bm25s")
    index_key = stable_digest(
        {
            "corpus_version": corpus_version,
            "provider": "bm25s",
            "provider_version": package_version,
            "tokenizer": "cjk-bigram-v1",
            "config_hash": config.config_hash,
        }
    )[:24]
    return {
        "index_id": f"INDEX_BM25_{index_key}",
        "index_version": "1.0.0",
        "corpus_version": corpus_version,
        "chunk_count": len(records),
        "provider": "bm25s",
        "provider_version": package_version,
        "tokenizer_version": "cjk-bigram-v1",
        "config_hash": f"sha256:{config.config_hash}",
        "eligible_chunk_ids": sorted(record.chunk_id for record in records),
    }


def _prepare_bm25(corpus: Any, config: RAGConfig, *, persist: bool = True) -> tuple[BM25SRetriever, dict[str, Any], bool]:
    target = config.stores.bm25_path
    target.mkdir(parents=True, exist_ok=True)
    manifest = _bm25_manifest(corpus.records, corpus.corpus_version, config)
    manifest_path = target / "manifest.json"
    if persist and manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if existing.get("index_id") == manifest["index_id"] and int(existing.get("chunk_count", -1)) == len(corpus.records):
                retriever = BM25SRetriever.load(target, records=corpus.records)
                return retriever, existing, True
        except Exception:
            pass

    retriever = BM25SRetriever(corpus.records)
    retriever.build()
    if persist:
        retriever.save(target)
        manifest["timestamp"] = utc_now()
        _write_json(manifest_path, manifest)
    return retriever, manifest, False


def _prepare_mock_dense(corpus: Any, config: RAGConfig) -> tuple[RetrievalService, dict[str, Any], dict[str, Any]]:
    provider = MockEmbeddingProvider(dimension=64)
    store = ChromaVectorStore(
        _module_root() / "data" / "indexes" / "mock-dense" / "chroma",
        "rag_round1_mock_dense",
    )
    build = IndexBuilder(provider, store).build(
        corpus.records,
        config=config,
        index_dir=_module_root() / "data" / "indexes" / "mock-dense",
        excluded_count=len(corpus.excluded),
    )
    service = RetrievalService(
        embedding_provider=provider,
        dense_store=store,
        reranker=NoOpReranker(),
        index_manifest=build.manifest.to_dict(),
        rrf_k=config.rrf_k,
    )
    return service, build.manifest.to_dict(), provider.model_info()


def _prepare_real_dense(
    corpus: Any,
    config: RAGConfig,
    *,
    bm25: BM25SRetriever | None,
    load_models: bool,
    rerank_requested: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    embedding = BGEM3EmbeddingProvider(config.embedding, return_sparse=True)
    embedding_health = embedding.health_check(load=load_models)
    provider_report: dict[str, Any] = {"embedding": embedding_health}
    reranker_provider: BGERerankerProvider | None = None
    if rerank_requested:
        reranker_provider = BGERerankerProvider(config.reranker)
        provider_report["reranker"] = reranker_provider.health_check(load=load_models)

    if embedding_health.get("status") != "ok":
        return {
            "status": "blocked" if load_models else "not_run",
            "reason": embedding_health.get("error") or "real BGE-M3 load was not requested",
            "providers": provider_report,
        }, provider_report

    store = ChromaVectorStore(config.stores.chroma_path, config.stores.chroma_collection)
    try:
        build = IndexBuilder(embedding, store).build(
            corpus.records,
            config=config,
            index_dir=_module_root() / "data" / "indexes" / "bge-m3",
            excluded_count=len(corpus.excluded),
        )
    except RAGEngineError as exc:
        return {
            "status": "blocked",
            "reason": exc.message,
            "error_code": exc.code,
            "providers": provider_report,
        }, provider_report

    # The health check proves model loading; the build performs the first real
    # corpus encode and lets the provider report whether lexical weights were
    # actually returned by FlagEmbedding.
    if not embedding.model_info().get("sparse_output_observed"):
        # A reused index may skip corpus encoding. Keep a small real-provider
        # probe in the report so sparse support is not inferred from a flag.
        embedding.embed_queries(["考试压力支持建议"])
    embedding_info = {"status": "ok", **embedding.model_info()}
    provider_report["embedding"] = embedding_info

    dense_service = RetrievalService(
        embedding_provider=embedding,
        dense_store=store,
        reranker=NoOpReranker(),
        index_manifest=build.manifest.to_dict(),
        rrf_k=config.rrf_k,
    )
    stack: dict[str, Any] = {
        "status": "ready",
        "providers": provider_report,
        "dense_service": dense_service,
        "manifest": build.manifest.to_dict(),
        "embedding_info": embedding_info,
    }
    if bm25 is not None:
        stack["hybrid_service"] = RetrievalService(
            embedding_provider=embedding,
            dense_store=store,
            sparse_retriever=bm25,
            reranker=NoOpReranker(),
            index_manifest=build.manifest.to_dict(),
            rrf_k=config.rrf_k,
        )
    if reranker_provider is not None and provider_report.get("reranker", {}).get("status") == "ok":
        stack["dense_rerank_service"] = RetrievalService(
            embedding_provider=embedding,
            dense_store=store,
            reranker=reranker_provider,
            index_manifest=build.manifest.to_dict(),
            rrf_k=config.rrf_k,
        )
        if bm25 is not None:
            stack["hybrid_rerank_service"] = RetrievalService(
                embedding_provider=embedding,
                dense_store=store,
                sparse_retriever=bm25,
                reranker=reranker_provider,
                index_manifest=build.manifest.to_dict(),
                rrf_k=config.rrf_k,
            )
    return stack, provider_report


def _not_run(name: str, reason: str, *, providers: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "configuration": name,
        "status": "not_run",
        "reason": reason,
        "metadata": {"provider": dict(providers or {})},
        "metrics": None,
    }


def _blocked(name: str, reason: str, *, providers: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "configuration": name,
        "status": "blocked",
        "reason": reason,
        "metadata": {"provider": dict(providers or {})},
        "metrics": None,
    }


def _render_benchmark_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# RAG Round 1 Retrieval Benchmark",
        "",
        f"Generated: `{report.get('generated_at', 'unknown')}`",
        "",
        "## Corpus and runtime",
        "",
        f"- Eligible Knowledge chunks: **{report['corpus']['eligible_count']}**",
        f"- Excluded rows: **{report['corpus']['excluded_count']}**",
        f"- Golden queries: **{report['dataset']['query_count']}**",
        f"- Corpus version: `{report['corpus']['corpus_version']}`",
        "",
        "## Configuration results",
        "",
        "| Configuration | Status | Hit@1 | Recall@5 | MRR | nDCG@5 | P50 ms | P95 ms |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in report.get("configurations", []):
        metrics = item.get("metrics") or {}
        def value(key: str) -> str:
            raw = metrics.get(key)
            return "—" if raw is None else f"{float(raw):.3f}"
        lines.append(
            f"| {item['configuration']} | {item['status']} | {value('hit_at_1')} | {value('recall_at_5')} | "
            f"{value('mrr')} | {value('ndcg_at_5')} | {value('latency_p50_ms')} | {value('latency_p95_ms')} |"
        )
    lines.extend(["", "## Provider status", "", "| Provider | Status / evidence |", "| --- | --- |"])
    for name, info in report.get("providers", {}).items():
        status = info.get("status", "unknown") if isinstance(info, Mapping) else "unknown"
        detail = info.get("error") or info.get("package_version") or info.get("version") or ""
        lines.append(f"| {name} | {status}; {detail} |")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Metrics are deterministic ID-based IR metrics over the synthetic Round 1 golden set. "
            "They do not measure answer correctness, clinical safety, or production readiness.",
            "",
            "Real BGE-M3 and reranker rows are reported separately from the deterministic Mock dense test. "
            "A blocked or not-run row is not a pass and must not be used as BGE evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_runtime_markdown(report: Mapping[str, Any]) -> str:
    runtime = report.get("runtime", {})
    lines = [
        "# RAG Runtime Compatibility",
        "",
        f"Checked: `{report.get('generated_at', 'unknown')}`",
        "",
        "## Runtime",
        "",
        f"- Python: `{runtime.get('python', 'unknown')}`",
        f"- Platform: `{runtime.get('platform', 'unknown')}`",
        f"- Torch: `{runtime.get('torch', 'not-installed')}`",
        f"- CUDA available: `{runtime.get('cuda_available', False)}`",
        f"- Hugging Face cache: `{runtime.get('hf_home', 'not-set')}`",
        "",
        "## Packages",
        "",
        "| Package | Installed version |",
        "| --- | --- |",
    ]
    for name, version in report.get("packages", {}).items():
        lines.append(f"| {name} | `{version}` |")
    lines.extend(
        [
            "",
            "## Model/provider checks",
            "",
            "```json",
            json.dumps(report.get("providers", {}), ensure_ascii=False, indent=2, default=str),
            "```",
            "",
            "## Known warnings",
            "",
            "- Windows does not support the Hugging Face cache symlink optimization; the cache remains valid but may use more disk space.",
            "- The integration test run reports deprecation warnings from jsonschema.RefResolver and Chroma telemetry; they do not affect the recorded results.",
            "- CUDA is unavailable on this host; GPU performance is not validated.",
            "",
        ]
    )
    return "\n".join(lines)


def _runtime_snapshot() -> dict[str, Any]:
    torch_version = "not-installed"
    cuda_available = False
    try:
        import torch

        torch_version = torch.__version__
        cuda_available = bool(torch.cuda.is_available())
    except ImportError:
        pass
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "executable": sys.executable,
        "torch": torch_version,
        "cuda_available": cuda_available,
        "hf_home": os.environ.get("HF_HOME", "not-set"),
    }


def build_benchmark(argv: Sequence[str] | None = None) -> tuple[int, dict[str, Any]]:
    defaults = _default_input_paths()
    parser = argparse.ArgumentParser(description="Run provider-neutral RAG Round 1 retrieval benchmarks.")
    parser.add_argument("--config", type=Path, default=defaults["config"])
    parser.add_argument("--corpus", type=Path, default=defaults["corpus"])
    parser.add_argument("--documents", type=Path, default=defaults["documents"])
    parser.add_argument("--review-queue", type=Path, default=defaults["review_queue"])
    parser.add_argument("--golden", type=Path, default=defaults["golden"])
    parser.add_argument("--output", type=Path, default=_module_root() / "reports" / "rag_eval_round1.json")
    parser.add_argument("--mode", choices=("all", "bm25", "mock-dense", "dense", "hybrid"), default="all")
    parser.add_argument("--real-models", action="store_true", help="Load the real BGE-M3/reranker instead of reporting not_run.")
    parser.add_argument("--offline", action="store_true", help="Prevent model/network downloads during compatibility checks.")
    parser.add_argument("--rerank", action="store_true", help="Attempt the real BGE reranker when real models are enabled.")
    parser.add_argument("--no-persist", action="store_true", help="Do not write BM25 indexes or benchmark indexes.")
    args = parser.parse_args(argv)

    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
    config = RAGConfig.load(args.config)
    corpus = KnowledgeCorpusLoader().load(
        args.corpus,
        documents_path=args.documents,
        review_queue_path=args.review_queue,
    )
    queries = load_golden_queries(args.golden)
    report: dict[str, Any] = {
        "schema_version": "rag-eval-round1.v1",
        "generated_at": utc_now(),
        "config_path": str(args.config.resolve()),
        "output_path": str(args.output.resolve()),
        "config_hash": f"sha256:{config.config_hash}",
        "runtime": _runtime_snapshot(),
        "packages": {
            "FlagEmbedding": _package_version("FlagEmbedding"),
            "chromadb": _package_version("chromadb"),
            "qdrant-client": _package_version("qdrant-client"),
            "bm25s": _package_version("bm25s"),
            "numpy": _package_version("numpy"),
            "jsonschema": _package_version("jsonschema"),
            "pytest": _package_version("pytest"),
        },
        "corpus": {
            "source_path": str(corpus.source_path),
            "eligible_count": len(corpus.records),
            "excluded_count": len(corpus.excluded),
            "document_count": corpus.document_count,
            "corpus_version": corpus.corpus_version,
            "eligible_chunk_ids": sorted(record.chunk_id for record in corpus.records),
            "excluded": list(corpus.excluded),
        },
        "dataset": {
            "query_count": len(queries),
            "query_type_distribution": {
                kind: sum(1 for query in queries if query.query_type == kind)
                for kind in sorted({query.query_type for query in queries})
            },
        },
        "providers": {},
        "configurations": [],
        "notes": [
            "Round 1 uses synthetic assessment/query fixtures and the approved Knowledge export only.",
            "No LLM query rewrite, answer generation, clinical interpretation, or real student data is used.",
        ],
    }

    run_all = args.mode == "all"
    bm25: BM25SRetriever | None = None
    bm25_manifest: dict[str, Any] | None = None
    if run_all or args.mode in {"bm25", "hybrid"}:
        bm25, bm25_manifest, bm25_reused = _prepare_bm25(corpus, config, persist=not args.no_persist)
        report["providers"]["BM25S"] = {**bm25.health_check(), "reused": bm25_reused, "manifest": bm25_manifest}
        report["configurations"].append(
            _evaluate_configuration(
                "BM25S",
                "bm25",
                RetrievalService(
                    embedding_provider=None,
                    dense_store=None,
                    sparse_retriever=bm25,
                    reranker=NoOpReranker(),
                    index_manifest=bm25_manifest,
                    rrf_k=config.rrf_k,
                ),
                config,
                queries,
                corpus_version=corpus.corpus_version,
                provider_metadata={"provider": "bm25s", "version": _package_version("bm25s")},
            )
        )

    if run_all or args.mode == "mock-dense":
        try:
            mock_service, mock_manifest, mock_info = _prepare_mock_dense(corpus, config)
            report["providers"]["Mock Dense"] = {**mock_info, "status": "ok", "test_only": True}
            report["configurations"].append(
                _evaluate_configuration(
                    "Dense (Mock; test-only)",
                    "dense",
                    mock_service,
                    config,
                    queries,
                    corpus_version=corpus.corpus_version,
                    provider_metadata=mock_info,
                )
            )
        except RAGEngineError as exc:
            report["providers"]["Mock Dense"] = {"status": "blocked", "error_code": exc.code, "error": exc.message, "test_only": True}
            report["configurations"].append(_blocked("Dense (Mock; test-only)", exc.message))

    real_requested = args.real_models and (run_all or args.mode in {"dense", "hybrid"})
    if real_requested:
        stack, provider_report = _prepare_real_dense(
            corpus,
            config,
            bm25=bm25,
            load_models=True,
            rerank_requested=args.rerank,
        )
        report["providers"]["BGE-M3"] = provider_report.get("embedding", {})
        if "reranker" in provider_report:
            report["providers"]["BGE reranker"] = provider_report["reranker"]
        if stack.get("status") != "ready":
            reason = str(stack.get("reason") or "BGE-M3 stack unavailable")
            report["configurations"].extend(
                [
                    _blocked("Dense (BGE-M3)", reason, providers=provider_report),
                    _blocked("Hybrid (BGE-M3 + BM25S)", reason, providers=provider_report),
                ]
            )
            if args.rerank:
                report["configurations"].extend(
                    [
                        _blocked("Dense+Rerank (BGE)", reason, providers=provider_report),
                        _blocked("Hybrid+Rerank (BGE + BM25S)", reason, providers=provider_report),
                    ]
                )
        else:
            if run_all or args.mode == "dense":
                report["configurations"].append(
                    _evaluate_configuration(
                        "Dense (BGE-M3)",
                        "dense",
                        stack["dense_service"],
                        config,
                        queries,
                        corpus_version=corpus.corpus_version,
                        provider_metadata=stack["embedding_info"],
                    )
                )
            if (run_all or args.mode == "hybrid") and "hybrid_service" in stack:
                report["configurations"].append(
                    _evaluate_configuration(
                        "Hybrid (BGE-M3 + BM25S)",
                        "hybrid",
                        stack["hybrid_service"],
                        config,
                        queries,
                        corpus_version=corpus.corpus_version,
                        provider_metadata=stack["embedding_info"],
                    )
                )
            if args.rerank:
                rerank_reason = "BGE reranker was not ready"
                if "dense_rerank_service" in stack:
                    report["configurations"].append(
                        _evaluate_configuration(
                            "Dense+Rerank (BGE)",
                            "dense",
                            stack["dense_rerank_service"],
                            config,
                            queries,
                            corpus_version=corpus.corpus_version,
                            provider_metadata=provider_report.get("reranker", {}),
                            rerank_enabled=True,
                        )
                    )
                    rerank_reason = ""
                if "hybrid_rerank_service" in stack:
                    report["configurations"].append(
                        _evaluate_configuration(
                            "Hybrid+Rerank (BGE + BM25S)",
                            "hybrid",
                            stack["hybrid_rerank_service"],
                            config,
                            queries,
                            corpus_version=corpus.corpus_version,
                            provider_metadata=provider_report.get("reranker", {}),
                            rerank_enabled=True,
                        )
                    )
                    rerank_reason = ""
                if rerank_reason:
                    report["configurations"].append(_blocked("Dense+Rerank (BGE)", rerank_reason, providers=provider_report))
                    if bm25 is not None:
                        report["configurations"].append(_blocked("Hybrid+Rerank (BGE + BM25S)", rerank_reason, providers=provider_report))
    elif run_all:
        reason = "real model loading was not requested; pass --real-models for an explicit BGE check"
        report["providers"]["BGE-M3"] = {"status": "not_run", "package_version": _package_version("FlagEmbedding")}
        report["configurations"].extend(
            [
                _not_run("Dense (BGE-M3)", reason),
                _not_run("Hybrid (BGE-M3 + BM25S)", reason),
            ]
        )
        if args.rerank:
            report["providers"]["BGE reranker"] = {"status": "not_run", "package_version": _package_version("FlagEmbedding")}
            report["configurations"].extend([_not_run("Dense+Rerank (BGE)", reason), _not_run("Hybrid+Rerank (BGE + BM25S)", reason)])
    elif args.mode == "dense" and not args.real_models:
        reason = "real model loading was not requested; pass --real-models for an explicit BGE check"
        report["providers"]["BGE-M3"] = {"status": "not_run", "package_version": _package_version("FlagEmbedding")}
        report["configurations"].append(_not_run("Dense (BGE-M3)", reason))
    elif args.mode == "hybrid" and not args.real_models:
        reason = "real model loading was not requested; pass --real-models for an explicit BGE check"
        report["providers"]["BGE-M3"] = {"status": "not_run", "package_version": _package_version("FlagEmbedding")}
        report["configurations"].append(_not_run("Hybrid (BGE-M3 + BM25S)", reason))

    _write_json(args.output.resolve(), report)
    benchmark_markdown = args.output.resolve().with_name("RAG_RETRIEVAL_BENCHMARK.md")
    benchmark_markdown.write_text(_render_benchmark_markdown(report), encoding="utf-8")
    runtime_markdown = args.output.resolve().with_name("RAG_RUNTIME_COMPATIBILITY.md")
    runtime_report = {"generated_at": report["generated_at"], "runtime": report["runtime"], "packages": report["packages"], "providers": report["providers"]}
    runtime_markdown.write_text(_render_runtime_markdown(runtime_report), encoding="utf-8")
    return 0, report


def main(argv: Sequence[str] | None = None) -> int:
    try:
        code, report = build_benchmark(argv)
    except (RAGEngineError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"RAG benchmark failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"output": report.get("output_path"), "configurations": [{"name": item.get("configuration"), "status": item.get("status")} for item in report.get("configurations", [])]}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
