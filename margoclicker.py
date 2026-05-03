from __future__ import annotations

import ctypes
import json
import logging
import hashlib
import random
import subprocess
import sys
import threading
import time
import importlib
import unicodedata
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from datetime import datetime
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import scrolledtext, ttk

try:
    import customtkinter as ctk
except ModuleNotFoundError:
    ctk = None

from license_client import (
    clear_saved_license,
    clear_saved_license_key,
    load_license_config,
    require_active_license,
    update_saved_license_key,
    verify_license,
)
from storage_cleanup import (
    SCREENSHOT_CLEANUP_INTERVAL_SECONDS,
    cleanup_old_files,
    ensure_screenshot_dirs,
    iter_screenshot_files,
    save_screenshot_image,
    should_save_debug_screenshots,
)

try:
    import keyboard
except ModuleNotFoundError:
    keyboard = None

try:
    import pyautogui
except ModuleNotFoundError:
    pyautogui = None
try:
    import cv2
except ModuleNotFoundError:
    cv2 = None
try:
    import numpy as np
except ModuleNotFoundError:
    np = None
try:
    from PIL import Image, ImageDraw
except ModuleNotFoundError:
    Image = None
    ImageDraw = None
try:
    import pytesseract
except ModuleNotFoundError:
    pytesseract = None
try:
    import mss
except ModuleNotFoundError:
    mss = None
try:
    import imagehash
except ModuleNotFoundError:
    imagehash = None

try:
    from flask import Flask, jsonify, make_response, request, send_file
    from flask_cors import CORS

    FLASK_AVAILABLE = True
except ModuleNotFoundError:
    FLASK_AVAILABLE = False

    class _DummyFlask:
        def route(self, *_args, **_kwargs):
            def _decorator(func):
                return func

            return _decorator

        def run(self, *_args, **_kwargs):
            raise RuntimeError("Flask nie jest zainstalowany.")

    def Flask(_name):  # type: ignore[misc]
        return _DummyFlask()

    def CORS(*_args, **_kwargs):  # type: ignore[misc]
        return None

# =========================
# MODELE / CONFIG
# =========================

BROWSER_PROCESS_NAMES = {"brave.exe", "chrome.exe", "firefox.exe", "msedge.exe"}
TEST_POINT_PRESETS = {
    "center": (0.50, 0.50),
    "pre_zapadki": (0.50, 0.50),
    "top_center": (0.50, 0.12),
    "left_top_margin": (0.10, 0.10),
    "right_top_margin": (0.90, 0.10),
    "bottom_center": (0.50, 0.88),
}

app = Flask(__name__)
if FLASK_AVAILABLE:
    CORS(app, resources={r"/*": {"origins": "*"}})
config_lock = threading.Lock()
SETTINGS_PATH = Path(__file__).with_name("margoclicker_settings.json")
DATA_DIR = Path(__file__).with_name("data")


@dataclass
class WindowCandidate:
    hwnd: int
    title: str
    class_name: str
    pid: int
    process_name: str
    rect: Dict[str, int]
    client_rect: Dict[str, int]
    client_origin: Dict[str, int]
    monitor_index: int
    monitor_name: str
    monitor_rect: Dict[str, int]
    work_rect: Dict[str, int]
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)


@dataclass
class WindowGeometry:
    hwnd: int
    window_rect: Dict[str, int]
    client_rect: Dict[str, int]
    client_origin: Dict[str, int]
    monitor_index: int
    monitor_name: str
    monitor_rect: Dict[str, int]
    work_rect: Dict[str, int]


DEFAULT_CONFIG: Dict[str, Any] = {
    "api_enabled": True,
    "use_client_area": True,
    "manual_offset_enabled": True,
    "manual_offset_y": 0.0,
    "answer_offset_enabled": False,
    "answer_offset_y": 0.0,
    "window_keyword": "margonem",
    "restore_window_before_click": False,
    "hide_console_on_start": True,
    "launch_command": "",
    "browser_url_hint": "",
    "window_selection_mode": "auto",  # auto/title/process/picked
    "target_hwnd_last": 0,
    "target_pid": 0,
    "target_process_name": "",
    "target_window_title": "",
    "target_class_name": "",
    "target_monitor_name": "",
    "target_monitor_index": -1,
    "use_virtual_mouse": True,
    "allow_physical_click_fallback": False,
    "click_hold_ms_min": 60,
    "click_hold_ms_max": 130,
    "click_jitter_px": 3,
    "hotkey": "f9",
    "disable_randomness": False,
    "calibration": {},
    "manual_click_points": {},
    "vision_enabled": True,
    "vision_auto_install": True,
    "vision_threshold": 0.72,
    "vision_templates_dir": "templates",
    "vision_debug": False,
    "SAVE_DEBUG_SCREENSHOTS": False,
    "save_debug_screenshots": False,
    "vision_debug_save": False,
    "vision_click_mode": "absolute",
    "vision_min_confidence_to_label": 0.72,
    "vision_dataset_enabled": False,
    "vision_save_failed_samples": False,
    "dataset_dedupe_enabled": True,
    "dataset_hash_distance_threshold": 6,
    "dataset_box_delta_px": 8,
    "dataset_min_seconds_between_duplicates": 600,
    "dataset_save_on_window_size_change": True,
    "dataset_save_unknown": False,
    "vision_auto_watch": True,
    "vision_watch_interval_ms": 900,
    "vision_click_cooldown_ms": 2000,
    "vision_auto_click_precaptcha": True,
    "vision_auto_click_answers": False,
    "vision_auto_click_confirm": False,
    "vision_auto_solve_captcha": True,
    "captcha_solver_default_symbol": "star",
    "captcha_solver_auto_confirm": True,
    "captcha_solver_require_question_ocr": False,
    "captcha_solver_click_all_targets": True,
    "captcha_solver_unselect_wrong_answers": False,
    "captcha_solver_save_debug": False,
    "captcha_solver_debug_min_interval_ms": 2000,
    "captcha_solver_click_delay_ms": 320,
    "captcha_solver_confirm_delay_ms": 650,
    "captcha_solver_answer_delay_min_ms": 420,
    "captcha_solver_answer_delay_max_ms": 950,
    "captcha_solver_confirm_delay_min_ms": 900,
    "captcha_solver_confirm_delay_max_ms": 1800,
    "captcha_solver_same_quiz_cooldown_ms": 6000,
    "captcha_solver_strict_quiz_window": True,
    "vision_ignore_right_panel_ratio": 0.84,
    "pre_captcha_green_fallback_enabled": True,
    "pre_captcha_button_text": "Rozwiąż teraz",
    "vision_fallback_manual": True,
    "target_prefer_game_title": True,
    "target_title_required_keywords": ["margonem"],
    "target_exclude_process_names": ["python.exe"],
    "target_exclude_title_keywords": ["MargoClicker", "Codex", "GitHub", "DevTools"],
}
config: Dict[str, Any] = dict(DEFAULT_CONFIG)

def get_manual_click_point(name: str) -> Optional[Dict[str, int]]:
    with config_lock:
        points = config.get("manual_click_points", {})
        point = points.get(name) if isinstance(points, dict) else None
    if not isinstance(point, dict):
        return None
    try:
        return {"x": int(point.get("x", 0)), "y": int(point.get("y", 0))}
    except Exception:
        return None


def resolve_click_point(name: str, fallback_ratio: Tuple[float, float], client_w: int, client_h: int) -> Tuple[float, float]:
    point = get_manual_click_point(name)
    if point:
        return float(point["x"]), float(point["y"])
    return client_w * fallback_ratio[0], client_h * fallback_ratio[1]


def wait_for_left_click(timeout_sec: float = 10.0) -> Optional[Tuple[int, int]]:
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    pt = POINT()
    start = time.time()
    while time.time() - start < timeout_sec:
        if user32.GetAsyncKeyState(0x01) & 0x8000:
            while user32.GetAsyncKeyState(0x01) & 0x8000:
                time.sleep(0.01)
            if user32.GetCursorPos(ctypes.byref(pt)):
                return int(pt.x), int(pt.y)
        time.sleep(0.01)
    return None


# =========================
# DIAGNOSTYKA (stan runtime)
# =========================

runtime_state = {
    "paused": False,
    "last_candidates": [],
    "last_selected_candidate": None,
    "last_click": None,
    "last_match": None,
    "click_history": deque(maxlen=20),
    "log_hook": None,
    "hotkey_registered": False,
    "hotkey_registered_key": "",
    "capture_method": None,
    "capture_quality": None,
    "dataset_index": [],
    "watcher_started": False,
    "watcher_state": "IDLE",
    "last_ocr_texts": [],
    "last_dataset_event": None,
    "last_saved_by_kind": {"precaptcha": None, "answers": None, "confirm": None, "unknown": None, "failed": None},
    "watcher_running": False,
    "watcher_thread": None,
    "force_answers_scan": False,
    "last_quiz_debug": None,
    "last_quiz_debug_ts": 0.0,
    "last_quiz_debug_status": "",
    "last_quiz_debug_signature": "",
    "last_quiz_solve_signature": "",
    "last_quiz_solve_ts": 0.0,
    "last_quiz_clicked_signature": "",
    "last_quiz_clicked_indexes": [],
    "last_quiz_solved_at": 0.0,
    "last_quiz_solved_result": None,
}


quiz_solver_lock = threading.Lock()


def ensure_data_dirs() -> Dict[str, Path]:
    paths = {
        "screenshots": DATA_DIR / "screenshots",
        "debug": DATA_DIR / "debug",
        "quiz": DATA_DIR / "quiz",
        "captures_raw": DATA_DIR / "captures" / "raw",
        "captures_detected": DATA_DIR / "captures" / "detected",
        "captures_failed": DATA_DIR / "captures" / "failed",
        "captures_quiz": DATA_DIR / "captures" / "quiz",
        "dataset_images_precaptcha": DATA_DIR / "dataset" / "images" / "precaptcha",
        "dataset_images_answers": DATA_DIR / "dataset" / "images" / "answers",
        "dataset_images_confirm": DATA_DIR / "dataset" / "images" / "confirm",
        "dataset_images_unknown": DATA_DIR / "dataset" / "images" / "unknown",
        "dataset_labels_precaptcha": DATA_DIR / "dataset" / "labels" / "precaptcha",
        "dataset_labels_answers": DATA_DIR / "dataset" / "labels" / "answers",
        "dataset_labels_confirm": DATA_DIR / "dataset" / "labels" / "confirm",
        "dataset_labels_unknown": DATA_DIR / "dataset" / "labels" / "unknown",
        "logs": DATA_DIR / "logs",
        "models": DATA_DIR / "models",
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "dataset" / "index.jsonl").touch(exist_ok=True)
    (DATA_DIR / "dataset" / "metadata.jsonl").touch(exist_ok=True)
    return paths


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", ctypes.c_ulong),
        ("szDevice", ctypes.c_wchar * 32),
    ]


def log_event(message: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    hook = runtime_state.get("log_hook")
    if callable(hook):
        try:
            hook(line)
        except Exception:
            pass


# =========================
# WINAPI HELPERS
# =========================

def setup_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        log_event("DPI awareness ustawione: Per Monitor v1 (shcore)")
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            log_event("DPI awareness ustawione: System")
        except Exception as e:
            log_event(f"Nie udało się ustawić DPI awareness: {e}")


def hide_console_window() -> None:
    if sys.platform != "win32":
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def show_console_window() -> None:
    if sys.platform != "win32":
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 5)
    except Exception:
        pass


def _rect_to_dict(rc: RECT) -> Dict[str, int]:
    return {"left": int(rc.left), "top": int(rc.top), "right": int(rc.right), "bottom": int(rc.bottom)}


def _is_valid_hwnd(hwnd: int) -> bool:
    if sys.platform != "win32" or not hwnd:
        return False
    return bool(ctypes.windll.user32.IsWindow(hwnd))


def get_window_text(hwnd: int) -> str:
    if sys.platform != "win32" or not hwnd:
        return ""
    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buff = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buff, length + 1)
    return buff.value.strip()


def get_class_name(hwnd: int) -> str:
    if sys.platform != "win32" or not hwnd:
        return ""
    buff = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, buff, 255)
    return buff.value.strip()


def get_window_pid(hwnd: int) -> int:
    if sys.platform != "win32" or not hwnd:
        return 0
    pid = ctypes.c_ulong(0)
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def get_process_name(pid: int) -> str:
    if sys.platform != "win32" or not pid:
        return ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    hproc = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not hproc:
        return ""
    try:
        size = ctypes.c_ulong(32768)
        buff = ctypes.create_unicode_buffer(size.value)
        ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(hproc, 0, buff, ctypes.byref(size))
        if not ok:
            return ""
        return Path(buff.value).name.lower()
    finally:
        ctypes.windll.kernel32.CloseHandle(hproc)


def get_window_rect(hwnd: int) -> Optional[Dict[str, int]]:
    if not _is_valid_hwnd(hwnd):
        return None
    rc = RECT()
    if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rc)) == 0:
        return None
    return _rect_to_dict(rc)


def get_client_rect(hwnd: int) -> Optional[Dict[str, int]]:
    if not _is_valid_hwnd(hwnd):
        return None
    rc = RECT()
    if ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rc)) == 0:
        return None
    return _rect_to_dict(rc)


def get_client_origin(hwnd: int) -> Optional[Dict[str, int]]:
    if not _is_valid_hwnd(hwnd):
        return None
    pt = POINT(0, 0)
    if ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt)) == 0:
        return None
    return {"x": int(pt.x), "y": int(pt.y)}


def monitor_info_from_window(hwnd: int) -> Tuple[int, str, Dict[str, int], Dict[str, int]]:
    if sys.platform != "win32" or not hwnd:
        return -1, "", {}, {}
    user32 = ctypes.windll.user32
    MONITOR_DEFAULTTONEAREST = 2
    hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not hmon:
        return -1, "", {}, {}

    info = MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(MONITORINFOEXW)
    if user32.GetMonitorInfoW(hmon, ctypes.byref(info)) == 0:
        return -1, "", {}, {}

    monitors: List[str] = []
    CALLBACK = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(RECT), ctypes.c_double)

    def enum_monitors(hm, _hdc, _lprc, _data):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hm, ctypes.byref(mi)):
            monitors.append(mi.szDevice)
        return 1

    user32.EnumDisplayMonitors(0, 0, CALLBACK(enum_monitors), 0)
    monitor_name = info.szDevice
    monitor_index = monitors.index(monitor_name) if monitor_name in monitors else -1

    return monitor_index, monitor_name, _rect_to_dict(info.rcMonitor), _rect_to_dict(info.rcWork)


def client_to_screen_point(hwnd: int, x: float, y: float) -> Optional[Tuple[int, int]]:
    if not _is_valid_hwnd(hwnd):
        return None
    pt = POINT(int(round(x)), int(round(y)))
    if ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt)) == 0:
        return None
    return int(pt.x), int(pt.y)


def screen_to_client_point(hwnd: int, x: int, y: int) -> Optional[Tuple[int, int]]:
    try:
        if not _is_valid_hwnd(hwnd):
            return None
        pt = POINT(int(x), int(y))
        if ctypes.windll.user32.ScreenToClient(hwnd, ctypes.byref(pt)) == 0:
            return None
        return int(pt.x), int(pt.y)
    except Exception:
        return None


def get_window_geometry(hwnd: int) -> Optional[WindowGeometry]:
    if not _is_valid_hwnd(hwnd):
        return None
    wr = get_window_rect(hwnd)
    cr = get_client_rect(hwnd)
    co = get_client_origin(hwnd)
    if not wr or not cr or not co:
        return None
    midx, mname, mrect, wrect = monitor_info_from_window(hwnd)
    return WindowGeometry(
        hwnd=hwnd,
        window_rect=wr,
        client_rect=cr,
        client_origin=co,
        monitor_index=midx,
        monitor_name=mname,
        monitor_rect=mrect,
        work_rect=wrect,
    )


def ensure_window_ready(hwnd: int) -> bool:
    if not _is_valid_hwnd(hwnd):
        return False
    user32 = ctypes.windll.user32
    try:
        SW_RESTORE = 9
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
            log_event("Okno było zminimalizowane - wykonano SW_RESTORE")
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.08)
        return True
    except Exception:
        return False


# =========================
# WINDOW DISCOVERY
# =========================

def score_window_candidate(candidate: WindowCandidate, cfg: Dict[str, Any]) -> Tuple[float, List[str]]:
    score = 0.0
    reasons: List[str] = []
    title_low = candidate.title.lower()
    kw = (cfg.get("window_keyword") or "").lower().strip()

    if kw and kw in title_low:
        score += 100
        reasons.append("title matches keyword")
    if candidate.process_name in BROWSER_PROCESS_NAMES:
        score += 70
        reasons.append("browser process")
    if "margonem" in title_low:
        score += 60
        reasons.append("title has margonem")
    if "margonem mmorpg" in title_low and bool(cfg.get("target_prefer_game_title", True)):
        score += 180
        reasons.append("exact game title")
    if candidate.process_name in {"python.exe"}:
        score -= 300
        reasons.append("excluded process penalty")
    for ex_kw in (cfg.get("target_exclude_title_keywords") or []):
        if str(ex_kw).strip().lower() and str(ex_kw).strip().lower() in title_low and "margonem" not in title_low:
            score -= 240
            reasons.append(f"excluded title keyword:{ex_kw}")

    client_w = candidate.client_rect["right"] - candidate.client_rect["left"]
    client_h = candidate.client_rect["bottom"] - candidate.client_rect["top"]
    if client_w > 600 and client_h > 400:
        score += 30
        reasons.append("client area sensible")

    mode = cfg.get("window_selection_mode", "auto")
    if mode == "picked":
        if cfg.get("target_pid") and candidate.pid == cfg.get("target_pid"):
            score += 80
            reasons.append("picked pid")
        if cfg.get("target_class_name") and candidate.class_name == cfg.get("target_class_name"):
            score += 20
            reasons.append("picked class")
    if mode == "process":
        p = (cfg.get("target_process_name") or "").lower().strip()
        if p and p == candidate.process_name:
            score += 120
            reasons.append("process mode match")
    if mode == "title":
        t = (cfg.get("target_window_title") or "").lower().strip()
        if t and t in title_low:
            score += 120
            reasons.append("title mode match")

    pref_midx = cfg.get("target_monitor_index", -1)
    if isinstance(pref_midx, int) and pref_midx >= 0 and candidate.monitor_index == pref_midx:
        score += 25
        reasons.append("preferred monitor")

    return score, reasons


def list_window_candidates() -> List[WindowCandidate]:
    if sys.platform != "win32":
        return []

    user32 = ctypes.windll.user32
    candidates: List[WindowCandidate] = []

    CALLBACK = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def handler(hwnd, _lparam):
        hwnd = int(hwnd)
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.IsIconic(hwnd):
            return True

        title = get_window_text(hwnd)
        if not title:
            return True

        wr = get_window_rect(hwnd)
        cr = get_client_rect(hwnd)
        co = get_client_origin(hwnd)
        if not wr or not cr or not co:
            return True

        client_w = cr["right"] - cr["left"]
        client_h = cr["bottom"] - cr["top"]
        if client_w <= 0 or client_h <= 0:
            return True

        pid = get_window_pid(hwnd)
        process_name = get_process_name(pid)
        class_name = get_class_name(hwnd)
        midx, mname, mrect, wrect = monitor_info_from_window(hwnd)

        candidates.append(
            WindowCandidate(
                hwnd=hwnd,
                title=title,
                class_name=class_name,
                pid=pid,
                process_name=process_name,
                rect=wr,
                client_rect=cr,
                client_origin=co,
                monitor_index=midx,
                monitor_name=mname,
                monitor_rect=mrect,
                work_rect=wrect,
            )
        )
        return True

    user32.EnumWindows(CALLBACK(handler), 0)

    with config_lock:
        cfg = dict(config)
    for c in candidates:
        c.score, c.reasons = score_window_candidate(c, cfg)

    candidates.sort(key=lambda c: c.score, reverse=True)
    runtime_state["last_candidates"] = [asdict(c) for c in candidates]
    return candidates


def find_best_target_window() -> Optional[WindowCandidate]:
    candidates = list_window_candidates()
    if not candidates:
        return None
    best = candidates[0]
    runtime_state["last_selected_candidate"] = asdict(best)
    return best


def resolve_target_window() -> Optional[int]:
    with config_lock:
        cfg = dict(config)

    hwnd_saved = int(cfg.get("target_hwnd_last") or 0)
    pid_saved = int(cfg.get("target_pid") or 0)

    required_keywords = [str(x).lower() for x in (cfg.get("target_title_required_keywords") or []) if str(x).strip()]
    excluded_proc = {str(x).lower() for x in (cfg.get("target_exclude_process_names") or []) if str(x).strip()}
    excluded_title = [str(x).lower() for x in (cfg.get("target_exclude_title_keywords") or []) if str(x).strip()]
    def _game_like(hwnd: int) -> bool:
        title = get_window_text(hwnd).lower()
        proc = get_process_name(get_window_pid(hwnd)).lower()
        if proc in excluded_proc:
            return False
        if any(k in title for k in excluded_title) and "margonem" not in title:
            return False
        return all(k in title for k in required_keywords) if required_keywords else ("margonem" in title)

    if hwnd_saved and _is_valid_hwnd(hwnd_saved):
        if (not pid_saved or get_window_pid(hwnd_saved) == pid_saved) and _game_like(hwnd_saved):
            return hwnd_saved

    if pid_saved:
        for candidate in list_window_candidates():
            if candidate.pid == pid_saved and _is_valid_hwnd(candidate.hwnd):
                with config_lock:
                    config["target_hwnd_last"] = candidate.hwnd
                return candidate.hwnd

    best = find_best_target_window()
    if not best:
        return None

    with config_lock:
        config["target_hwnd_last"] = best.hwnd
        config["target_pid"] = best.pid
        config["target_process_name"] = best.process_name
        config["target_window_title"] = best.title
        config["target_class_name"] = best.class_name
        config["target_monitor_name"] = best.monitor_name
        config["target_monitor_index"] = best.monitor_index
    return best.hwnd


def pick_window_under_cursor() -> Optional[WindowCandidate]:
    if sys.platform != "win32":
        return None

    time.sleep(3.0)
    user32 = ctypes.windll.user32
    pt = POINT()
    if user32.GetCursorPos(ctypes.byref(pt)) == 0:
        return None
    hwnd = user32.WindowFromPoint(pt)
    if not hwnd:
        return None

    hwnd = user32.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT

    all_candidates = list_window_candidates()
    for c in all_candidates:
        if c.hwnd == hwnd:
            with config_lock:
                config["window_selection_mode"] = "picked"
                config["target_hwnd_last"] = c.hwnd
                config["target_pid"] = c.pid
                config["target_process_name"] = c.process_name
                config["target_window_title"] = c.title
                config["target_class_name"] = c.class_name
                config["target_monitor_name"] = c.monitor_name
                config["target_monitor_index"] = c.monitor_index
            save_settings_to_disk()
            return c
    return None


# =========================
# CLICK EXECUTION
# =========================

def _make_lparam(client_x: int, client_y: int) -> int:
    return ((client_y & 0xFFFF) << 16) | (client_x & 0xFFFF)


def _background_click_target(hwnd: int, client_x: int, client_y: int) -> Tuple[int, int, int]:
    try:
        screen = client_to_screen_point(hwnd, client_x, client_y)
        if not screen:
            return hwnd, client_x, client_y
        user32 = ctypes.windll.user32
        pt = POINT(int(screen[0]), int(screen[1]))
        child = int(user32.WindowFromPoint(pt))
        GA_ROOT = 2
        if child and _is_valid_hwnd(child) and int(user32.GetAncestor(child, GA_ROOT)) == int(hwnd):
            child_pt = POINT(int(screen[0]), int(screen[1]))
            if user32.ScreenToClient(child, ctypes.byref(child_pt)) != 0:
                return child, int(child_pt.x), int(child_pt.y)
    except Exception:
        pass
    return hwnd, client_x, client_y


