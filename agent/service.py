"""
Windows Service and Task Scheduler Lifecycle Manager for SentinelX Endpoint Agent.

Configures an elevated startup task under NT AUTHORITY\\SYSTEM or manages
service execution with rotating file logs.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

TASK_NAME = "SentinelXEndpointAgent"


def is_admin() -> bool:
    """Returns True if running with Administrator privileges on Windows."""
    if sys.platform != "win32":
        return os.getuid() == 0 if hasattr(os, "getuid") else False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def get_agent_executable_command() -> str:
    """Builds the command string for background service execution."""
    python_exe = sys.executable
    # Path to agent module root
    agent_dir = Path(__file__).resolve().parent.parent
    return f'"{python_exe}" -m agent.main run --service'


def install_service() -> bool:
    """
    Registers an elevated Scheduled Task that starts at system boot under SYSTEM.
    Requires elevated Administrator privileges.
    """
    if not is_admin():
        print("[ERROR] Administrator privileges are required to install the SentinelX Endpoint Service.")
        print("Please restart your terminal or PowerShell as an Administrator and retry.")
        return False

    cmd_action = get_agent_executable_command()
    agent_dir = str(Path(__file__).resolve().parent.parent)

    print(f"[*] Registering Windows Startup Task '{TASK_NAME}' ...")
    schtasks_cmd = [
        "schtasks.exe",
        "/create",
        "/tn", TASK_NAME,
        "/tr", cmd_action,
        "/sc", "onstart",
        "/ru", "SYSTEM",
        "/rl", "HIGHEST",
        "/f",
    ]

    try:
        res = subprocess.run(schtasks_cmd, capture_output=True, text=True, check=True)
        print(f"[+] Task registered successfully under NT AUTHORITY\\SYSTEM.")
        print(f"    Action: {cmd_action}")
        print(f"    Schedule: On System Startup (Elevated)")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"[ERROR] Failed to register task: {exc.stderr.strip()}", file=sys.stderr)
        return False


def uninstall_service() -> bool:
    """Removes the Scheduled Task."""
    if not is_admin():
        print("[ERROR] Administrator privileges are required to uninstall the service.")
        return False

    print(f"[*] Removing Windows Startup Task '{TASK_NAME}' ...")
    schtasks_cmd = ["schtasks.exe", "/delete", "/tn", TASK_NAME, "/f"]

    try:
        subprocess.run(schtasks_cmd, capture_output=True, text=True, check=True)
        print("[+] Service task uninstalled successfully.")
        return True
    except subprocess.CalledProcessError as exc:
        if "cannot find the file" in exc.stderr or "does not exist" in exc.stderr:
            print("[*] Task is not currently registered.")
            return True
        print(f"[ERROR] Failed to uninstall task: {exc.stderr.strip()}", file=sys.stderr)
        return False


def start_service() -> bool:
    """Runs the Scheduled Task immediately."""
    print(f"[*] Starting '{TASK_NAME}' ...")
    try:
        subprocess.run(["schtasks.exe", "/run", "/tn", TASK_NAME], capture_output=True, text=True, check=True)
        print("[+] Service task triggered.")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"[ERROR] Failed to start service: {exc.stderr.strip()}", file=sys.stderr)
        return False


def stop_service() -> bool:
    """Stops the running Scheduled Task."""
    print(f"[*] Stopping '{TASK_NAME}' ...")
    try:
        subprocess.run(["schtasks.exe", "/end", "/tn", TASK_NAME], capture_output=True, text=True, check=True)
        print("[+] Service task stopped.")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"[ERROR] Failed to stop service: {exc.stderr.strip()}", file=sys.stderr)
        return False


def get_service_status() -> str:
    """Queries current state of Scheduled Task."""
    try:
        res = subprocess.run(
            ["schtasks.exe", "/query", "/tn", TASK_NAME, "/fo", "list"],
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except subprocess.CalledProcessError as exc:
        return f"Not Installed or Inaccessible: {exc.stderr.strip()}"
