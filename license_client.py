from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from urllib import error, request

APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
LICENSE_PATH = DATA_DIR / "license.json"
CONFIG_PATH = APP_DIR / "config.json"

PRODUCT_SLUG = "margoclicker"
SCRIPT_VERSION = "0.1.0"
DEFAULT_API_BASE_URL = "https://www.margoneuro.pl"


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_api_base_url() -> str:
    env_url = os.environ.get("MARGO_API_BASE_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")

    config = _read_json(CONFIG_PATH)
    configured_url = str(config.get("api_base_url", "")).strip()
    if configured_url:
        return configured_url.rstrip("/")

    return DEFAULT_API_BASE_URL


def load_license_config() -> Dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[License] Plik licencji: {LICENSE_PATH}")
    config = _read_json(LICENSE_PATH)
    if str(config.get("license_key", "")).strip():
        print("[License] Wczytano zapisany klucz z data/license.json")
    else:
        print("[License] Brak zapisanego klucza, proszę o aktywację")
    return config


def save_license_config(config: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LICENSE_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_or_create_device_id() -> str:
    config = load_license_config()
    device_id = str(config.get("device_id", "")).strip()

    if len(device_id) >= 8:
        return device_id

    device_id = str(uuid.uuid4())
    config["device_id"] = device_id
    save_license_config(config)
    return device_id


def ask_for_license_key() -> Optional[str]:
    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk.Tk()
        root.withdraw()
        key = simpledialog.askstring(
            "Licencja Margoclicker",
            "Licencja jest nieważna, wygasła albo cofnięta.\nWprowadź nowy klucz:",
        )
        root.destroy()
        return key.strip() if key else None
    except Exception:
        pass

    print("Wprowadź klucz licencyjny Margoclicker.")
    try:
        key = input("Klucz licencyjny: ").strip()
        return key or None
    except Exception:
        return None


def update_saved_license_key(license_key: str) -> Dict[str, Any]:
    config = load_license_config()
    device_id = str(config.get("device_id", "")).strip()
    config["license_key"] = license_key.strip()
    config["device_id"] = device_id if len(device_id) >= 8 else str(uuid.uuid4())
    save_license_config(config)
    return config


def verify_license(
    license_key: Optional[str] = None,
    device_id: Optional[str] = None,
    save_if_missing: bool = True,
    allow_prompt: bool = True,
) -> Dict[str, Any]:
    config = load_license_config()
    key = (license_key or str(config.get("license_key", ""))).strip()

    if not key and allow_prompt:
        key = ask_for_license_key() or ""

    if not key:
        return {
            "active": False,
            "status": "missing",
            "message": "Brak klucza licencyjnego.",
        }

    resolved_device_id = device_id or get_or_create_device_id()
    payload = {
        "license_key": key,
        "product_slug": PRODUCT_SLUG,
        "device_id": resolved_device_id,
        "script_version": SCRIPT_VERSION,
    }

    body = json.dumps(payload).encode("utf-8")
    api_request = request.Request(
        f"{get_api_base_url()}/api/license/verify",
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"Margoclicker/{SCRIPT_VERSION}",
        },
        method="POST",
    )

    try:
        with request.urlopen(api_request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
    except error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:
            data = {
                "active": False,
                "status": "http_error",
                "message": f"Błąd HTTP {exc.code} podczas weryfikacji licencji.",
            }
    except Exception as exc:
        data = {
            "active": False,
            "status": "network_error",
            "message": f"Nie udało się połączyć z API licencji: {exc}",
        }

    config.update(
        {
            "license_key": key,
            "device_id": resolved_device_id,
            "api_base_url": get_api_base_url(),
            "last_status": data.get("status"),
            "last_message": data.get("message"),
            "last_expires_at": data.get("expires_at"),
        }
    )

    if save_if_missing or data.get("active") is True:
        save_license_config(config)

    if data.get("active") is True:
        print("[License] Licencja aktywna")
    else:
        print("[License] Licencja odrzucona, wymagany nowy klucz")

    return data


def clear_saved_license() -> None:
    if LICENSE_PATH.exists():
        LICENSE_PATH.unlink()


def clear_saved_license_key(keep_device_id: bool = True) -> None:
    config = load_license_config()
    device_id = str(config.get("device_id", "")).strip()
    if keep_device_id and len(device_id) >= 8:
        save_license_config({"device_id": device_id})
    elif LICENSE_PATH.exists():
        LICENSE_PATH.unlink()


def require_active_license(reset_license: bool = False) -> Dict[str, Any]:
    if reset_license:
        clear_saved_license()
        print("Zapisana licencja została usunięta. Wprowadź nowy klucz.")

    while True:
        result = verify_license()
        if result.get("active") is True:
            print("Licencja Margoclicker aktywna.")
            return result

        print(result.get("message") or "Licencja nieprawidłowa.")
        print("[License] Licencja odrzucona, wymagany nowy klucz")
        replacement = ask_for_license_key()
        if not replacement:
            raise SystemExit(1)
        update_saved_license_key(replacement)


if __name__ == "__main__":
    if "--reset-license" in sys.argv:
        clear_saved_license()
        print("Zapisana licencja została usunięta.")
    else:
        print(json.dumps(verify_license(), ensure_ascii=False, indent=2))
