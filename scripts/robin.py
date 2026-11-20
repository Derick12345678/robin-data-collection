#!/usr/bin/env python3
"""Manage the pinned Robin deployment without modifying global MCP settings."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "deploy" / "robin.lock.json"
LOCAL_ENV = ROOT / "deploy" / "robin.env"


def docker_binary():
    candidate = shutil.which("docker")
    if candidate:
        return candidate
    desktop = Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe")
    if os.name == "nt" and desktop.is_file():
        return str(desktop)
    raise RuntimeError("Docker not found. Start Docker Desktop and enable your WSL distro integration.")


def call(args):
    return subprocess.run(args, cwd=ROOT, check=True).returncode


def prepare():
    # Exclusive creation prevents accidentally replacing a teammate's secrets.
    try:
        with LOCAL_ENV.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write((ROOT / "deploy" / "robin.env.example").read_text(encoding="utf-8"))
        LOCAL_ENV.chmod(0o600)
        print("Created deploy/robin.env (ignored by Git).")
    except FileExistsError:
        print("Keeping existing deploy/robin.env.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "config", "pull", "verify", "up", "status", "logs", "down", "mcp"])
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
        return 0
    try:
        docker = docker_binary()
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        image = lock["image"]
        if args.action == "verify":
            # Bypass entrypoint and disable networking: no Tor, queries, or provider calls.
            code = (
                "import hashlib,json,os,subprocess; from pathlib import Path; "
                "import pipeline,mcp_server; "
                "expected=" + repr(lock["source_sha256"]) + "; "
                "assert os.getuid()==1000, 'Expected non-root image user'; "
                "actual={name:hashlib.sha256((Path('/app')/name).read_bytes()).hexdigest() for name in expected}; "
                "assert actual==expected, 'Image source does not match locked release'; "
                "subprocess.run(['tor','--version'],check=True,stdout=subprocess.DEVNULL); "
                "print(json.dumps({'release':'" + lock["release"] + "','source_files':'matched','uid':os.getuid(),'tor':'installed','imports':'passed','network':'disabled'}))"
            )
            return call([docker, "run", "--rm", "--network", "none", "--entrypoint", "python3", image, "-c", code])
        if not LOCAL_ENV.is_file():
            raise RuntimeError("Run python scripts/robin.py prepare first.")
        compose = [docker, "compose", "--project-directory", str(ROOT), "-f", str(ROOT / "compose.yaml")]
        actions = {
            "config": ["config", "--quiet"],
            "pull": ["--profile", "ui", "--profile", "mcp", "pull"],
            "up": ["up", "-d", "robin-ui"],
            "status": ["ps", "--all"],
            "logs": ["logs", "--tail", "60", "robin-ui"],
            "down": ["down"],
            "mcp": ["run", "--rm", "--no-deps", "-T", "robin-mcp"],
        }
        return call(compose + actions[args.action])
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print("Docker command failed; see the preceding Docker error. Check engine availability, WSL integration, and port conflicts.", file=sys.stderr)
        return exc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
