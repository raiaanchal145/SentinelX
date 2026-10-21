"""
SentinelX API Client for Device Enrollment, Telemetry Ingestion, and Heartbeat.

Handles HTTP communication, rate limiting backoff, time sync sanity checks,
and immediate kill-switch on device revocation.
"""

from __future__ import annotations

import email.utils
import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

from agent.config import AgentConfig
from agent.crypto import mask_secret

logger = logging.getLogger("sentinelx.agent.client")

# Max allowed clock skew between endpoint and SentinelX server (5 minutes)
MAX_CLOCK_SKEW_SECONDS = 300.0


class AgentApiError(Exception):
    """Base API exception with HTTP code and detail message."""

    def __init__(self, message: str, status_code: int = 0, error_code: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class TransientError(AgentApiError):
    """Network connection failure or 5xx server error; should be retried."""
    pass


class RateLimitedError(TransientError):
    """429 Rate limited; contains retry delay."""

    def __init__(self, message: str, retry_after: float = 5.0) -> None:
        super().__init__(message, status_code=429, error_code="rate_limited")
        self.retry_after = retry_after


class RevokedError(AgentApiError):
    """Device or consent revoked by administrator; agent must halt."""
    pass


class ConsentRequiredError(AgentApiError):
    """Enrollment token has not been authorized on consent screen."""
    pass


class TokenExpiredError(AgentApiError):
    """Enrollment token expired (> 30 minutes)."""
    pass


class TokenUsedError(AgentApiError):
    """Enrollment token was already consumed."""
    pass


class SentinelXClient:
    """Client for SentinelX Agent API endpoints."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def _make_request(
        self,
        endpoint: str,
        data: Optional[dict[str, Any]] = None,
        method: str = "GET",
        auth_required: bool = True,
        timeout: float = 15.0,
    ) -> tuple[dict[str, Any], email.message.Message]:
        url = self.config.server_url.rstrip("/") + endpoint
        headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": f"SentinelX-Endpoint-Agent/{self.config.agent_version}",
        }

        if auth_required:
            api_key = self.config.get_api_key()
            if not api_key:
                raise AgentApiError("No device API key configured.", status_code=401)
            headers["Authorization"] = f"Bearer {api_key}"

        body_bytes = None
        if data is not None:
            body_bytes = json.dumps(data, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
                resp_headers = resp.headers
                raw_body = resp.read().decode("utf-8")
                parsed = json.loads(raw_body) if raw_body else {}
                self._check_time_sync(resp_headers)
                return parsed, resp_headers

        except urllib.error.HTTPError as exc:
            status = exc.code
            raw_err = exc.read().decode("utf-8")
            err_code = None
            err_msg = f"HTTP {status}"

            try:
                err_data = json.loads(raw_err)
                if isinstance(err_data.get("detail"), dict):
                    err_code = err_data["detail"].get("code")
                    err_msg = err_data["detail"].get("message", err_msg)
                elif isinstance(err_data.get("detail"), str):
                    err_msg = err_data["detail"]
            except Exception:
                err_msg = raw_err or err_msg

            # Handle specific error codes
            if status == 403:
                if err_code in ("device_revoked", "consent_revoked") or "revoked" in err_msg.lower():
                    raise RevokedError(f"Device revoked: {err_msg}", status_code=403, error_code=err_code)
                if err_code == "consent_required":
                    raise ConsentRequiredError(err_msg, status_code=403, error_code=err_code)

            if status == 409:
                if err_code == "enrollment_token_expired":
                    raise TokenExpiredError(err_msg, status_code=409, error_code=err_code)
                if err_code == "enrollment_token_used":
                    raise TokenUsedError(err_msg, status_code=409, error_code=err_code)

            if status == 429:
                retry_after_hdr = exc.headers.get("Retry-After")
                retry_seconds = 5.0
                if retry_after_hdr:
                    try:
                        retry_seconds = float(retry_after_hdr)
                    except ValueError:
                        pass
                raise RateLimitedError(f"Rate limited by server: {err_msg}", retry_after=retry_seconds)

            if status >= 500:
                raise TransientError(f"Server error {status}: {err_msg}", status_code=status, error_code=err_code)

            raise AgentApiError(err_msg, status_code=status, error_code=err_code)

        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransientError(f"Connection failure to {url}: {exc}") from exc

    def _check_time_sync(self, headers: email.message.Message) -> None:
        """Verifies endpoint clock against server HTTP Date header."""
        date_hdr = headers.get("Date")
        if not date_hdr:
            return
        try:
            server_tuple = email.utils.parsedate_to_datetime(date_hdr)
            server_time = server_tuple.timestamp()
            local_time = datetime.now(timezone.utc).timestamp()
            drift = abs(local_time - server_time)
            if drift > MAX_CLOCK_SKEW_SECONDS:
                logger.warning(
                    "CLOCK DRIFT DETECTED: Endpoint time differs from server by %.1f seconds (> 300s). "
                    "Ensure Windows Time service (W32Time) is running.",
                    drift,
                )
        except Exception:
            pass

    def enroll(
        self,
        token: str,
        device_name: Optional[str] = None,
        operating_system: Optional[str] = None,
    ) -> dict[str, Any]:
        """Swaps one-time enrollment token for device API key."""
        logger.info("Enrolling endpoint with token %s ...", mask_secret(token))
        payload = {
            "enrollment_token": token.strip(),
            "device_name": device_name or self.config.device_name,
            "operating_system": operating_system or self.config.operating_system,
            "agent_version": self.config.agent_version,
        }
        res, _ = self._make_request("/agent/enroll", data=payload, method="POST", auth_required=False)
        device_id = res.get("device_id")
        api_key = res.get("api_key")
        categories = res.get("enabled_categories", [])
        consent_ver = res.get("consent_version", "v1.0")

        if not api_key or not device_id:
            raise AgentApiError("Malformed enrollment response from server.")

        self.config.device_id = device_id
        if device_name:
            self.config.device_name = device_name
        if operating_system:
            self.config.operating_system = operating_system
        self.config.save_api_key(api_key)
        self.config.update_consent(categories, consent_ver)
        logger.info("Enrollment succeeded for device ID %s. Granted categories: %s", device_id, categories)
        return res

    def heartbeat(self) -> dict[str, Any]:
        """Sends periodic heartbeat to maintain 'connected' status and sync consent config."""
        payload = {"agent_version": self.config.agent_version}
        res, _ = self._make_request("/agent/heartbeat", data=payload, method="POST", auth_required=True)
        status = res.get("status")
        terminate = res.get("terminate", False)

        if terminate or status == "revoked":
            logger.error("Server signaled that device or consent has been REVOKED.")
            raise RevokedError("Device authorization revoked by administrator.", status_code=403)

        categories = res.get("enabled_categories")
        if categories is not None and set(categories) != self.config.enabled_categories:
            logger.info("Consent categories updated from server: %s", categories)
            self.config.update_consent(categories)

        self.config.last_heartbeat_at = datetime.now(timezone.utc).isoformat()
        self.config.save()
        return res

    def send_events(self, events: list[dict[str, Any]]) -> tuple[int, int, int]:
        """
        Sends a batch of events to /api/v1/events.
        Returns (accepted_count, rejected_count, rejected_no_consent_count).
        """
        if not events:
            return 0, 0, 0

        res, headers = self._make_request(
            "/events",
            data={"events": events},
            method="POST",
            auth_required=True,
            timeout=20.0,
        )

        accepted = int(res.get("accepted", 0))
        rejected = int(res.get("rejected", 0))
        no_consent = int(res.get("rejected_no_consent", 0))

        warning_hdr = headers.get("X-Ingestion-Warning")
        if warning_hdr:
            logger.warning("Ingestion warning from server: %s", warning_hdr)

        return accepted, rejected, no_consent

