#!/usr/bin/env python3
"""
Agents IDE Daemon Manager

Ensures a single instance of the Agents IDE daemon is running system-wide.
Uses a PID file to track the daemon process.

Usage:
    python agents_ide_manager.py start    # Start daemon if not running
    python agents_ide_manager.py stop     # Stop the daemon
    python agents_ide_manager.py status   # Check if daemon is running
    python agents_ide_manager.py restart  # Restart the daemon
    python agents_ide_manager.py ensure   # Ensure running (for MCP startup)
"""

import grp
import os
import sys
import signal
import subprocess
import time
import argparse
from pathlib import Path

import requests

# Configuration
DEFAULT_PORT = 7902
DAEMON_SCRIPT = Path(__file__).parent / "daemon.py"
RUN_DIR = Path("/tmp/agents_ide")
PID_FILE = RUN_DIR / "daemon.pid"
LOG_FILE = RUN_DIR / "daemon.log"
HEALTH_URL = f"http://localhost:{DEFAULT_PORT}/health"
STARTUP_TIMEOUT = 15  # seconds


def ensure_run_dir():
    """Ensure run directory exists with group-writable permissions."""
    if RUN_DIR.exists():
        return
    RUN_DIR.mkdir(mode=0o770)
    try:
        staff_gid = grp.getgrnam("staff").gr_gid
        os.chown(RUN_DIR, -1, staff_gid)
    except KeyError:
        pass  # 'staff' group doesn't exist on this system
    os.chmod(RUN_DIR, 0o770)


def get_pid() -> int | None:
    """Get PID from PID file if it exists and process is running."""
    if not PID_FILE.exists():
        return None

    try:
        pid = int(PID_FILE.read_text().strip())
        # Check if process is actually running
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        # PID file exists but process is dead or inaccessible
        try:
            PID_FILE.unlink(missing_ok=True)
        except PermissionError:
            pass
        return None


def is_healthy() -> bool:
    """Check if daemon is responding to health checks."""
    try:
        resp = requests.get(HEALTH_URL, timeout=2)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def start_daemon(port: int = DEFAULT_PORT) -> bool:
    """Start the daemon if not already running."""
    # Check if already running
    pid = get_pid()
    if pid and is_healthy():
        print(f"Daemon already running (PID {pid})")
        return True

    # Clean up stale PID file
    if pid:
        print(f"Stale PID {pid}, cleaning up...")
        try:
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)
        except ProcessLookupError:
            pass
        try:
            PID_FILE.unlink(missing_ok=True)
        except PermissionError:
            pass

    # Check if port is in use by something else
    if is_healthy():
        print(f"Port {port} already has a healthy LSP daemon (external)")
        return True

    # Start the daemon
    print(f"Starting LSP HTTP daemon on port {port}...")
    ensure_run_dir()

    with open(LOG_FILE, "a") as log:
        os.chmod(LOG_FILE, 0o660)
        # Set PYTHONPATH to include the package root
        env = os.environ.copy()
        package_root = str(DAEMON_SCRIPT.parent.parent)
        env["PYTHONPATH"] = f"{package_root}:{env.get('PYTHONPATH', '')}"
        process = subprocess.Popen(
            [sys.executable, str(DAEMON_SCRIPT), "--port", str(port)],
            stdout=log,
            stderr=log,
            env=env,
            start_new_session=True,  # Detach from parent
        )

    # Write PID file with group-writable permissions
    PID_FILE.write_text(str(process.pid))
    os.chmod(PID_FILE, 0o660)

    # Wait for daemon to be healthy
    print(f"Waiting for daemon to initialize (PID {process.pid})...")
    for i in range(STARTUP_TIMEOUT * 2):
        if is_healthy():
            print(f"Daemon started successfully (PID {process.pid})")
            return True
        time.sleep(0.5)

    print("ERROR: Daemon failed to start within timeout")
    print(f"Check logs at: {LOG_FILE}")
    return False


def stop_daemon() -> bool:
    """Stop the daemon."""
    pid = get_pid()
    if not pid:
        print("Daemon not running")
        return True

    print(f"Stopping daemon (PID {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)

        # Wait for graceful shutdown
        for _ in range(10):
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except ProcessLookupError:
                break
        else:
            # Force kill if still running
            print("Force killing...")
            os.kill(pid, signal.SIGKILL)

        try:
            PID_FILE.unlink(missing_ok=True)
        except PermissionError:
            pass
        print("Daemon stopped")
        return True
    except ProcessLookupError:
        try:
            PID_FILE.unlink(missing_ok=True)
        except PermissionError:
            pass
        print("Daemon was not running")
        return True
    except PermissionError:
        print(f"ERROR: Permission denied to stop PID {pid}")
        return False


def status() -> dict:
    """Get daemon status."""
    pid = get_pid()
    healthy = is_healthy()

    result = {
        "running": pid is not None,
        "healthy": healthy,
        "pid": pid,
        "port": DEFAULT_PORT,
        "pid_file": str(PID_FILE),
        "log_file": str(LOG_FILE),
    }

    if healthy:
        try:
            resp = requests.get(f"http://localhost:{DEFAULT_PORT}/stats", timeout=2)
            if resp.status_code == 200:
                result["stats"] = resp.json()
        except requests.RequestException:
            pass

    return result


def print_status():
    """Print human-readable status."""
    s = status()

    if s["healthy"]:
        print(f"✓ Daemon is running and healthy")
        print(f"  PID: {s['pid']}")
        print(f"  Port: {s['port']}")
        if "stats" in s:
            stats = s["stats"]
            print(f"  Indexed files: {stats.get('indexed_files_count', 0)}")
            print(f"  Requests: {stats.get('request_count', 0)}")
    elif s["running"]:
        print(f"⚠ Daemon process exists but not responding")
        print(f"  PID: {s['pid']}")
        print(f"  Check logs: {s['log_file']}")
    else:
        print(f"✗ Daemon is not running")

    print(f"\nPID file: {s['pid_file']}")
    print(f"Log file: {s['log_file']}")


def ensure_running(port: int = DEFAULT_PORT) -> bool:
    """Ensure daemon is running (idempotent - safe to call multiple times)."""
    if is_healthy():
        return True
    return start_daemon(port)


def main():
    parser = argparse.ArgumentParser(description="LSP HTTP Daemon Manager")
    parser.add_argument(
        "command",
        choices=["start", "stop", "restart", "status", "ensure"],
        help="Command to execute"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port for daemon (default: {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output status as JSON"
    )

    args = parser.parse_args()

    if args.command == "start":
        success = start_daemon(args.port)
        sys.exit(0 if success else 1)

    elif args.command == "stop":
        success = stop_daemon()
        sys.exit(0 if success else 1)

    elif args.command == "restart":
        stop_daemon()
        time.sleep(1)
        success = start_daemon(args.port)
        sys.exit(0 if success else 1)

    elif args.command == "status":
        if args.json:
            import json
            print(json.dumps(status(), indent=2))
        else:
            print_status()
        sys.exit(0 if is_healthy() else 1)

    elif args.command == "ensure":
        success = ensure_running(args.port)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
