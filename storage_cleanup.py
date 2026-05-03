from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"

SAVE_DEBUG_SCREENSHOTS = False
SCREENSHOT_MAX_AGE_HOURS = 24
SCREENSHOT_MAX_FILES = 300
SCREENSHOT_CLEANUP_INTERVAL_SECONDS = 600

SCREENSHOT_DIRS = [
    DATA_DIR / "screenshots",
    DATA_DIR / "debug",
    DATA_DIR / "quiz",
    DATA_DIR / "captures" / "raw",
    DATA_DIR / "captures" / "detected",
    DATA_DIR / "captures" / "failed",
    DATA_DIR / "captures" / "quiz",
    DATA_DIR / "dataset" / "images" / "precaptcha",
    DATA_DIR / "dataset" / "images" / "answers",
    DATA_DIR / "dataset" / "images" / "confirm",
    DATA_DIR / "dataset" / "images" / "unknown",
]

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
LEGACY_ROOT_PATTERNS = [
    "vision_*.png",
    "vision_*.jpg",
    "client_area_*.png",
    "client_area_*.jpg",
]


def ensure_screenshot_dirs() -> None:
    for folder in SCREENSHOT_DIRS[:3]:
        folder.mkdir(parents=True, exist_ok=True)


def iter_screenshot_files(base_dir: Optional[Path] = None) -> Iterable[Path]:
    roots = [base_dir] if base_dir else SCREENSHOT_DIRS
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                yield path
    if base_dir is None:
        for pattern in LEGACY_ROOT_PATTERNS:
            for path in APP_DIR.glob(pattern):
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                    yield path


def cleanup_old_files(
    max_age_hours: int = SCREENSHOT_MAX_AGE_HOURS,
    max_files: int = SCREENSHOT_MAX_FILES,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    ensure_screenshot_dirs()
    now = time.time()
    max_age_seconds = max_age_hours * 3600
    files: List[Path] = list(iter_screenshot_files(base_dir))
    to_delete: List[Path] = []

    for path in files:
        try:
            if now - path.stat().st_mtime > max_age_seconds:
                to_delete.append(path)
        except OSError:
            continue

    remaining = [path for path in files if path not in set(to_delete)]
    remaining.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0)

    if len(remaining) > max_files:
        to_delete.extend(remaining[: len(remaining) - max_files])

    deleted = 0
    freed_bytes = 0
    seen = set()
    for path in to_delete:
        if path in seen:
            continue
        seen.add(path)
        try:
            size = path.stat().st_size
            path.unlink()
            deleted += 1
            freed_bytes += size
        except OSError:
            continue

    return {
        "deleted": deleted,
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / (1024 * 1024), 2),
        "remaining": max(0, len(files) - deleted),
    }


def should_save_debug_screenshots(config: Optional[Dict[str, Any]] = None) -> bool:
    if not config:
        return SAVE_DEBUG_SCREENSHOTS

    return bool(
        config.get("SAVE_DEBUG_SCREENSHOTS")
        or config.get("save_debug_screenshots")
        or config.get("vision_debug_save")
        or config.get("captcha_solver_save_debug")
    )


def save_screenshot_image(image: Any, path: Path, prefer_jpg: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)

    if prefer_jpg and path.suffix.lower() == ".png":
        path = path.with_suffix(".jpg")

    if path.suffix.lower() in {".jpg", ".jpeg"}:
        if getattr(image, "mode", "RGB") not in {"RGB", "L"}:
            image = image.convert("RGB")
        image.save(path, quality=80, optimize=True)
    else:
        image.save(path)

    return path
