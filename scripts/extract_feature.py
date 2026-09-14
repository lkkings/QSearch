#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import multiprocessing as mp
import os
import time
from pathlib import Path
from queue import Empty
from typing import Optional

import click
from tqdm import tqdm

from qsearch.features.feature_extractor import FeatureExtractor
from qsearch.features.ocr_engine import OCREngine
from qsearch.features.text_extractor import TextFeatureExtractor
from qsearch.features.image_extractor import ImageFeatureExtractor


OCR_MAX_NEW_TOKENS = 2048
TEXT_MAX_LENGTH = 2048
IMAGE_USE_FP16 = True

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp",
    ".bmp", ".gif", ".tif", ".tiff",
}

_worker_extractor: Optional[FeatureExtractor] = None


# ============================================================
# Worker
# ============================================================

def _init_worker(gpu_id: int,use_gpu:bool, enable_image: bool):
    """每个 Worker 只初始化一次模型。"""

    global _worker_extractor

    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)

    ocr_engine = OCREngine(
        OCR_MAX_NEW_TOKENS,
        use_gpu=use_gpu,
        gpu_id=0,
    )

    text_extractor = TextFeatureExtractor(
        TEXT_MAX_LENGTH,
        use_gpu=use_gpu,
        gpu_id=0,
    )

    image_extractor = (
        ImageFeatureExtractor(
            IMAGE_USE_FP16,
            use_gpu=use_gpu,
            gpu_id=0,
        )
        if enable_image
        else None
    )

    _worker_extractor = FeatureExtractor(
        ocr_engine,
        text_extractor,
        image_extractor,
    )


def _worker(
    task_queue,
    result_queue,
    gpu_id: int,
    use_gpu:bool,
    worker_id: int,
    
    enable_image: bool,
):
    """Worker 主循环。"""

    logging.basicConfig(
        level=logging.INFO,
        format=f"[Worker-{worker_id}/GPU-{gpu_id}] %(message)s" if use_gpu else f"[Worker-{worker_id}/CPU] %(message)s",
    )

    try:
        _init_worker(gpu_id,use_gpu, enable_image)

        while True:
            task = task_queue.get()

            if task is None:
                break

            batch_id, paths = task
            results = []

            for path in paths:
                try:
                    # 根据你的 FeatureExtractor 实际接口调整这里
                    result = _worker_extractor.extract(path)

                    results.append({
                        "path": path,
                        "ok": True,
                        "data": result,
                    })

                except Exception as e:
                    results.append({
                        "path": path,
                        "ok": False,
                        "error": repr(e),
                        "error_type": type(e).__name__,
                    })

            result_queue.put({
                "batch_id": batch_id,
                "worker_id": worker_id,
                "gpu_id": gpu_id,
                "results": results,
            })

    except Exception:
        logging.exception("Worker crashed")
        raise


# ============================================================
# 文件扫描
# ============================================================

def iter_images(root: Path):
    """递归扫描图片。"""

    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            yield path


# ============================================================
# Checkpoint
# ============================================================

def load_completed(path: Path) -> set[str]:
    """读取已经完成的图片。"""

    if not path.exists():
        return set()

    with path.open("r", encoding="utf-8") as f:
        return {
            line.strip()
            for line in f
            if line.strip()
        }


def load_failed(path: Path) -> set[str]:
    """读取失败图片。"""

    if not path.exists():
        return set()

    failed = set()

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                item = json.loads(line)
                if item.get("path"):
                    failed.add(item["path"])
            except json.JSONDecodeError:
                continue

    return failed


# ============================================================
# Writer
# ============================================================

class OutputWriter:

    def __init__(self, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)

        self.results = (output_dir / "results.jsonl").open(
            "a",
            encoding="utf-8",
            buffering=1,
        )

        self.failed = (output_dir / "failed.jsonl").open(
            "a",
            encoding="utf-8",
            buffering=1,
        )

        self.completed = (output_dir / "completed.txt").open(
            "a",
            encoding="utf-8",
            buffering=1,
        )

    def success(self, path: str, data):
        self.results.write(
            json.dumps(
                {
                    "path": path,
                    "data": data,
                },
                ensure_ascii=False,
            ) + "\n"
        )

        self.completed.write(path + "\n")

    def failure(
        self,
        path: str,
        error: str,
        error_type: str,
        worker_id: int,
        gpu_id: int,
    ):
        self.failed.write(
            json.dumps(
                {
                    "path": path,
                    "error": error,
                    "error_type": error_type,
                    "worker_id": worker_id,
                    "gpu_id": gpu_id,
                    "time": time.time(),
                },
                ensure_ascii=False,
            ) + "\n"
        )

    def flush(self):
        self.results.flush()
        self.completed.flush()
        self.failed.flush()

    def close(self):
        self.flush()
        self.results.close()
        self.completed.close()
        self.failed.close()


