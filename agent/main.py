"""
SentinelX Windows Endpoint Agent — Main Entrypoint and Service Daemon.

Usage:
    python -m agent.main enroll --server http://localhost:8000/api/v1 --token sxe_...
    python -m agent.main run [--foreground]
    python -m agent.main service {install,uninstall,start,stop,status}
    python -m agent.main status
"""

from __future__ import annotations

import argparse
import logging
import os
import platform
import socket
import sys
import time
from logging.handlers import RotatingFileHandler
from typing import Optional

from agent.buffer import LocalBuffer
from agent.client import (
    ConsentRequiredError,
    RateLimitedError,
    RevokedError,
    SentinelXClient,
    TokenExpiredError,
    TokenUsedError,
    TransientError,
)
from agent.collectors.downloads import DownloadsCollector
from agent.collectors.win_events import WindowsEventCollector
from agent.config import AgentConfig, get_log_dir
from agent.crypto import mask_secret
from agent.service import (
    get_service_status,
    install_service,
    start_service,
    stop_service,
    uninstall_service,
)
from agent.state import BookmarkState

# Polling and batching intervals
HEARTBEAT_INTERVAL_SECONDS = 30.0
POLL_INTERVAL_SECONDS = 3.0
MAX_BATCH_SIZE = 200


def setup_logging(foreground: bool = False, log_level: int = logging.INFO) -> None:
    """Configures rotating file logging and optional stdout console handler."""
    log_dir = get_log_dir()
    log_file = log_dir / "agent.log"

    root_logger = logging.getLogger("sentinelx")
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 5 MB rotating log with 3 backups
    file_handler = RotatingFileHandler(
        str(log_file),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    if foreground or not sys.stdout.isatty():
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)


def cmd_enroll(args: argparse.Namespace) -> int:
    """Executes endpoint enrollment and saves DPAPI protected key."""
    setup_logging(foreground=True)
    logger = logging.getLogger("sentinelx.agent.enroll")

    config = AgentConfig()
    if args.server:
        config.server_url = args.server.rstrip("/")
        if "/api/v1" not in config.server_url:
            config.server_url += "/api/v1"

    token = args.token.strip()
    device_name = args.name or socket.gethostname()
    os_name = f"{platform.system()} {platform.release()}"

    print(f"[*] Enrolling device '{device_name}' with SentinelX server at {config.server_url} ...")
    print(f"    Token: {mask_secret(token)}")

    client = SentinelXClient(config)
    try:
        res = client.enroll(token=token, device_name=device_name, operating_system=os_name)
        print("\n[+] ENROLLMENT SUCCESSFUL!")
        print(f"    Device ID: {res.get('device_id')}")
        print(f"    Target Asset: {res.get('asset_id')}")
        print(f"    Granted Categories: {res.get('enabled_categories')}")
        print(f"    Consent Version: {res.get('consent_version', 'v1.0')}")
        print("\n[+] Device API key securely stored via Windows DPAPI.")
        print("[*] To start collecting telemetry, run:")
        print("    python -m agent.main run")
        print("    or register as service with: python -m agent.main service install")
        return 0

    except ConsentRequiredError:
        print("\n[ERROR] Consent Required (HTTP 403)", file=sys.stderr)
        print("The device user has not yet authorized monitoring on the consent screen.", file=sys.stderr)
        print(f"Please open: {config.server_url.replace('/api/v1', '')}/consent/enroll?token={token}", file=sys.stderr)
        return 1
    except TokenExpiredError:
        print("\n[ERROR] Enrollment Token Expired (HTTP 409)", file=sys.stderr)
        print("This 30-minute token has expired. Please generate a new token in SentinelX.", file=sys.stderr)
        return 1
    except TokenUsedError:
        print("\n[ERROR] Enrollment Token Already Used (HTTP 409)", file=sys.stderr)
        print("This single-use token was already swapped for a device key.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\n[ERROR] Enrollment failed: {exc}", file=sys.stderr)
        return 1


