"""Small dependency-free helpers for terminal interaction.

The CLI scripts use these functions to mirror the choices exposed by the
Streamlit forms while keeping all prompts easy to unit test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]


def prompt_text(
    label: str,
    default: str | None = None,
    *,
    required: bool = False,
    input_fn: InputFn = input,
) -> str:
    """Prompt for text, applying an optional default and required check."""
    suffix = f" [{default}]" if default not in (None, "") else ""
    while True:
        value = input_fn(f"{label}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return str(default)
        if not required:
            return ""
        print("该项不能为空，请重新输入。")


def prompt_int(
    label: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    input_fn: InputFn = input,
) -> int:
    """Prompt for a bounded integer."""
    while True:
        raw = input_fn(f"{label} [{default}]: ").strip()
        try:
            value = default if raw == "" else int(raw)
        except ValueError:
            print("请输入整数。")
            continue
        if minimum is not None and value < minimum:
            print(f"请输入不小于 {minimum} 的值。")
            continue
        if maximum is not None and value > maximum:
            print(f"请输入不大于 {maximum} 的值。")
            continue
        return value


def prompt_float(
    label: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    input_fn: InputFn = input,
) -> float:
    """Prompt for a bounded floating-point value."""
    while True:
        raw = input_fn(f"{label} [{default:g}]: ").strip()
        try:
            value = default if raw == "" else float(raw)
        except ValueError:
            print("请输入数字。")
            continue
        if minimum is not None and value < minimum:
            print(f"请输入不小于 {minimum:g} 的值。")
            continue
        if maximum is not None and value > maximum:
            print(f"请输入不大于 {maximum:g} 的值。")
            continue
        return value


def prompt_bool(
    label: str,
    default: bool,
    *,
    input_fn: InputFn = input,
) -> bool:
    """Prompt for a yes/no answer."""
    hint = "Y/n" if default else "y/N"
    while True:
        raw = input_fn(f"{label} [{hint}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes", "1", "true", "是"}:
            return True
        if raw in {"n", "no", "0", "false", "否"}:
            return False
        print("请输入 y 或 n。")


def prompt_choice(
    label: str,
    options: Sequence[str],
    default: str,
    *,
    input_fn: InputFn = input,
    output_fn: OutputFn = print,
) -> str:
    """Prompt for a numbered or literal option."""
    if default not in options:
        raise ValueError(f"default {default!r} is not in options")
    output_fn(label)
    for number, option in enumerate(options, 1):
        marker = " (默认)" if option == default else ""
        output_fn(f"  {number}. {option}{marker}")
    while True:
        raw = input_fn("请选择: ").strip()
        if not raw:
            return default
        if raw in options:
            return raw
        try:
            index = int(raw) - 1
        except ValueError:
            index = -1
        if 0 <= index < len(options):
            return options[index]
        print(f"请输入 1-{len(options)} 或选项名称。")


def prompt_existing_path(
    label: str,
    default: str | None = None,
    *,
    kind: str = "any",
    input_fn: InputFn = input,
) -> Path:
    """Prompt until an existing path of the requested kind is supplied."""
    while True:
        path = Path(prompt_text(label, default, required=True, input_fn=input_fn)).expanduser()
        if not path.exists():
            print(f"路径不存在：{path}")
            continue
        if kind == "directory" and not path.is_dir():
            print(f"不是目录：{path}")
            continue
        if kind == "file" and not path.is_file():
            print(f"不是文件：{path}")
            continue
        return path.resolve()


def nested_get(config: dict, path: Iterable[str], default: Any) -> Any:
    """Read a nested configuration value with a safe fallback."""
    value: Any = config
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return default if value is None else value


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into ``base`` and return ``base``."""
    for key, value in override.items():
        if isinstance(base.get(key), dict) and isinstance(value, dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def scan_images(directory: Path) -> list[Path]:
    """Recursively collect supported image files once, in stable order."""
    extensions = {".jpg", ".jpeg", ".png", ".bmp"}
    return sorted(
        path.resolve()
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in extensions
    )


def load_image_list(path: Path) -> list[Path]:
    """Load existing supported image paths from a UTF-8 text file."""
    extensions = {".jpg", ".jpeg", ".png", ".bmp"}
    seen: set[Path] = set()
    images: list[Path] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        raw = line.strip()
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if candidate.exists() and candidate.is_file() and candidate.suffix.lower() in extensions:
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                images.append(resolved)
    return images