def send_background_click(hwnd: int, client_x: int, client_y: int, hold_ms: Optional[int] = None) -> bool:
    if not _is_valid_hwnd(hwnd):
        return False
    try:
        user32 = ctypes.windll.user32
        with config_lock:
            hold_min = int(config.get("click_hold_ms_min", 60))
            hold_max = int(config.get("click_hold_ms_max", 130))
            disable_randomness = bool(config.get("disable_randomness", False))

        if hold_max < hold_min:
            hold_min, hold_max = hold_max, hold_min
        if hold_ms is not None:
            real_hold = max(1, int(hold_ms))
        elif disable_randomness:
            real_hold = max(1, hold_min)
        else:
            real_hold = random.randint(max(1, hold_min), max(1, hold_max))

        WM_MOUSEMOVE = 0x0200
        WM_LBUTTONDOWN = 0x0201
        WM_LBUTTONUP = 0x0202
        MK_LBUTTON = 0x0001
        target_hwnd, tx, ty = _background_click_target(hwnd, client_x, client_y)
        lparam = _make_lparam(tx, ty)
        user32.PostMessageW(target_hwnd, WM_MOUSEMOVE, 0, lparam)
        user32.PostMessageW(target_hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
        time.sleep(real_hold / 1000.0)
        user32.PostMessageW(target_hwnd, WM_LBUTTONUP, 0, lparam)
        return True
    except Exception as e:
        log_event(f"Błąd wirtualnej myszki (SendMessage): {e}")
        return False


def perform_click(screen_x: int, screen_y: int, debug_label: str = "") -> bool:
    with config_lock:
        disable_randomness = bool(config.get("disable_randomness", False))

    fx = float(screen_x)
    fy = float(screen_y)
    if not disable_randomness:
        fx += random.uniform(-3, 3)
        fy += random.uniform(-2, 2)

    duration = 0.0 if disable_randomness else random.uniform(0.12, 0.26)
    pyautogui.moveTo(fx, fy, duration)
    pyautogui.click()
    return True


def click_in_game(client_x: float, client_y: float, label: str = "api", use_manual_offset: bool = True, is_answer_click: bool = False) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    with config_lock:
        cfg = dict(config)

    hwnd = resolve_target_window() if cfg.get("use_client_area", True) else None
    if not hwnd:
        return False, "NO_TARGET_WINDOW", None

    use_virtual_mouse = bool(cfg.get("use_virtual_mouse", False))
    allow_physical_fallback = bool(cfg.get("allow_physical_click_fallback", False))
    if ctypes.windll.user32.IsIconic(hwnd):
        if use_virtual_mouse:
            return False, "WINDOW_MINIMIZED", None
        ensure_window_ready(hwnd)
    elif cfg.get("restore_window_before_click", False) and not use_virtual_mouse:
        ensure_window_ready(hwnd)

    geom = get_window_geometry(hwnd)
    if not geom:
        return False, "NO_GEOMETRY", None

    cw = geom.client_rect["right"] - geom.client_rect["left"]
    ch = geom.client_rect["bottom"] - geom.client_rect["top"]

    # Konwersja ułamków na piksele okna
    if 0.0 <= client_x <= 1.0 and 0.0 <= client_y <= 1.0:
        client_x = cw * client_x
        client_y = ch * client_y

    # Aplikowanie offsetów po konwersji
    if use_manual_offset and cfg.get("manual_offset_enabled", True):
        client_y += float(cfg.get("manual_offset_y", 0.0))
    if is_answer_click and cfg.get("answer_offset_enabled", False):
        client_y += float(cfg.get("answer_offset_y", 0.0))

    cx = max(0, min(int(round(client_x)), max(0, cw - 1)))
    cy = max(0, min(int(round(client_y)), max(0, ch - 1)))

    scr = client_to_screen_point(hwnd, cx, cy)
    if not scr:
        sx = geom.client_origin["x"] + cx
        sy = geom.client_origin["y"] + cy
    else:
        sx, sy = scr

    disable_randomness = bool(cfg.get("disable_randomness", False))
    jitter_px = max(0, int(cfg.get("click_jitter_px", 3)))

    if use_virtual_mouse and jitter_px > 0 and not disable_randomness:
        cx = max(0, min(cx + random.randint(-jitter_px, jitter_px), max(0, cw - 1)))
        cy = max(0, min(cy + random.randint(-jitter_px, jitter_px), max(0, ch - 1)))

    if use_virtual_mouse:
        click_ok = send_background_click(hwnd, cx, cy)
        if not click_ok and allow_physical_fallback:
            log_event("Fallback: wirtualna myszka nieudana, używam pyautogui")
            click_ok = perform_click(sx, sy, debug_label=label)
        elif not click_ok:
            return False, "BACKGROUND_CLICK_FAILED", None
    else:
        click_ok = perform_click(sx, sy, debug_label=label)

    payload = {
        "timestamp": time.time(),
        "label": label,
        "hwnd": hwnd,
        "client_x": cx,
        "client_y": cy,
        "screen_x": int(sx),
        "screen_y": int(sy),
        "monitor": geom.monitor_name,
        "monitor_index": geom.monitor_index,
        "client_size": {"width": cw, "height": ch},
    }
    runtime_state["last_click"] = payload
    runtime_state["click_history"].append(payload)
    return click_ok, "OK", payload


# =========================
# SCREENSHOT / OVERLAYS / DIAGNOSTYKA
# =========================

def capture_client_image(hwnd: int) -> Optional[Any]:
    geom = get_window_geometry(hwnd)
    if not geom:
        return None
    cw = geom.client_rect["right"] - geom.client_rect["left"]
    ch = geom.client_rect["bottom"] - geom.client_rect["top"]
    ox, oy = geom.client_origin["x"], geom.client_origin["y"]
    if cw <= 0 or ch <= 0:
        return None
    try:
        from PIL import ImageGrab
        return ImageGrab.grab(bbox=(ox, oy, ox + cw, oy + ch), all_screens=True)
    except Exception as exc:
        log_event(f"ImageGrab capture failed: {exc}")
    if mss is not None and Image is not None:
        try:
            with mss.mss() as sct:
                shot = sct.grab({"left": ox, "top": oy, "width": cw, "height": ch})
                return Image.frombytes("RGB", shot.size, shot.rgb)
        except Exception as exc:
            log_event(f"MSS capture failed: {exc}")
    if pyautogui is None:
        return None
    try:
        return pyautogui.screenshot(region=(ox, oy, cw, ch))
    except Exception as exc:
        log_event(f"PyAutoGUI capture failed: {exc}")
        return None


def capture_client_area(hwnd: int, save_debug_file: bool = True) -> Optional[Path]:
    image = capture_client_image(hwnd)
    if image is None:
        return None
    ensure_data_dirs()
    if save_debug_file and should_save_debug_screenshots(config):
        out_path = DATA_DIR / "screenshots" / f"client_area_{int(time.time())}.jpg"
    else:
        out_path = DATA_DIR / "captures" / "raw" / "_client_area_work.jpg"
    return save_screenshot_image(image, out_path)


def capture_client_pil(hwnd: int) -> Optional[Any]:
    geom = get_window_geometry(hwnd)
    if not geom or pyautogui is None:
        return None
    cw = geom.client_rect["right"] - geom.client_rect["left"]
    ch = geom.client_rect["bottom"] - geom.client_rect["top"]
    ox, oy = geom.client_origin["x"], geom.client_origin["y"]
    if cw <= 0 or ch <= 0:
        return None
    image = capture_client_image(hwnd)
    if image is None:
        return None
    if should_save_debug_screenshots(config):
        debug_path = DATA_DIR / "debug" / f"vision_precaptcha_raw_{int(time.time())}.jpg"
        debug_path = save_screenshot_image(image, debug_path)
        log_event(f"Vision capture client_origin=({ox},{oy}) client_size=({cw}x{ch}) raw={debug_path}")
    else:
        log_event(f"Vision capture client_origin=({ox},{oy}) client_size=({cw}x{ch})")
    return image


def is_bad_capture(image: Any) -> Dict[str, Any]:
    if image is None or np is None:
        return {"is_bad": True, "brightness": 0.0, "variance": 0.0}
    if not hasattr(image, "size") or image.size[0] <= 0 or image.size[1] <= 0:
        return {"is_bad": True, "brightness": 0.0, "variance": 0.0}
    arr = np.array(image.convert("L")) if hasattr(image, "convert") else np.array(image)
    brightness = float(arr.mean()) if arr.size else 0.0
    variance = float(arr.var()) if arr.size else 0.0
    is_bad = brightness < 5.0 or variance < 2.0
    return {"is_bad": is_bad, "brightness": round(brightness, 3), "variance": round(variance, 3)}


def capture_client_area_robust(hwnd: int) -> Dict[str, Any]:
    ensure_data_dirs()
    hwnd = resolve_target_window() or hwnd
    time.sleep(0.15)
    geom = get_window_geometry(hwnd)
    if not geom:
        return {"ok": False, "status": "NO_GEOMETRY"}
    ox, oy = geom.client_origin["x"], geom.client_origin["y"]
    cw = geom.client_rect["right"] - geom.client_rect["left"]
    ch = geom.client_rect["bottom"] - geom.client_rect["top"]
    methods = []
    debug_capture = bool(config.get("vision_debug", False))
    mss_monitors = []
    if debug_capture and mss is not None:
        try:
            with mss.mss() as sct:
                mss_monitors = [dict(m) for m in sct.monitors]
        except Exception:
            mss_monitors = []
    if debug_capture:
        log_event(
            f"capture_client_area_robust hwnd={hwnd} title='{get_window_text(hwnd)}' monitor={geom.monitor_name} idx={geom.monitor_index} "
            f"monitor_rect={geom.monitor_rect} client_origin={geom.client_origin} client_size=({cw}x{ch}) mss_monitors={mss_monitors}"
        )
    if mss is not None:
        methods.append("mss")
    methods = ["imagegrab", *methods, "pyautogui", "full_desktop_crop"]
    for method in methods:
        image = None
        try:
            if method == "mss" and mss is not None and Image is not None:
                with mss.mss() as sct:
                    shot = sct.grab({"left": ox, "top": oy, "width": cw, "height": ch})
                    image = Image.frombytes("RGB", shot.size, shot.rgb)
            elif method == "imagegrab":
                from PIL import ImageGrab
                image = ImageGrab.grab(bbox=(ox, oy, ox + cw, oy + ch), all_screens=True)
            elif method == "pyautogui" and pyautogui is not None:
                image = pyautogui.screenshot(region=(ox, oy, cw, ch))
            elif method == "full_desktop_crop":
                image = capture_by_full_desktop_crop(hwnd)
        except Exception as exc:
            log_event(f"Capture method {method} failed: {exc}")
        quality = is_bad_capture(image) if image is not None else {"is_bad": True, "brightness": 0.0, "variance": 0.0}
        if not quality["is_bad"]:
            runtime_state["capture_method"] = method
            runtime_state["capture_quality"] = quality
            return {"ok": True, "image": image, "method": method, "quality": quality}
        if debug_capture:
            log_event(f"Capture method {method} produced bad frame: {quality}")
    return {"ok": False, "status": "CAPTURE_BLACK", "message": "Screenshot czarny. Wyłącz akcelerację sprzętową w Brave/Chrome: Ustawienia → System → Użyj akceleracji sprzętowej → OFF, potem restart przeglądarki."}


def capture_by_full_desktop_crop(hwnd: int) -> Optional[Any]:
    if Image is None:
        return None
    geom = get_window_geometry(hwnd)
    if not geom:
        return None
    ox, oy = geom.client_origin["x"], geom.client_origin["y"]
    cw = geom.client_rect["right"] - geom.client_rect["left"]
    ch = geom.client_rect["bottom"] - geom.client_rect["top"]
    if cw <= 0 or ch <= 0:
        return None
    try:
        from PIL import ImageGrab
        return ImageGrab.grab(bbox=(ox, oy, ox + cw, oy + ch), all_screens=True)
    except Exception:
        if pyautogui is None:
            return None
        full = pyautogui.screenshot()
        return full.crop((ox, oy, ox + cw, oy + ch))


def validate_click_coordinate_pipeline(hwnd: int, client_x: float, client_y: float) -> Dict[str, Any]:
    screen_pt = client_to_screen_point(hwnd, client_x, client_y)
    if not screen_pt:
        return {"ok": False, "status": "CLIENT_TO_SCREEN_FAILED"}
    roundtrip = screen_to_client_point(hwnd, int(screen_pt[0]), int(screen_pt[1]))
    if not roundtrip:
        return {"ok": False, "status": "SCREEN_TO_CLIENT_FAILED"}
    dx = int(roundtrip[0] - int(round(client_x)))
    dy = int(roundtrip[1] - int(round(client_y)))
    return {
        "input_client": {"x": int(round(client_x)), "y": int(round(client_y))},
        "screen": {"x": int(screen_pt[0]), "y": int(screen_pt[1])},
        "roundtrip_client": {"x": int(roundtrip[0]), "y": int(roundtrip[1])},
        "delta": {"x": dx, "y": dy},
        "ok": abs(dx) <= 2 and abs(dy) <= 2,
    }


def _image_hash(image: Any) -> str:
    if imagehash is not None and Image is not None:
        try:
            return str(imagehash.phash(image))
        except Exception:
            pass
    small = image.convert("L").resize((32, 32))
    return hashlib.md5(small.tobytes()).hexdigest()


def _hash_distance(a: str, b: str) -> int:
    if not a or not b:
        return 999
    if len(a) == len(b) and all(c in "0123456789abcdef" for c in a.lower()+b.lower()):
        return sum(ch1 != ch2 for ch1, ch2 in zip(a.lower(), b.lower()))
    return 0 if a == b else 999


def _boxes_changed(prev_boxes: List[Dict[str, Any]], boxes: List[Dict[str, Any]], delta: int) -> bool:
    if len(prev_boxes) != len(boxes):
        return True
    for pb, cb in zip(prev_boxes, boxes):
        for k in ("x", "y", "w", "h"):
            if abs(int(pb.get(k, 0)) - int(cb.get(k, 0))) > delta:
                return True
    return False


def should_save_sample(image: Any, kind: str, boxes: List[Dict[str, Any]], metadata: Dict[str, Any]) -> Tuple[bool, str, str]:
    image_hash = _image_hash(image)
    now = time.time()
    threshold = int(config.get("dataset_min_seconds_between_duplicates", 600))
    box_delta = int(config.get("dataset_box_delta_px", 8))
    hash_delta = int(config.get("dataset_hash_distance_threshold", 6))
    for row in reversed(runtime_state.get("dataset_index", [])):
        if row.get("kind") != kind:
            continue
        elapsed = now - float(row.get("_ts", now))
        if elapsed >= threshold:
            return True, "min_interval_elapsed", image_hash
        if row.get("ocr_texts") != metadata.get("ocr_texts"):
            return True, "ocr_changed", image_hash
        if _boxes_changed(row.get("boxes", []), boxes, box_delta):
            return True, "boxes_changed", image_hash
        if row.get("client_size") != metadata.get("client_size"):
            return True, "client_size_changed", image_hash
        if row.get("monitor_index") != metadata.get("monitor_index") or row.get("monitor_rect") != metadata.get("monitor_rect"):
            return True, "monitor_changed", image_hash
        if row.get("detection_method") != metadata.get("detection_method"):
            return True, "detection_method_changed", image_hash
        if _hash_distance(str(row.get("image_hash", "")), image_hash) > hash_delta:
            return True, "hash_changed", image_hash
        return False, "duplicate_interval", image_hash
    return True, "first_of_kind", image_hash


def save_dataset_sample_deduped(image: Any, kind: str, boxes: List[Dict[str, Any]], metadata: Dict[str, Any]) -> Dict[str, Any]:
    if not bool(config.get("vision_dataset_enabled", False)):
        return {"ok": False, "status": "DATASET_DISABLED"}
    ensure_data_dirs()
    ok, reason, image_hash = should_save_sample(image, kind, boxes, metadata)
    if not ok:
        return {"ok": False, "status": "DEDUPED"}
    ts = datetime.utcnow()
    stamp = ts.strftime("%Y%m%d_%H%M%S_") + f"{int(ts.microsecond/1000):03d}"
    img_path = DATA_DIR / "dataset" / "images" / kind / f"{stamp}_{kind}_ok_{metadata.get('capture_method','unknown')}.jpg"
    lbl_path = DATA_DIR / "dataset" / "labels" / kind / f"{img_path.stem}.txt"
    img_path = save_screenshot_image(image, img_path)
    iw, ih = image.size
    class_map = {"precaptcha": 0, "answers": 1, "confirm": 2, "unknown": 1}
    lines = []
    for b in boxes:
        cx = (float(b["x"]) + float(b["w"]) / 2.0) / iw
        cy = (float(b["y"]) + float(b["h"]) / 2.0) / ih
        bw = float(b["w"]) / iw
        bh = float(b["h"]) / ih
        lines.append(f"{class_map.get(kind,1)} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
    lbl_path.write_text("\n".join(lines), encoding="utf-8")
    index_row = {"timestamp": ts.isoformat(), "kind": kind, "image_path": str(img_path), "label_path": str(lbl_path), "image_hash": image_hash, "client_size": metadata.get("client_size", {}), "boxes": boxes, "capture_method": metadata.get("capture_method"), "detection_method": metadata.get("detection_method"), "saved_reason": reason, "ocr_texts": metadata.get("ocr_texts", []), "monitor_index": metadata.get("monitor_index"), "monitor_rect": metadata.get("monitor_rect"), "_ts": time.time()}
    with (DATA_DIR / "dataset" / "index.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(index_row, ensure_ascii=False) + "\n")
    with (DATA_DIR / "dataset" / "metadata.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({**index_row, **metadata}, ensure_ascii=False) + "\n")
    runtime_state["dataset_index"].append(index_row)
    runtime_state["last_dataset_event"] = {"kind": kind, "status": "SAVED", "image_path": str(img_path), "reason": reason}
    runtime_state["last_saved_by_kind"][kind] = str(img_path)
    return {"ok": True, "status": "SAVED", "image_path": str(img_path), "label_path": str(lbl_path), "reason": reason}


MOJIBAKE_REPLACEMENTS = {
    "\u00c4\u2026": "a",
    "\u00c4\u2021": "c",
    "\u00c4\u2122": "e",
    "\u0139\u201a": "l",
    "\u0139\u201e": "n",
    "\u0102\u0142": "o",
    "\u0139\u203a": "s",
    "\u0139\u017a": "z",
    "\u0139\u013d": "z",
}


def normalize_vision_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    for src, dst in MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(src, dst)
    text = text.replace("\u0142", "l").replace("\u0141", "l")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split())


def _point_in_region(cx: int, cy: int, region: Optional[Dict[str, int]]) -> bool:
    if not region:
        return True
    x = int(region.get("x", 0))
    y = int(region.get("y", 0))
    w = int(region.get("w", 0))
    h = int(region.get("h", 0))
    return x <= cx <= x + w and y <= cy <= y + h


def find_green_button_by_cv(image: Any, search_region: Optional[Dict[str, int]] = None, method: str = "green_button_cv") -> Dict[str, Any]:
    if cv2 is None or np is None or image is None:
        return {"found": False, "method": method, "reason": "MISSING_DEPS"}
    arr = np.array(image)
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([35, 40, 40]), np.array([90, 255, 255]))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h_img, w_img = mask.shape[:2]
    try:
        ignore_right_ratio = float(config.get("vision_ignore_right_panel_ratio", 0.84))
    except Exception:
        ignore_right_ratio = 0.84
    ignore_right_x = int(w_img * ignore_right_ratio) if 0.1 < ignore_right_ratio < 1.0 else w_img + 1
    best = None
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if not (70 <= w <= 220 and 20 <= h <= 60):
            continue
        center_x, center_y = x + w // 2, y + h // 2
        if center_x >= ignore_right_x:
            continue
        if not _point_in_region(center_x, center_y, search_region):
            continue
        ratio = w / max(1.0, float(h))
        if ratio < 2.0 or ratio > 7.5:
            continue
        roi = mask[y:y + h, x:x + w]
        green_ratio = float(cv2.countNonZero(roi)) / float(max(1, w * h))
        y_bonus = 0.15 if y < (h_img * 0.55) else 0.0
        score = green_ratio + y_bonus + min(w / 220.0, 1.0) * 0.1
        cand = {"found": True, "method": method, "x": x, "y": y, "w": w, "h": h, "center_x": center_x, "center_y": center_y, "score": round(score, 4)}
        if best is None or cand["score"] > best["score"]:
            best = cand
    return best or {"found": False, "method": method}


def find_text_button_by_ocr(image: Any, text: str = "Rozwiąż teraz") -> Dict[str, Any]:
    if pytesseract is None or np is None:
        return {"found": False, "method": "ocr", "reason": "OCR_UNAVAILABLE"}
    try:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        target_a = normalize_vision_text(text)
        target_b = "rozwiaz teraz"
        for i in range(len(data.get("text", []))):
            token = normalize_vision_text(data["text"][i])
            if not token:
                continue
            if "rozwiaz" in token or "teraz" in token:
                full = token
                if i + 1 < len(data["text"]):
                    full = normalize_vision_text(f"{token} {data['text'][i + 1]}")
                if target_a in full or target_b in full or ("rozwiaz" in full and "teraz" in full):
                    x, y, w, h = int(data["left"][i]), int(data["top"][i]), int(data["width"][i]), int(data["height"][i])
                    return {"found": True, "method": "ocr", "x": x, "y": y, "w": w, "h": h, "center_x": x + w // 2, "center_y": y + h // 2, "score": 0.6}
    except Exception as exc:
        return {"found": False, "method": "ocr", "reason": str(exc)}
    return {"found": False, "method": "ocr"}


def find_text_regions(image: Any, phrases: List[str]) -> List[Dict[str, Any]]:
    if pytesseract is None:
        return []
    out = []
    try:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        tokens = [str(t or "").strip() for t in data.get("text", [])]
        norm_phrases = [normalize_vision_text(p) for p in phrases]
        for i in range(len(tokens)):
            for span in (2, 3, 4):
                if i + span > len(tokens):
                    continue
                frag = " ".join(tokens[i:i + span]).lower()
                frag_norm = normalize_vision_text(frag)
                if any(p in frag_norm for p in norm_phrases):
                    x = min(int(data["left"][j]) for j in range(i, i + span))
                    y = min(int(data["top"][j]) for j in range(i, i + span))
                    r = max(int(data["left"][j]) + int(data["width"][j]) for j in range(i, i + span))
                    b = max(int(data["top"][j]) + int(data["height"][j]) for j in range(i, i + span))
                    out.append({"text": frag, "x": x, "y": y, "w": r - x, "h": b - y, "center_x": (x + r) // 2, "center_y": (y + b) // 2})
    except Exception:
        return []
    return out


def find_precaptcha_panel_by_text(image: Any) -> Optional[Dict[str, Any]]:
    regions = find_text_regions(image, ["Zagadka pojawi się za"])
    if not regions:
        return None
    r = max(regions, key=lambda x: x["w"] * x["h"])
    m = 20
    return {"x": max(0, r["x"] - m), "y": max(0, r["y"] - m), "w": r["w"] + m * 2, "h": r["h"] + 90, "text_region": r}


def is_captcha_challenge_visible(image: Any) -> bool:
    challenge_regions = find_text_regions(image, [
        "zaznacz wszystkie",
        "liczba pozostalych",
        "milego dnia",
    ])
    if challenge_regions:
        return True
    try:
        layout = revive_rejected_quiz_layout(image, find_quiz_layout_by_cv(image))
        return bool(layout.get("answers"))
    except Exception:
        return False


def build_precaptcha_green_search_region(image: Any) -> Optional[Dict[str, int]]:
    if image is None or not hasattr(image, "size"):
        return None
    w_img, h_img = image.size
    return {
        "x": int(w_img * 0.20),
        "y": int(h_img * 0.05),
        "w": int(w_img * 0.62),
        "h": int(h_img * 0.40),
    }


def validate_precaptcha_green_candidate(image: Any, candidate: Dict[str, Any]) -> bool:
    if image is None or not candidate.get("found") or not hasattr(image, "size"):
        return False
    w_img, h_img = image.size
    x = int(candidate.get("x", 0))
    y = int(candidate.get("y", 0))
    w = int(candidate.get("w", 0))
    h = int(candidate.get("h", 0))
    cx = int(candidate.get("center_x", x + w // 2))
    cy = int(candidate.get("center_y", y + h // 2))
    if not (w_img * 0.32 <= cx <= w_img * 0.68 and h_img * 0.08 <= cy <= h_img * 0.30):
        return False
    if not (85 <= w <= 150 and 18 <= h <= 36):
        return False
    panel = image.crop((
        max(0, x - 50),
        max(0, y - 42),
        min(w_img, x + w + 50),
        min(h_img, y + h + 28),
    ))
    try:
        stat = is_bad_capture(panel)
        gray = np.array(panel.convert("L")) if np is not None else None
        if gray is None:
            return True
        brightness = float(gray.mean()) if gray.size else 255.0
        dark_ratio = float((gray < 85).sum()) / float(max(1, gray.size))
        return brightness < 115.0 and dark_ratio > 0.35 and not stat.get("is_bad", True)
    except Exception:
        return True


def find_pre_captcha_button(hwnd: int) -> Dict[str, Any]:
    cap = capture_client_area_robust(hwnd)
    image = cap.get("image")
    if image is None:
        return {"found": False, "status": "CAPTURE_FAILED"}
    with config_lock:
        button_text = str(config.get("pre_captcha_button_text", "Rozwiąż teraz"))
        templates_dir = str(config.get("vision_templates_dir", "templates")).strip() or "templates"
        debug_save = bool(config.get("vision_debug_save", True))
        green_fallback_enabled = bool(config.get("pre_captcha_green_fallback_enabled", True))
    panel = find_precaptcha_panel_by_text(image)
    challenge_visible = is_captcha_challenge_visible(image)
    result = {"found": False, "method": "none"}
    if panel:
        crop = image.crop((panel["x"], panel["y"], panel["x"] + panel["w"], panel["y"] + panel["h"]))
        regs = find_text_regions(crop, ["Rozwiąż teraz", "Rozwiaz teraz"])
        if regs:
            rr = regs[0]
            result = {"found": True, "method": "ocr_panel", "x": panel["x"] + rr["x"], "y": panel["y"] + rr["y"], "w": rr["w"], "h": rr["h"], "center_x": panel["x"] + rr["center_x"], "center_y": panel["y"] + rr["center_y"], "score": 0.8, "panel": panel}
    if not result.get("found"):
        point = find_template_in_client(hwnd, "rozwiaz_teraz.png")
        if point:
            result = {"found": True, "method": "template", "center_x": point[0], "center_y": point[1], "x": point[0] - 45, "y": point[1] - 15, "w": 90, "h": 30, "score": 0.5}
    if not result.get("found") and green_fallback_enabled and not challenge_visible:
        result = find_green_button_by_cv(
            image,
            search_region=build_precaptcha_green_search_region(image),
            method="green_button_cv_precaptcha",
        )
        if result.get("found") and not validate_precaptcha_green_candidate(image, result):
            result = {"found": False, "method": "green_button_cv_precaptcha", "status": "GREEN_CANDIDATE_REJECTED"}
    elif not result.get("found") and challenge_visible:
        result = {"found": False, "method": "challenge_visible", "status": "CAPTCHA_CHALLENGE_VISIBLE"}
    if result.get("found") and debug_save and ImageDraw is not None:
        out_path = DATA_DIR / "debug" / f"vision_precaptcha_detected_{int(time.time())}.jpg"
        vis = image.copy()
        draw = ImageDraw.Draw(vis)
        x, y, w, h = int(result["x"]), int(result["y"]), int(result["w"]), int(result["h"])
        draw.rectangle([x, y, x + w, y + h], outline="red", width=3)
        save_screenshot_image(vis, out_path)
        result["debug_detected_path"] = str(out_path)
        log_event(f"Vision detected rectangle=({x},{y},{w},{h}) center=({result['center_x']},{result['center_y']}) method={result.get('method')}")
    runtime_state["last_match"] = result
    return result


def click_pre_captcha_button() -> Dict[str, Any]:
    hwnd = resolve_target_window()
    if not hwnd:
        return {"ok": False, "status": "NO_TARGET_WINDOW"}
    detected = find_pre_captcha_button(hwnd)
    geom = get_window_geometry(hwnd)
    debug_paths: List[str] = []
    client_size = None
    client_origin = None
    if geom:
        client_size = {
            "width": geom.client_rect["right"] - geom.client_rect["left"],
            "height": geom.client_rect["bottom"] - geom.client_rect["top"],
        }
        client_origin = dict(geom.client_origin)
    if detected.get("debug_detected_path"):
        debug_paths.append(str(detected.get("debug_detected_path")))
    if detected.get("found"):
        cap = capture_client_area_robust(hwnd)
        if cap.get("image"):
            box=[{k: detected[k] for k in ("x","y","w","h") if k in detected}]
            meta = build_capture_metadata(hwnd, cap, "precaptcha", box, [str(config.get("pre_captcha_button_text","Rozwiąż teraz"))], str(detected.get("method","unknown")))
            dbg = maybe_save_debug_detected(cap.get("image"), "precaptcha", box)
            if dbg: meta["debug_detected_path"] = dbg
            save_dataset_sample_deduped(cap["image"], "precaptcha", box, meta)
        mode = str(config.get("vision_click_mode", "absolute")).strip().lower()
        if mode == "absolute":
            click_result = click_detected_box(hwnd, detected, "vision_pre_captcha")
            ok, msg, payload = click_result["ok"], click_result.get("status", "OK"), click_result.get("click_payload")
        else:
            ok, msg, payload = click_in_game(detected["center_x"], detected["center_y"], label="vision_pre_captcha", use_manual_offset=False, is_answer_click=False)
        post_click_result = None
        if ok:
            runtime_state["watcher_state"] = "PRECAPTCHA_CLICKED"
            log_event("After precaptcha click: scanning answers...")
            time.sleep(random.uniform(0.3, 0.8))
            if bool(config.get("vision_auto_solve_captcha", True)):
                post_click_result = solve_visible_captcha_until_clear(hwnd)
            else:
                post_click_result = find_captcha_answers(hwnd)
        log_event(f"Ostatni click payload: {payload}")
        return {
            "ok": ok,
            "method": detected.get("method", "vision"),
            "status": msg,
            "match": detected,
            "click_payload": payload,
            "client_origin": client_origin,
            "client_size": client_size,
            "debug_paths": debug_paths,
            "post_click_result": post_click_result,
        }
        
    if not geom:
        return {"ok": False, "method": "vision_pre_captcha", "status": "NO_GEOMETRY", "match": detected, "click_payload": None, "debug_paths": debug_paths}
    return {
        "ok": False,
        "method": "vision_pre_captcha",
        "status": "NOT_FOUND",
        "match": detected,
        "click_payload": None,
        "client_origin": client_origin,
        "client_size": client_size,
        "debug_paths": debug_paths,
    }


def click_detected_box(hwnd: int, box: Dict[str, Any], label: str) -> Dict[str, Any]:
    cx = int(round(float(box.get("center_x", 0))))
    cy = int(round(float(box.get("center_y", 0))))
    geo = validate_click_coordinate_pipeline(hwnd, cx, cy)
    if not geo.get("ok"):
        return {"ok": False, "status": "GEOMETRY_MISMATCH", "geometry": geo}
    sx, sy = geo["screen"]["x"], geo["screen"]["y"]
    with config_lock:
        use_virtual = bool(config.get("use_virtual_mouse", True))
        allow_physical_fallback = bool(config.get("allow_physical_click_fallback", False))
    method = "vision_background"
    if use_virtual:
        ok = send_background_click(hwnd, cx, cy)
        if not ok and allow_physical_fallback:
            method = "vision_absolute_fallback"
            ok = perform_click(sx, sy, debug_label=label)
    else:
        method = "vision_absolute"
        ok = perform_click(sx, sy, debug_label=label)
    payload = {"client_x": cx, "client_y": cy, "screen_x": sx, "screen_y": sy, "method": method, "label": label}
    runtime_state["last_click"] = payload
    return {"ok": ok, "status": "OK" if ok else "CLICK_FAILED", "click_payload": payload, "geometry": geo}




def build_capture_metadata(hwnd: int, cap: Dict[str, Any], kind: str, boxes: List[Dict[str, Any]], ocr_texts: List[str], detection_method: str, click_payload: Optional[Dict[str, Any]] = None, saved_reason: str = "") -> Dict[str, Any]:
    geom = get_window_geometry(hwnd)
    image = cap.get("image")
    brightness = variance = None
    if image is not None and Image is not None:
        try:
            gray = image.convert("L")
            data = list(gray.getdata())
            if data:
                brightness = float(sum(data) / len(data))
                mean = brightness
                variance = float(sum((x - mean) ** 2 for x in data) / len(data))
        except Exception:
            pass
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "kind": kind,
        "client_size": {"width": image.size[0], "height": image.size[1]} if image is not None else {},
        "monitor_index": geom.monitor_index if geom else None,
        "monitor_rect": geom.monitor_rect if geom else {},
        "client_origin": geom.client_origin if geom else {},
        "boxes": boxes,
        "ocr_texts": ocr_texts,
        "capture_method": cap.get("method"),
        "detection_method": detection_method,
        "brightness": brightness,
        "variance": variance,
        "click_payload": click_payload,
        "watcher_state": runtime_state.get("watcher_state"),
        "saved_reason": saved_reason,
    }


def maybe_save_debug_detected(image: Any, kind: str, boxes: List[Dict[str, Any]]) -> Optional[str]:
    if ImageDraw is None or image is None:
        return None
    if not should_save_debug_screenshots(config):
        return None
    out = DATA_DIR / "captures" / "detected" / f"{int(time.time()*1000)}_{kind}_detected.jpg"
    vis = image.copy()
    d = ImageDraw.Draw(vis)
    for b in boxes:
        x,y,w,h = int(b.get("x",0)),int(b.get("y",0)),int(b.get("w",0)),int(b.get("h",0))
        d.rectangle([x,y,x+w,y+h], outline="red", width=3)
    return str(save_screenshot_image(vis, out))


def _rect_iou(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    ax1, ay1 = int(a.get("x", 0)), int(a.get("y", 0))
    ax2, ay2 = ax1 + int(a.get("w", 0)), ay1 + int(a.get("h", 0))
    bx1, by1 = int(b.get("x", 0)), int(b.get("y", 0))
    bx2, by2 = bx1 + int(b.get("w", 0)), by1 + int(b.get("h", 0))
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1, (bx2 - bx1) * (by2 - by1))
    return inter / float(area_a + area_b - inter)


def _dedupe_rects(rects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ordered = sorted(rects, key=lambda r: (float(r.get("area", 0)), int(r.get("w", 0)) * int(r.get("h", 0))), reverse=True)
    out: List[Dict[str, Any]] = []
    for rect in ordered:
        cx, cy = int(rect.get("center_x", 0)), int(rect.get("center_y", 0))
        duplicate = False
        for existing in out:
            if _rect_iou(rect, existing) > 0.45:
                duplicate = True
                break
            if abs(cx - int(existing.get("center_x", 0))) <= 6 and abs(cy - int(existing.get("center_y", 0))) <= 6:
                duplicate = True
                break
        if not duplicate:
            out.append(rect)
    return sorted(out, key=lambda r: (int(r.get("y", 0)), int(r.get("x", 0))))


def _button_search_bounds(image: Any) -> Tuple[int, int, int, int]:
    w_img, h_img = image.size
    if w_img >= 800:
        try:
            right_ratio = float(config.get("vision_ignore_right_panel_ratio", 0.84))
        except Exception:
            right_ratio = 0.84
        return int(w_img * 0.20), int(h_img * 0.14), int(w_img * min(0.90, right_ratio)), int(h_img * 0.88)
    return 0, 0, w_img, h_img


def find_quiz_button_rects_by_cv(image: Any) -> List[Dict[str, Any]]:
    if cv2 is None or np is None or image is None or not hasattr(image, "size"):
        return []
    arr = np.array(image.convert("RGB") if hasattr(image, "convert") else image)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 30, 100)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    bx1, by1, bx2, by2 = _button_search_bounds(image)
    rects: List[Dict[str, Any]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        cx, cy = x + w // 2, y + h // 2
        if not (bx1 <= cx <= bx2 and by1 <= cy <= by2):
            continue
        if not (55 <= w <= 180 and 16 <= h <= 58):
            continue
        ratio = w / max(1.0, float(h))
        if ratio < 2.0 or ratio > 7.2:
            continue
        area = float(cv2.contourArea(contour))
        if area < 100:
            continue
        rects.append({"x": int(x), "y": int(y), "w": int(w), "h": int(h), "center_x": int(cx), "center_y": int(cy), "area": round(area, 2)})
    return _dedupe_rects(rects)


def _pick_row_triplets(rects: List[Dict[str, Any]]) -> List[Tuple[List[Dict[str, Any]], List[Dict[str, Any]], float]]:
    triplets: List[Tuple[List[Dict[str, Any]], List[Dict[str, Any]], float]] = []
    for i, a in enumerate(rects):
        for j, b in enumerate(rects):
            if j <= i:
                continue
            top_y = (int(a["center_y"]) + int(b["center_y"])) / 2.0
            row_tol = max(14.0, (float(a["h"]) + float(b["h"])) * 0.35)
            top_row = [r for r in rects if abs(float(r["center_y"]) - top_y) <= row_tol]
            if len(top_row) < 3:
                continue
            top_row = sorted(top_row, key=lambda r: float(r["center_x"]))[:3]
            if len(top_row) != 3:
                continue
            for bottom_seed in rects:
                bottom_y = float(bottom_seed["center_y"])
                gap = bottom_y - top_y
                if gap < 20 or gap > 75:
                    continue
                bottom_tol = max(14.0, float(bottom_seed["h"]) * 0.75)
                bottom_row = [r for r in rects if abs(float(r["center_y"]) - bottom_y) <= bottom_tol]
                if len(bottom_row) < 3:
                    continue
                bottom_row = sorted(bottom_row, key=lambda r: float(r["center_x"]))[:3]
                if len(bottom_row) != 3:
                    continue
                top_x = [float(r["center_x"]) for r in top_row]
                bottom_x = [float(r["center_x"]) for r in bottom_row]
                col_delta = sum(abs(top_x[k] - bottom_x[k]) for k in range(3)) / 3.0
                avg_w = sum(float(r["w"]) for r in top_row + bottom_row) / 6.0
                if col_delta > max(30.0, avg_w * 0.65):
                    continue
                if min(top_x[1] - top_x[0], top_x[2] - top_x[1], bottom_x[1] - bottom_x[0], bottom_x[2] - bottom_x[1]) < avg_w * 0.45:
                    continue
                score = 200.0 - col_delta - abs(gap - 34.0) * 0.8
                triplets.append((top_row, bottom_row, score))
    return triplets


def _button_selected_state(image: Any, box: Dict[str, Any]) -> bool:
    if cv2 is None or np is None:
        return False
    arr = np.array(image.convert("RGB") if hasattr(image, "convert") else image)
    x, y, w, h = int(box["x"]), int(box["y"]), int(box["w"]), int(box["h"])
    crop = arr[max(0, y):max(0, y) + h, max(0, x):max(0, x) + w]
    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    green = cv2.inRange(hsv, np.array([35, 30, 25]), np.array([95, 255, 220]))
    margin = max(2, int(min(w, h) * 0.16))
    if green.shape[0] > margin * 2 and green.shape[1] > margin * 2:
        green[:margin, :] = 0
        green[-margin:, :] = 0
        green[:, :margin] = 0
        green[:, -margin:] = 0
        denom = max(1, (w - margin * 2) * (h - margin * 2))
    else:
        denom = max(1, w * h)
    return (cv2.countNonZero(green) / float(denom)) >= 0.25


def _unique_quiz_box_count(boxes: List[Dict[str, Any]], tolerance_px: int = 10) -> int:
    keys = set()
    tol = max(1, int(tolerance_px))
    for box in boxes:
        try:
            cx = int(box.get("center_x", int(box.get("x", 0)) + int(box.get("w", 0)) // 2))
            cy = int(box.get("center_y", int(box.get("y", 0)) + int(box.get("h", 0)) // 2))
        except Exception:
            continue
        keys.add((int(round(cx / tol)), int(round(cy / tol))))
    return len(keys)


def _quiz_dark_panel_metrics(image: Any, panel: Dict[str, int]) -> Dict[str, float]:
    if cv2 is None or np is None or image is None or not hasattr(image, "size"):
        return {"dark_ratio": 0.0, "mean": 255.0, "edge_dark_ratio": 0.0}
    try:
        img_w, img_h = image.size
        x1 = max(0, min(img_w - 1, int(panel.get("x1", 0))))
        y1 = max(0, min(img_h - 1, int(panel.get("y1", 0))))
        x2 = max(x1 + 1, min(img_w, int(panel.get("x2", img_w))))
        y2 = max(y1 + 1, min(img_h, int(panel.get("y2", img_h))))
        crop = np.array(image.crop((x1, y1, x2, y2)).convert("RGB"))
        if crop.size == 0:
            return {"dark_ratio": 0.0, "mean": 255.0, "edge_dark_ratio": 0.0}
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        dark_ratio = float((gray < 82).sum()) / float(max(1, gray.size))
        mean_val = float(gray.mean())
        strip = max(4, min(18, min(gray.shape[:2]) // 8))
        edge_parts = [
            gray[:strip, :],
            gray[-strip:, :],
            gray[:, :strip],
            gray[:, -strip:],
        ]
        edge_pixels = np.concatenate([part.reshape(-1) for part in edge_parts if part.size])
        edge_dark_ratio = float((edge_pixels < 92).sum()) / float(max(1, edge_pixels.size))
        return {
            "dark_ratio": round(dark_ratio, 4),
            "mean": round(mean_val, 2),
            "edge_dark_ratio": round(edge_dark_ratio, 4),
        }
    except Exception:
        return {"dark_ratio": 0.0, "mean": 255.0, "edge_dark_ratio": 0.0}


def validate_quiz_layout_window(image: Any, answer_boxes: List[Dict[str, Any]], confirm: Optional[Dict[str, Any]], score: float = 0.0) -> Dict[str, Any]:
    if image is None or not hasattr(image, "size"):
        return {"ok": False, "reason": "no_image"}
    try:
        with config_lock:
            strict_window = bool(config.get("captcha_solver_strict_quiz_window", True))
    except Exception:
        strict_window = True
    if not strict_window:
        return {"ok": True, "reason": "strict_window_disabled"}
    if len(answer_boxes) != 6:
        return {"ok": False, "reason": "answer_count", "answer_count": len(answer_boxes)}
    unique_count = _unique_quiz_box_count(answer_boxes)
    if unique_count < 6:
        return {"ok": False, "reason": "duplicate_answer_boxes", "unique_answers": unique_count}
    img_w, img_h = image.size
    rows = [
        sorted(answer_boxes[:3], key=lambda r: int(r.get("center_x", 0))),
        sorted(answer_boxes[3:], key=lambda r: int(r.get("center_x", 0))),
    ]
    top_y_vals = [float(r.get("center_y", 0)) for r in rows[0]]
    bottom_y_vals = [float(r.get("center_y", 0)) for r in rows[1]]
    top_y = sum(top_y_vals) / 3.0
    bottom_y = sum(bottom_y_vals) / 3.0
    row_gap = bottom_y - top_y
    row_spread = max(max(top_y_vals) - min(top_y_vals), max(bottom_y_vals) - min(bottom_y_vals))
    if row_gap < 18 or row_gap > 75 or row_spread > 16:
        return {"ok": False, "reason": "bad_answer_rows", "row_gap": round(row_gap, 2), "row_spread": round(row_spread, 2)}
    col_deltas = []
    for idx in range(3):
        col_deltas.append(abs(float(rows[0][idx].get("center_x", 0)) - float(rows[1][idx].get("center_x", 0))))
    avg_w = sum(float(r.get("w", 0)) for r in answer_boxes) / 6.0
    if max(col_deltas) > max(24.0, avg_w * 0.45):
        return {"ok": False, "reason": "bad_answer_columns", "col_deltas": [round(v, 2) for v in col_deltas]}
    x_centers = [float(r.get("center_x", 0)) for r in rows[0]]
    gaps = [x_centers[1] - x_centers[0], x_centers[2] - x_centers[1]]
    if min(gaps) < max(45.0, avg_w * 0.65) or max(gaps) > max(170.0, avg_w * 2.25):
        return {"ok": False, "reason": "bad_answer_spacing", "gaps": [round(v, 2) for v in gaps], "avg_w": round(avg_w, 2)}
    grid_left = min(int(r.get("x", 0)) for r in answer_boxes)
    grid_right = max(int(r.get("x", 0)) + int(r.get("w", 0)) for r in answer_boxes)
    grid_top = min(int(r.get("y", 0)) for r in answer_boxes)
    grid_bottom = max(int(r.get("y", 0)) + int(r.get("h", 0)) for r in answer_boxes)
    grid_width = grid_right - grid_left
    if grid_width > max(390, int(img_w * 0.23)):
        return {"ok": False, "reason": "answer_grid_too_wide", "grid_width": grid_width}
    confirm_fallback = bool(confirm and confirm.get("fallback"))
    if confirm:
        confirm_cx = float(confirm.get("center_x", 0))
        confirm_cy = float(confirm.get("center_y", 0))
        if abs(confirm_cx - ((grid_left + grid_right) / 2.0)) > max(55.0, avg_w * 0.75):
            return {"ok": False, "reason": "confirm_off_center"}
        if confirm_cy < grid_bottom + 16 or confirm_cy > grid_bottom + 95:
            return {"ok": False, "reason": "confirm_bad_y"}
    panel = {
        "x1": max(0, grid_left - 28),
        "y1": max(0, grid_top - 225),
        "x2": min(img_w, grid_right + 28),
        "y2": min(img_h, max(grid_bottom + 95, int((confirm or {}).get("y", grid_bottom)) + int((confirm or {}).get("h", 0)) + 48)),
    }
    metrics = _quiz_dark_panel_metrics(image, panel)
    dark_ratio = float(metrics.get("dark_ratio", 0.0))
    edge_dark_ratio = float(metrics.get("edge_dark_ratio", 0.0))
    mean_val = float(metrics.get("mean", 255.0))
    has_modal_panel = (dark_ratio >= 0.24 and edge_dark_ratio >= 0.32) or (dark_ratio >= 0.30 and mean_val <= 145.0)
    if not has_modal_panel:
        return {"ok": False, "reason": "missing_dark_quiz_panel", "panel": panel, "metrics": metrics}
    if confirm_fallback and (dark_ratio < 0.34 or edge_dark_ratio < 0.40):
        return {"ok": False, "reason": "fallback_confirm_without_strong_panel", "panel": panel, "metrics": metrics}
    return {
        "ok": True,
        "reason": "ok",
        "unique_answers": unique_count,
        "row_gap": round(row_gap, 2),
        "grid_width": grid_width,
        "panel": panel,
        "metrics": metrics,
        "score": round(float(score), 3),
    }


def normalize_quiz_answer_grid(answer_boxes: List[Dict[str, Any]], image: Any = None) -> List[Dict[str, Any]]:
    if len(answer_boxes) != 6:
        return answer_boxes
    try:
        widths = [int(a.get("w", 0)) for a in answer_boxes if int(a.get("w", 0)) > 0]
        heights = [int(a.get("h", 0)) for a in answer_boxes if int(a.get("h", 0)) > 0]
        if not widths or not heights:
            return answer_boxes
        box_w = int(round(float(median(widths))))
        box_h = int(round(float(median(heights))))
        box_w = max(55, min(120, box_w))
        box_h = max(22, min(34, box_h))
        top_row = sorted(answer_boxes[:3], key=lambda r: int(r.get("center_x", 0)))
        bottom_row = sorted(answer_boxes[3:], key=lambda r: int(r.get("center_x", 0)))
        top_y = int(round(float(median([float(r.get("center_y", 0)) for r in top_row]))))
        bottom_y = int(round(float(median([float(r.get("center_y", 0)) for r in bottom_row]))))
        col_centers: List[int] = []
        for idx in range(3):
            tx = float(top_row[idx].get("center_x", 0))
            bx = float(bottom_row[idx].get("center_x", 0))
            col_centers.append(int(round((tx + bx) / 2.0)))
        img_w = int(getattr(image, "size", (100000, 100000))[0]) if image is not None else 100000
        img_h = int(getattr(image, "size", (100000, 100000))[1]) if image is not None else 100000
        normalized: List[Dict[str, Any]] = []
        for idx in range(6):
            cx = col_centers[idx % 3]
            cy = top_y if idx < 3 else bottom_y
            x = max(0, min(img_w - box_w, cx - box_w // 2))
            y = max(0, min(img_h - box_h, cy - box_h // 2))
            raw_box = top_row[idx] if idx < 3 else bottom_row[idx - 3]
            normalized.append({
                **raw_box,
                "x": int(x),
                "y": int(y),
                "w": int(box_w),
                "h": int(box_h),
                "center_x": int(x + box_w // 2),
                "center_y": int(y + box_h // 2),
                "normalized_from": {
                    "x": int(raw_box.get("x", 0)),
                    "y": int(raw_box.get("y", 0)),
                    "w": int(raw_box.get("w", 0)),
                    "h": int(raw_box.get("h", 0)),
                },
            })
        return normalized
    except Exception:
        return answer_boxes


def _button_text_mask_and_bbox(image: Any, box: Dict[str, Any]) -> Tuple[Optional[Any], Optional[Tuple[int, int, int, int]], Dict[str, Any]]:
    if cv2 is None or np is None:
        return None, None, {"reason": "cv_unavailable"}
    arr = np.array(image.convert("RGB") if hasattr(image, "convert") else image)
    x, y, w, h = int(box["x"]), int(box["y"]), int(box["w"]), int(box["h"])
    crop = arr[max(0, y):max(0, y) + h, max(0, x):max(0, x) + w]
    if crop.size == 0:
        return None, None, {"reason": "empty_crop"}
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    text_mask = cv2.inRange(gray, 170, 255)
    margin_x = max(5, int(w * 0.10))
    margin_y = max(4, int(h * 0.20))
    text_mask[:margin_y, :] = 0
    text_mask[-margin_y:, :] = 0
    text_mask[:, :margin_x] = 0
    text_mask[:, -margin_x:] = 0
    ys, xs = np.where(text_mask > 0)
    if len(xs) == 0:
        return text_mask, None, {"reason": "no_text_pixels"}
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    return text_mask, bbox, {"pixels": int(len(xs)), "bbox": bbox}


def _left_marker_star_score(text_mask: Any, bbox: Tuple[int, int, int, int]) -> Dict[str, Any]:
    x0, y0, x1, y1 = bbox
    sub = text_mask[y0:y1, x0:x1]
    if sub.size == 0:
        return {"star": False, "score": 0.0, "reason": "empty_text_bbox"}
    text_h, text_w = sub.shape[:2]
    edge_w = max(3, int(round(text_w * 0.34)))
    left = sub[:, :edge_w]
    ys, xs = np.where(left > 0)
    if len(xs) == 0:
        return {"star": False, "score": 0.0, "reason": "empty_left_marker", "text_w": int(text_w), "text_h": int(text_h)}
    marker = left[int(ys.min()):int(ys.max()) + 1, int(xs.min()):int(xs.max()) + 1]
    mh, mw = marker.shape[:2]
    pixels = int(cv2.countNonZero(marker))
    row_counts = [int(cv2.countNonZero(marker[row, :])) for row in range(mh)]
    max_row = max(row_counts) if row_counts else 0
    dense_rows = sum(1 for count in row_counts if count >= 3)
    density = pixels / float(max(1, mw * mh))
    compact = 3 <= mw <= 7 and 3 <= mh <= 7
    star = bool(compact and pixels >= 7 and max_row >= 3 and density >= 0.32)
    score = 0.0
    if compact:
        score += 0.35
    score += min(0.25, max_row / 12.0)
    score += min(0.20, pixels / 55.0)
    score += min(0.20, density / 2.0)
    if dense_rows >= 2:
        score += 0.10
    return {
        "star": star,
        "score": round(score, 3),
        "marker_w": int(mw),
        "marker_h": int(mh),
        "pixels": int(pixels),
        "max_row": int(max_row),
        "dense_rows": int(dense_rows),
        "density": round(density, 3),
        "text_w": int(text_w),
        "text_h": int(text_h),
    }


def detect_answer_symbol_details(image: Any, box: Dict[str, Any]) -> Dict[str, Any]:
    if cv2 is None or np is None:
        return {"symbols": [], "method": "unavailable"}
    text_mask, bbox, text_debug = _button_text_mask_and_bbox(image, box)
    if text_mask is None or bbox is None:
        return {"symbols": ["other"], "method": "text_mask", "debug": text_debug}
    star_debug = _left_marker_star_score(text_mask, bbox)
    if star_debug.get("star"):
        return {"symbols": ["star"], "method": "left_marker_shape", "debug": {"text": text_debug, "star": star_debug}}

    w = int(box["w"])
    h = int(box["h"])
    text_mask_legacy = text_mask.copy()
    margin = max(2, int(min(w, h) * 0.14))
    text_mask_legacy[:margin, :] = 0
    text_mask_legacy[-margin:, :] = 0
    text_mask_legacy[:, :margin] = 0
    text_mask_legacy[:, -margin:] = 0
    symbols: List[str] = []
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(text_mask_legacy, 8)
    comps: List[Tuple[int, int, int, int, int]] = []
    for idx in range(1, count):
        xx, yy, ww, hh, area = (int(v) for v in stats[idx])
        if area < 3:
            continue
        if hh <= 2 or ww >= w * 0.55:
            continue
        comps.append((xx, yy, ww, hh, area))
    if not comps:
        return {"symbols": ["other"], "method": "shape_fallback", "debug": {"text": text_debug, "star": star_debug, "components": []}}
    narrow = [c for c in comps if c[2] <= max(4, int(w * 0.055)) and c[3] >= max(7, int(h * 0.24)) and c[4] >= 8]
    large_round = [c for c in comps if c[2] >= max(12, int(w * 0.14)) and c[3] >= max(10, int(h * 0.28)) and c[4] >= 45]
    percent_like = [c for c in comps if c[2] >= max(14, int(w * 0.16)) and c[3] >= max(8, int(h * 0.22)) and c[4] >= 55]
    if len(narrow) >= 2:
        symbols.append("bang")
    if len(large_round) >= 2 and sum(c[4] for c in large_round) >= 120 and (sum(c[3] for c in large_round) / float(len(large_round))) >= h * 0.38:
        symbols.append("at")
    if "at" not in symbols and "bang" not in symbols and len(percent_like) >= 1:
        symbols.append("percent")
    if not symbols:
        symbols.append("other")
    return {
        "symbols": symbols,
        "method": "shape_fallback",
        "debug": {
            "text": text_debug,
            "star": star_debug,
            "component_count": len(comps),
            "narrow": len(narrow),
            "large_round": len(large_round),
            "percent_like": len(percent_like),
        },
    }


def detect_answer_symbols(image: Any, box: Dict[str, Any]) -> List[str]:
    return list(detect_answer_symbol_details(image, box).get("symbols", []))


def find_quiz_layout_by_cv(image: Any) -> Dict[str, Any]:
    rects = find_quiz_button_rects_by_cv(image)
    triplets = _pick_row_triplets(rects)
    if not triplets:
        return {"found": False, "answers": [], "confirm": None, "button_candidates": rects, "method": "quiz_cv"}
    top_row, bottom_row, score = max(triplets, key=lambda item: item[2])
    answer_boxes = sorted(top_row, key=lambda r: int(r["center_x"])) + sorted(bottom_row, key=lambda r: int(r["center_x"]))
    answer_boxes = normalize_quiz_answer_grid(answer_boxes, image)
    grid_left = min(int(r["x"]) for r in answer_boxes)
    grid_right = max(int(r["x"]) + int(r["w"]) for r in answer_boxes)
    grid_center_x = (grid_left + grid_right) / 2.0
    answer_bottom = max(int(r["y"]) + int(r["h"]) for r in answer_boxes)
    avg_w = sum(float(r["w"]) for r in answer_boxes) / 6.0
    confirm_candidates = [
        r for r in rects
        if int(r["center_y"]) > answer_bottom + 12
        and int(r["center_y"]) < answer_bottom + 95
        and abs(float(r["center_x"]) - grid_center_x) <= max(45.0, avg_w * 0.75)
        and int(r["w"]) >= avg_w * 0.75
        and int(r["h"]) <= 45
    ]
    confirm = max(confirm_candidates, key=lambda r: (float(r.get("area", 0)), int(r.get("w", 0)) * int(r.get("h", 0))), default=None)
    if not confirm:
        confirm_w = int(max(90.0, min(140.0, avg_w * 1.25)))
        confirm_h = 30
        confirm_cx = int(round(grid_center_x))
        confirm_cy = int(round(answer_bottom + 39))
        confirm = {
            "x": confirm_cx - confirm_w // 2,
            "y": confirm_cy - confirm_h // 2,
            "w": confirm_w,
            "h": confirm_h,
            "center_x": confirm_cx,
            "center_y": confirm_cy,
            "area": 0.0,
            "fallback": True,
        }
    if confirm:
        confirm = {**confirm, "found": True, "kind": "confirm", "confidence": 0.72, "method": "quiz_cv_confirm"}
    validation = validate_quiz_layout_window(image, answer_boxes, confirm, score)
    if not validation.get("ok"):
        return {
            "found": False,
            "answers": [],
            "confirm": None,
            "button_candidates": rects,
            "score": round(score, 3),
            "method": "quiz_cv",
            "status": "QUIZ_LAYOUT_REJECTED",
            "validation": validation,
            "rejected_answers": answer_boxes,
            "rejected_confirm": confirm,
        }
    answers: List[Dict[str, Any]] = []
    for idx, box in enumerate(answer_boxes):
        details = detect_answer_symbol_details(image, box)
        symbols = list(details.get("symbols", []))
        selected = _button_selected_state(image, box)
        answers.append({
            **box,
            "index": idx,
            "kind": "answer",
            "confidence": 0.86 if "star" in symbols else 0.72,
            "symbols": symbols,
            "selected": selected,
            "text": "".join(symbols) or "",
            "symbol_method": details.get("method"),
            "symbol_debug": details.get("debug", {}),
        })
    return {"found": True, "answers": answers, "confirm": confirm, "button_candidates": rects, "score": round(score, 3), "method": "quiz_cv", "validation": validation}


def revive_rejected_quiz_layout(image: Any, layout: Dict[str, Any]) -> Dict[str, Any]:
    """Use the old detected answer grid when the newer strict modal validation is too defensive."""
    if layout.get("answers"):
        return layout
    if layout.get("status") != "QUIZ_LAYOUT_REJECTED":
        return layout
    rejected_answers = list(layout.get("rejected_answers") or [])
    if len(rejected_answers) != 6:
        return layout

    answers: List[Dict[str, Any]] = []
    for idx, box in enumerate(rejected_answers):
        details = detect_answer_symbol_details(image, box)
        symbols = list(details.get("symbols", []))
        selected = _button_selected_state(image, box)
        answers.append({
            **box,
            "index": idx,
            "kind": "answer",
            "confidence": 0.80 if symbols else 0.55,
            "symbols": symbols,
            "selected": selected,
            "text": "".join(symbols) or "",
            "symbol_method": details.get("method"),
            "symbol_debug": details.get("debug", {}),
        })

    confirm = layout.get("rejected_confirm")
    if confirm:
        confirm = {**confirm, "found": True, "kind": "confirm", "method": str(confirm.get("method", "quiz_cv_confirm_relaxed"))}

    revived = {
        **layout,
        "found": True,
        "answers": answers,
        "confirm": confirm,
        "status": "OK_RELAXED_FROM_REJECTED",
        "method": "quiz_cv_relaxed",
        "validation": {
            "ok": True,
            "reason": "relaxed_from_rejected_layout",
            "original_validation": layout.get("validation"),
        },
    }
    return revived


def infer_required_answer_symbol(image: Any) -> Dict[str, Any]:
    text = ""
    ocr_error = ""
    if pytesseract is not None:
        try:
            text = normalize_vision_text(pytesseract.image_to_string(image))
        except Exception as exc:
            ocr_error = str(exc)
            text = ""
    else:
        ocr_error = "pytesseract_module_unavailable"
    mapping = [
        ("star", ["gwiazdk", "asterysk", "*"]),
        ("percent", ["procent", "%"]),
        ("bang", ["wykrzykn", "!"]),
        ("at", ["malp", "małp", "@"]),
    ]
    for symbol, needles in mapping:
        if any(normalize_vision_text(needle) in text for needle in needles):
            return {"symbol": symbol, "source": "ocr", "instruction": text}
    with config_lock:
        default_symbol = normalize_vision_text(config.get("captcha_solver_default_symbol", "star")) or "star"
    aliases = {"gwiazdka": "star", "gwiazdke": "star", "asterisk": "star", "*": "star", "procent": "percent", "%": "percent", "wykrzyknik": "bang", "!": "bang", "malpa": "at", "@": "at"}
    return {"symbol": aliases.get(default_symbol, default_symbol), "source": "config_default", "instruction": text, "ocr_error": ocr_error}


def quiz_signature_from_layout(image: Any, layout: Dict[str, Any], required: Dict[str, Any]) -> str:
    answers = sorted(list(layout.get("answers") or []), key=lambda a: int(a.get("index", 0)))
    signature_answers: List[Dict[str, Any]] = []
    for answer in answers:
        try:
            x, y, w, h = (int(answer.get(k, 0)) for k in ("x", "y", "w", "h"))
        except Exception:
            x = y = w = h = 0
        signature_answers.append({
            "i": int(answer.get("index", len(signature_answers))),
            "x": round(x / 4) * 4,
            "y": round(y / 4) * 4,
            "w": round(w / 4) * 4,
            "h": round(h / 4) * 4,
            "symbols": sorted(str(s) for s in answer.get("symbols", [])),
        })
    crop_hash = ""
    try:
        if image is not None and hasattr(image, "crop") and answers:
            width, height = image.size
            left = max(0, min(int(a.get("x", 0)) for a in answers) - 18)
            right = min(width, max(int(a.get("x", 0)) + int(a.get("w", 0)) for a in answers) + 18)
            answer_top = min(int(a.get("y", 0)) for a in answers)
            top = max(0, answer_top - 220)
            bottom = min(height, max(top + 1, answer_top - 8))
            if right > left and bottom > top:
                crop = image.crop((left, top, right, bottom)).convert("L").resize((96, 48))
                crop_hash = hashlib.sha1(crop.tobytes()).hexdigest()[:20]
        elif image is not None and hasattr(image, "copy"):
            thumb = image.copy().convert("L").resize((64, 36))
            crop_hash = hashlib.sha1(thumb.tobytes()).hexdigest()[:20]
    except Exception:
        crop_hash = ""
    payload = {
        "required": str(required.get("symbol", "")),
        "answers": signature_answers,
        "crop": crop_hash,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:24]


def save_quiz_debug_snapshot(image: Any, layout: Dict[str, Any], required: Dict[str, Any], status: str, plan: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    ensure_data_dirs()
    status_upper = status.upper()
    error_status = any(
        token in status_upper
        for token in ("ERROR", "FAILED", "REJECTED", "NOT_FOUND", "AMBIGUOUS", "NO_MATCHING")
    )
    if not should_save_debug_screenshots(config) and not error_status:
        return {}
    now = time.time()
    signature = quiz_signature_from_layout(image, layout, required)
    with config_lock:
        min_interval = max(0.0, float(config.get("captcha_solver_debug_min_interval_ms", 2000)) / 1000.0)
    if signature and runtime_state.get("last_quiz_debug") and runtime_state.get("last_quiz_debug_signature") == signature:
        return dict(runtime_state.get("last_quiz_debug") or {})
    if (
        not signature
        and runtime_state.get("last_quiz_debug")
        and runtime_state.get("last_quiz_debug_status") == status
        and now - float(runtime_state.get("last_quiz_debug_ts", 0.0)) < min_interval
    ):
        return dict(runtime_state.get("last_quiz_debug") or {})
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    folder = DATA_DIR / "quiz"
    raw_path = folder / f"{stamp}_quiz_raw.jpg"
    annotated_path = folder / f"{stamp}_quiz_detected.jpg"
    json_path = folder / f"{stamp}_quiz.json"
    out: Dict[str, str] = {}
    try:
        if image is not None:
            raw_path = save_screenshot_image(image, raw_path)
            out["raw"] = str(raw_path)
            if ImageDraw is not None:
                vis = image.copy()
                draw = ImageDraw.Draw(vis)
                target_symbol = str(required.get("symbol", ""))
                for answer in layout.get("answers", []):
                    x, y, w, h = (int(answer.get(k, 0)) for k in ("x", "y", "w", "h"))
                    symbols = ",".join(str(s) for s in answer.get("symbols", []))
                    selected = "sel" if answer.get("selected") else "off"
                    is_target = target_symbol and target_symbol in answer.get("symbols", [])
                    color = "lime" if is_target else "red"
                    draw.rectangle([x, y, x + w, y + h], outline=color, width=3)
                    draw.text((x, max(0, y - 14)), f"{answer.get('index')} {symbols} {selected}", fill=color)
                confirm = layout.get("confirm")
                if confirm:
                    x, y, w, h = (int(confirm.get(k, 0)) for k in ("x", "y", "w", "h"))
                    draw.rectangle([x, y, x + w, y + h], outline="cyan", width=3)
                    draw.text((x, max(0, y - 14)), "confirm", fill="cyan")
                draw.text((8, 8), f"status={status} required={target_symbol} source={required.get('source')}", fill="yellow")
                annotated_path = save_screenshot_image(vis, annotated_path)
                out["annotated"] = str(annotated_path)
        payload = {
            "timestamp": stamp,
            "status": status,
            "signature": signature,
            "required": required,
            "layout": layout,
            "plan": plan or {},
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        out["json"] = str(json_path)
        runtime_state["last_quiz_debug"] = out
        runtime_state["last_quiz_debug_ts"] = now
        runtime_state["last_quiz_debug_status"] = status
        runtime_state["last_quiz_debug_signature"] = signature
    except Exception as exc:
        log_event(f"Quiz debug save failed: {exc}")
    return out


def find_captcha_answers(hwnd: int) -> Dict[str, Any]:
    cap = capture_client_area_robust(hwnd)
    if not cap.get("image"):
        return {"ok": False, "answers": [], "status": "CAPTURE_FAILED"}
    image = cap["image"]
    layout = revive_rejected_quiz_layout(image, find_quiz_layout_by_cv(image))
    answers: List[Dict[str, Any]] = list(layout.get("answers", []))
    detection_method = str(layout.get("method", "quiz_cv"))
    if not answers and layout.get("status") == "QUIZ_LAYOUT_REJECTED":
        required = infer_required_answer_symbol(image)
        debug_paths = save_quiz_debug_snapshot(image, layout, required, "QUIZ_LAYOUT_REJECTED")
        return {
            "ok": False,
            "answers": [],
            "matching_answers": [],
            "required": required,
            "confirm": None,
            "layout": layout,
            "status": "QUIZ_LAYOUT_REJECTED",
            "debug_paths": debug_paths,
            "capture_method": cap.get("method"),
            "quality": cap.get("quality"),
            "method": detection_method,
            "message": "Odrzucono uklad przyciskow, bo nie wyglada jak kompletne okno quizu.",
        }
    if not answers:
        regions = find_text_regions(image, ["A", "B", "C", "D", "E", "F"])
        for i, r in enumerate(regions):
            if r["w"] < 25 or r["h"] < 12:
                continue
            answers.append({**r, "index": i, "kind": "answer", "confidence": 0.6, "symbols": [], "selected": False})
        detection_method = "ocr_regions"
    meta = build_capture_metadata(hwnd, cap, "answers", answers, [a.get("text","") for a in answers], detection_method)
    dbg = maybe_save_debug_detected(image, "answers", answers)
    if dbg:
        meta["debug_detected_path"] = dbg
    ds = save_dataset_sample_deduped(image, "answers", answers, meta) if answers else {"ok": False, "status": "NO_ANSWERS"}
    runtime_state["last_ocr_texts"] = [a.get("text","") for a in answers]
    log_event(f"Answers found: {len(answers)}")
    log_event(f"Dataset saved/skipped duplicate: answers ({ds.get('status')})")
    for i, a in enumerate(answers):
        a["index"] = i
        a["kind"] = "answer"
    required = infer_required_answer_symbol(image)
    matching = [a for a in answers if required.get("symbol") in a.get("symbols", [])]
    return {"ok": True, "answers": answers, "matching_answers": matching, "required": required, "confirm": layout.get("confirm"), "status": "OK", "capture_method": cap.get("method"), "quality": cap.get("quality"), "method": detection_method}


def find_confirm_button(hwnd: int) -> Dict[str, Any]:
    cap = capture_client_area_robust(hwnd)
    if not cap.get("ok"):
        return {"found": False, "status": cap.get("status", "CAPTURE_FAILED")}
    image = cap["image"]
    layout = revive_rejected_quiz_layout(image, find_quiz_layout_by_cv(image))
    if layout.get("confirm"):
        return layout["confirm"]
    regs = find_text_regions(image, ["Potwierdzam", "Potwierdź", "Potwierdz", "Zatwierdź", "Zatwierdz", "OK"])
    ocr = {"found": False}
    if regs:
        r = regs[0]
        ocr = {"found": True, "method": "ocr", "x": r["x"], "y": r["y"], "w": r["w"], "h": r["h"], "center_x": r["center_x"], "center_y": r["center_y"]}
    if ocr.get("found"):
        runtime_state["last_ocr_texts"] = [r.get("text","") for r in regs]
        box=[{k: ocr[k] for k in ("x", "y", "w", "h")}]
        meta = build_capture_metadata(hwnd, cap, "confirm", box, [r.get("text","") for r in regs], "ocr_confirm")
        dbg = maybe_save_debug_detected(image, "confirm", box)
        if dbg: meta["debug_detected_path"] = dbg
        save_dataset_sample_deduped(image, "confirm", box, meta)
        return {**ocr, "kind": "confirm", "confidence": 0.7}
    green = find_green_button_by_cv(image)
    if green.get("found") and not layout.get("answers"):
        return {**green, "kind": "confirm", "confidence": green.get("score", 0.6)}
    pt = find_template_in_client(hwnd, "confirm.png") or find_template_in_client(hwnd, "potwierdz.png")
    if pt:
        return {"found": True, "kind": "confirm", "x": pt[0]-45, "y": pt[1]-15, "w": 90, "h": 30, "center_x": pt[0], "center_y": pt[1], "confidence": 0.6, "method": "template"}
    return {"found": False, "kind": "confirm", "status": "NOT_FOUND"}


def solver_human_delay_seconds(min_ms: int, max_ms: int, fallback_ms: int, floor_ms: int, disable_randomness: bool = False) -> Tuple[float, int]:
    try:
        low = int(min_ms)
        high = int(max_ms)
    except Exception:
        low = high = int(fallback_ms)
    if low <= 0 and high <= 0:
        low = high = int(fallback_ms)
    if low <= 0:
        low = int(fallback_ms)
    if high <= 0:
        high = low
    if high < low:
        low, high = high, low
    picked = low if disable_randomness else random.randint(low, high)
    picked = max(int(floor_ms), int(picked))
    return picked / 1000.0, picked


def _solve_captcha_challenge_locked(hwnd: int) -> Dict[str, Any]:
    cap = capture_client_area_robust(hwnd)
    if not cap.get("image"):
        return {"ok": False, "status": "CAPTURE_FAILED"}
    image = cap["image"]
    layout = revive_rejected_quiz_layout(image, find_quiz_layout_by_cv(image))
    answers = list(layout.get("answers", []))
    if not answers:
        log_event("[Quiz Solver] Nie wykryto okna quizu ani odpowiedzi")
        required = infer_required_answer_symbol(image)
        debug_paths = save_quiz_debug_snapshot(image, layout, required, "ANSWERS_NOT_FOUND")
        return {"ok": False, "status": "ANSWERS_NOT_FOUND", "layout": layout, "debug_paths": debug_paths}
    required = infer_required_answer_symbol(image)
    symbol = str(required.get("symbol", "star"))
    log_event("[Quiz Solver] Okno quizu wykryte")
    log_event(f"[Quiz Solver] Pytanie: {required.get('instruction') or required.get('source') or 'brak odczytu OCR'}")
    log_event(f"[Quiz Solver] Odpowiedzi znalezione: {len(answers)}")
    quiz_signature = quiz_signature_from_layout(image, layout, required)
    with config_lock:
        delay_ms = int(config.get("captcha_solver_click_delay_ms", 320))
        confirm_delay_ms = int(config.get("captcha_solver_confirm_delay_ms", 650))
        answer_delay_min_ms = int(config.get("captcha_solver_answer_delay_min_ms", delay_ms))
        answer_delay_max_ms = int(config.get("captcha_solver_answer_delay_max_ms", max(delay_ms, delay_ms + 450)))
        confirm_delay_min_ms = int(config.get("captcha_solver_confirm_delay_min_ms", confirm_delay_ms))
        confirm_delay_max_ms = int(config.get("captcha_solver_confirm_delay_max_ms", max(confirm_delay_ms, confirm_delay_ms + 800)))
        same_quiz_cooldown_ms = int(config.get("captcha_solver_same_quiz_cooldown_ms", 6000))
        auto_confirm = bool(config.get("captcha_solver_auto_confirm", True))
        require_question_ocr = bool(config.get("captcha_solver_require_question_ocr", False))
        click_all_targets = bool(config.get("captcha_solver_click_all_targets", True))
        unselect_wrong = bool(config.get("captcha_solver_unselect_wrong_answers", False))
        save_debug = bool(config.get("captcha_solver_save_debug", True))
        disable_randomness = bool(config.get("disable_randomness", False))
    if (
        quiz_signature
        and runtime_state.get("last_quiz_solve_signature") == quiz_signature
        and (time.time() - float(runtime_state.get("last_quiz_solve_ts", 0.0))) * 1000.0 < max(0, same_quiz_cooldown_ms)
    ):
        return {
            "ok": True,
            "status": "SAME_QUIZ_RECENTLY_ATTEMPTED",
            "required": required,
            "answers": answers,
            "layout": layout,
            "signature": quiz_signature,
            "message": "Ten sam quiz byl juz klikniety przed chwila; czekam na reakcje gry.",
        }
    desired = [a for a in answers if symbol in a.get("symbols", [])]
    wrong_selected = [a for a in answers if symbol not in a.get("symbols", []) and bool(a.get("selected", False))]
    missing_targets = [a for a in desired if not bool(a.get("selected", False))]
    selected_targets = [a for a in desired if bool(a.get("selected", False))]
    if quiz_signature and runtime_state.get("last_quiz_clicked_signature") != quiz_signature:
        runtime_state["last_quiz_clicked_signature"] = quiz_signature
        runtime_state["last_quiz_clicked_indexes"] = []
    clicked_indexes = set(int(i) for i in (runtime_state.get("last_quiz_clicked_indexes") or []))
    base_click_targets = list(desired if click_all_targets else missing_targets)
    skipped_reclick = [a for a in base_click_targets if int(a.get("index", -1)) in clicked_indexes]
    to_toggle = [a for a in base_click_targets if int(a.get("index", -1)) not in clicked_indexes]
    if unselect_wrong:
        to_toggle.extend(a for a in wrong_selected if int(a.get("index", -1)) not in clicked_indexes)
    deduped: List[Dict[str, Any]] = []
    seen_click_indexes = set()
    for answer in to_toggle:
        idx = int(answer.get("index", -1))
        if idx in seen_click_indexes:
            continue
        seen_click_indexes.add(idx)
        deduped.append(answer)
    to_toggle = deduped
    plan = {
        "signature": quiz_signature,
        "desired_indexes": [a.get("index") for a in desired],
        "selected_target_indexes": [a.get("index") for a in selected_targets],
        "missing_target_indexes": [a.get("index") for a in missing_targets],
        "wrong_selected_indexes": [a.get("index") for a in wrong_selected],
        "already_clicked_indexes": sorted(clicked_indexes),
        "skipped_reclick_indexes": [a.get("index") for a in skipped_reclick],
        "click_indexes": [a.get("index") for a in to_toggle],
        "click_all_targets": click_all_targets,
        "auto_confirm": auto_confirm,
        "require_question_ocr": require_question_ocr,
        "unselect_wrong": unselect_wrong,
        "click_delay_ms": delay_ms,
        "confirm_delay_ms": confirm_delay_ms,
        "answer_delay_range_ms": [answer_delay_min_ms, answer_delay_max_ms],
        "confirm_delay_range_ms": [confirm_delay_min_ms, confirm_delay_max_ms],
    }
    debug_paths: Dict[str, str] = {}
    if save_debug:
        debug_paths = save_quiz_debug_snapshot(image, layout, required, "PLAN", plan)
    unknown_answers = [a for a in answers if not a.get("symbols")]
    if len(answers) != 6 or unknown_answers:
        if save_debug:
            debug_paths = save_quiz_debug_snapshot(image, layout, required, "AMBIGUOUS_ANSWERS", plan)
        return {
            "ok": False,
            "status": "AMBIGUOUS_ANSWERS",
            "required": required,
            "answers": answers,
            "layout": layout,
            "plan": plan,
            "debug_paths": debug_paths,
            "message": "Nie klikam, bo nie wszystkie 6 odpowiedzi ma jednoznacznie rozpoznany symbol.",
        }
    if require_question_ocr and required.get("source") != "ocr":
        return {
            "ok": False,
            "status": "QUESTION_NOT_READ",
            "required": required,
            "answers": answers,
            "layout": layout,
            "plan": plan,
            "debug_paths": debug_paths,
            "message": "OCR pytania nie dziala albo nie odczytal symbolu; quiz nie zostal klikniety.",
        }
    if not desired:
        if save_debug:
            debug_paths = save_quiz_debug_snapshot(image, layout, required, "NO_MATCHING_ANSWERS", plan)
        return {"ok": False, "status": "NO_MATCHING_ANSWERS", "required": required, "answers": answers, "layout": layout, "plan": plan, "debug_paths": debug_paths}
    log_event(f"[Quiz Solver] Wybrane odpowiedzi: {[a.get('index') for a in desired]}")
    if quiz_signature:
        runtime_state["last_quiz_solve_signature"] = quiz_signature
        runtime_state["last_quiz_solve_ts"] = time.time()
    clicks: List[Dict[str, Any]] = []
    for answer in to_toggle:
        label = f"solver_answer_{answer.get('index', len(clicks))}"
        log_event(f"[Quiz Solver] Klikam odpowiedź: {answer.get('index')} symbols={answer.get('symbols')}")
        click = click_detected_box(hwnd, answer, label)
        answer_index = int(answer.get("index", -1))
        if click.get("ok") and quiz_signature and answer_index >= 0:
            clicked_indexes.add(answer_index)
            runtime_state["last_quiz_clicked_signature"] = quiz_signature
            runtime_state["last_quiz_clicked_indexes"] = sorted(clicked_indexes)
        answer_delay_s, answer_delay_used_ms = solver_human_delay_seconds(
            answer_delay_min_ms,
            answer_delay_max_ms,
            delay_ms,
            120,
            disable_randomness,
        )
        clicks.append({"answer": answer, "click": click, "post_click_delay_ms": answer_delay_used_ms})
        time.sleep(answer_delay_s)
        if not click.get("ok"):
            return {"ok": False, "status": "ANSWER_CLICK_FAILED", "required": required, "answers": answers, "plan": plan, "clicks": clicks, "debug_paths": debug_paths}
    confirm_click = None
    confirm = layout.get("confirm")
    confirm_delay_used_ms = 0
    if auto_confirm:
        confirm_delay_s, confirm_delay_used_ms = solver_human_delay_seconds(
            confirm_delay_min_ms,
            confirm_delay_max_ms,
            confirm_delay_ms,
            250,
            disable_randomness,
        )
        time.sleep(confirm_delay_s)
        confirm = find_confirm_button(hwnd)
        if not confirm.get("found", True):
            log_event("[Quiz Solver] Nie znaleziono przycisku Potwierdzam")
            return {"ok": False, "status": "CONFIRM_NOT_FOUND", "required": required, "answers": answers, "plan": plan, "clicks": clicks, "confirm": confirm, "debug_paths": debug_paths}
        log_event("[Quiz Solver] Klikam Potwierdzam")
        confirm_click = click_detected_box(hwnd, confirm, "solver_confirm")
        if not confirm_click.get("ok"):
            return {"ok": False, "status": "CONFIRM_CLICK_FAILED", "required": required, "answers": answers, "plan": plan, "clicks": clicks, "confirm": confirm, "confirm_click": confirm_click, "debug_paths": debug_paths}
    if quiz_signature:
        runtime_state["last_quiz_solve_signature"] = quiz_signature
        runtime_state["last_quiz_solve_ts"] = time.time()
    runtime_state["watcher_state"] = "CAPTCHA_SOLVED"
    runtime_state["last_quiz_solved_at"] = time.time()
    runtime_state["last_quiz_solved_result"] = {
        "status": "SOLVED",
        "signature": quiz_signature,
        "required": required,
    }
    return {
        "ok": True,
        "status": "SOLVED",
        "signature": quiz_signature,
        "required": required,
        "answers": answers,
        "selected_targets": desired,
        "toggled": to_toggle,
        "plan": plan,
        "clicks": clicks,
        "confirm": confirm,
        "confirm_click": confirm_click,
        "confirm_delay_ms": confirm_delay_used_ms,
        "debug_paths": debug_paths,
        "method": "quiz_cv_solver",
    }


def solve_captcha_challenge(hwnd: int) -> Dict[str, Any]:
    if not quiz_solver_lock.acquire(blocking=False):
        return {
            "ok": True,
            "status": "SOLVER_BUSY",
            "message": "Solver quizu juz pracuje; pomijam drugi start, zeby nie kliknac odpowiedzi drugi raz.",
        }
    try:
        return _solve_captcha_challenge_locked(hwnd)
    finally:
        quiz_solver_lock.release()


def solve_visible_captcha_until_clear(hwnd: int, max_rounds: int = 3) -> Dict[str, Any]:
    rounds: List[Dict[str, Any]] = []
    last_result: Dict[str, Any] = {"ok": False, "status": "NOT_RUN"}
    for _round in range(max(1, max_rounds)):
        cap = capture_client_area_robust(hwnd)
        image = cap.get("image")
        if image is None:
            last_result = {"ok": False, "status": "CAPTURE_FAILED"}
            break
        layout = revive_rejected_quiz_layout(image, find_quiz_layout_by_cv(image))
        if not layout.get("answers"):
            runtime_state["last_quiz_solve_signature"] = ""
            runtime_state["last_quiz_solve_ts"] = 0.0
            runtime_state["last_quiz_clicked_signature"] = ""
            runtime_state["last_quiz_clicked_indexes"] = []
            return {"ok": True, "status": "NO_VISIBLE_CHALLENGE", "rounds": rounds, "last_result": last_result}
        last_result = solve_captcha_challenge(hwnd)
        rounds.append(last_result)
        if last_result.get("status") in ("SAME_QUIZ_RECENTLY_ATTEMPTED", "SOLVER_BUSY"):
            return {"ok": True, "status": "WAITING_FOR_QUIZ_RESULT", "rounds": rounds, "last_result": last_result}
        if not last_result.get("ok"):
            break
        time.sleep(max(0.2, float(config.get("vision_click_cooldown_ms", 2000)) / 2500.0))
    return {"ok": bool(last_result.get("ok")), "status": "SOLVE_ROUNDS_DONE", "rounds": rounds, "last_result": last_result}


def find_template_in_client(hwnd: int, template_name: str) -> Optional[Tuple[int, int]]:
    try:
        with config_lock:
            threshold = float(config.get("vision_threshold", 0.85))
            templates_dir = str(config.get("vision_templates_dir", "templates")).strip() or "templates"
            debug_enabled = bool(config.get("vision_debug", False))

        if cv2 is None or np is None:
            return None

        screenshot_path = capture_client_area(hwnd, save_debug_file=False)
        if not screenshot_path or not screenshot_path.exists():
            return None

        template_path = Path(templates_dir) / template_name
        if template_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
            template_path = template_path.with_suffix(".png")
        if not template_path.is_absolute():
            template_path = SETTINGS_PATH.parent / template_path
        if not template_path.exists():
            return None

        screenshot = cv2.imread(str(screenshot_path), cv2.IMREAD_COLOR)
        template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
        if screenshot is None or template is None:
            return None

        result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
        if float(max_val) < threshold:
            return None

        h, w = template.shape[:2]
        center_x = int(max_loc[0] + w / 2)
        center_y = int(max_loc[1] + h / 2)

        if debug_enabled:
            try:
                vis = screenshot.copy()
                cv2.rectangle(vis, max_loc, (max_loc[0] + w, max_loc[1] + h), (0, 0, 255), 2)
                cv2.circle(vis, (center_x, center_y), 5, (0, 255, 0), -1)
                out_dbg = DATA_DIR / "debug" / f"vision_debug_{template_name}_{int(time.time())}.jpg"
                out_dbg.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(out_dbg), vis, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            except Exception:
                pass
        return center_x, center_y
    except Exception:
        return None


def click_template(template_name: str, fallback_point: Optional[str] = None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    try:
        with config_lock:
            vision_enabled = bool(config.get("vision_enabled", False))
            fallback_manual = bool(config.get("vision_fallback_manual", True))

        hwnd = resolve_target_window()
        if not hwnd:
            return False, "NO_TARGET_WINDOW", None

        if vision_enabled:
            point = find_template_in_client(hwnd, template_name)
            if point:
                ok, msg, payload = click_in_game(point[0], point[1], label=f"vision_{template_name}", use_manual_offset=False)
                return ok, msg, payload

        if fallback_manual and fallback_point:
            geom = get_window_geometry(hwnd)
            if not geom:
                return False, "NO_GEOMETRY", None
            cw = geom.client_rect["right"] - geom.client_rect["left"]
            ch = geom.client_rect["bottom"] - geom.client_rect["top"]
            ratio = TEST_POINT_PRESETS.get(fallback_point, (0.50, 0.50))
            px, py = resolve_click_point(fallback_point, ratio, cw, ch)
            return click_in_game(px, py, label=f"fallback_{fallback_point}", use_manual_offset=False)

        return False, "TEMPLATE_NOT_FOUND", None
    except Exception as e:
        return False, f"ERROR: {e}", None


def draw_overlay_rect(root: tk.Tk, x: int, y: int, w: int, h: int, color: str = "#ff3333", duration_ms: int = 1300) -> None:
    overlay = tk.Toplevel(root)
    overlay.overrideredirect(True)
    overlay.attributes("-topmost", True)
    try:
        overlay.attributes("-alpha", 0.35)
    except Exception:
        pass
    overlay.geometry(f"{max(1, w)}x{max(1, h)}+{x}+{y}")
    canvas = tk.Canvas(overlay, bg="black", highlightthickness=0)
    canvas.pack(fill=tk.BOTH, expand=True)
    canvas.create_rectangle(2, 2, max(3, w - 2), max(3, h - 2), outline=color, width=4)
    overlay.after(duration_ms, overlay.destroy)


def draw_overlay_point(root: tk.Tk, x: int, y: int, duration_ms: int = 1100) -> None:
    draw_overlay_rect(root, x - 10, y - 10, 20, 20, color="#ff0000", duration_ms=duration_ms)


def export_diagnostics_json() -> Path:
    with config_lock:
        cfg = dict(config)
    out = {
        "config": cfg,
        "last_selected_candidate": runtime_state.get("last_selected_candidate"),
        "last_candidates": runtime_state.get("last_candidates"),
        "last_click": runtime_state.get("last_click"),
        "click_history": list(runtime_state.get("click_history", [])),
    }
    path = SETTINGS_PATH.with_name(f"diagnostics_{int(time.time())}.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# =========================
# FLASK ROUTES
# =========================

def toggle_pause_from_hotkey() -> None:
    runtime_state["paused"] = not bool(runtime_state.get("paused"))
    log_event(f"Pause: {'ON' if runtime_state['paused'] else 'OFF'}")


def register_hotkey() -> None:
    if keyboard is None:
        log_event("Brak modułu 'keyboard' -> globalny hotkey wyłączony.")
        return

    with config_lock:
        hotkey = str(config.get("hotkey", "f9")).strip().lower() or "f9"

    old_key = str(runtime_state.get("hotkey_registered_key", "")).strip().lower()
    if runtime_state.get("hotkey_registered") and old_key == hotkey:
        return

    try:
        if runtime_state.get("hotkey_registered"):
            keyboard.clear_all_hotkeys()
        keyboard.add_hotkey(hotkey, toggle_pause_from_hotkey)
        runtime_state["hotkey_registered"] = True
        runtime_state["hotkey_registered_key"] = hotkey
        log_event(f"Globalny hotkey aktywny: {hotkey.upper()}")
    except Exception as exc:
        log_event(f"Nie udało się aktywować hotkey '{hotkey}': {exc}")


def _api_blocked_response():
    return jsonify({"ok": False, "status": "PAUSED_OR_DISABLED", "paused": bool(runtime_state.get("paused"))}), 423

def configure_flask_logging() -> None:
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.logger.setLevel(logging.ERROR)


@app.route("/health", methods=["GET"])
def health():
    with config_lock:
        api_enabled = bool(config.get("api_enabled", True))
        hotkey = str(config.get("hotkey", "f9")).strip().lower() or "f9"
    return jsonify({"status": "OK", "paused": bool(runtime_state.get("paused")), "api_enabled": api_enabled, "hotkey": hotkey}), 200


@app.route("/quiz/solved", methods=["GET"])
def quiz_solved_route():
    solved_at = float(runtime_state.get("last_quiz_solved_at") or 0.0)
    return jsonify({
        "ok": True,
        "solved_at": solved_at,
        "age_ms": int((time.time() - solved_at) * 1000) if solved_at else None,
        "last_result": runtime_state.get("last_quiz_solved_result"),
        "watcher_state": runtime_state.get("watcher_state", "IDLE"),
    }), 200


@app.route("/fullscreen", methods=["GET", "POST", "OPTIONS"])
def fullscreen():
    if request.method == "OPTIONS":
        return make_response("", 200)
    with config_lock:
        api_enabled = bool(config.get("api_enabled", True))
    if runtime_state.get("paused") or not api_enabled:
        return _api_blocked_response()
    hwnd = resolve_target_window()
    if not hwnd:
        return "NO_WINDOW", 404
    try:
        ensure_window_ready(hwnd)
        ctypes.windll.user32.keybd_event(0x7A, 0, 0, 0)
        time.sleep(0.02)
        ctypes.windll.user32.keybd_event(0x7A, 0, 0x0002, 0)
        return "OK", 200
    except Exception:
        return "ERROR", 500


@app.route("/launch", methods=["POST", "OPTIONS"])
def launch_target_app():
    if request.method == "OPTIONS":
        return make_response("", 200)
    with config_lock:
        api_enabled = bool(config.get("api_enabled", True))
    if runtime_state.get("paused") or not api_enabled:
        return _api_blocked_response()
    with config_lock:
        cmd = str(config.get("launch_command", "")).strip()
    if not cmd:
        return "NO_LAUNCH_COMMAND", 400
    try:
        subprocess.Popen(cmd, shell=True)
        return "OK", 200
    except Exception:
        return "ERROR", 500


@app.route("/click", methods=["GET", "OPTIONS"])
def click_route():
    if request.method == "OPTIONS":
        return make_response("", 200)
    with config_lock:
        api_enabled = bool(config.get("api_enabled", True))
    if runtime_state.get("paused") or not api_enabled:
        return _api_blocked_response()
    try:
        vx = request.args.get("vx")
        vy = request.args.get("vy")
        no_offset = request.args.get("no_offset") in {"1", "true", "yes"}
        answer_click = request.args.get("answer_click") in {"1", "true", "yes"}
        ax = request.args.get("ax")
        ay = request.args.get("ay")
        x_abs = request.args.get("x")
        y_abs = request.args.get("y")

        if vx is not None and vy is not None:
            ok, msg, payload = click_in_game(float(vx), float(vy), label="api_v", use_manual_offset=not no_offset, is_answer_click=answer_click)
            return jsonify({"status": msg, "ok": ok, "payload": payload}), (200 if ok else 404)

        hwnd = resolve_target_window()
        geom = get_window_geometry(hwnd) if hwnd else None

        if not geom:
            return jsonify({"status": "NO_WINDOW_GEOMETRY", "ok": False}), 404

        if ax is not None and ay is not None:
            rel_x = float(ax) - geom.client_origin["x"]
            rel_y = float(ay) - geom.client_origin["y"]
            ok, msg, payload = click_in_game(rel_x, rel_y, label="api_ax", use_manual_offset=not no_offset, is_answer_click=answer_click)
            return jsonify({"status": msg, "ok": ok, "payload": payload}), (200 if ok else 404)

        if x_abs is not None and y_abs is not None:
            rel_x = float(x_abs) - geom.client_origin["x"]
            rel_y = float(y_abs) - geom.client_origin["y"]
            ok, msg, payload = click_in_game(rel_x, rel_y, label="api_x", use_manual_offset=not no_offset, is_answer_click=answer_click)
            return jsonify({"status": msg, "ok": ok, "payload": payload}), (200 if ok else 404)

        return jsonify({"status": "MISSING_COORDINATES", "ok": False}), 400

    except Exception as e:
        return jsonify({"status": "ERROR", "error": str(e)}), 500


@app.route("/debug/window", methods=["GET"])
def debug_window():
    hwnd = resolve_target_window()
    if not hwnd:
        return jsonify({"status": "NO_WINDOW"}), 404
    geom = get_window_geometry(hwnd)
    return jsonify({"status": "OK", "hwnd": hwnd, "geometry": asdict(geom) if geom else None, "candidate": runtime_state.get("last_selected_candidate")})


@app.route("/debug/candidates", methods=["GET"])
def debug_candidates():
    candidates = [asdict(c) for c in list_window_candidates()]
    return jsonify({"status": "OK", "count": len(candidates), "candidates": candidates})


@app.route("/debug/screenshot", methods=["GET"])
def debug_screenshot():
    hwnd = resolve_target_window()
    if not hwnd:
        return jsonify({"status": "NO_WINDOW"}), 404
    path = capture_client_area(hwnd)
    if not path:
        return jsonify({"status": "CAPTURE_FAILED"}), 500
    return send_file(path, mimetype="image/png")


@app.route("/test_points", methods=["POST"])
def test_points():
    with config_lock:
        api_enabled = bool(config.get("api_enabled", True))
    if runtime_state.get("paused") or not api_enabled:
        return _api_blocked_response()
    hwnd = resolve_target_window()
    geom = get_window_geometry(hwnd) if hwnd else None
    if not geom:
        return jsonify({"status": "NO_WINDOW"}), 404
    cw = geom.client_rect["right"] - geom.client_rect["left"]
    ch = geom.client_rect["bottom"] - geom.client_rect["top"]

    results = []
    for name, (rx, ry) in TEST_POINT_PRESETS.items():
        px, py = resolve_click_point(name, (rx, ry), cw, ch)
        ok, msg, payload = click_in_game(px, py, label=f"test_{name}")
        results.append({"name": name, "ok": ok, "msg": msg, "payload": payload})
        time.sleep(0.12)
    return jsonify({"status": "OK", "results": results})


@app.route("/pause", methods=["POST", "OPTIONS"])
def pause_route():
    if request.method == "OPTIONS":
        return make_response("", 200)
    runtime_state["paused"] = not bool(runtime_state.get("paused"))
    return jsonify({"ok": True, "paused": bool(runtime_state.get("paused"))}), 200


@app.route("/vision/click", methods=["GET", "OPTIONS"])
def vision_click_route():
    if request.method == "OPTIONS":
        return make_response("", 200)
    with config_lock:
        api_enabled = bool(config.get("api_enabled", True))
    if runtime_state.get("paused") or not api_enabled:
        return _api_blocked_response()
    try:
        name = (request.args.get("name") or "").strip().lower()
        mapping = {"answer": "answer", "confirm": "confirm"}
        if name not in mapping:
            return jsonify({"ok": False, "status": "UNSUPPORTED_TEMPLATE"}), 400
        ok, msg, payload = click_template(name, fallback_point=mapping[name])
        return jsonify({"ok": ok, "status": msg, "payload": payload}), (200 if ok else 404)
    except Exception as e:
        return jsonify({"ok": False, "status": "ERROR", "error": str(e)}), 500


@app.route("/vision/pre_captcha", methods=["GET"])
def vision_pre_captcha_route():
    hwnd = resolve_target_window()
    if not hwnd:
        return jsonify({"ok": False, "status": "NO_TARGET_WINDOW"}), 404
    return jsonify(find_pre_captcha_button(hwnd))


@app.route("/vision/click_pre_captcha", methods=["GET"])
@app.route("/pre_captcha/click", methods=["GET"])
def vision_click_pre_captcha_route():
    result = click_pre_captcha_button()
    return jsonify(result), (200 if result.get("ok") else 404)


@app.route("/vision/debug_geometry", methods=["GET"])
def vision_debug_geometry_route():
    hwnd = resolve_target_window()
    if not hwnd:
        return jsonify({"ok": False, "status": "NO_TARGET_WINDOW"}), 404
    geom = get_window_geometry(hwnd)
    if not geom:
        return jsonify({"ok": False, "status": "NO_GEOMETRY"}), 404
    client_w = geom.client_rect["right"] - geom.client_rect["left"]
    client_h = geom.client_rect["bottom"] - geom.client_rect["top"]
    return jsonify({
        "ok": True,
        "hwnd": hwnd,
        "window_rect": geom.window_rect,
        "client_rect": geom.client_rect,
        "client_origin": geom.client_origin,
        "client_width": client_w,
        "client_height": client_h,
        "last_match": runtime_state.get("last_match"),
        "last_click": runtime_state.get("last_click"),
    })


@app.route("/vision/debug_coordinate", methods=["GET"])
def vision_debug_coordinate_route():
    hwnd = resolve_target_window()
    if not hwnd:
        return jsonify({"ok": False, "status": "NO_TARGET_WINDOW"}), 404
    x = float(request.args.get("x", "100"))
    y = float(request.args.get("y", "100"))
    return jsonify(validate_click_coordinate_pipeline(hwnd, x, y))


@app.route("/vision/answers", methods=["GET"])
def vision_answers_route():
    hwnd = resolve_target_window()
    if not hwnd:
        return jsonify({"ok": False, "answers": [], "status": "NO_TARGET_WINDOW"}), 404
    return jsonify(find_captcha_answers(hwnd))


@app.route("/vision/confirm", methods=["GET"])
def vision_confirm_route():
    hwnd = resolve_target_window()
    if not hwnd:
        return jsonify({"ok": False, "status": "NO_TARGET_WINDOW"}), 404
    return jsonify(find_confirm_button(hwnd))


@app.route("/vision/click_answer", methods=["GET"])
def vision_click_answer_route():
    hwnd = resolve_target_window()
    if not hwnd:
        return jsonify({"ok": False, "status": "NO_TARGET_WINDOW"}), 404
    idx = int(request.args.get("index", "0"))
    result = find_captcha_answers(hwnd)
    answers = result.get("answers", [])
    if idx < 0 or idx >= len(answers):
        return jsonify({"ok": False, "status": "ANSWER_INDEX_OUT_OF_RANGE", "answers": answers}), 404
    click = click_detected_box(hwnd, answers[idx], f"vision_answer_{idx}")
    return jsonify({**click, "answer": answers[idx]})


@app.route("/vision/click_answer_by_text", methods=["GET"])
def vision_click_answer_by_text_route():
    hwnd = resolve_target_window()
    if not hwnd:
        return jsonify({"ok": False, "status": "NO_TARGET_WINDOW"}), 404
    query = (request.args.get("text") or "").strip().lower()
    result = find_captcha_answers(hwnd)
    for answer in result.get("answers", []):
        if query and query in str(answer.get("text", "")).lower():
            click = click_detected_box(hwnd, answer, "vision_answer_text")
            return jsonify({**click, "answer": answer})
    return jsonify({"ok": False, "status": "ANSWER_TEXT_NOT_FOUND", "answers": result.get("answers", [])}), 404


@app.route("/vision/click_confirm", methods=["GET"])
def vision_click_confirm_route():
    hwnd = resolve_target_window()
    if not hwnd:
        return jsonify({"ok": False, "status": "NO_TARGET_WINDOW"}), 404
    found = find_confirm_button(hwnd)
    if not found.get("found"):
        return jsonify({"ok": False, "status": "CONFIRM_NOT_FOUND", "confirm": found}), 404
    return jsonify(click_detected_box(hwnd, found, "vision_confirm"))


@app.route("/vision/solve_captcha", methods=["GET"])
@app.route("/captcha/solve", methods=["GET"])
def vision_solve_captcha_route():
    hwnd = resolve_target_window()
    if not hwnd:
        return jsonify({"ok": False, "status": "NO_TARGET_WINDOW"}), 404
    result = solve_visible_captcha_until_clear(hwnd)
    return jsonify(result), (200 if result.get("ok") else 404)


@app.route("/vision/capture_debug", methods=["GET"])
def vision_capture_debug_route():
    hwnd = resolve_target_window()
    if not hwnd:
        return jsonify({"ok": False, "status": "NO_TARGET_WINDOW"}), 404
    cap = capture_client_area_robust(hwnd)
    if not cap.get("image"):
        return jsonify(cap), 500
    ensure_data_dirs()
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    kind = "ok" if cap.get("ok") else "failed"
    folder = DATA_DIR / "captures" / ("raw" if kind == "ok" else "failed")
    path = folder / f"{ts}_capture_{kind}_{cap.get('method','unknown')}.jpg"
    path = save_screenshot_image(cap["image"], path)
    return jsonify({"ok": True, "path": str(path), "quality": cap.get("quality"), "method": cap.get("method")})


@app.route("/vision/debug_monitors", methods=["GET"])
def vision_debug_monitors_route():
    hwnd = resolve_target_window()
    geom = get_window_geometry(hwnd) if hwnd else None
    monitors = []
    if mss is not None:
        try:
            with mss.mss() as sct:
                monitors = [dict(m) for m in sct.monitors]
        except Exception:
            monitors = []
    return jsonify({"ok": True, "hwnd": hwnd, "selected_geometry": asdict(geom) if geom else None, "mss_monitors": monitors})


def summarize_detection_box(box: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not box:
        return None
    return {
        "found": bool(box.get("found", True)),
        "x": box.get("x"),
        "y": box.get("y"),
        "w": box.get("w"),
        "h": box.get("h"),
        "center_x": box.get("center_x"),
        "center_y": box.get("center_y"),
        "method": box.get("method"),
        "status": box.get("status"),
        "confidence": box.get("confidence", box.get("score")),
    }


def collect_vision_scan_state() -> Dict[str, Any]:
    hwnd = resolve_target_window()
    state: Dict[str, Any] = {
        "ok": bool(hwnd),
        "hwnd": hwnd,
        "watcher_state": runtime_state.get("watcher_state", "IDLE"),
        "watcher_running": bool(runtime_state.get("watcher_running")),
        "capture_method": runtime_state.get("capture_method"),
        "last_ocr_texts": runtime_state.get("last_ocr_texts", []),
        "last_dataset_event": runtime_state.get("last_dataset_event"),
        "last_quiz_debug": runtime_state.get("last_quiz_debug"),
    }
    geom = get_window_geometry(hwnd) if hwnd else None
    if geom:
        state["window"] = {
            "client_origin": dict(geom.client_origin),
            "client_rect": dict(geom.client_rect),
            "window_rect": dict(geom.window_rect),
        }
    if not hwnd:
        state["status"] = "NO_TARGET_WINDOW"
        return state

    pre = find_pre_captcha_button(hwnd)
    state["pre_captcha"] = summarize_detection_box(pre)
    cap = capture_client_area_robust(hwnd)
    state["capture"] = {k: v for k, v in cap.items() if k != "image"}
    image = cap.get("image")
    if image is None:
        state["status"] = cap.get("status", "CAPTURE_FAILED")
        return state

    raw_layout = find_quiz_layout_by_cv(image)
    layout = revive_rejected_quiz_layout(image, raw_layout)
    answers = list(layout.get("answers") or [])
    confirm = layout.get("confirm") or find_confirm_button(hwnd)
    quiz_box = None
    if answers:
        left = min(int(a.get("x", 0)) for a in answers)
        top = min(int(a.get("y", 0)) for a in answers)
        right = max(int(a.get("x", 0)) + int(a.get("w", 0)) for a in answers)
        bottom = max(int(a.get("y", 0)) + int(a.get("h", 0)) for a in answers)
        if confirm:
            bottom = max(bottom, int(confirm.get("y", bottom)) + int(confirm.get("h", 0)))
        quiz_box = {"x": left, "y": top, "w": right - left, "h": bottom - top}

    state.update({
        "status": "OK",
        "quiz_detected": bool(answers),
        "quiz_box": quiz_box,
        "answers_count": len(answers),
        "answer_boxes": [summarize_detection_box(a) for a in answers],
        "confirm": summarize_detection_box(confirm),
        "layout_method": layout.get("method"),
        "layout_status": layout.get("status"),
        "raw_layout_status": raw_layout.get("status"),
        "raw_validation": raw_layout.get("validation"),
    })
    return state


def log_vision_scan_state() -> Dict[str, Any]:
    state = collect_vision_scan_state()
    log_event(
        "[Quiz Solver] Skan stanu: "
        f"quiz={state.get('quiz_detected')} "
        f"answers={state.get('answers_count', 0)} "
        f"confirm={bool((state.get('confirm') or {}).get('found'))} "
        f"hwnd={state.get('hwnd')}"
    )
    log_event(f"[Quiz Solver] Bounding box quizu: {state.get('quiz_box')}")
    log_event(f"[Quiz Solver] Bounding box odpowiedzi: {state.get('answer_boxes')}")
    log_event(f"[Quiz Solver] Bounding box Potwierdzam: {state.get('confirm')}")
    log_event(f"[Quiz Solver] Offset monitora/okna: {state.get('window')}")
    return state


@app.route("/vision/scan_state", methods=["GET"])
def vision_scan_state_route():
    return jsonify(collect_vision_scan_state())


@app.route("/vision/dataset_stats", methods=["GET"])
def vision_dataset_stats_route():
    ensure_data_dirs()
    count = lambda p: len([f for f in p.glob("*") if f.suffix.lower() in {".png", ".jpg", ".jpeg"}])
    return jsonify({"ok": True, "precaptcha": count(DATA_DIR/"dataset/images/precaptcha"), "answers": count(DATA_DIR/"dataset/images/answers"), "confirm": count(DATA_DIR/"dataset/images/confirm"), "unknown": count(DATA_DIR/"dataset/images/unknown"), "failed": count(DATA_DIR/"captures/failed")})




def vision_watcher_tick() -> None:
    if runtime_state.get("paused"):
        runtime_state["watcher_state"] = "PAUSED"
        return
    hwnd = resolve_target_window()
    if not hwnd:
        runtime_state["watcher_state"] = "IDLE"
        return
    now = time.time()
    should_log_scan = now - float(runtime_state.get("last_quiz_scan_log_ts", 0.0) or 0.0) > 8.0
    if should_log_scan:
        runtime_state["last_quiz_scan_log_ts"] = now
        log_event("[Margoclicker] Wywołuję funkcję wykrywania quizu: find_pre_captcha_button")
    pre = find_pre_captcha_button(hwnd)
    if pre.get("found"):
        log_event("[Margoclicker] Quiz wykryty")
        runtime_state["watcher_state"] = "PRECAPTCHA_VISIBLE"
        if bool(config.get("vision_auto_click_precaptcha", True)):
            log_event("[Margoclicker] Klikam odpowiedź / rozwiązuję quiz")
            res = click_pre_captcha_button()
            if res.get("ok"):
                runtime_state["watcher_state"] = "PRECAPTCHA_CLICKED"
    elif pre.get("status") == "CAPTCHA_CHALLENGE_VISIBLE" and bool(config.get("vision_auto_solve_captcha", True)):
        log_event("[Margoclicker] Quiz wykryty")
        log_event("[Margoclicker] Odpowiedzi wykryte")
        log_event("[Margoclicker] Klikam odpowiedź / rozwiązuję quiz")
        runtime_state["watcher_state"] = "ANSWERS_VISIBLE"
        solve_visible_captcha_until_clear(hwnd)
    elif should_log_scan:
        log_event("[Margoclicker] Quiz niewykryty")
    if runtime_state.get("force_answers_scan"):
        runtime_state["force_answers_scan"] = False
        runtime_state["watcher_state"] = "ANSWERS_VISIBLE"
        if bool(config.get("vision_auto_solve_captcha", True)):
            log_event("[Margoclicker] Wywołuję funkcję wykrywania quizu: solve_visible_captcha_until_clear")
            solve_visible_captcha_until_clear(hwnd)
        else:
            log_event("[Margoclicker] Wywołuję funkcję wykrywania quizu: find_captcha_answers")
            find_captcha_answers(hwnd)
    conf = find_confirm_button(hwnd)
    if conf.get("found"):
        runtime_state["watcher_state"] = "CONFIRM_VISIBLE"
        if bool(config.get("vision_auto_click_confirm", False)):
            click_detected_box(hwnd, conf, "watcher_confirm")
            runtime_state["watcher_state"] = "DONE"
            time.sleep(max(0.1,float(config.get("vision_click_cooldown_ms",2000))/1000.0))
            runtime_state["watcher_state"] = "COOLDOWN"
    if runtime_state.get("watcher_state") not in {"COOLDOWN","DONE"}:
        runtime_state["watcher_state"] = "IDLE"


def start_watcher() -> None:
    if runtime_state.get("watcher_running"):
        log_event("[Margoclicker] Watcher aktywny")
        return
    log_event("[Margoclicker] Start głównej pętli OCR")
    runtime_state["watcher_running"] = True
    def _loop():
        log_event("[Margoclicker] Watcher aktywny")
        while runtime_state.get("watcher_running"):
            try:
                vision_watcher_tick()
            except Exception as exc:
                log_event(f"Watcher error: {exc}")
            time.sleep(max(0.05, float(config.get("vision_watch_interval_ms",300))/1000.0))
    t=threading.Thread(target=_loop, daemon=True)
    runtime_state["watcher_thread"] = t
    t.start()


def stop_watcher() -> None:
    runtime_state["watcher_running"] = False
    runtime_state["watcher_state"] = "STOPPED"


def run_storage_cleanup_once() -> None:
    result = cleanup_old_files()
    if result.get("deleted"):
        log_event(
            f"Cleanup screenshotów: usunięto {result['deleted']} plików, zwolniono {result['freed_mb']} MB"
        )


def start_storage_cleanup_scheduler() -> None:
    def _loop() -> None:
        while True:
            try:
                run_storage_cleanup_once()
            except Exception as exc:
                log_event(f"Cleanup screenshotów nieudany: {exc}")
            time.sleep(SCREENSHOT_CLEANUP_INTERVAL_SECONDS)

    threading.Thread(target=_loop, daemon=True).start()


# =========================
# GUI
# =========================

def _normalize_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(DEFAULT_CONFIG)
    normalized.update(raw or {})

    # migracja kompatybilności
    if not normalized.get("launch_command") and normalized.get("app_path"):
        normalized["launch_command"] = str(normalized.get("app_path", ""))
    if "click_without_mouse_move" in (raw or {}) and "use_virtual_mouse" not in (raw or {}):
        normalized["use_virtual_mouse"] = bool((raw or {}).get("click_without_mouse_move"))

    normalized["window_selection_mode"] = str(normalized.get("window_selection_mode", "auto")).lower().strip()
    if normalized["window_selection_mode"] not in {"auto", "title", "process", "picked"}:
        normalized["window_selection_mode"] = "auto"

    normalized["window_keyword"] = str(normalized.get("window_keyword", "margonem")).strip() or "margonem"
    normalized["launch_command"] = str(normalized.get("launch_command", "")).strip()
    normalized["browser_url_hint"] = str(normalized.get("browser_url_hint", "")).strip()
    normalized["target_process_name"] = str(normalized.get("target_process_name", "")).strip().lower()
    normalized["target_window_title"] = str(normalized.get("target_window_title", "")).strip()
    normalized["target_class_name"] = str(normalized.get("target_class_name", "")).strip()
    normalized["target_monitor_name"] = str(normalized.get("target_monitor_name", "")).strip()
    normalized["hotkey"] = str(normalized.get("hotkey", "f9")).strip().lower() or "f9"
    normalized["vision_templates_dir"] = str(normalized.get("vision_templates_dir", "templates")).strip() or "templates"
    normalized["vision_enabled"] = bool(normalized.get("vision_enabled", False))
    normalized["vision_auto_install"] = bool(normalized.get("vision_auto_install", True))
    normalized["vision_debug"] = bool(normalized.get("vision_debug", False))
    normalized["SAVE_DEBUG_SCREENSHOTS"] = bool(normalized.get("SAVE_DEBUG_SCREENSHOTS", False))
    normalized["save_debug_screenshots"] = bool(normalized.get("save_debug_screenshots", normalized["SAVE_DEBUG_SCREENSHOTS"]))
    normalized["vision_debug_save"] = bool(normalized.get("vision_debug_save", normalized["save_debug_screenshots"]))
    normalized["vision_dataset_enabled"] = bool(normalized.get("vision_dataset_enabled", False))
    normalized["vision_save_failed_samples"] = bool(normalized.get("vision_save_failed_samples", False))
    normalized["vision_fallback_manual"] = bool(normalized.get("vision_fallback_manual", True))
    normalized["use_virtual_mouse"] = bool(normalized.get("use_virtual_mouse", True))
    normalized["restore_window_before_click"] = bool(normalized.get("restore_window_before_click", False))
    normalized["allow_physical_click_fallback"] = bool(normalized.get("allow_physical_click_fallback", False))
    normalized["vision_auto_solve_captcha"] = bool(normalized.get("vision_auto_solve_captcha", True))
    normalized["captcha_solver_auto_confirm"] = bool(normalized.get("captcha_solver_auto_confirm", True))
    normalized["captcha_solver_require_question_ocr"] = bool(normalized.get("captcha_solver_require_question_ocr", False))
    normalized["captcha_solver_click_all_targets"] = bool(normalized.get("captcha_solver_click_all_targets", True))
    normalized["captcha_solver_unselect_wrong_answers"] = bool(normalized.get("captcha_solver_unselect_wrong_answers", False))
    normalized["captcha_solver_save_debug"] = bool(normalized.get("captcha_solver_save_debug", normalized["save_debug_screenshots"]))
    normalized["captcha_solver_strict_quiz_window"] = bool(normalized.get("captcha_solver_strict_quiz_window", True))
    normalized["captcha_solver_default_symbol"] = str(normalized.get("captcha_solver_default_symbol", "star")).strip().lower() or "star"
    normalized["captcha_solver_click_delay_ms"] = int(normalized.get("captcha_solver_click_delay_ms", 320))
    normalized["captcha_solver_confirm_delay_ms"] = int(normalized.get("captcha_solver_confirm_delay_ms", 650))
    normalized["captcha_solver_answer_delay_min_ms"] = int(normalized.get("captcha_solver_answer_delay_min_ms", normalized.get("captcha_solver_click_delay_ms", 420)))
    normalized["captcha_solver_answer_delay_max_ms"] = int(normalized.get("captcha_solver_answer_delay_max_ms", max(normalized["captcha_solver_answer_delay_min_ms"], normalized["captcha_solver_answer_delay_min_ms"] + 530)))
    normalized["captcha_solver_confirm_delay_min_ms"] = int(normalized.get("captcha_solver_confirm_delay_min_ms", normalized.get("captcha_solver_confirm_delay_ms", 900)))
    normalized["captcha_solver_confirm_delay_max_ms"] = int(normalized.get("captcha_solver_confirm_delay_max_ms", max(normalized["captcha_solver_confirm_delay_min_ms"], normalized["captcha_solver_confirm_delay_min_ms"] + 900)))
    if normalized["captcha_solver_answer_delay_max_ms"] < normalized["captcha_solver_answer_delay_min_ms"]:
        normalized["captcha_solver_answer_delay_min_ms"], normalized["captcha_solver_answer_delay_max_ms"] = normalized["captcha_solver_answer_delay_max_ms"], normalized["captcha_solver_answer_delay_min_ms"]
    if normalized["captcha_solver_confirm_delay_max_ms"] < normalized["captcha_solver_confirm_delay_min_ms"]:
        normalized["captcha_solver_confirm_delay_min_ms"], normalized["captcha_solver_confirm_delay_max_ms"] = normalized["captcha_solver_confirm_delay_max_ms"], normalized["captcha_solver_confirm_delay_min_ms"]
    normalized["captcha_solver_same_quiz_cooldown_ms"] = int(normalized.get("captcha_solver_same_quiz_cooldown_ms", 6000))
    normalized["captcha_solver_debug_min_interval_ms"] = int(normalized.get("captcha_solver_debug_min_interval_ms", 2000))
    normalized["pre_captcha_green_fallback_enabled"] = bool(normalized.get("pre_captcha_green_fallback_enabled", True))
    normalized["vision_threshold"] = float(normalized.get("vision_threshold", 0.72))
    normalized["vision_ignore_right_panel_ratio"] = float(normalized.get("vision_ignore_right_panel_ratio", 0.84))
    if not 0.1 < normalized["vision_ignore_right_panel_ratio"] <= 1.0:
        normalized["vision_ignore_right_panel_ratio"] = 0.84
    normalized["vision_click_mode"] = str(normalized.get("vision_click_mode", "absolute")).strip().lower()
    if normalized["vision_click_mode"] not in {"absolute", "client", "virtual"}:
        normalized["vision_click_mode"] = "absolute"
    normalized["pre_captcha_button_text"] = str(normalized.get("pre_captcha_button_text", "Rozwiąż teraz")).strip() or "Rozwiąż teraz"

    for key in ["manual_offset_y", "answer_offset_y"]:
        normalized[key] = float(normalized.get(key, 0.0))
    for key in ["target_hwnd_last", "target_pid", "target_monitor_index", "click_hold_ms_min", "click_hold_ms_max", "click_jitter_px"]:
        normalized[key] = int(normalized.get(key, 0))

    return normalized


def load_settings_from_disk() -> None:
    if not SETTINGS_PATH.exists():
        return
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            with config_lock:
                config.update(_normalize_config(saved))
    except Exception as e:
        log_event(f"Nie udało się wczytać ustawień: {e}")


def save_settings_to_disk() -> None:
    with config_lock:
        payload = dict(config)
    try:
        SETTINGS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log_event(f"Nie udało się zapisać ustawień: {e}")


def launch_gui() -> None:
    if ctk is not None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

    root = tk.Tk()
    root.title("Margoclicker")
    root.geometry("1120x860")
    root.configure(bg="#05070d")

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Dark.TFrame", background="#05070d")
    style.configure("Card.TFrame", background="#0f172a", relief="flat")
    style.configure("Dark.TLabel", background="#05070d", foreground="#e5e7eb")
    style.configure("Card.TLabel", background="#0f172a", foreground="#e5e7eb")
    style.configure("Muted.TLabel", background="#0f172a", foreground="#94a3b8")
    style.configure("Accent.TButton", background="#22d3ee", foreground="#05070d", padding=(10, 7))
    style.configure("Lime.TButton", background="#a3e635", foreground="#05070d", padding=(10, 7))
    style.configure("Danger.TButton", background="#fb7185", foreground="#05070d", padding=(10, 7))
    style.configure("Dark.TButton", background="#111827", foreground="#f8fafc", padding=(10, 7))
    style.configure("Dark.TEntry", fieldbackground="#111827", foreground="#f9fafb", insertcolor="#f9fafb")
    style.configure("Dark.TCheckbutton", background="#0f172a", foreground="#e5e7eb")
    style.configure("TLabelframe", background="#0f172a", foreground="#e5e7eb", bordercolor="#1f2937")
    style.configure("TLabelframe.Label", background="#0f172a", foreground="#22d3ee")
    style.configure("Treeview", background="#020617", fieldbackground="#020617", foreground="#f8fafc", rowheight=25, bordercolor="#1f2937")
    style.configure("Treeview.Heading", background="#0f172a", foreground="#22d3ee", relief="flat")
    style.configure("TCombobox", fieldbackground="#111827", background="#111827", foreground="#f8fafc", arrowcolor="#22d3ee")
    style.map("Dark.TButton", background=[("active", "#1f2937")])
    style.map("Accent.TButton", background=[("active", "#67e8f9")])
    style.map("Lime.TButton", background=[("active", "#bef264")])
    style.map("Danger.TButton", background=[("active", "#fda4af")])
    style.map("Treeview", background=[("selected", "#164e63")], foreground=[("selected", "#f8fafc")])

    frame = ttk.Frame(root, style="Dark.TFrame", padding=12)
    frame.pack(fill=tk.BOTH, expand=True)

    with config_lock:
        cfg = dict(config)

    status_var = tk.StringVar(value="Status: gotowy")
    watcher_var = tk.StringVar(value="watcher_state: IDLE")
    ocr_var = tk.StringVar(value="OCR: []")
    ds_var = tk.StringVar(value="Dataset: -")
    license_cfg = load_license_config()
    license_status_var = tk.StringVar(value=f"Licencja: {license_cfg.get('last_status') or 'Aktywna'}")
    license_expiry_var = tk.StringVar(value=f"Wygasa: {license_cfg.get('last_expires_at') or 'brak danych'}")
    api_status_var = tk.StringVar(value=f"API: {license_cfg.get('api_base_url') or 'http://localhost:3000'}")
    activity_var = tk.StringVar(value="Program: aktywny" if runtime_state.get("watcher_running") else "Program: zatrzymany")
    screenshot_count_var = tk.StringVar(value="Screenshoty: liczenie...")
    screenshot_size_var = tk.StringVar(value="Rozmiar: liczenie...")
    keyword_var = tk.StringVar(value=cfg["window_keyword"])
    launch_cmd_var = tk.StringVar(value=cfg.get("launch_command", ""))
    url_hint_var = tk.StringVar(value=cfg.get("browser_url_hint", ""))
    offset_var = tk.StringVar(value=str(cfg.get("manual_offset_y", 0.0)))
    answer_offset_var = tk.StringVar(value=str(cfg.get("answer_offset_y", 0.0)))
    mode_var = tk.StringVar(value=cfg.get("window_selection_mode", "auto"))
    process_var = tk.StringVar(value=cfg.get("target_process_name", ""))
    hotkey_var = tk.StringVar(value=cfg.get("hotkey", "f9"))
    hold_min_var = tk.StringVar(value=str(cfg.get("click_hold_ms_min", 60)))
    hold_max_var = tk.StringVar(value=str(cfg.get("click_hold_ms_max", 130)))
    jitter_var = tk.StringVar(value=str(cfg.get("click_jitter_px", 3)))
    vision_threshold_var = tk.StringVar(value=str(cfg.get("vision_threshold", 0.85)))

    use_client_var = tk.BooleanVar(value=bool(cfg.get("use_client_area", True)))
    api_enabled_var = tk.BooleanVar(value=bool(cfg.get("api_enabled", True)))
    restore_var = tk.BooleanVar(value=bool(cfg.get("restore_window_before_click", False)))
    hide_console_var = tk.BooleanVar(value=bool(cfg.get("hide_console_on_start", True)))
    manual_off_var = tk.BooleanVar(value=bool(cfg.get("manual_offset_enabled", True)))
    answer_off_var = tk.BooleanVar(value=bool(cfg.get("answer_offset_enabled", False)))
    no_random_var = tk.BooleanVar(value=bool(cfg.get("disable_randomness", False)))
    click_msg_var = tk.BooleanVar(value=bool(cfg.get("use_virtual_mouse", True)))
    vision_enabled_var = tk.BooleanVar(value=bool(cfg.get("vision_enabled", True)))
    debug_screenshots_var = tk.BooleanVar(value=should_save_debug_screenshots(cfg))
    debug_mode_var = tk.BooleanVar(value=False)
    debug_open_var = tk.BooleanVar(value=False)

    def refresh_license_labels(result: Optional[Dict[str, Any]] = None) -> None:
        cfg_now = load_license_config()
        status = (result or {}).get("status") or cfg_now.get("last_status") or "brak"
        expires = (result or {}).get("expires_at") or cfg_now.get("last_expires_at") or "brak danych"
        active = (result or {}).get("active")
        if active is True:
            status_text = "Aktywna"
        elif status == "expired":
            status_text = "Wygasła"
        elif status in {"missing", "invalid"}:
            status_text = "Brak"
        else:
            status_text = str(status)
        license_status_var.set(f"Licencja: {status_text}")
        license_expiry_var.set(f"Wygasa: {expires}")
        api_status_var.set(f"API: {cfg_now.get('api_base_url') or 'http://localhost:3000'}")

    def refresh_screenshot_count() -> None:
        try:
            files = list(iter_screenshot_files())
            count = len(files)
            total_mb = sum(path.stat().st_size for path in files if path.exists()) / (1024 * 1024)
            screenshot_count_var.set(f"Screenshoty: {count}")
            screenshot_size_var.set(f"Rozmiar: {total_mb:.1f} MB")
        except Exception as exc:
            screenshot_count_var.set(f"Screenshoty: błąd liczenia ({exc})")
            screenshot_size_var.set("Rozmiar: błąd")

    def check_license_gui(change_key: bool = False) -> None:
        def _worker() -> None:
            result = verify_license(allow_prompt=False)
            root.after(0, lambda: refresh_license_labels(result))
            root.after(0, lambda: status_var.set(result.get("message", "Sprawdzono licencję")))

        threading.Thread(target=_worker, daemon=True).start()

    def start_program_gui() -> None:
        log_event("[Margoclicker] Start kliknięty")
        log_event("[Margoclicker] Uruchamiam istniejący watcher/OCR loop")
        start_watcher()
        activity_var.set("Program: aktywny")
        status_var.set("Status: program uruchomiony")

    def stop_program_gui() -> None:
        stop_watcher()
        activity_var.set("Program: zatrzymany")
        status_var.set("Status: program zatrzymany")

    def pause_resume_gui() -> None:
        runtime_state["paused"] = not bool(runtime_state.get("paused"))
        state = "pauza" if runtime_state["paused"] else "wznowiono"
        status_var.set(f"Status: {state}")
        log_event(f"Program: {state}")

    def clear_screenshots_gui() -> None:
        result = cleanup_old_files(max_age_hours=0, max_files=0)
        refresh_screenshot_count()
        status_var.set(
            f"Wyczyszczono screenshoty: {result['deleted']} plików, {result['freed_mb']} MB"
        )

    header = ttk.Frame(frame, style="Dark.TFrame")
    header.pack(fill=tk.X, pady=(0, 10))
    tk.Label(
        header,
        text="Margoclicker",
        bg="#05070d",
        fg="#f8fafc",
        font=("Segoe UI", 24, "bold"),
    ).pack(anchor="w")
    tk.Label(
        header,
        text="Panel aktywacji, OCR i automatyzacji w stylu Margoneuro",
        bg="#05070d",
        fg="#94a3b8",
        font=("Segoe UI", 10),
    ).pack(anchor="w", pady=(2, 0))

    top_grid = ttk.Frame(frame, style="Dark.TFrame")
    top_grid.pack(fill=tk.X, pady=(0, 8))

    license_frame = ttk.LabelFrame(top_grid, text="LICENCJA", padding=10)
    license_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
    ttk.Label(license_frame, textvariable=license_status_var, style="Card.TLabel").pack(anchor="w")
    ttk.Label(license_frame, textvariable=license_expiry_var, style="Muted.TLabel").pack(anchor="w", pady=(3, 0))
    ttk.Label(license_frame, textvariable=api_status_var, style="Muted.TLabel").pack(anchor="w", pady=(3, 8))
    ttk.Button(license_frame, text="Wprowadź / zmień klucz", command=lambda: check_license_gui(True), style="Accent.TButton").pack(side=tk.LEFT)
    ttk.Button(license_frame, text="Sprawdź licencję", command=lambda: check_license_gui(False), style="Dark.TButton").pack(side=tk.LEFT, padx=8)

    control_frame = ttk.LabelFrame(top_grid, text="STEROWANIE", padding=10)
    control_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))
    ttk.Label(control_frame, textvariable=activity_var, style="Card.TLabel").pack(anchor="w")
    ttk.Button(control_frame, text="Start", command=start_program_gui, style="Lime.TButton").pack(side=tk.LEFT, pady=(10, 0))
    ttk.Button(control_frame, text="Stop", command=stop_program_gui, style="Danger.TButton").pack(side=tk.LEFT, padx=8, pady=(10, 0))
    ttk.Button(control_frame, text="Pauza / Wznów", command=pause_resume_gui, style="Dark.TButton").pack(side=tk.LEFT, pady=(10, 0))

    shot_frame = ttk.LabelFrame(frame, text="OCR / SCREENSHOTY", padding=10)
    shot_frame.pack(fill=tk.X, pady=4)
    ttk.Checkbutton(
        shot_frame,
        text="Zapisuj screenshoty debug",
        variable=debug_screenshots_var,
        style="Dark.TCheckbutton",
    ).pack(side=tk.LEFT)
    ttk.Label(shot_frame, textvariable=screenshot_count_var, style="Card.TLabel").pack(side=tk.LEFT, padx=14)
    ttk.Label(shot_frame, textvariable=screenshot_size_var, style="Card.TLabel").pack(side=tk.LEFT, padx=(0, 14))
    ttk.Button(shot_frame, text="Wyczyść screenshoty", command=clear_screenshots_gui, style="Dark.TButton").pack(side=tk.LEFT, padx=8)
    ttk.Checkbutton(frame, text="Tryb debug", variable=debug_mode_var, style="Dark.TCheckbutton").pack(anchor="w", pady=(0, 8))

    window_frame = ttk.LabelFrame(frame, text="OKNO", padding=8)
    window_frame.pack(fill=tk.X, pady=4)
    ttk.Label(window_frame, text="Fraza tytułu:", style="Dark.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Entry(window_frame, textvariable=keyword_var, width=34, style="Dark.TEntry").grid(row=0, column=1, sticky="w", padx=6)
    ttk.Label(window_frame, text="Tryb wyboru:", style="Dark.TLabel").grid(row=0, column=2, sticky="w")
    ttk.Combobox(window_frame, textvariable=mode_var, values=["auto", "title", "process", "picked"], width=12).grid(row=0, column=3, sticky="w", padx=6)

    vision_frame = ttk.LabelFrame(frame, text="OCR / WYKRYWANIE", padding=8)
    vision_frame.pack(fill=tk.X, pady=4)
    ttk.Checkbutton(vision_frame, text="Wykrywanie OCR aktywne", variable=vision_enabled_var, style="Dark.TCheckbutton").grid(row=0, column=0, sticky="w")
    ttk.Label(vision_frame, text="Czułość:", style="Dark.TLabel").grid(row=0, column=1, sticky="w", padx=(12, 0))
    ttk.Entry(vision_frame, textvariable=vision_threshold_var, width=8, style="Dark.TEntry").grid(row=0, column=2, sticky="w", padx=6)

    debug_frame = ttk.LabelFrame(frame, text="NARZĘDZIA DEBUG", padding=8)
    debug_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 4))
    ttk.Checkbutton(debug_frame, text="Pokaż szczegóły debug", variable=debug_open_var, style="Dark.TCheckbutton").pack(anchor="w", pady=(0, 6))
    debug_content = ttk.Frame(debug_frame, style="Dark.TFrame")
    debug_content.pack(fill=tk.BOTH, expand=True)
    diag_frame = ttk.LabelFrame(debug_content, text="Diagnostyka")
    diag_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

    columns = ("hwnd", "title", "proc", "class", "monitor", "score", "client")
    tree = ttk.Treeview(diag_frame, columns=columns, show="headings", height=12)
    for col, w in [("hwnd", 90), ("title", 300), ("proc", 120), ("class", 150), ("monitor", 150), ("score", 70), ("client", 110)]:
        tree.heading(col, text=col)
        tree.column(col, width=w, anchor="w")
    tree.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    logs_frame = ttk.LabelFrame(frame, text="LOGI", padding=8)
    logs_frame.pack(fill=tk.BOTH, expand=False, pady=(6, 4))
    log_box = scrolledtext.ScrolledText(
        logs_frame,
        height=9,
        bg="#020617",
        fg="#e5e7eb",
        insertbackground="#22d3ee",
        relief=tk.FLAT,
    )
    log_box.pack(fill=tk.BOTH, expand=False)
    log_box.tag_config("info", foreground="#f8fafc")
    log_box.tag_config("success", foreground="#a3e635")
    log_box.tag_config("warning", foreground="#facc15")
    log_box.tag_config("error", foreground="#fb7185")

    def gui_log(msg: str) -> None:
        lowered = msg.lower()
        if "błąd" in lowered or "error" in lowered or "nieud" in lowered:
            tag = "error"
        elif "ostrze" in lowered or "warning" in lowered:
            tag = "warning"
        elif "ok" in lowered or "aktywn" in lowered or "wznowiono" in lowered or "zapisano" in lowered:
            tag = "success"
        else:
            tag = "info"
        log_box.insert(tk.END, msg + "\n", tag)
        log_box.see(tk.END)
        status_var.set(f"Status: {msg}")

    runtime_state["log_hook"] = gui_log

    def save_from_gui() -> None:
        try:
            parsed_off = float(offset_var.get().strip())
            parsed_answer_off = float(answer_offset_var.get().strip())
            hold_min = int(float(hold_min_var.get().strip()))
            hold_max = int(float(hold_max_var.get().strip()))
            jitter_px = int(float(jitter_var.get().strip()))
            vision_threshold = float(vision_threshold_var.get().strip())
        except ValueError:
            status_var.set("Offset/Hold/Jitter muszą być liczbami")
            return

        with config_lock:
            config["window_keyword"] = keyword_var.get().strip() or "margonem"
            config["launch_command"] = launch_cmd_var.get().strip()
            config["browser_url_hint"] = url_hint_var.get().strip()
            config["hotkey"] = hotkey_var.get().strip().lower() or "f9"
            config["window_selection_mode"] = mode_var.get().strip() or "auto"
            config["target_process_name"] = process_var.get().strip().lower()
            config["api_enabled"] = bool(api_enabled_var.get())
            config["use_client_area"] = bool(use_client_var.get())
            config["restore_window_before_click"] = bool(restore_var.get())
            config["manual_offset_enabled"] = bool(manual_off_var.get())
            config["manual_offset_y"] = parsed_off
            config["answer_offset_enabled"] = bool(answer_off_var.get())
            config["answer_offset_y"] = parsed_answer_off
            config["click_hold_ms_min"] = max(1, hold_min)
            config["click_hold_ms_max"] = max(1, hold_max)
            config["click_jitter_px"] = max(0, jitter_px)
            config["disable_randomness"] = bool(no_random_var.get())
            config["use_virtual_mouse"] = bool(click_msg_var.get())
            config["vision_enabled"] = bool(vision_enabled_var.get())
            config["vision_threshold"] = max(0.0, min(1.0, vision_threshold))
            config["SAVE_DEBUG_SCREENSHOTS"] = bool(debug_screenshots_var.get())
            config["save_debug_screenshots"] = bool(debug_screenshots_var.get())
            config["vision_debug_save"] = bool(debug_screenshots_var.get())
            config["captcha_solver_save_debug"] = bool(debug_screenshots_var.get())
            config["hide_console_on_start"] = bool(hide_console_var.get())
        save_settings_to_disk()
        register_hotkey()
        status_var.set("Status: zapisano ustawienia")

    def refresh_candidates() -> None:
        tree.delete(*tree.get_children())
        candidates = list_window_candidates()
        for c in candidates:
            cw = c.client_rect["right"] - c.client_rect["left"]
            ch = c.client_rect["bottom"] - c.client_rect["top"]
            tree.insert("", tk.END, values=(c.hwnd, c.title[:70], c.process_name, c.class_name, f"{c.monitor_index}:{c.monitor_name}", f"{c.score:.1f}", f"{cw}x{ch}"))
        status_var.set(f"Status: wykryto okna: {len(candidates)}")

    def pick_under_cursor_gui() -> None:
        status_var.set("Masz 3 sekundy aby najechać kursorem na docelowe okno...")

        def worker():
            c = pick_window_under_cursor()
            if c:
                status_var.set(f"Wybrane okno: {c.title[:60]} | {c.process_name} | hwnd={c.hwnd} | mon={c.monitor_index}")
                log_event(f"PICKED hwnd={c.hwnd} pid={c.pid} proc={c.process_name} monitor={c.monitor_name}")
            else:
                status_var.set("Nie udało się wybrać okna pod kursorem")

        threading.Thread(target=worker, daemon=True).start()

    def test_highlight_client() -> None:
        hwnd = resolve_target_window()
        geom = get_window_geometry(hwnd) if hwnd else None
        if not geom:
            status_var.set("Brak okna do zaznaczenia")
            return
        cw = geom.client_rect["right"] - geom.client_rect["left"]
        ch = geom.client_rect["bottom"] - geom.client_rect["top"]
        draw_overlay_rect(root, geom.client_origin["x"], geom.client_origin["y"], cw, ch)
        status_var.set("Zaznaczono client-area")

    def test_show_click_point() -> None:
        hwnd = resolve_target_window()
        geom = get_window_geometry(hwnd) if hwnd else None
        if not geom:
            status_var.set("Brak okna")
            return
        cw = geom.client_rect["right"] - geom.client_rect["left"]
        ch = geom.client_rect["bottom"] - geom.client_rect["top"]
        cx, cy = int(cw * 0.5), int(ch * 0.5)
        point = client_to_screen_point(hwnd, cx, cy)
        if not point:
            status_var.set("ClientToScreen fail")
            return
        draw_overlay_point(root, point[0], point[1])
        status_var.set(f"Punkt kliknięcia: {point[0]}, {point[1]}")

    def snapshot_client() -> None:
        hwnd = resolve_target_window()
        if not hwnd:
            status_var.set("Brak okna")
            return
        p = capture_client_area(hwnd)
        if p:
            status_var.set(f"Zapisano screenshot: {p.name}")
        else:
            status_var.set("Nie udało się zrobić screenshotu")

    def calibrate_active() -> None:
        if sys.platform != "win32":
            status_var.set("Kalibracja tylko Windows")
            return
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        geom = get_window_geometry(hwnd) if hwnd else None
        if not geom:
            status_var.set("Brak aktywnego okna do kalibracji")
            return
        cw = geom.client_rect["right"] - geom.client_rect["left"]
        ch = geom.client_rect["bottom"] - geom.client_rect["top"]
        calib = {
            "client_width": cw,
            "client_height": ch,
            "origin_x": geom.client_origin["x"],
            "origin_y": geom.client_origin["y"],
            "monitor_name": geom.monitor_name,
            "monitor_index": geom.monitor_index,
            "preset_points": {k: {"x": int(cw * v[0]), "y": int(ch * v[1])} for k, v in TEST_POINT_PRESETS.items()},
        }
        with config_lock:
            config["calibration"] = calib
        save_settings_to_disk()
        status_var.set(f"Kalibracja zapisana: {cw}x{ch}, monitor {geom.monitor_index}")

    def run_test_points() -> None:
        hwnd = resolve_target_window()
        geom = get_window_geometry(hwnd) if hwnd else None
        if not geom:
            status_var.set("Brak okna")
            return
        cw = geom.client_rect["right"] - geom.client_rect["left"]
        ch = geom.client_rect["bottom"] - geom.client_rect["top"]
        for name, (rx, ry) in TEST_POINT_PRESETS.items():
            px, py = resolve_click_point(name, (rx, ry), cw, ch)
            ok, msg, payload = click_in_game(px, py, label=f"gui_{name}")
            log_event(f"TEST {name}: {msg} -> {payload}")
            if not ok:
                status_var.set(f"Test punktu {name} nieudany")
                return
            time.sleep(0.12)
        status_var.set("Test wszystkich punktów zakończony")

    def test_pre_zapadki() -> None:
        result = click_pre_captcha_button()
        if result.get("ok"):
            match = result.get("match") or {}
            conf = match.get("score")
            cx = match.get("center_x")
            cy = match.get("center_y")
            if isinstance(conf, (float, int)) and cx is not None and cy is not None:
                status_var.set(f"Kliknięto Rozwiąż teraz | confidence: {conf:.2f} | {cx},{cy}")
            else:
                status_var.set("Kliknięto Rozwiąż teraz")
        else:
            status_var.set("Nie znaleziono przycisku")

    def detect_pre_zapadki() -> None:
        hwnd = resolve_target_window()
        if not hwnd:
            status_var.set("Brak okna")
            return
        log_event("[Margoclicker] Wywołuję funkcję wykrywania quizu: find_pre_captcha_button")
        result = find_pre_captcha_button(hwnd)
        log_event(f"Detect pre-captcha: {result}")
        conf = result.get("score")
        if result.get("found"):
            status_var.set(f"Tylko wykryj: box=({result.get('x')},{result.get('y')},{result.get('w')},{result.get('h')}) confidence={float(conf):.2f}" if isinstance(conf, (float, int)) else "Tylko wykryj: znaleziono")
        else:
            status_var.set("Nie znaleziono przycisku")

    def test_solve_captcha() -> None:
        hwnd = resolve_target_window()
        if not hwnd:
            status_var.set("Brak okna")
            return
        log_event("[Margoclicker] Wywołuję funkcję wykrywania quizu: solve_visible_captcha_until_clear")
        result = solve_visible_captcha_until_clear(hwnd)
        log_event(f"Solve captcha: {result}")
        last_result = result.get("last_result") if isinstance(result.get("last_result"), dict) else result
        required = (last_result.get("required") or {}).get("symbol", "?")
        debug_paths = last_result.get("debug_paths") or runtime_state.get("last_quiz_debug") or {}
        if result.get("ok"):
            status_var.set(f"Quiz rozwiazany | symbol={required} | debug={Path(str(debug_paths.get('annotated',''))).name}")
        else:
            status_var.set(f"Quiz blad: {last_result.get('status', result.get('status'))} | symbol={required} | debug={Path(str(debug_paths.get('annotated',''))).name}")

    def force_answers_scan_gui() -> None:
        log_event("[Margoclicker] Wywołuję funkcję wykrywania quizu: force_answers_scan")
        runtime_state["force_answers_scan"] = True
        vision_watcher_tick()

    def scan_state_gui() -> None:
        state = log_vision_scan_state()
        status_var.set(
            f"Skan: quiz={state.get('quiz_detected')} "
            f"odpowiedzi={state.get('answers_count', 0)} "
            f"potwierdzam={bool((state.get('confirm') or {}).get('found'))}"
        )

    def debug_geometry() -> None:
        hwnd = resolve_target_window()
        geom = get_window_geometry(hwnd) if hwnd else None
        if not geom:
            status_var.set("Brak geometrii")
            return
        cw = geom.client_rect["right"] - geom.client_rect["left"]
        ch = geom.client_rect["bottom"] - geom.client_rect["top"]
        status_var.set(f"Debug geometrii: hwnd={hwnd} client_origin={geom.client_origin} client={cw}x{ch}")

    def show_last_click() -> None:
        last = runtime_state.get("last_click")
        status_var.set(f"Ostatni klik: {last}" if last else "Brak historii kliknięć")

    def toggle_pause_gui() -> None:
        runtime_state["paused"] = not bool(runtime_state.get("paused"))
        state = "pauza" if runtime_state["paused"] else "wznowiono"
        status_var.set(f"Status: {state}")
        log_event(f"Program: {state}")

    def export_diag() -> None:
        p = export_diagnostics_json()
        status_var.set(f"Wyeksportowano diagnostykę: {p.name}")

    def save_manual_point(point_key: str, point_label: str) -> None:
        hwnd = resolve_target_window()
        geom = get_window_geometry(hwnd) if hwnd else None
        if not geom:
            status_var.set("Brak okna do zapisu punktu")
            return

        status_var.set(f"Kliknij teraz punkt: {point_label} (max 10s)")

        def _worker() -> None:
            clicked = wait_for_left_click(10.0)
            if not clicked:
                root.after(0, lambda: status_var.set(f"Timeout: nie kliknięto punktu {point_label}"))
                return
            sx, sy = clicked
            cpt = screen_to_client_point(hwnd, sx, sy)
            if not cpt:
                root.after(0, lambda: status_var.set("Nie udało się przeliczyć punktu"))
                return
            cx, cy = int(cpt[0]), int(cpt[1])
            with config_lock:
                points = config.setdefault("manual_click_points", {})
                points[point_key] = {"x": cx, "y": cy}
            save_settings_to_disk()
            persisted = get_manual_click_point(point_key)
            if persisted and persisted.get("x") == cx and persisted.get("y") == cy:
                root.after(0, lambda: status_var.set(f"Zapisano {point_label}: client=({cx}, {cy})"))
            else:
                root.after(0, lambda: status_var.set(f"Błąd weryfikacji zapisu {point_label}"))

        threading.Thread(target=_worker, daemon=True).start()

    def test_answer_click() -> None:
        hwnd = resolve_target_window()
        geom = get_window_geometry(hwnd) if hwnd else None
        if not geom:
            status_var.set("Brak okna")
            return
        cw = geom.client_rect["right"] - geom.client_rect["left"]
        ch = geom.client_rect["bottom"] - geom.client_rect["top"]
        px, py = resolve_click_point("answer", (0.50, 0.56), cw, ch)
        ok, msg, payload = click_in_game(px, py, label="gui_answer", use_manual_offset=False, is_answer_click=True)
        status_var.set(f"Odpowiedź klik: {payload}" if ok else f"Odpowiedź błąd: {msg}")

    def test_confirm_click() -> None:
        hwnd = resolve_target_window()
        geom = get_window_geometry(hwnd) if hwnd else None
        if not geom:
            status_var.set("Brak okna")
            return
        cw = geom.client_rect["right"] - geom.client_rect["left"]
        ch = geom.client_rect["bottom"] - geom.client_rect["top"]
        px, py = resolve_click_point("confirm", (0.50, 0.63), cw, ch)
        ok, msg, payload = click_in_game(px, py, label="gui_confirm", use_manual_offset=False)
        status_var.set(f"Potwierdź klik: {payload}" if ok else f"Potwierdź błąd: {msg}")

    actions_frame = ttk.LabelFrame(frame, text="AKCJE", padding=8)
    actions_frame.pack(fill=tk.X, pady=4)
    ttk.Button(actions_frame, text="Kliknij Rozwiąż teraz (AI)", command=test_pre_zapadki).pack(side=tk.LEFT)
    ttk.Button(actions_frame, text="Tylko wykryj (AI)", command=detect_pre_zapadki).pack(side=tk.LEFT, padx=8)
    ttk.Button(actions_frame, text="Rozwiaz quiz (AI)", command=test_solve_captcha).pack(side=tk.LEFT, padx=8)

    clicking_frame = ttk.LabelFrame(frame, text="KLIKANIE", padding=8)
    clicking_frame.pack(fill=tk.X, pady=4)
    ttk.Checkbutton(clicking_frame, text="Użyj wirtualnej myszki w tle", variable=click_msg_var).pack(side=tk.LEFT)
    ttk.Checkbutton(clicking_frame, text="Aktywuj okno przed kliknięciem", variable=restore_var, style="Dark.TCheckbutton").pack(side=tk.LEFT, padx=12)
    ttk.Label(clicking_frame, text="Jitter px:", style="Dark.TLabel").pack(side=tk.LEFT, padx=(8, 2))
    ttk.Entry(clicking_frame, textvariable=jitter_var, width=6, style="Dark.TEntry").pack(side=tk.LEFT)

    system_frame = ttk.LabelFrame(frame, text="SYSTEM", padding=8)
    system_frame.pack(fill=tk.X, pady=4)
    ttk.Button(system_frame, text="Pauza / Wznów", command=toggle_pause_gui, style="Dark.TButton").pack(side=tk.LEFT)
    ttk.Button(system_frame, text="Zapisz ustawienia", command=save_from_gui).pack(side=tk.LEFT, padx=8)
    ttk.Button(system_frame, text="Debug geometrii", command=debug_geometry).pack(side=tk.LEFT, padx=8)
    ttk.Button(system_frame, text="Debug monitory", command=lambda: log_event(f"Monitors: {vision_debug_monitors_route().get_json()}" )).pack(side=tk.LEFT, padx=6)
    ttk.Button(system_frame, text="Skan stanu", command=scan_state_gui, style="Dark.TButton").pack(side=tk.LEFT, padx=6)
    ttk.Button(system_frame, text="Wymuś skan odpowiedzi", command=force_answers_scan_gui).pack(side=tk.LEFT, padx=6)
    ttk.Button(system_frame, text="Otwórz folder data", command=lambda: subprocess.Popen(["explorer", str(DATA_DIR)]) if sys.platform=="win32" else log_event(str(DATA_DIR))).pack(side=tk.LEFT, padx=6)
    ttk.Label(frame, textvariable=status_var, style="Dark.TLabel").pack(anchor="w", pady=(8, 0))
    ttk.Label(frame, textvariable=watcher_var, style="Dark.TLabel").pack(anchor="w")
    ttk.Label(frame, textvariable=ocr_var, style="Dark.TLabel").pack(anchor="w")
    ttk.Label(frame, textvariable=ds_var, style="Dark.TLabel").pack(anchor="w")

    debug_buttons_a = ttk.Frame(debug_content, style="Dark.TFrame")
    debug_buttons_a.pack(fill=tk.X, pady=(6, 2))
    ttk.Button(debug_buttons_a, text="Pokaż wykryte okna", command=refresh_candidates).pack(side=tk.LEFT)
    ttk.Button(debug_buttons_a, text="Wskaż okno myszą", command=pick_under_cursor_gui).pack(side=tk.LEFT, padx=6)
    ttk.Button(debug_buttons_a, text="Test: zaznacz client-area", command=test_highlight_client).pack(side=tk.LEFT)
    ttk.Button(debug_buttons_a, text="Test: pokaż punkt kliknięcia", command=test_show_click_point).pack(side=tk.LEFT, padx=6)
    ttk.Button(debug_buttons_a, text="Zrzut client-area", command=snapshot_client).pack(side=tk.LEFT)
    ttk.Button(debug_buttons_a, text="Kalibracja aktywnego okna", command=calibrate_active).pack(side=tk.LEFT, padx=6)

    debug_buttons_b = ttk.Frame(debug_content, style="Dark.TFrame")
    debug_buttons_b.pack(fill=tk.X, pady=(2, 2))
    ttk.Button(debug_buttons_b, text="Test wszystkie punkty", command=run_test_points).pack(side=tk.LEFT)
    ttk.Button(debug_buttons_b, text="Test odpowiedź", command=test_answer_click).pack(side=tk.LEFT, padx=6)
    ttk.Button(debug_buttons_b, text="Test potwierdź", command=test_confirm_click).pack(side=tk.LEFT, padx=6)
    ttk.Button(debug_buttons_b, text="pokaż współrzędne", command=show_last_click).pack(side=tk.LEFT, padx=6)
    ttk.Button(debug_buttons_b, text="Eksport diagnostyki", command=export_diag).pack(side=tk.LEFT)

    debug_buttons_c = ttk.Frame(debug_content, style="Dark.TFrame")
    debug_buttons_c.pack(fill=tk.X, pady=(2, 4))
    ttk.Button(debug_buttons_c, text="Ustaw punkt: Pre zapadka", command=lambda: save_manual_point("pre_zapadki", "Pre zapadka")).pack(side=tk.LEFT)
    ttk.Button(debug_buttons_c, text="Ustaw punkt: Odpowiedź", command=lambda: save_manual_point("answer", "Odpowiedź")).pack(side=tk.LEFT, padx=6)
    ttk.Button(debug_buttons_c, text="Ustaw punkt: Potwierdź", command=lambda: save_manual_point("confirm", "Potwierdź")).pack(side=tk.LEFT)

    def toggle_debug_ui() -> None:
        show_debug = debug_mode_var.get()
        show_debug_content = show_debug and debug_open_var.get()
        if show_debug:
            debug_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 4))
        else:
            debug_frame.pack_forget()
        if show_debug_content:
            debug_content.pack(fill=tk.BOTH, expand=True)
        else:
            debug_content.pack_forget()

    debug_mode_var.trace_add("write", lambda *_: toggle_debug_ui())
    debug_open_var.trace_add("write", lambda *_: toggle_debug_ui())
    toggle_debug_ui()

    def refresh_runtime_ui():
        sel = runtime_state.get("last_selected_candidate") or {}
        activity_var.set("Program: aktywny" if runtime_state.get("watcher_running") else "Program: zatrzymany")
        refresh_screenshot_count()
        watcher_var.set(f"window={sel.get('title','-')[:30]} mon={sel.get('monitor_index','-')} origin={sel.get('client_origin',{})} capture={runtime_state.get('capture_method')} watcher_state={runtime_state.get('watcher_state')} watcher_running={runtime_state.get('watcher_running')}")
        ocr_var.set(f"last OCR: {runtime_state.get('last_ocr_texts', [])}")
        stats = vision_dataset_stats_route().get_json()
        ds_var.set(f"dataset last={runtime_state.get('last_dataset_event')} counts p/a/c/u/f={stats.get('precaptcha')}/{stats.get('answers')}/{stats.get('confirm')}/{stats.get('unknown')}/{stats.get('failed')}")
        root.after(1000, refresh_runtime_ui)

    refresh_license_labels()
    refresh_screenshot_count()
    save_from_gui()
    root.after(300, refresh_candidates)
    root.after(500, refresh_runtime_ui)
    root.mainloop()


def launch_gui_v2() -> None:
    if ctk is None:
        raise RuntimeError(
            "customtkinter jest wymagany dla nowego GUI Margoclickera. "
            "Zainstaluj: python -m pip install customtkinter"
        )

    colors = {
        "bg": "#0b0f1a",
        "card": "#0f172a",
        "card2": "#0f172a",
        "border": "#1b2333",
        "cyan": "#00f0ff",
        "success": "#22c55e",
        "danger": "#ef4444",
        "text": "#e5e7eb",
        "muted": "#e5e7eb",
        "warning": "#e5e7eb",
        "shadow": "#070b13",
    }

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.title("Margoclicker")
    root.geometry("1240x920")
    root.minsize(1080, 800)
    root.configure(fg_color=colors["bg"])

    bg_canvas = tk.Canvas(root, bg=colors["bg"], highlightthickness=0, bd=0)
    bg_canvas.place(relx=0, rely=0, relwidth=1, relheight=1)

    def draw_background(event=None) -> None:
        width = max(1, int(bg_canvas.winfo_width()))
        height = max(1, int(bg_canvas.winfo_height()))
        bg_canvas.delete("all")
        top = (11, 15, 26)
        bottom = (7, 10, 18)
        bands = max(80, height // 4)
        for i in range(bands):
            ratio = i / max(1, bands - 1)
            r = int(top[0] + (bottom[0] - top[0]) * ratio)
            g = int(top[1] + (bottom[1] - top[1]) * ratio)
            b = int(top[2] + (bottom[2] - top[2]) * ratio)
            y1 = int(height * i / bands)
            y2 = int(height * (i + 1) / bands) + 1
            bg_canvas.create_rectangle(0, y1, width, y2, fill=f"#{r:02x}{g:02x}{b:02x}", outline="")

        # Subtle dashboard grid, intentionally close to the background color.
        for x in range(0, width, 42):
            bg_canvas.create_line(x, 0, x, height, fill="#0d1320")
        for y in range(0, height, 42):
            bg_canvas.create_line(0, y, width, y, fill="#0d1320")

    bg_canvas.bind("<Configure>", draw_background)

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(
        "Neon.Treeview",
        background=colors["card"],
        fieldbackground=colors["card"],
        foreground=colors["text"],
        rowheight=26,
        bordercolor=colors["border"],
        relief="flat",
    )
    style.configure(
        "Neon.Treeview.Heading",
        background=colors["card"],
        foreground=colors["cyan"],
        relief="flat",
    )
    style.map("Neon.Treeview", background=[("selected", colors["card"])])

    with config_lock:
        cfg = dict(config)

    status_var = tk.StringVar(value="Status: gotowy")
    watcher_var = tk.StringVar(value="watcher_state: IDLE")
    ocr_var = tk.StringVar(value="OCR: []")
    ds_var = tk.StringVar(value="Dataset: -")
    license_cfg = load_license_config()
    license_status_var = tk.StringVar(value=f"Licencja: {license_cfg.get('last_status') or 'Aktywna'}")
    license_expiry_var = tk.StringVar(value=f"Wygasa: {license_cfg.get('last_expires_at') or 'brak danych'}")
    api_status_var = tk.StringVar(value=f"API: {license_cfg.get('api_base_url') or 'http://localhost:3000'}")
    activity_var = tk.StringVar(value="Program: aktywny" if runtime_state.get("watcher_running") else "Program: zatrzymany")
    screenshot_count_var = tk.StringVar(value="Screenshoty: liczenie...")
    screenshot_size_var = tk.StringVar(value="Rozmiar: liczenie...")
    keyword_var = tk.StringVar(value=cfg["window_keyword"])
    launch_cmd_var = tk.StringVar(value=cfg.get("launch_command", ""))
    url_hint_var = tk.StringVar(value=cfg.get("browser_url_hint", ""))
    offset_var = tk.StringVar(value=str(cfg.get("manual_offset_y", 0.0)))
    answer_offset_var = tk.StringVar(value=str(cfg.get("answer_offset_y", 0.0)))
    mode_var = tk.StringVar(value=cfg.get("window_selection_mode", "auto"))
    process_var = tk.StringVar(value=cfg.get("target_process_name", ""))
    hotkey_var = tk.StringVar(value=cfg.get("hotkey", "f9"))
    hold_min_var = tk.StringVar(value=str(cfg.get("click_hold_ms_min", 60)))
    hold_max_var = tk.StringVar(value=str(cfg.get("click_hold_ms_max", 130)))
    jitter_var = tk.StringVar(value=str(cfg.get("click_jitter_px", 3)))
    vision_threshold_var = tk.StringVar(value=str(cfg.get("vision_threshold", 0.85)))

    use_client_var = tk.BooleanVar(value=bool(cfg.get("use_client_area", True)))
    api_enabled_var = tk.BooleanVar(value=bool(cfg.get("api_enabled", True)))
    restore_var = tk.BooleanVar(value=bool(cfg.get("restore_window_before_click", False)))
    hide_console_var = tk.BooleanVar(value=bool(cfg.get("hide_console_on_start", True)))
    manual_off_var = tk.BooleanVar(value=bool(cfg.get("manual_offset_enabled", True)))
    answer_off_var = tk.BooleanVar(value=bool(cfg.get("answer_offset_enabled", False)))
    no_random_var = tk.BooleanVar(value=bool(cfg.get("disable_randomness", False)))
    click_msg_var = tk.BooleanVar(value=bool(cfg.get("use_virtual_mouse", True)))
    vision_enabled_var = tk.BooleanVar(value=bool(cfg.get("vision_enabled", True)))
    debug_screenshots_var = tk.BooleanVar(value=should_save_debug_screenshots(cfg))
    debug_open_var = tk.BooleanVar(value=False)

    tree = None
    log_box = None
    debug_content = None

    def normalize_license_status(status: str, active: Optional[bool] = None) -> str:
        if active is True and status == "trial":
            return "Trial"
        if active is True:
            return "Aktywna"
        labels = {
            "trial": "Trial",
            "active": "Aktywna",
            "expired": "Wygasła",
            "revoked": "Cofnięta",
            "missing": "Brak",
            "invalid": "Brak",
            "brak": "Brak",
        }
        return labels.get(str(status).lower(), str(status) or "Brak")

    def refresh_license_labels(result: Optional[Dict[str, Any]] = None) -> None:
        cfg_now = load_license_config()
        status = (result or {}).get("status") or cfg_now.get("last_status") or "brak"
        expires = (result or {}).get("expires_at") or cfg_now.get("last_expires_at") or "brak danych"
        active = (result or {}).get("active")
        license_status_var.set(f"Licencja: {normalize_license_status(str(status), active)}")
        license_expiry_var.set(f"Wygasa: {expires}")
        api_status_var.set(f"API: {cfg_now.get('api_base_url') or 'http://localhost:3000'}")

    def refresh_screenshot_count() -> None:
        try:
            files = list(iter_screenshot_files())
            count = len(files)
            total_mb = sum(path.stat().st_size for path in files if path.exists()) / (1024 * 1024)
            screenshot_count_var.set(f"Screenshoty: {count}")
            screenshot_size_var.set(f"Rozmiar: {total_mb:.1f} MB")
        except Exception as exc:
            screenshot_count_var.set(f"Screenshoty: błąd ({exc})")
            screenshot_size_var.set("Rozmiar: błąd")

    def check_license_gui(change_key: bool = False) -> None:
        if change_key:
            try:
                dialog = ctk.CTkInputDialog(
                    text="Licencja jest nieważna, wygasła albo cofnięta.\nWprowadź nowy klucz:",
                    title="Zmień klucz Margoclicker",
                )
                new_key = dialog.get_input()
            except Exception as exc:
                status_var.set(f"Nie udało się otworzyć okna klucza: {exc}")
                return

            if not new_key or not new_key.strip():
                status_var.set("Zmiana klucza anulowana")
                return

            update_saved_license_key(new_key.strip())

        def _worker() -> None:
            result = verify_license(allow_prompt=False)
            root.after(0, lambda: refresh_license_labels(result))
            root.after(0, lambda: status_var.set(result.get("message", "Sprawdzono licencję")))

        threading.Thread(target=_worker, daemon=True).start()

    def start_program_gui() -> None:
        log_event("[Margoclicker] Start kliknięty")
        log_event("[Margoclicker] Uruchamiam istniejący watcher/OCR loop")
        start_watcher()
        activity_var.set("Program: aktywny")
        status_var.set("Status: program uruchomiony")

    def stop_program_gui() -> None:
        stop_watcher()
        activity_var.set("Program: zatrzymany")
        status_var.set("Status: program zatrzymany")

    def pause_resume_gui() -> None:
        runtime_state["paused"] = not bool(runtime_state.get("paused"))
        state = "pauza" if runtime_state["paused"] else "wznowiono"
        status_var.set(f"Status: {state}")
        log_event(f"Program: {state}")

    def clear_screenshots_gui() -> None:
        result = cleanup_old_files(max_age_hours=0, max_files=0)
        refresh_screenshot_count()
        status_var.set(f"Wyczyszczono screenshoty: {result['deleted']} plików, {result['freed_mb']} MB")

    def save_from_gui() -> None:
        try:
            parsed_off = float(offset_var.get().strip())
            parsed_answer_off = float(answer_offset_var.get().strip())
            hold_min = int(float(hold_min_var.get().strip()))
            hold_max = int(float(hold_max_var.get().strip()))
            jitter_px = int(float(jitter_var.get().strip()))
            vision_threshold = float(vision_threshold_var.get().strip())
        except ValueError:
            status_var.set("Offset/Hold/Jitter muszą być liczbami")
            return

        with config_lock:
            config["window_keyword"] = keyword_var.get().strip() or "margonem"
            config["launch_command"] = launch_cmd_var.get().strip()
            config["browser_url_hint"] = url_hint_var.get().strip()
            config["hotkey"] = hotkey_var.get().strip().lower() or "f9"
            config["window_selection_mode"] = mode_var.get().strip() or "auto"
            config["target_process_name"] = process_var.get().strip().lower()
            config["api_enabled"] = bool(api_enabled_var.get())
            config["use_client_area"] = bool(use_client_var.get())
            config["restore_window_before_click"] = bool(restore_var.get())
            config["manual_offset_enabled"] = bool(manual_off_var.get())
            config["manual_offset_y"] = parsed_off
            config["answer_offset_enabled"] = bool(answer_off_var.get())
            config["answer_offset_y"] = parsed_answer_off
            config["click_hold_ms_min"] = max(1, hold_min)
            config["click_hold_ms_max"] = max(1, hold_max)
            config["click_jitter_px"] = max(0, jitter_px)
            config["disable_randomness"] = bool(no_random_var.get())
            config["use_virtual_mouse"] = bool(click_msg_var.get())
            config["vision_enabled"] = bool(vision_enabled_var.get())
            config["vision_threshold"] = max(0.0, min(1.0, vision_threshold))
            config["SAVE_DEBUG_SCREENSHOTS"] = bool(debug_screenshots_var.get())
            config["save_debug_screenshots"] = bool(debug_screenshots_var.get())
            config["vision_debug_save"] = bool(debug_screenshots_var.get())
            config["captcha_solver_save_debug"] = bool(debug_screenshots_var.get())
            config["hide_console_on_start"] = bool(hide_console_var.get())
        save_settings_to_disk()
        register_hotkey()
        status_var.set("Status: zapisano ustawienia")

    def refresh_candidates() -> None:
        if tree is None:
            return
        tree.delete(*tree.get_children())
        candidates = list_window_candidates()
        for c in candidates:
            cw = c.client_rect["right"] - c.client_rect["left"]
            ch = c.client_rect["bottom"] - c.client_rect["top"]
            tree.insert("", tk.END, values=(c.hwnd, c.title[:70], c.process_name, c.class_name, f"{c.monitor_index}:{c.monitor_name}", f"{c.score:.1f}", f"{cw}x{ch}"))
        status_var.set(f"Status: wykryto okna: {len(candidates)}")

    def pick_under_cursor_gui() -> None:
        status_var.set("Masz 3 sekundy, aby najechać kursorem na docelowe okno...")

        def worker() -> None:
            c = pick_window_under_cursor()
            if c:
                status_var.set(f"Wybrane okno: {c.title[:60]} | {c.process_name} | hwnd={c.hwnd} | mon={c.monitor_index}")
                log_event(f"PICKED hwnd={c.hwnd} pid={c.pid} proc={c.process_name} monitor={c.monitor_name}")
            else:
                status_var.set("Nie udało się wybrać okna pod kursorem")

        threading.Thread(target=worker, daemon=True).start()

    def test_highlight_client() -> None:
        hwnd = resolve_target_window()
        geom = get_window_geometry(hwnd) if hwnd else None
        if not geom:
            status_var.set("Brak okna do zaznaczenia")
            return
        cw = geom.client_rect["right"] - geom.client_rect["left"]
        ch = geom.client_rect["bottom"] - geom.client_rect["top"]
        draw_overlay_rect(root, geom.client_origin["x"], geom.client_origin["y"], cw, ch)
        status_var.set("Zaznaczono client-area")

    def test_show_click_point() -> None:
        hwnd = resolve_target_window()
        geom = get_window_geometry(hwnd) if hwnd else None
        if not geom:
            status_var.set("Brak okna")
            return
        cw = geom.client_rect["right"] - geom.client_rect["left"]
        ch = geom.client_rect["bottom"] - geom.client_rect["top"]
        point = client_to_screen_point(hwnd, int(cw * 0.5), int(ch * 0.5))
        if not point:
            status_var.set("Nie udało się przeliczyć punktu")
            return
        draw_overlay_point(root, point[0], point[1])
        status_var.set(f"Punkt kliknięcia: {point[0]}, {point[1]}")

    def snapshot_client() -> None:
        hwnd = resolve_target_window()
        if not hwnd:
            status_var.set("Brak okna")
            return
        p = capture_client_area(hwnd)
        status_var.set(f"Zapisano screenshot: {p.name}" if p else "Nie udało się zrobić screenshotu")

    def calibrate_active() -> None:
        if sys.platform != "win32":
            status_var.set("Kalibracja tylko Windows")
            return
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        geom = get_window_geometry(hwnd) if hwnd else None
        if not geom:
            status_var.set("Brak aktywnego okna do kalibracji")
            return
        cw = geom.client_rect["right"] - geom.client_rect["left"]
        ch = geom.client_rect["bottom"] - geom.client_rect["top"]
        with config_lock:
            config["calibration"] = {
                "client_width": cw,
                "client_height": ch,
                "origin_x": geom.client_origin["x"],
                "origin_y": geom.client_origin["y"],
                "monitor_name": geom.monitor_name,
                "monitor_index": geom.monitor_index,
                "preset_points": {k: {"x": int(cw * v[0]), "y": int(ch * v[1])} for k, v in TEST_POINT_PRESETS.items()},
            }
        save_settings_to_disk()
        status_var.set(f"Kalibracja zapisana: {cw}x{ch}, monitor {geom.monitor_index}")

    def run_test_points() -> None:
        hwnd = resolve_target_window()
        geom = get_window_geometry(hwnd) if hwnd else None
        if not geom:
            status_var.set("Brak okna")
            return
        cw = geom.client_rect["right"] - geom.client_rect["left"]
        ch = geom.client_rect["bottom"] - geom.client_rect["top"]
        for name, (rx, ry) in TEST_POINT_PRESETS.items():
            px, py = resolve_click_point(name, (rx, ry), cw, ch)
            ok, msg, payload = click_in_game(px, py, label=f"gui_{name}")
            log_event(f"TEST {name}: {msg} -> {payload}")
            if not ok:
                status_var.set(f"Test punktu {name} nieudany")
                return
            time.sleep(0.12)
        status_var.set("Test wszystkich punktów zakończony")

    def test_pre_zapadki() -> None:
        result = click_pre_captcha_button()
        if result.get("ok"):
            match = result.get("match") or {}
            conf = match.get("score")
            cx = match.get("center_x")
            cy = match.get("center_y")
            if isinstance(conf, (float, int)) and cx is not None and cy is not None:
                status_var.set(f"Kliknięto Rozwiąż teraz | confidence: {conf:.2f} | {cx},{cy}")
            else:
                status_var.set("Kliknięto Rozwiąż teraz")
        else:
            status_var.set("Nie znaleziono przycisku")

    def detect_pre_zapadki() -> None:
        hwnd = resolve_target_window()
        if not hwnd:
            status_var.set("Brak okna")
            return
        log_event("[Margoclicker] Wywołuję funkcję wykrywania quizu: find_pre_captcha_button")
        result = find_pre_captcha_button(hwnd)
        log_event(f"Detect pre-captcha: {result}")
        conf = result.get("score")
        if result.get("found"):
            status_var.set(f"Tylko wykryj: box=({result.get('x')},{result.get('y')},{result.get('w')},{result.get('h')}) confidence={float(conf):.2f}" if isinstance(conf, (float, int)) else "Tylko wykryj: znaleziono")
        else:
            status_var.set("Nie znaleziono przycisku")

    def test_solve_captcha() -> None:
        hwnd = resolve_target_window()
        if not hwnd:
            status_var.set("Brak okna")
            return
        log_event("[Margoclicker] Wywołuję funkcję wykrywania quizu: solve_visible_captcha_until_clear")
        result = solve_visible_captcha_until_clear(hwnd)
        log_event(f"Solve captcha: {result}")
        last_result = result.get("last_result") if isinstance(result.get("last_result"), dict) else result
        required = (last_result.get("required") or {}).get("symbol", "?")
        debug_paths = last_result.get("debug_paths") or runtime_state.get("last_quiz_debug") or {}
        if result.get("ok"):
            status_var.set(f"Quiz rozwiązany | symbol={required} | debug={Path(str(debug_paths.get('annotated',''))).name}")
        else:
            status_var.set(f"Quiz błąd: {last_result.get('status', result.get('status'))} | symbol={required} | debug={Path(str(debug_paths.get('annotated',''))).name}")

    def force_answers_scan_gui() -> None:
        log_event("[Margoclicker] Wywołuję funkcję wykrywania quizu: force_answers_scan")
        runtime_state["force_answers_scan"] = True
        vision_watcher_tick()

    def scan_state_gui() -> None:
        state = log_vision_scan_state()
        status_var.set(
            f"Skan: quiz={state.get('quiz_detected')} "
            f"odpowiedzi={state.get('answers_count', 0)} "
            f"potwierdzam={bool((state.get('confirm') or {}).get('found'))}"
        )

    def debug_geometry() -> None:
        hwnd = resolve_target_window()
        geom = get_window_geometry(hwnd) if hwnd else None
        if not geom:
            status_var.set("Brak geometrii")
            return
        cw = geom.client_rect["right"] - geom.client_rect["left"]
        ch = geom.client_rect["bottom"] - geom.client_rect["top"]
        status_var.set(f"Debug geometrii: hwnd={hwnd} client_origin={geom.client_origin} client={cw}x{ch}")

    def show_last_click() -> None:
        last = runtime_state.get("last_click")
        status_var.set(f"Ostatni klik: {last}" if last else "Brak historii kliknięć")

    def export_diag() -> None:
        p = export_diagnostics_json()
        status_var.set(f"Wyeksportowano diagnostykę: {p.name}")

    def save_manual_point(point_key: str, point_label: str) -> None:
        hwnd = resolve_target_window()
        geom = get_window_geometry(hwnd) if hwnd else None
        if not geom:
            status_var.set("Brak okna do zapisu punktu")
            return
        status_var.set(f"Kliknij teraz punkt: {point_label} (max 10s)")

        def _worker() -> None:
            clicked = wait_for_left_click(10.0)
            if not clicked:
                root.after(0, lambda: status_var.set(f"Timeout: nie kliknięto punktu {point_label}"))
                return
            sx, sy = clicked
            cpt = screen_to_client_point(hwnd, sx, sy)
            if not cpt:
                root.after(0, lambda: status_var.set("Nie udało się przeliczyć punktu"))
                return
            cx, cy = int(cpt[0]), int(cpt[1])
            with config_lock:
                points = config.setdefault("manual_click_points", {})
                points[point_key] = {"x": cx, "y": cy}
            save_settings_to_disk()
            root.after(0, lambda: status_var.set(f"Zapisano {point_label}: client=({cx}, {cy})"))

        threading.Thread(target=_worker, daemon=True).start()

    def test_answer_click() -> None:
        hwnd = resolve_target_window()
        geom = get_window_geometry(hwnd) if hwnd else None
        if not geom:
            status_var.set("Brak okna")
            return
        cw = geom.client_rect["right"] - geom.client_rect["left"]
        ch = geom.client_rect["bottom"] - geom.client_rect["top"]
        px, py = resolve_click_point("answer", (0.50, 0.56), cw, ch)
        ok, msg, payload = click_in_game(px, py, label="gui_answer", use_manual_offset=False, is_answer_click=True)
        status_var.set(f"Odpowiedź klik: {payload}" if ok else f"Odpowiedź błąd: {msg}")

    def test_confirm_click() -> None:
        hwnd = resolve_target_window()
        geom = get_window_geometry(hwnd) if hwnd else None
        if not geom:
            status_var.set("Brak okna")
            return
        cw = geom.client_rect["right"] - geom.client_rect["left"]
        ch = geom.client_rect["bottom"] - geom.client_rect["top"]
        px, py = resolve_click_point("confirm", (0.50, 0.63), cw, ch)
        ok, msg, payload = click_in_game(px, py, label="gui_confirm", use_manual_offset=False)
        status_var.set(f"Potwierdź klik: {payload}" if ok else f"Potwierdź błąd: {msg}")

    def ctk_card(parent, title: str, _accent: str = "cyan"):
        card = ctk.CTkFrame(
            parent,
            fg_color=colors["card"],
            border_width=1,
            border_color=colors["border"],
            corner_radius=20,
        )
        card.bind("<Enter>", lambda _event: card.configure(border_color=colors["border"]))
        card.bind("<Leave>", lambda _event: card.configure(border_color=colors["border"]))
        ctk.CTkLabel(
            card,
            text=title,
            text_color=colors["text"],
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w", padx=20, pady=(18, 5))
        return card

    def draw_round_rect(canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs) -> None:
        points = [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
        ]
        canvas.create_polygon(points, smooth=True, splinesteps=20, **kwargs)

    class NeonButton(tk.Canvas):
        def __init__(
            self,
            parent,
            text: str,
            command,
            variant: str = "secondary",
            width: int = 168,
            height: int = 42,
        ) -> None:
            super().__init__(
                parent,
                width=width,
                height=height,
                highlightthickness=0,
                bd=0,
                bg=colors["card"],
                cursor="hand2",
            )
            self.text = text
            self.command = command
            self.variant = variant
            self.w = width
            self.h = height
            self.hovered = False
            self.bind("<Enter>", self._enter)
            self.bind("<Leave>", self._leave)
            self.bind("<Button-1>", self._click)
            self._draw()

        def _palette(self) -> Tuple[str, str, str, str]:
            if self.variant == "primary":
                return colors["cyan"], colors["card"], colors["bg"], colors["cyan"]
            if self.variant == "danger":
                return colors["danger"], colors["danger"], colors["text"], colors["danger"]
            return colors["card"], colors["card"], colors["text"], colors["border"]

        def _draw(self) -> None:
            self.delete("all")
            left, right, text_color, border = self._palette()
            glow = colors["cyan"] if self.hovered and self.variant == "primary" else colors["card"]
            draw_round_rect(self, 2, 2, self.w - 2, self.h - 2, 15, fill=glow, outline=glow)
            if self.variant == "primary":
                for x in range(5, self.w - 5):
                    ratio = (x - 5) / max(1, self.w - 10)
                    c1 = tuple(int(left[i:i + 2], 16) for i in (1, 3, 5))
                    c2 = tuple(int(right[i:i + 2], 16) for i in (1, 3, 5))
                    r = int(c1[0] + (c2[0] - c1[0]) * ratio)
                    g = int(c1[1] + (c2[1] - c1[1]) * ratio)
                    b = int(c1[2] + (c2[2] - c1[2]) * ratio)
                    self.create_line(x, 6, x, self.h - 6, fill=f"#{r:02x}{g:02x}{b:02x}")
                draw_round_rect(self, 5, 5, self.w - 5, self.h - 5, 13, fill="", outline=border, width=2 if self.hovered else 1)
            elif self.variant == "danger":
                draw_round_rect(self, 5, 5, self.w - 5, self.h - 5, 13, fill=colors["danger"], outline=colors["danger"], width=1)
            else:
                fill = colors["card"] if self.hovered else colors["bg"]
                outline = colors["cyan"] if self.hovered else colors["border"]
                draw_round_rect(self, 5, 5, self.w - 5, self.h - 5, 13, fill=fill, outline=outline, width=1)
            self.create_text(
                self.w // 2,
                self.h // 2,
                text=self.text,
                fill=text_color,
                font=("Segoe UI", 11, "bold"),
            )

        def _enter(self, _event=None) -> None:
            self.hovered = True
            self._draw()

        def _leave(self, _event=None) -> None:
            self.hovered = False
            self._draw()

        def _click(self, _event=None) -> None:
            if self.command:
                self.command()

    def ctk_button(parent, text: str, command, variant: str = "dark", **pack_kwargs):
        variant_map = {
            "cyan": "primary",
        "success": "primary",
            "danger": "danger",
            "dark": "secondary",
        }
        width = max(168, min(260, len(text) * 9 + 46))
        btn = NeonButton(parent, text, command, variant_map.get(variant, "secondary"), width=width)
        if pack_kwargs:
            btn.pack(**pack_kwargs)
        return btn

    content = ctk.CTkScrollableFrame(root, fg_color="transparent", corner_radius=0, scrollbar_button_color=colors["cyan"])
    content.place(relx=0.02, rely=0.02, relwidth=0.96, relheight=0.96)
    content.grid_columnconfigure((0, 1), weight=1, uniform="cards")

    header = ctk.CTkFrame(content, fg_color="transparent")
    header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=22, pady=(22, 12))
    header.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(header, text="Margoclicker", text_color=colors["text"], font=("Segoe UI", 34, "bold")).grid(row=0, column=0, sticky="w")
    ctk.CTkLabel(header, text="Desktopowy panel OCR, licencji i automatyzacji", text_color=colors["muted"], font=("Segoe UI", 14)).grid(row=1, column=0, sticky="w", pady=(2, 0))
    badges = ctk.CTkFrame(header, fg_color="transparent")
    badges.grid(row=0, column=1, rowspan=2, sticky="e")
    program_badge = ctk.CTkLabel(
        badges,
        textvariable=activity_var,
        fg_color=colors["card"],
        text_color=colors["success"],
        corner_radius=999,
        height=36,
        width=166,
        font=("Segoe UI", 12, "bold"),
    )
    program_badge.pack(side=tk.LEFT, padx=(0, 8))
    license_badge = ctk.CTkLabel(
        badges,
        textvariable=license_status_var,
        fg_color=colors["card"],
        text_color=colors["cyan"],
        corner_radius=999,
        height=36,
        width=166,
        font=("Segoe UI", 12, "bold"),
    )
    license_badge.pack(side=tk.LEFT)

    license_card = ctk_card(content, "LICENCJA", "cyan")
    license_card.grid(row=1, column=0, sticky="nsew", padx=(22, 8), pady=8)
    for var in (license_status_var, license_expiry_var, api_status_var):
        ctk.CTkLabel(license_card, textvariable=var, text_color=colors["text"] if var is license_status_var else colors["muted"], anchor="w").pack(anchor="w", padx=18, pady=3)
    license_buttons = ctk.CTkFrame(license_card, fg_color="transparent")
    license_buttons.pack(fill=tk.X, padx=18, pady=(14, 18))
    ctk_button(license_buttons, "Wprowadź / zmień klucz", lambda: check_license_gui(True), "dark", side=tk.LEFT, padx=(0, 8))
    ctk_button(license_buttons, "Sprawdź licencję", lambda: check_license_gui(False), "cyan", side=tk.LEFT)

    control_card = ctk_card(content, "STEROWANIE", "cyan")
    control_card.grid(row=1, column=1, sticky="nsew", padx=(8, 22), pady=8)
    ctk.CTkLabel(control_card, textvariable=activity_var, text_color=colors["text"], anchor="w").pack(anchor="w", padx=18, pady=(2, 14))
    control_buttons = ctk.CTkFrame(control_card, fg_color="transparent")
    control_buttons.pack(fill=tk.X, padx=18, pady=(0, 18))
    ctk_button(control_buttons, "Start", start_program_gui, "cyan", side=tk.LEFT, padx=(0, 8))
    ctk_button(control_buttons, "Stop", stop_program_gui, "danger", side=tk.LEFT, padx=(0, 8))
    ctk_button(control_buttons, "Pauza / Wznów", pause_resume_gui, "dark", side=tk.LEFT)

    shot_card = ctk_card(content, "OCR / SCREENSHOTY", "cyan")
    shot_card.grid(row=2, column=0, columnspan=2, sticky="ew", padx=22, pady=8)
    shot_inner = ctk.CTkFrame(shot_card, fg_color="transparent")
    shot_inner.pack(fill=tk.X, padx=18, pady=(4, 18))
    ctk.CTkSwitch(
        shot_inner,
        text="Zapisuj screenshoty debug",
        variable=debug_screenshots_var,
        command=save_from_gui,
        progress_color=colors["success"],
        button_color=colors["success"],
        text_color=colors["text"],
    ).pack(side=tk.LEFT, padx=(0, 18))
    ctk.CTkLabel(shot_inner, textvariable=screenshot_count_var, text_color=colors["text"]).pack(side=tk.LEFT, padx=(0, 16))
    ctk.CTkLabel(shot_inner, textvariable=screenshot_size_var, text_color=colors["muted"]).pack(side=tk.LEFT, padx=(0, 16))
    ctk_button(shot_inner, "Wyczyść screenshoty", clear_screenshots_gui, "dark", side=tk.LEFT)

    window_card = ctk_card(content, "OKNO", "cyan")
    window_card.grid(row=3, column=0, sticky="nsew", padx=(22, 8), pady=8)
    ctk.CTkLabel(window_card, text="Fraza tytułu", text_color=colors["muted"]).pack(anchor="w", padx=18, pady=(4, 3))
    ctk.CTkEntry(window_card, textvariable=keyword_var, fg_color=colors["card"], border_color=colors["border"], text_color=colors["text"], corner_radius=12).pack(fill=tk.X, padx=18, pady=(0, 12))
    ctk.CTkLabel(window_card, text="Tryb wyboru", text_color=colors["muted"]).pack(anchor="w", padx=18, pady=(0, 3))
    ctk.CTkOptionMenu(window_card, variable=mode_var, values=["auto", "title", "process", "picked"], fg_color=colors["card"], button_color=colors["cyan"], button_hover_color=colors["cyan"], dropdown_fg_color=colors["card"], corner_radius=12).pack(fill=tk.X, padx=18, pady=(0, 18))

    vision_card = ctk_card(content, "OCR / WYKRYWANIE", "cyan")
    vision_card.grid(row=3, column=1, sticky="nsew", padx=(8, 22), pady=8)
    ctk.CTkSwitch(
        vision_card,
        text="Wykrywanie OCR aktywne",
        variable=vision_enabled_var,
        command=save_from_gui,
        progress_color=colors["success"],
        button_color=colors["success"],
        text_color=colors["text"],
    ).pack(anchor="w", padx=18, pady=(4, 14))
    ctk.CTkLabel(vision_card, text="Czułość", text_color=colors["muted"]).pack(anchor="w", padx=18, pady=(0, 3))
    ctk.CTkEntry(vision_card, textvariable=vision_threshold_var, fg_color=colors["card"], border_color=colors["border"], text_color=colors["text"], corner_radius=12).pack(fill=tk.X, padx=18, pady=(0, 18))

    logs_card = ctk_card(content, "LOGI", "cyan")
    logs_card.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=22, pady=8)
    log_box = ctk.CTkTextbox(logs_card, height=190, fg_color=colors["bg"], border_width=1, border_color=colors["border"], text_color=colors["text"], corner_radius=16, font=("Consolas", 12))
    log_box.pack(fill=tk.BOTH, expand=True, padx=18, pady=(6, 18))
    try:
        log_box._textbox.tag_config("info", foreground=colors["text"])
        log_box._textbox.tag_config("success", foreground=colors["success"])
        log_box._textbox.tag_config("warning", foreground=colors["warning"])
        log_box._textbox.tag_config("error", foreground=colors["danger"])
    except Exception:
        pass

    def gui_log(msg: str) -> None:
        lowered = msg.lower()
        if "błąd" in lowered or "blad" in lowered or "error" in lowered or "nieud" in lowered:
            tag = "error"
        elif "ostrze" in lowered or "warning" in lowered:
            tag = "warning"
        elif "ok" in lowered or "aktywn" in lowered or "wznowiono" in lowered or "zapisano" in lowered:
            tag = "success"
        else:
            tag = "info"
        try:
            log_box._textbox.insert(tk.END, msg + "\n", tag)
        except Exception:
            log_box.insert(tk.END, msg + "\n")
        log_box.see(tk.END)
        status_var.set(f"Status: {msg}")

    runtime_state["log_hook"] = gui_log

    actions_card = ctk_card(content, "AKCJE / SYSTEM", "cyan")
    actions_card.grid(row=5, column=0, columnspan=2, sticky="ew", padx=22, pady=8)
    actions_inner = ctk.CTkFrame(actions_card, fg_color="transparent")
    actions_inner.pack(fill=tk.X, padx=18, pady=(6, 18))
    actions = [
        ("Kliknij Rozwiąż teraz", test_pre_zapadki),
        ("Tylko wykryj", detect_pre_zapadki),
        ("Rozwiąż quiz", test_solve_captcha),
        ("Debug geometrii", debug_geometry),
        ("Debug monitory", lambda: log_event(f"Monitors: {vision_debug_monitors_route().get_json()}")),
        ("Skan stanu", scan_state_gui),
        ("Wymuś skan odpowiedzi", force_answers_scan_gui),
        ("Otwórz folder data", lambda: subprocess.Popen(["explorer", str(DATA_DIR)]) if sys.platform == "win32" else log_event(str(DATA_DIR))),
        ("Zapisz ustawienia", save_from_gui),
    ]
    for col in range(4):
        actions_inner.grid_columnconfigure(col, weight=1)
    for idx, (label, command) in enumerate(actions):
        btn = ctk_button(actions_inner, label, command, "dark")
        btn.grid(row=idx // 4, column=idx % 4, sticky="ew", padx=4, pady=4)

    status_card = ctk.CTkFrame(content, fg_color=colors["card2"], border_width=1, border_color=colors["cyan"], corner_radius=16)
    status_card.grid(row=6, column=0, columnspan=2, sticky="ew", padx=22, pady=(0, 8))
    for var in (status_var, watcher_var, ocr_var, ds_var):
        ctk.CTkLabel(status_card, textvariable=var, text_color=colors["muted"], anchor="w", justify="left").pack(anchor="w", padx=16, pady=2)

    debug_card = ctk_card(content, "SZCZEGÓŁY DEBUG", "cyan")
    debug_card.grid(row=7, column=0, columnspan=2, sticky="nsew", padx=22, pady=(8, 22))
    ctk.CTkSwitch(debug_card, text="Pokaż szczegóły debug", variable=debug_open_var, progress_color=colors["success"], button_color=colors["success"], text_color=colors["text"]).pack(anchor="w", padx=18, pady=(4, 8))
    debug_content = ctk.CTkFrame(debug_card, fg_color="transparent")
    debug_content.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 18))
    columns = ("hwnd", "title", "proc", "class", "monitor", "score", "client")
    tree = ttk.Treeview(debug_content, columns=columns, show="headings", height=8, style="Neon.Treeview")
    for col, w in [("hwnd", 90), ("title", 300), ("proc", 120), ("class", 150), ("monitor", 150), ("score", 70), ("client", 110)]:
        tree.heading(col, text=col)
        tree.column(col, width=w, anchor="w")
    tree.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
    debug_buttons = ctk.CTkFrame(debug_content, fg_color="transparent")
    debug_buttons.pack(fill=tk.X)
    debug_actions = [
        ("Pokaż wykryte okna", refresh_candidates),
        ("Wskaż okno myszą", pick_under_cursor_gui),
        ("Zaznacz client-area", test_highlight_client),
        ("Pokaż punkt kliknięcia", test_show_click_point),
        ("Zrzut client-area", snapshot_client),
        ("Kalibracja", calibrate_active),
        ("Test punkty", run_test_points),
        ("Test odpowiedź", test_answer_click),
        ("Test potwierdź", test_confirm_click),
        ("Współrzędne", show_last_click),
        ("Eksport diagnostyki", export_diag),
        ("Ustaw pre", lambda: save_manual_point("pre_zapadki", "Pre zapadka")),
        ("Ustaw odpowiedź", lambda: save_manual_point("answer", "Odpowiedź")),
        ("Ustaw potwierdź", lambda: save_manual_point("confirm", "Potwierdź")),
    ]
    for col in range(4):
        debug_buttons.grid_columnconfigure(col, weight=1)
    for idx, (label, command) in enumerate(debug_actions):
        btn = ctk_button(debug_buttons, label, command, "dark")
        btn.grid(row=idx // 4, column=idx % 4, sticky="ew", padx=4, pady=4)

    def toggle_debug_ui() -> None:
        if debug_open_var.get():
            debug_content.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 18))
        else:
            debug_content.pack_forget()

    debug_open_var.trace_add("write", lambda *_: toggle_debug_ui())
    toggle_debug_ui()

    def refresh_runtime_ui() -> None:
        sel = runtime_state.get("last_selected_candidate") or {}
        activity_var.set("Program: aktywny" if runtime_state.get("watcher_running") else "Program: zatrzymany")
        if runtime_state.get("watcher_running"):
            program_badge.configure(text_color=colors["success"], fg_color=colors["card"])
        else:
            program_badge.configure(text_color=colors["muted"], fg_color=colors["card2"])
        refresh_screenshot_count()
        watcher_var.set(f"window={sel.get('title','-')[:30]} mon={sel.get('monitor_index','-')} capture={runtime_state.get('capture_method')} watcher={runtime_state.get('watcher_state')} running={runtime_state.get('watcher_running')}")
        ocr_var.set(f"last OCR: {runtime_state.get('last_ocr_texts', [])}")
        try:
            stats = vision_dataset_stats_route().get_json()
        except Exception:
            stats = {}
        ds_var.set(f"dataset last={runtime_state.get('last_dataset_event')} counts p/a/c/u/f={stats.get('precaptcha')}/{stats.get('answers')}/{stats.get('confirm')}/{stats.get('unknown')}/{stats.get('failed')}")
        root.after(1000, refresh_runtime_ui)

    refresh_license_labels()
    refresh_screenshot_count()
    save_from_gui()
    root.after(300, refresh_candidates)
    root.after(500, refresh_runtime_ui)
    root.mainloop()


# =========================
# BOOTSTRAP
# =========================

def run_console_policy() -> None:
    with config_lock:
        should_hide = bool(config.get("hide_console_on_start", True))
    if should_hide:
        hide_console_window()


def start_http_server() -> None:
    app.run(port=5000, host="127.0.0.1", debug=False, use_reloader=False)


def check_required_dependencies() -> bool:
    missing: List[str] = []
    if pyautogui is None:
        missing.append("pyautogui")
    if not FLASK_AVAILABLE:
        missing.extend(["flask", "flask-cors"])
    if missing:
        uniq = ", ".join(sorted(set(missing)))
        print("Brak wymaganych bibliotek Pythona:", uniq)
        print("Zainstaluj je poleceniem:")
        print("  pip install pyautogui flask flask-cors")
        return False
    return True


def ensure_optional_vision_dependencies() -> None:
    required = ["opencv-python", "numpy", "pillow", "pytesseract", "pywin32"]
    import_names = {"opencv-python": "cv2", "numpy": "numpy", "pillow": "PIL", "pytesseract": "pytesseract", "pywin32": "win32api"}
    with config_lock:
        auto_install = bool(config.get("vision_auto_install", True))
    missing = [pkg for pkg in required if importlib.util.find_spec(import_names[pkg]) is None]
    if not missing:
        return
    print("Brakują biblioteki vision. Uruchom:")
    print("  python -m pip install opencv-python numpy pillow pytesseract pywin32")
    if not auto_install:
        return
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
    except Exception as exc:
        log_event(f"Auto-instalacja vision nieudana: {exc}")


if __name__ == "__main__":
    reset_license = "--reset-license" in sys.argv
    license_state = require_active_license(reset_license=reset_license)
    if not check_required_dependencies():
        raise SystemExit(1)
    load_settings_from_disk()
    ensure_optional_vision_dependencies()
    ensure_screenshot_dirs()
    configure_flask_logging()
    setup_dpi_awareness()
    run_console_policy()
    register_hotkey()
    pyautogui.FAILSAFE = False

    log_event("MargoClicker start")
    runtime_state["license"] = license_state
    run_storage_cleanup_once()
    start_storage_cleanup_scheduler()
    server_thread = threading.Thread(target=start_http_server, daemon=True)
    server_thread.start()
    if bool(config.get("vision_auto_watch", True)):
        start_watcher()
    launch_gui_v2()
