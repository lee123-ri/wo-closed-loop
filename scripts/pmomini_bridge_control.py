#!/usr/bin/env python3
"""Start/check the local PMO bridge without sending any DingTalk notifications."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from pmomini_bridge import __version__
RUNTIME = Path.home() / "Library/Application Support/xh-wo-closed-loop/pmomini"
LOGS = Path.home() / "Library/Logs/xh-wo-closed-loop"
LABEL = "com.xh.wo-closed-loop.pmomini"
TARGET = f"gui/{os.getuid()}/{LABEL}"


def status():
    try:
        with urlopen("http://127.0.0.1:8768/health", timeout=2) as response:
            value = json.load(response)
        return value if value.get("version") == __version__ and value.get("policy") == "workorders-and-platform-only" else None
    except Exception:
        return None


def agent_plist():
    python = ROOT / "backend/.venv/bin/python"
    if not python.exists():
        raise RuntimeError("缺少平台运行环境")
    path_parts = ["/Users/lee/bin", "/Users/lee/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    codex = Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS")
    if codex.is_dir():
        path_parts.insert(0, str(codex))
    return {
        "Label": LABEL,
        "ProgramArguments": [str(python), "-m", "pmomini_bridge.service"],
        "WorkingDirectory": str(ROOT / "backend"),
        "EnvironmentVariables": {"PATH": ":".join(path_parts), "PYTHONUNBUFFERED": "1"},
        "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 20,
        "StandardOutPath": str(LOGS / "pmomini.log"),
        "StandardErrorPath": str(LOGS / "pmomini-error.log"),
    }


def ensure(wait_seconds=35):
    current = status()
    if current:
        return current
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    LOGS.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Staged outside LaunchAgents: loaded when the desktop launcher runs,
    # without adding a separate login-start requirement.
    plist = RUNTIME / "agent.plist"
    plist.write_bytes(plistlib.dumps(agent_plist()))
    os.chmod(plist, 0o600)
    check = subprocess.run(["launchctl", "print", TARGET], capture_output=True)
    if check.returncode == 0:
        subprocess.run(["launchctl", "kickstart", TARGET], check=True, capture_output=True)
    else:
        loaded = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)], capture_output=True)
        if loaded.returncode:
            raise RuntimeError("PMO接入后台启动失败，请检查本机运行日志")
    deadline = time.monotonic() + wait_seconds
    latest = None
    while time.monotonic() < deadline:
        latest = status()
        if latest and latest.get("stream_connected"):
            return latest
        time.sleep(0.5)
    return latest or {"status": "starting", "stream_connected": False, "codex_verified": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["ensure", "status", "stop", "preview"])
    parser.add_argument("--human", action="store_true")
    args = parser.parse_args()
    if args.action == "preview":
        result = agent_plist()
    elif args.action == "status":
        result = status() or {"status": "stopped"}
    elif args.action == "stop":
        result = subprocess.run(["launchctl", "bootout", TARGET], capture_output=True)
        result = {"stopped": status() is None, "exit_code": result.returncode}
    else:
        result = ensure()
    if args.human:
        if result.get("stream_connected") and result.get("codex_verified"):
            print("PMO mini 工单问答已就绪，等待新提问；未发送提醒。")
        elif result.get("stream_connected"):
            print("PMO mini 已连接，Codex 检查中；未发送提醒。")
        else:
            print("PMO mini 接入尚未就绪，请检查本机运行状态。")
    else:
        print(json.dumps(result, ensure_ascii=False))
    if args.action == "ensure" and not result.get("stream_connected"):
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
