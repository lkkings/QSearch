"""Queue or directly execute batch-search jobs from a terminal.

Running the script without a complete set of paths starts an interactive
wizard modelled after ``render_batch_search_tab`` and submits the work to the
same scheduler as the WebUI. Legacy ``--index-dir``/``--output-file`` commands
remain available for synchronous automation.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
from pathlib import Path
from typing import Callable, Sequence

import yaml

from qsearch.cli.interactive import (
    deep_merge,
    load_image_list,
    nested_get,
    prompt_bool,
    prompt_choice,
    prompt_existing_path,
    prompt_float,
    prompt_int,
    prompt_text,
    scan_images,
)
from qsearch.config.loader import ConfigLoader
from qsearch.config.presets import get_preset
from qsearch.features.feature_extractor import FeatureExtractor
from qsearch.indexing.faiss_index import FaissIndexBuilder
from qsearch.indexing.hash_index import HashIndex
from qsearch.matching.matchers import ContentMatcher, ExactMatcher, QuestionMatcher
from qsearch.webui import search_params
from qsearch.webui.task_manager import TaskManager

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def load_image_paths(image_dir: Path) -> list[Path]:
    """Backward-compatible image directory scanner."""
    return scan_images(Path(image_dir))


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch-search a QSearch database")
    parser.add_argument("--query-dir", help="Directory containing query images")
    parser.add_argument("--query-list", help="UTF-8 file containing one query path per line")
    parser.add_argument("--index-dir", help="Index directory or managed database directory")
    parser.add_argument("--database-name", help="Managed database name")
    parser.add_argument("--databases-root", default="databases", help="Managed database root")
    parser.add_argument("--task-name", help="Readable name for a scheduled search task")
    parser.add_argument(
        "--output-file",
        help="Legacy synchronous result JSON path; requires --index-dir or opts a managed search out of scheduling",
    )
    parser.add_argument("--config", help="Complete YAML configuration override")
    parser.add_argument(
        "--preset",
        choices=("conservative", "balanced", "aggressive"),
        default="balanced",
        help="Fallback matching preset when no database/config YAML is available",
    )
    parser.add_argument("--top-n", type=int, help="Results returned per query (1-20)")
    parser.add_argument(
        "--num-gpus",
        type=int,
        help="GPUs used for query feature extraction; 0 uses CPU workers",
    )
    parser.add_argument("--batch-size", type=int, help="Text/image extraction batch size")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--interactive", action="store_true", help="Always open the wizard")
    mode.add_argument("--non-interactive", action="store_true", help="Never prompt")
    parser.add_argument("--yes", action="store_true", help="Skip the final confirmation")
    return parser


def _managed_databases(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    required = {"features.pkl", "text_index.faiss", "text_index_ids.pkl", "hash_index.pkl"}
    databases = []
    for path in root.iterdir():
        index_dir = path / "index"
        if path.is_dir() and all((index_dir / name).exists() for name in required):
            databases.append(path.name)
    return sorted(databases)


def _resolve_index_and_config(path: Path, config_path: str | None, preset: str) -> tuple[Path, dict]:
    """Accept either ``database/`` or ``database/index/`` paths."""
    path = path.expanduser().resolve()
    index_dir = path / "index" if (path / "index").is_dir() else path
    database_dir = path if index_dir != path else path.parent

    if config_path:
        config = ConfigLoader.load_yaml(config_path)
    elif (database_dir / "config.yaml").exists():
        config = ConfigLoader.load_yaml(database_dir / "config.yaml")
    else:
        config = get_preset(preset)
    return index_dir, config


def _collect_query_images(mode: str, source: Path) -> list[Path]:
    images = scan_images(source) if mode == "folder" else load_image_list(source)
    if not images:
        raise ValueError("查询输入中没有有效的 jpg/jpeg/png/bmp 图片")
    return images


def _prompt_search_values(
    specs: list[search_params.ParamSpec],
    *,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> dict:
    values = {}
    current_group = None
    for spec in specs:
        if spec.group != current_group:
            current_group = spec.group
            output_fn(f"\n[{current_group}]")
        if spec.kind == "bool":
            values[spec.key] = prompt_bool(
                spec.label, bool(spec.default), input_fn=input_fn
            )
        elif spec.kind == "int":
            values[spec.key] = prompt_int(
                spec.label,
                int(spec.default),
                minimum=int(spec.min_value) if spec.min_value is not None else None,
                maximum=int(spec.max_value) if spec.max_value is not None else None,
                input_fn=input_fn,
            )
        elif spec.kind == "float":
            values[spec.key] = prompt_float(
                spec.label,
                float(spec.default),
                minimum=spec.min_value,
                maximum=spec.max_value,
                input_fn=input_fn,
            )
        else:
            raise ValueError(f"不支持的查询参数类型：{spec.kind}")
    return values


def collect_search_wizard(
    args: argparse.Namespace,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> dict:
    """Collect the terminal equivalent of ``render_batch_search_tab``."""
    output_fn("\n=== QSearch 批量检索 ===")
    databases_root = Path(
        prompt_text(
            "数据库根目录", args.databases_root, required=True, input_fn=input_fn
        )
    ).expanduser().resolve()
    databases = _managed_databases(databases_root)
    if not databases:
        raise ValueError(f"未找到已构建索引的数据库：{databases_root}")

    default_database = args.database_name if args.database_name in databases else databases[0]
    database_name = prompt_choice(
        "选择数据库", databases, default_database,
        input_fn=input_fn, output_fn=output_fn,
    )
    database_dir = databases_root / database_name
    index_dir, build_config = _resolve_index_and_config(
        database_dir, args.config, args.preset
    )

    task_name = prompt_text(
        "任务名称", f"批量检索 {database_name}", required=True, input_fn=input_fn
    )
    input_mode = prompt_choice(
        "查询图片输入方式", ("folder", "file_list"), "folder",
        input_fn=input_fn, output_fn=output_fn,
    )
    if input_mode == "folder":
        source = prompt_existing_path(
            "查询图片目录", args.query_dir, kind="directory", input_fn=input_fn
        )
    else:
        source = prompt_existing_path(
            "查询图片列表", args.query_list, kind="file", input_fn=input_fn
        )
    query_paths = _collect_query_images(input_mode, source)

    specs = search_params.build_param_specs(build_config)
    values = _prompt_search_values(specs, input_fn=input_fn, output_fn=output_fn)
    if args.top_n is not None:
        values["top_n"] = args.top_n
    if not 1 <= int(values.get("top_n", 10)) <= 20:
        raise ValueError("top_n 必须在 1-20 之间")
    override = search_params.build_search_config(specs, values)

    batch_size = prompt_int(
        "特征提取批大小",
        args.batch_size if args.batch_size is not None else 32,
        minimum=1,
        maximum=512,
        input_fn=input_fn,
    )
    num_gpus = prompt_int(
        "GPU 数量（0 表示 CPU）",
        args.num_gpus if args.num_gpus is not None else 0,
        minimum=0,
        maximum=8,
        input_fn=input_fn,
    )
    return {
        "database_name": database_name,
        "databases_root": databases_root,
        "index_dir": index_dir,
        "query_paths": query_paths,
        "task_name": task_name,
        "config_yaml": yaml.safe_dump(
            override, allow_unicode=True, sort_keys=False
        ),
        "top_n": int(values.get("top_n", 10)),
        "batch_size": batch_size,
        "num_gpus": num_gpus,
    }


def _managed_queue_options(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> dict:
    """Validate a non-interactive managed search and build its queue payload."""
    if not (args.query_dir or args.query_list):
        parser.error("--non-interactive 需要 --query-dir 或 --query-list")
    if not args.database_name:
        parser.error("调度模式需要 --database-name")

    databases_root = Path(args.databases_root).expanduser().resolve()
    if args.database_name not in _managed_databases(databases_root):
        raise ValueError(f"数据库不存在或尚未构建索引：{args.database_name}")

    database_dir = databases_root / args.database_name
    _index_dir, build_config = _resolve_index_and_config(
        database_dir, None, args.preset
    )
    override = ConfigLoader.load_yaml(args.config) if args.config else {}
    effective_config = deep_merge(copy.deepcopy(build_config), copy.deepcopy(override))

    top_n = args.top_n or int(
        nested_get(effective_config, ("matching", "output", "top_k"), 10)
    )
    if not 1 <= top_n <= 20:
        raise ValueError(f"top_n 必须在 1-20 之间，当前为 {top_n}")
    batch_size = args.batch_size or 32
    if batch_size < 1:
        raise ValueError("batch_size 必须大于 0")
    num_gpus = 0 if args.num_gpus is None else args.num_gpus
    if num_gpus < 0:
        raise ValueError("num_gpus 不能小于 0")

    query_mode = "folder" if args.query_dir else "file_list"
    query_source = Path(args.query_dir or args.query_list).expanduser().resolve()
    if not query_source.exists():
        raise ValueError(f"查询输入不存在：{query_source}")

    return {
        "database_name": args.database_name,
        "databases_root": databases_root,
        "query_paths": _collect_query_images(query_mode, query_source),
        "task_name": args.task_name or f"批量检索 {args.database_name}",
        "config_yaml": (
            yaml.safe_dump(override, allow_unicode=True, sort_keys=False)
            if override else None
        ),
        "top_n": top_n,
        "batch_size": batch_size,
        "num_gpus": num_gpus,
    }


def _enqueue_managed_search(options: dict) -> tuple[str, dict]:
    """Submit a batch search through the same TaskManager used by the WebUI."""
    task_manager = TaskManager(options["databases_root"])
    task_id = task_manager.enqueue_batch_search(
        database_name=options["database_name"],
        image_paths=options["query_paths"],
        top_n=options["top_n"],
        batch_size=options["batch_size"],
        num_gpus=options["num_gpus"],
        task_name=options["task_name"],
        config_yaml=options["config_yaml"],
    )
    return task_id, task_manager.scheduler_status()


def _direct_options(args: argparse.Namespace, parser: argparse.ArgumentParser) -> dict:
    if not (args.query_dir or args.query_list):
        parser.error("--non-interactive 需要 --query-dir 或 --query-list")
    if not (args.index_dir or args.database_name):
        parser.error("--non-interactive 需要 --index-dir 或 --database-name")
    if not args.output_file:
        parser.error("--non-interactive 需要 --output-file")

    if args.database_name:
        source_index = Path(args.databases_root) / args.database_name
    else:
        source_index = Path(args.index_dir)
    index_dir, config = _resolve_index_and_config(source_index, args.config, args.preset)
    query_mode = "folder" if args.query_dir else "file_list"
    query_source = Path(args.query_dir or args.query_list).expanduser().resolve()
    if not query_source.exists():
        raise ValueError(f"查询输入不存在：{query_source}")

    top_n = args.top_n or int(
        nested_get(config, ("matching", "output", "top_k"), 10)
    )
    if not 1 <= top_n <= 20:
        raise ValueError(f"top_n 必须在 1-20 之间，当前为 {top_n}")
    batch_size = args.batch_size or 32
    if batch_size < 1:
        raise ValueError("batch_size 必须大于 0")
    num_gpus = 7 if args.num_gpus is None else args.num_gpus
    if num_gpus < 0:
        raise ValueError("num_gpus 不能小于 0")

    return {
        "database_name": args.database_name or index_dir.parent.name,
        "index_dir": index_dir,
        "query_paths": _collect_query_images(query_mode, query_source),
        "output_file": Path(args.output_file).expanduser().resolve(),
        "config": config,
        "top_n": top_n,
        "batch_size": batch_size,
        "num_gpus": num_gpus,
    }


def run_search(options: dict) -> tuple[list[dict], dict]:
    """Extract query features in batches and execute batched matching."""
    index_dir = Path(options["index_dir"])
    config = options["config"]
    dimension = int(nested_get(config, ("text", "encoding", "embedding_dim"), 768))
    index_config = config.get("index", {})

    faiss_index = FaissIndexBuilder(
        dimension=dimension,
        use_gpu=options["num_gpus"] > 0,
        gpu_id=0,
        index_type=index_config.get("type", "Flat"),
        nprobe=int(index_config.get("nprobe", 10)),
        ef_search=int(index_config.get("ef_search", 32)),
    )
    faiss_index.load(
        str(index_dir / "text_index.faiss"),
        str(index_dir / "text_index_ids.pkl"),
    )
    faiss_index.apply_search_params()

    hash_index = HashIndex()
    hash_index.load(str(index_dir / "hash_index.pkl"), format="pickle")

    extractor = FeatureExtractor(config, use_gpu=options["num_gpus"] > 0)
    features_list = extractor.load_features(index_dir / "features.pkl", format="pickle")
    features_db = {features["image_path"]: features for features in features_list}

    matching_config = config.get("matching", {})
    matcher = QuestionMatcher(
        ExactMatcher(hash_index, matching_config.get("exact_match", {})),
        ContentMatcher(
            faiss_index, features_db, matching_config.get("content_match", {})
        ),
        matching_config.get("output", {}),
    )

    query_paths = options["query_paths"]
    if options["num_gpus"] > 0:
        query_features = extractor.extract_batch_gpu_distributed(
            query_paths,
            num_gpus=options["num_gpus"],
            show_progress=True,
            batch_size=options["batch_size"],
        )
    else:
        query_features = extractor.extract_batch(
            query_paths,
            show_progress=True,
            batch_size=options["batch_size"],
        )

    raw_results = matcher.match_batch(
        query_features,
        top_n=options["top_n"],
        vector_batch_size=options["batch_size"],
    )
    results = [
        _format_result(path, result)
        for path, result in zip(query_paths, raw_results)
    ]
    return results, _build_stats(results)


def _format_result(query_path: Path, result: dict) -> dict:
    matches = []
    for rank, match in enumerate(result.get("matches", []), 1):
        similarity = float(match.get("similarity", match.get("confidence", 0.0)))
        matches.append({
            "rank": rank,
            "image_id": match.get("image_id", ""),
            "match_type": match.get("match_type", ""),
            "similarity": round(similarity, 4),
            "confidence": round(float(match.get("confidence", 0.0)), 4),
            "scores": {
                key: round(value, 4) if isinstance(value, float) else value
                for key, value in match.get("scores", {}).items()
            },
        })
        if match.get("match_type") == "EXACT_MATCH":
            matches[-1]["hash_distance"] = match.get("distance", 0)
        elif match.get("match_type") == "CONTENT_MATCH":
            matches[-1]["final_score"] = round(
                float(match.get("final_score", similarity)), 4
            )
    return {
        "query_image": str(query_path),
        "query_image_name": query_path.name,
        "total_matches_found": int(result.get("total_matches", len(matches))),
        "top_k_returned": int(result.get("top_k", len(matches))),
        "processing_time_ms": float(result.get("processing_time_ms", 0.0)),
        "matches": matches,
    }


def _build_stats(results: list[dict]) -> dict:
    total = len(results)
    matched = sum(result["total_matches_found"] > 0 for result in results)
    average_time = (
        sum(result["processing_time_ms"] for result in results) / total if total else 0.0
    )
    averages = {}
    for rank in range(3):
        scores = [
            result["matches"][rank]["similarity"]
            for result in results
            if len(result["matches"]) > rank
        ]
        averages[f"top_{rank + 1}"] = round(sum(scores) / len(scores), 4) if scores else 0

    return {
        "total_queries": total,
        "queries_with_matches": matched,
        "match_rate": f"{matched / total * 100:.2f}%" if total else "0%",
        "avg_processing_time_ms": round(average_time, 2),
        "top_k": results[0]["top_k_returned"] if results else 0,
        "average_similarities": averages,
    }


def _save_results(options: dict, results: list[dict], stats: dict) -> None:
    output_file = Path(options["output_file"])
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    stats_file = output_file.parent / "query_stats.json"
    stats_file.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)
    has_query = bool(args.query_dir or args.query_list)
    has_index = bool(args.index_dir or args.database_name)
    managed_ready = has_query and bool(args.database_name) and not args.output_file
    legacy_ready = has_query and has_index and bool(args.output_file)
    interactive = args.interactive or not (managed_ready or legacy_ready)

    if args.query_dir and args.query_list:
        parser.error("--query-dir 与 --query-list 不能同时使用")
    if args.index_dir and args.database_name:
        parser.error("--index-dir 与 --database-name 不能同时使用")

    if args.non_interactive and interactive:
        if not has_query:
            parser.error("--non-interactive 需要 --query-dir 或 --query-list")
        if not has_index:
            parser.error("--non-interactive 需要 --index-dir 或 --database-name")
        parser.error("--index-dir 同步模式还需要 --output-file")

    try:
        scheduled = interactive or managed_ready
        if interactive:
            options = collect_search_wizard(args)
            print("\n即将执行：")
            print(f"  数据库：{options['database_name']}")
            print(f"  Query：{len(options['query_paths'])} 张")
            print(f"  Top-N：{options['top_n']}")
            print(f"  批大小：{options['batch_size']}")
            print(
                f"  设备：{'GPU x' + str(options['num_gpus']) if options['num_gpus'] else 'CPU'}"
            )
            print("  执行方式：后台调度器")
            if not args.yes and not prompt_bool("确认加入检索队列", True):
                print("已取消。")
                return 0
        elif managed_ready:
            options = _managed_queue_options(args, parser)
        else:
            options = _direct_options(args, parser)

        if scheduled:
            task_id, scheduler = _enqueue_managed_search(options)
        else:
            results, stats = run_search(options)
            _save_results(options, results, stats)
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        return 130
    except Exception as exc:
        logger.error("批量检索失败：%s", exc)
        return 1

    if scheduled:
        annotations_db = (
            options["databases_root"]
            / options["database_name"]
            / "annotations"
            / "annotations.db"
        )
        print("\n批量检索任务已入队。")
        print(f"任务 ID：{task_id}")
        print(f"结果数据库：{annotations_db}")
        if scheduler.get("pid"):
            print(f"调度器 PID：{scheduler['pid']}")
        print(f"调度器日志：{scheduler['log_path']}")
    else:
        print("\n批量检索完成。")
        print(f"结果文件：{options['output_file']}")
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