def cmd_status() -> int:
    """Prints current agent configuration, liveness, and buffer metrics."""
    config = AgentConfig()
    buffer = LocalBuffer()

    print("=" * 50)
    print("SentinelX Windows Endpoint Agent Status")
    print("=" * 50)
    print(f"Agent Version:       {config.agent_version}")
    print(f"Server URL:          {config.server_url}")
    print(f"Enrolled:            {config.is_enrolled()}")
    print(f"Device ID:           {config.device_id or '<none>'}")
    print(f"Device Name:         {config.device_name or socket.gethostname()}")
    print(f"Operating System:    {config.operating_system or platform.platform()}")
    print(f"Active Categories:   {sorted(list(config.enabled_categories)) if config.enabled_categories else '<none>'}")
    print(f"Consent Version:     {config.consent_version}")
    print(f"Last Heartbeat:      {config.last_heartbeat_at or 'Never'}")
    print("-" * 50)
    print(f"Queued Buffer Items: {buffer.count()}")
    print(f"Buffer Size:         {buffer.get_size_bytes() / (1024 * 1024):.2f} MB / 50 MB max")
    print("=" * 50)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Runs the main agent telemetry collection and delivery loop."""
    foreground = args.foreground or not args.service
    setup_logging(foreground=foreground)
    logger = logging.getLogger("sentinelx.agent.daemon")

    config = AgentConfig()
    if not config.is_enrolled():
        logger.error("Endpoint is not enrolled. Run 'agent enroll --server <url> --token <token>' first.")
        print("[ERROR] Agent not enrolled. Please enroll first.", file=sys.stderr)
        return 1

    logger.info("Starting SentinelX Endpoint Agent daemon (v%s) ...", config.agent_version)
    logger.info("Bound to Device ID %s at %s", config.device_id, config.server_url)

    buffer = LocalBuffer()
    bookmarks = BookmarkState()
    client = SentinelXClient(config)
    win_collector = WindowsEventCollector(
        get_bookmark_fn=bookmarks.get_bookmark,
        set_bookmark_fn=bookmarks.set_bookmark,
    )
    dl_collector = DownloadsCollector()

    # Initial heartbeat and consent category pull
    try:
        hb = client.heartbeat()
        logger.info("Initial heartbeat confirmed. Active categories: %s", hb.get("enabled_categories"))
    except RevokedError as exc:
        logger.critical("Cannot start: %s", exc)
        return 1
    except Exception as exc:
        logger.warning("Initial heartbeat warning (will retry in background): %s", exc)

    last_heartbeat_time = time.time()
    backoff_delay = 1.0

    # Main telemetry loop
    try:
        while True:
            now = time.time()

            # 1. Periodic Heartbeat & Config Sync (every 30 seconds)
            if now - last_heartbeat_time >= HEARTBEAT_INTERVAL_SECONDS:
                try:
                    client.heartbeat()
                    last_heartbeat_time = now
                except RevokedError as exc:
                    # KILL SWITCH: halt immediately
                    logger.critical("KILL SWITCH TRIGGERED: %s. Ceasing collection and exiting.", exc)
                    config.clear()
                    return 2
                except Exception as exc:
                    logger.debug("Heartbeat transient error: %s", exc)

            # 2. Event Log Collection (strictly gated to enabled consent categories)
            if config.enabled_categories:
                try:
                    new_events = win_collector.poll_events(config.enabled_categories, max_events_per_channel=50)
                    if new_events:
                        logger.debug("Collected %d new Windows events.", len(new_events))
                        buffer.push(new_events)
                except Exception as exc:
                    logger.debug("Windows event collector error: %s", exc)

            # 3. Downloads Collection (if 'file_downloads' category consented)
            if "file_downloads" in config.enabled_categories:
                try:
                    dl_events = dl_collector.poll_new_downloads(config.enabled_categories, max_files=10)
                    if dl_events:
                        logger.info("Collected %d new downloaded file events.", len(dl_events))
                        buffer.push(dl_events)
                except Exception as exc:
                    logger.debug("Downloads collector error: %s", exc)

            # 4. Telemetry Delivery to Server
            batch = buffer.pop_batch(limit=MAX_BATCH_SIZE)
            if batch:
                batch_ids = [item[0] for item in batch]
                raw_events = [item[1] for item in batch]

                try:
                    accepted, rejected, no_consent = client.send_events(raw_events)
                    # Successful delivery: remove batch from disk queue
                    buffer.delete(batch_ids)
                    backoff_delay = 1.0

                    if no_consent > 0:
                        logger.info(
                            "Delivered %d events (%d rejected_no_consent by server-side policy).",
                            accepted,
                            no_consent,
                        )
                    else:
                        logger.debug("Successfully delivered %d events to SentinelX.", accepted)

                except RevokedError as exc:
                    # KILL SWITCH
                    logger.critical("KILL SWITCH TRIGGERED DURING INGEST: %s", exc)
                    config.clear()
                    return 2

                except RateLimitedError as exc:
                    logger.warning("Ingestion rate limited. Backing off for %.1fs ...", exc.retry_after)
                    buffer.schedule_retry(batch_ids, delay_seconds=exc.retry_after)
                    time.sleep(min(exc.retry_after, 10.0))

                except TransientError as exc:
                    logger.warning("Ingestion temporary failure (%s). Backing off %.1fs ...", exc, backoff_delay)
                    buffer.schedule_retry(batch_ids, delay_seconds=backoff_delay)
                    backoff_delay = min(backoff_delay * 2.0, 60.0)
                    time.sleep(min(backoff_delay, 5.0))

                except Exception as exc:
                    logger.error("Unexpected ingestion error: %s", exc)
                    buffer.schedule_retry(batch_ids, delay_seconds=5.0)

            # Rest before next poll
            time.sleep(POLL_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        logger.info("Agent stopped by user (SIGINT).")
        return 0


def cmd_service(args: argparse.Namespace) -> int:
    """Manages Windows Service / Scheduled Task registration."""
    action = args.action
    if action == "install":
        return 0 if install_service() else 1
    elif action == "uninstall":
        return 0 if uninstall_service() else 1
    elif action == "start":
        return 0 if start_service() else 1
    elif action == "stop":
        return 0 if stop_service() else 1
    elif action == "status":
        print(get_service_status())
        return 0
    else:
        print(f"Unknown service action: {action}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="sentinelx-agent",
        description="SentinelX Windows Endpoint Security Monitoring Agent",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # enroll
    parser_enroll = subparsers.add_parser("enroll", help="Enroll endpoint device with one-time token")
    parser_enroll.add_argument("--server", default=None, help="SentinelX server URL (e.g. http://localhost:8000/api/v1)")
    parser_enroll.add_argument("--token", required=True, help="One-time enrollment token (sxe_...)")
    parser_enroll.add_argument("--name", default=None, help="Device name override")
    parser_enroll.set_defaults(func=cmd_enroll)

    # run
    parser_run = subparsers.add_parser("run", help="Run endpoint agent daemon")
    parser_run.add_argument("--foreground", action="store_true", help="Log output directly to stdout")
    parser_run.add_argument("--service", action="store_true", help="Run in background service mode")
    parser_run.set_defaults(func=cmd_run)

    # status
    parser_status = subparsers.add_parser("status", help="Show current agent and buffer status")
    parser_status.set_defaults(func=lambda args: cmd_status())

    # service
    parser_service = subparsers.add_parser("service", help="Manage Windows Service task")
    parser_service.add_argument("action", choices=["install", "uninstall", "start", "stop", "status"])
    parser_service.set_defaults(func=cmd_service)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
