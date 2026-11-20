"""Docker Desktop CLI fallback and project-path translation for WSL storage."""
import os
from pathlib import Path
import shutil
import subprocess


def docker_binary():
    # Keep SQLite native to WSL while using the already-running Desktop engine.
    if os.environ.get("WSL_DISTRO_NAME"):
        executable = shutil.which("docker.exe")
        if executable:
            return executable
    candidate = shutil.which("docker")
    if candidate:
        return candidate
    desktop = Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe")
    if os.name == "nt" and desktop.is_file():
        return str(desktop)
    raise RuntimeError("Docker unavailable; start Docker Desktop or enable WSL integration")


def project_path(root, docker):
    if os.environ.get("WSL_DISTRO_NAME") and str(docker).lower().endswith(".exe"):
        return subprocess.run(["wslpath", "-w", str(root)], capture_output=True, text=True, check=True, timeout=5).stdout.strip()
    return str(root)
