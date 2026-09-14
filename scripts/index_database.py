"""Create a QSearch database and build its indexes.

Run without the required legacy flags to start an interactive terminal wizard
that mirrors ``render_create_database_form``. Existing automation can continue
to pass ``--image-dir`` and ``--output-dir`` for direct, non-interactive builds.
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
from qsearch.indexing.builder import build_index
from qsearch.webui.database_manager import DatabaseManager
from qsearch.webui.task_manager import TaskManager

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CHINESE_MODELS = (
    "hfl/chinese-roberta-wwm-ext",
    "hfl/chinese-bert-wwm-ext",
    "shibing624/text2vec-base-chinese",
)
ENGLISH_MODELS = (
    "sentence-transformers/all-mpnet-base-v2",
    "sentence-transformers/all-MiniLM-L12-v2",
    "bert-base-uncased",
)
INDEX_TYPES = ("Flat", "IVFFlat", "IVFPQ", "HNSW")


def load_image_paths(image_dir: Path) -> list[Path]:
    """Backward-compatible image directory scanner."""
    return scan_images(Path(image_dir))


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a QSearch database and build its search indexes",
    )
    parser.add_argument("--image-dir", help="Directory containing source images")
    parser.add_argument(
        "--output-dir",
        help="Legacy direct-build output directory; bypasses managed database creation",
    )
    parser.add_argument("--database-name", help="Managed database name")
    parser.add_argument("--databases-root", default="databases", help="Managed database root")
    parser.add_argument("--config", help="YAML configuration used as prompt defaults")
    parser.add_argument(
        "--preset",
        choices=("conservative", "balanced", "aggressive"),
        default="balanced",
        help="Matching preset when no complete config is supplied",
    )
    parser.add_argument("--num-workers", type=int, help="CPU extraction workers")
    parser.add_argument("--num-gpus", type=int, help="GPUs used for extraction")
    parser.add_argument("--batch-size", type=int, help="Text/image extraction batch size")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--interactive", action="store_true", help="Always open the wizard")
    mode.add_argument(
        "--non-interactive",
        action="store_true",
        help="Never prompt; requires --image-dir and --output-dir or --database-name",
    )
    parser.add_argument("--yes", action="store_true", help="Skip the final confirmation")
    return parser


def default_feature_config(preset: str = "balanced") -> dict:
    """Return the same complete feature/index defaults as the WebUI form."""
    config = {
        "text": {
            "ocr": {
                "engine": "transformers",
                "languages": ["ch", "en"],
                "confidence_threshold": 0.5,
            },
            "encoding": {
                "chinese_model": CHINESE_MODELS[0],
                "english_model": ENGLISH_MODELS[0],
                "embedding_dim": 768,
                "max_length": 512,
                "batch_size": 128,
            },
        },
        "image": {
            "components": {
                "perceptual_hash": {
                    "enabled": True,
                    "algorithm": "dHash",
                    "hash_size": 16,
                },
                "deep_features": {
                    "enabled": False,
                    "model": "efficientnet_b4",
                    "output_dim": 512,
                },
            },
            "batch_size": 128,
        },
        "index": {"type": "Flat"},
    }
    deep_merge(config, copy.deepcopy(get_preset(preset)))
    return config


def load_base_config(config_path: str | None, preset: str) -> dict:
    if config_path:
        loaded = ConfigLoader.load_yaml(config_path)
        if not isinstance(loaded, dict):
            raise ValueError("配置文件顶层必须是对象")
        return loaded
    return default_feature_config(preset)


def collect_index_wizard(
    args: argparse.Namespace,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> dict:
    """Collect the terminal equivalent of ``render_create_database_form``."""
    base = load_base_config(args.config, args.preset)
    output_fn("\n=== QSearch 数据库创建与索引构建 ===")

    database_name = prompt_text(
        "数据库名称", args.database_name, required=True, input_fn=input_fn
    )
    image_dir = prompt_existing_path(
        "图片目录", args.image_dir, kind="directory", input_fn=input_fn
    )
    databases_root = Path(
        prompt_text(
            "数据库根目录", args.databases_root, required=True, input_fn=input_fn
        )
    ).expanduser().resolve()

    output_fn("\n[计算资源]")
    num_workers = prompt_int(
        "CPU 工作进程数",
        args.num_workers if args.num_workers is not None else 4,
        minimum=1,
        maximum=32,
        input_fn=input_fn,
    )
    num_gpus = prompt_int(
        "GPU 数量",
        args.num_gpus if args.num_gpus is not None else 0,
        minimum=0,
        maximum=8,
        input_fn=input_fn,
    )
    configured_batch = int(nested_get(base, ("image", "batch_size"), 128))
    batch_size = prompt_int(
        "批处理大小",
        args.batch_size if args.batch_size is not None else configured_batch,
        minimum=1,
        maximum=512,
        input_fn=input_fn,
    )

    output_fn("\n[文本特征提取]")
    languages_raw = prompt_text(
        "OCR 语言（逗号分隔：ch,en）",
        ",".join(nested_get(base, ("text", "ocr", "languages"), ["ch", "en"])),
        required=True,
        input_fn=input_fn,
    )
    languages = [item.strip() for item in languages_raw.split(",") if item.strip()]
    invalid_languages = sorted(set(languages) - {"ch", "en"})
    if invalid_languages:
        raise ValueError(f"不支持的 OCR 语言：{', '.join(invalid_languages)}")
    confidence = prompt_float(
        "OCR 置信度阈值",
        float(nested_get(base, ("text", "ocr", "confidence_threshold"), 0.5)),
        minimum=0.0,
        maximum=1.0,
        input_fn=input_fn,
    )
    chinese_model = prompt_choice(
        "中文编码模型",
        CHINESE_MODELS,
        str(nested_get(base, ("text", "encoding", "chinese_model"), CHINESE_MODELS[0])),
        input_fn=input_fn,
        output_fn=output_fn,
    )
    english_model = prompt_choice(
        "英文编码模型",
        ENGLISH_MODELS,
        str(nested_get(base, ("text", "encoding", "english_model"), ENGLISH_MODELS[0])),
        input_fn=input_fn,
        output_fn=output_fn,
    )
    embedding_dim = prompt_int(
        "文本向量维度",
        int(nested_get(base, ("text", "encoding", "embedding_dim"), 768)),
        minimum=128,
        maximum=1024,
        input_fn=input_fn,
    )
    max_length = prompt_int(
        "最大 token 数",
        int(nested_get(base, ("text", "encoding", "max_length"), 512)),
        minimum=64,
        maximum=512,
        input_fn=input_fn,
    )

    output_fn("\n[图片特征提取]")
    phash_enabled = prompt_bool(
        "启用感知哈希",
        bool(nested_get(base, ("image", "components", "perceptual_hash", "enabled"), True)),
        input_fn=input_fn,
    )
    phash_algorithm = prompt_choice(
        "感知哈希算法",
        ("dHash", "pHash", "aHash"),
        str(nested_get(base, ("image", "components", "perceptual_hash", "algorithm"), "dHash")),
        input_fn=input_fn,
        output_fn=output_fn,
    )
    hash_size = prompt_choice(
        "哈希尺寸",
        ("8", "16", "32"),
        str(nested_get(base, ("image", "components", "perceptual_hash", "hash_size"), 16)),
        input_fn=input_fn,
        output_fn=output_fn,
    )
    deep_enabled = prompt_bool(
        "启用 CNN 深度特征",
        bool(nested_get(base, ("image", "components", "deep_features", "enabled"), False)),
        input_fn=input_fn,
    )
    cnn_model = prompt_choice(
        "CNN 模型",
        ("efficientnet_b4", "resnet50"),
        str(nested_get(base, ("image", "components", "deep_features", "model"), "efficientnet_b4")),
        input_fn=input_fn,
        output_fn=output_fn,
    )
    cnn_output_dim = prompt_int(
        "CNN 特征维度",
        int(nested_get(base, ("image", "components", "deep_features", "output_dim"), 512)),
        minimum=128,
        maximum=2048,
        input_fn=input_fn,
    )

    output_fn("\n[Faiss 索引]")
    index_type = prompt_choice(
        "索引类型",
        INDEX_TYPES,
        str(nested_get(base, ("index", "type"), "Flat")),
        input_fn=input_fn,
        output_fn=output_fn,
    )
    index_settings: dict = {"type": index_type}
    if index_type in {"IVFFlat", "IVFPQ"}:
        index_settings["nlist"] = prompt_int(
            "聚类数 nlist", int(nested_get(base, ("index", "nlist"), 100)),
            minimum=1, maximum=65536, input_fn=input_fn,
        )
        index_settings["nprobe"] = prompt_int(
            "检索单元数 nprobe", int(nested_get(base, ("index", "nprobe"), 10)),
            minimum=1, maximum=index_settings["nlist"], input_fn=input_fn,
        )
    if index_type == "IVFPQ":
        index_settings["m_pq"] = prompt_int(
            "子向量数 m", int(nested_get(base, ("index", "m_pq"), 16)),
            minimum=1, maximum=128, input_fn=input_fn,
        )
        index_settings["nbits"] = prompt_int(
            "每个子量化器位数 nbits", int(nested_get(base, ("index", "nbits"), 8)),
            minimum=4, maximum=16, input_fn=input_fn,
        )
    elif index_type == "HNSW":
        index_settings["hnsw_m"] = prompt_int(
            "图连接数 M", int(nested_get(base, ("index", "hnsw_m"), 16)),
            minimum=4, maximum=128, input_fn=input_fn,
        )
        index_settings["ef_construction"] = prompt_int(
            "构建候选数 efConstruction",
            int(nested_get(base, ("index", "ef_construction"), 40)),
            minimum=8, maximum=512, input_fn=input_fn,
        )
        index_settings["ef_search"] = prompt_int(
            "查询候选数 efSearch", int(nested_get(base, ("index", "ef_search"), 32)),
            minimum=8, maximum=512, input_fn=input_fn,
        )

    config = copy.deepcopy(base)
    deep_merge(config, {
        "text": {
            "ocr": {
                "engine": "transformers",
                "languages": languages or ["ch", "en"],
                "confidence_threshold": confidence,
            },
            "encoding": {
                "chinese_model": chinese_model,
                "english_model": english_model,
                "embedding_dim": embedding_dim,
                "max_length": max_length,
                "batch_size": batch_size,
            },
        },
        "image": {
            "components": {
                "perceptual_hash": {
                    "enabled": phash_enabled,
                    "algorithm": phash_algorithm,
                    "hash_size": int(hash_size),
                },
                "deep_features": {
                    "enabled": deep_enabled,
                    "model": cnn_model,
                    "output_dim": cnn_output_dim,
                },
            },
            "batch_size": batch_size,
        },
        "index": index_settings,
    })

    return {
        "database_name": database_name,
        "databases_root": databases_root,
        "image_dir": image_dir,
        "num_workers": num_workers,
        "num_gpus": num_gpus,
        "batch_size": batch_size,
        "config": config,
    }


def _enqueue_managed_build(options: dict) -> tuple[str, dict]:
    """Create a managed database and enqueue its build like the WebUI."""
    manager = DatabaseManager(options["databases_root"])
    config_yaml = yaml.safe_dump(options["config"], allow_unicode=True, sort_keys=False)
    manager.create_database(
        options["database_name"], options["image_dir"], config_yaml=config_yaml
    )
    task_manager = TaskManager(options["databases_root"])
    task_id = task_manager.enqueue_index_build(
        database_name=options["database_name"],
        num_workers=(options["num_workers"] if options["num_gpus"] == 0 else None),
        num_gpus=options["num_gpus"],
        batch_size=options["batch_size"],
        task_name=f"建立索引：{options['database_name']}",
    )
    return task_id, task_manager.scheduler_status()


def _run_direct_build(args: argparse.Namespace) -> dict:
    image_dir = Path(args.image_dir).expanduser().resolve()
    if not image_dir.is_dir():
        raise ValueError(f"图片目录不存在：{image_dir}")
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_base_config(args.config, args.preset)
    batch_size = args.batch_size or int(nested_get(config, ("image", "batch_size"), 128))
    config.setdefault("text", {}).setdefault("encoding", {})["batch_size"] = batch_size
    config.setdefault("image", {})["batch_size"] = batch_size

    config_path = Path(args.config).resolve() if args.config else output_dir / "config.yaml"
    if not args.config:
        ConfigLoader().export_yaml(config, config_path)

    image_paths = scan_images(image_dir)
    if not image_paths:
        raise ValueError(f"图片目录中没有支持的图片：{image_dir}")
    image_list = output_dir / "image_list.txt"
    image_list.write_text("".join(f"{path}\n" for path in image_paths), encoding="utf-8")

    num_gpus = 1 if args.num_gpus is None else args.num_gpus
    if num_gpus < 0:
        raise ValueError("num_gpus 不能小于 0")

    return build_index(
        config_path=str(config_path),
        image_list=str(image_list),
        output_dir=str(output_dir),
        num_workers=args.num_workers,
        num_gpus=num_gpus,
        batch_size=batch_size,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)
    has_direct_target = bool(args.image_dir and (args.output_dir or args.database_name))
    interactive = args.interactive or not has_direct_target

    if args.output_dir and args.database_name:
        parser.error("--output-dir 与 --database-name 不能同时使用")

    if args.non_interactive and not has_direct_target:
        parser.error(
            "--non-interactive 需要 --image-dir，并指定 --output-dir 或 --database-name"
        )

    try:
        if interactive:
            options = collect_index_wizard(args)
            count = len(scan_images(options["image_dir"]))
            print("\n即将执行：")
            print(f"  数据库：{options['database_name']}")
            print(f"  图片目录：{options['image_dir']}（{count} 张）")
            print(f"  设备：{'GPU x' + str(options['num_gpus']) if options['num_gpus'] else 'CPU'}")
            print(f"  批大小：{options['batch_size']}")
            if not args.yes and not prompt_bool("确认创建并构建索引", True):
                print("已取消。")
                return 0
            task_id, scheduler = _enqueue_managed_build(options)
            index_dir = options["databases_root"] / options["database_name"] / "index"
        elif args.database_name:
            config = load_base_config(args.config, args.preset)
            batch_size = args.batch_size or int(nested_get(config, ("image", "batch_size"), 128))
            config.setdefault("text", {}).setdefault("encoding", {})["batch_size"] = batch_size
            config.setdefault("image", {})["batch_size"] = batch_size
            options = {
                "database_name": args.database_name,
                "databases_root": Path(args.databases_root).expanduser().resolve(),
                "image_dir": Path(args.image_dir).expanduser().resolve(),
                "num_workers": args.num_workers,
                "num_gpus": args.num_gpus or 0,
                "batch_size": batch_size,
                "config": config,
            }
            task_id, scheduler = _enqueue_managed_build(options)
            index_dir = options["databases_root"] / args.database_name / "index"
        else:
            stats = _run_direct_build(args)
            index_dir = Path(args.output_dir).expanduser().resolve()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        return 130
    except Exception as exc:
        logger.error("索引构建失败：%s", exc)
        return 1

    if args.database_name or interactive:
        print("\n数据库已创建，索引构建任务已入队。")
        print(f"任务 ID：{task_id}")
        print(f"索引目录：{index_dir}")
        if scheduler.get("pid"):
            print(f"调度器 PID：{scheduler['pid']}")
        print(f"调度器日志：{scheduler['log_path']}")
    else:
        print("\n索引构建完成。")
        print(f"输出目录：{index_dir}")
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
