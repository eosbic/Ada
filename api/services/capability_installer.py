"""
Capability installer.

Permite instalar librerias en tiempo de ejecucion de forma controlada
solo para paquetes permitidos.
"""

import os
import sys
import subprocess
import importlib.util


ALLOWED_PACKAGES = {
    "reportlab": "reportlab",
    "matplotlib": "matplotlib",
}


def _is_enabled() -> bool:
    value = os.getenv("ENABLE_AUTO_INSTALL", "true").strip().lower()
    return value in {"1", "true", "yes", "on"}


def ensure_package(import_name: str, pip_name: str | None = None) -> bool:
    """
    Garantiza que un paquete este disponible.

    Retorna True si ya existe o si se pudo instalar.
    """
    if importlib.util.find_spec(import_name):
        return True

    if not _is_enabled():
        print(f"AUTO-INSTALL disabled. Missing package: {import_name}")
        return False

    target_pip_name = pip_name or ALLOWED_PACKAGES.get(import_name)
    if not target_pip_name:
        print(f"AUTO-INSTALL blocked. Package not allowlisted: {import_name}")
        return False

    if target_pip_name not in ALLOWED_PACKAGES.values():
        print(f"AUTO-INSTALL blocked. Pip package not allowlisted: {target_pip_name}")
        return False

    try:
        print(f"AUTO-INSTALL: installing {target_pip_name} ...")
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", target_pip_name],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if proc.returncode != 0:
            print(f"AUTO-INSTALL failed: {proc.stderr[:1000]}")
            return False
        return importlib.util.find_spec(import_name) is not None
    except Exception as e:
        print(f"AUTO-INSTALL exception: {e}")
        return False