# ============================================================
# 主处理
# ============================================================

def run(
    input_dir: Path,
    output_dir: Path,
    batch_size: int,
    workers: int,
    gpus: list[int],
    enable_image: bool,
    retry_failed: bool,
    poll_interval: float,
):
    output_dir.mkdir(parents=True, exist_ok=True)

    completed_file = output_dir / "completed.txt"
    failed_file = output_dir / "failed.jsonl"

    completed = load_completed(completed_file)

    if retry_failed:
        failed = set()
    else:
        failed = load_failed(failed_file)

    click.echo(
        f"Completed: {len(completed):,} | "
        f"Failed: {len(failed):,}"
    )

    # --------------------------------------------------------
    # multiprocessing
    # --------------------------------------------------------

    ctx = mp.get_context("spawn")

    task_queue = ctx.Queue(
        maxsize=max(workers * 2, 2)
    )

    result_queue = ctx.Queue(
        maxsize=max(workers * 2, 2)
    )

    processes = []

    for worker_id in range(workers):
        if len(gpus) == 0:
            use_gpu = False
            gpu_id = 0
        else:
            use_gpu = True
            gpu_id = gpus[worker_id % len(gpus)]

        p = ctx.Process(
            target=_worker,
            args=(
                task_queue,
                result_queue,
                gpu_id,
                use_gpu,
                worker_id,
                enable_image,
            ),
        )

        p.start()
        processes.append(p)

    writer = OutputWriter(output_dir)

    # --------------------------------------------------------
    # Runtime state
    # --------------------------------------------------------

    discovered = 0
    submitted = 0
    finished = 0
    success = 0
    failed_count = 0

    batch_id = 0
    pending = []
    seen = set(completed) | failed

    # --------------------------------------------------------
    # Progress
    # --------------------------------------------------------

    progress = tqdm(
        desc="QSearch",
        unit="img",
        dynamic_ncols=True,
        bar_format=(
            "{desc} {bar:30} "
            "{n_fmt} "
            "[{elapsed}<{remaining}, {rate_fmt}] "
            "{postfix}"
        ),
    )

    try:
        while True:

            # =================================================
            # 扫描新图片
            # =================================================

            found_new = False

            for path in iter_images(input_dir):

                relative = str(
                    path.relative_to(input_dir)
                )

                if relative in seen:
                    continue

                seen.add(relative)
                pending.append((relative, str(path)))

                discovered += 1
                found_new = True

                if len(pending) >= batch_size:
                    batch = pending[:batch_size]
                    del pending[:batch_size]

                    task_queue.put(
                        (
                            batch_id,
                            [x[1] for x in batch],
                        )
                    )

                    batch_id += 1
                    submitted += len(batch)

            # =================================================
            # 处理完成队列
            # =================================================

            got_result = False

            while True:
                try:
                    result = result_queue.get_nowait()
                except Empty:
                    break

                got_result = True

                for item in result["results"]:

                    # 将绝对路径转换成相对路径
                    path = Path(item["path"])

                    relative = str(
                        path.relative_to(input_dir)
                    )

                    if item["ok"]:
                        writer.success(
                            relative,
                            item["data"],
                        )
                        success += 1

                    else:
                        writer.failure(
                            relative,
                            item["error"],
                            item["error_type"],
                            result["worker_id"],
                            result["gpu_id"],
                        )
                        failed_count += 1

                    finished += 1
                    progress.update(1)

                writer.flush()

            # =================================================
            # tqdm
            # =================================================

            progress.set_postfix(
                {
                    "发现": discovered,
                    "提交": submitted,
                    "成功": success,
                    "失败": failed_count,
                    "队列": _qsize(task_queue),
                }
            )

            # =================================================
            # 当前没有新文件
            # =================================================

            if not found_new and not got_result:

                # 最后不足 batch_size 的任务
                if pending:
                    batch = pending
                    pending = []

                    task_queue.put(
                        (
                            batch_id,
                            [x[1] for x in batch],
                        )
                    )

                    batch_id += 1
                    submitted += len(batch)

                else:
                    time.sleep(poll_interval)

            # =================================================
            # 没有新文件，但还有任务在处理
            # =================================================

            elif not found_new:

                time.sleep(0.05)

    except KeyboardInterrupt:
        click.echo("\nStopping...")

    finally:

        # ----------------------------------------------------
        # 提交最后一个 batch
        # ----------------------------------------------------

        if pending:
            task_queue.put(
                (
                    batch_id,
                    [x[1] for x in pending],
                )
            )
            submitted += len(pending)
            pending.clear()

        # ----------------------------------------------------
        # 等待所有任务完成
        # ----------------------------------------------------

        while finished < submitted:

            try:
                result = result_queue.get(timeout=1)

            except Empty:
                continue

            for item in result["results"]:

                path = Path(item["path"])

                relative = str(
                    path.relative_to(input_dir)
                )

                if item["ok"]:
                    writer.success(
                        relative,
                        item["data"],
                    )
                    success += 1

                else:
                    writer.failure(
                        relative,
                        item["error"],
                        item["error_type"],
                        result["worker_id"],
                        result["gpu_id"],
                    )
                    failed_count += 1

                finished += 1
                progress.update(1)

            writer.flush()

        # ----------------------------------------------------
        # 停止 Worker
        # ----------------------------------------------------

        for _ in processes:
            task_queue.put(None)

        for p in processes:
            p.join()

        writer.close()
        progress.close()

    click.echo(
        f"\nDone: success={success:,}, "
        f"failed={failed_count:,}"
    )


def _qsize(queue):
    try:
        return queue.qsize()
    except (NotImplementedError, AttributeError):
        return 0


# ============================================================
# CLI
# ============================================================

@click.command()
@click.option(
    "--input-dir",
    type=click.Path(
        exists=True,
        file_okay=False,
        path_type=Path,
    ),
    required=True,
    help="图片输入目录",
)
@click.option(
    "--output-dir",
    type=click.Path(
        file_okay=False,
        path_type=Path,
    ),
    required=True,
    help="结果输出目录",
)
@click.option(
    "--batch-size",
    default=32,
    show_default=True,
    type=click.IntRange(min=1),
    help="Worker batch 大小",
)
@click.option(
    "--workers",
    default=4,
    show_default=True,
    type=click.IntRange(min=1),
    help="Worker 并发数",
)
@click.option(
    "--gpus",
    default="",
    show_default=True,
    help="GPU，例如 0,1,2,3",
)
@click.option(
    "--enable-image",
    is_flag=True,
    help="启用 ImageFeatureExtractor",
)
@click.option(
    "--retry-failed",
    is_flag=True,
    help="重新处理之前失败的图片",
)
@click.option(
    "--poll-interval",
    default=1.0,
    show_default=True,
    type=float,
    help="目录扫描间隔（秒）",
)
def main(
    input_dir: Path,
    output_dir: Path,
    batch_size: int,
    workers: int,
    gpus: str,
    enable_image: bool,
    retry_failed: bool,
    poll_interval: float,
):
    """QSearch 多进程图片特征提取。"""

    gpu_ids = []
    if gpus:
        try:
            gpu_ids = [
                int(x.strip())
                for x in gpus.split(",")
                if x.strip()
            ]
        except ValueError:
            raise click.BadParameter(
                "--gpus 必须类似 0,1,2,3"
            )

    click.echo(
        f"Input : {input_dir}"
    )
    click.echo(
        f"Output: {output_dir}"
    )
    click.echo(
        f"Batch : {batch_size}"
    )
    click.echo(
        f"Workers: {workers}"
    )
    click.echo(
        f"GPUs  : {gpu_ids}"
    )

    run(
        input_dir=input_dir,
        output_dir=output_dir,
        batch_size=batch_size,
        workers=workers,
        gpus=gpu_ids,
        enable_image=enable_image,
        retry_failed=retry_failed,
        poll_interval=poll_interval,
    )


if __name__ == "__main__":
    # uv run scripts\extract_feature.py --input-dir test\data\image --output-dir test\data\features --batch-size 2 --workers 1 -gpus 0,1,2,3
    mp.freeze_support()
    main()