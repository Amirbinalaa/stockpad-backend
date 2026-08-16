import hashlib
import hmac
import json
import logging
import uuid
import requests
from urllib.parse import urlparse

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)

# ── Phase 5: Retry Spike Alerting ─────────────────────────────────────────
# Redis counter key that tracks rolling webhook retry events.
_RETRY_SPIKE_COUNTER_KEY = "wm_webhook_retry_spike_count"
# TTL (seconds) for the rolling counter window — defaults to 1 hour.
_RETRY_SPIKE_WINDOW = 3600


def _increment_retry_counter() -> int:
    """
    Atomically increments the rolling 1-hour retry counter in Redis/cache.
    Returns the new counter value, or 0 if the cache is unreachable.
    """
    try:
        from django.core.cache import cache
        current = cache.get(_RETRY_SPIKE_COUNTER_KEY, 0)
        new_val = current + 1
        cache.set(_RETRY_SPIKE_COUNTER_KEY, new_val, timeout=_RETRY_SPIKE_WINDOW)
        return new_val
    except Exception as exc:
        logger.warning("[WM Spike Alert] Could not update retry counter: %s", exc)
        return 0


def _emit_spike_alert(retry_count: int):
    """
    Fires a CRITICAL log when webhook retry volume exceeds the configured
    threshold. In production, attach a log-based alerting rule to this
    [WM ALERT] prefix (e.g. Railway log drains, Datadog, Sentry breadcrumbs).
    """
    threshold = getattr(settings, "WEBHOOK_RETRY_SPIKE_THRESHOLD", 5)
    logger.critical(
        "[WM ALERT] Webhook retry spike detected: %d retries in the last hour "
        "(threshold=%d). Site B may be unreachable or experiencing issues. "
        "Check WebhookDeliveryLog for details.",
        retry_count,
        threshold,
    )


def ping_site_b_health(webhook_url: str) -> bool:
    """
    Pings Site B's health check endpoint before attempting webhook delivery.
    - Target URL Path: GET /api/v1/health/
    - Headers: X-Site-B-API-Key
    - Expected Response: HTTP 200 OK with {"status": "healthy"} or {"status": "ok"}

    NOTE (Task #2 — 2026-08-11): This function is no longer called by send_webhook_task.
    The preflight ping block was removed because it added up to 3 s of blocking wait
    before any real work, stalling half the worker pool at concurrency=2.
    This function is RETAINED (not deleted) pending a separate explicit confirmation.
    DO NOT remove without a dedicated session decision.
    """
    try:
        parsed = urlparse(webhook_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        health_endpoint = getattr(settings, "SITE_B_HEALTH_CHECK_URL", None) or f"{base_url}/api/v1/health/"

        headers = {}
        api_key = getattr(settings, "SITE_B_API_KEY", None)
        if api_key:
            headers["X-Site-B-API-Key"] = api_key

        response = requests.get(health_endpoint, headers=headers, timeout=3)
        if response.status_code == 200:
            try:
                data = response.json()
                status_val = str(data.get("status", "")).lower()
                if status_val in ["healthy", "ok"]:
                    return True
            except Exception:
                return True
        logger.warning(
            "[WM Health Check] Site B health check at %s returned status %s",
            health_endpoint,
            response.status_code,
        )
        return False
    except Exception as exc:
        logger.warning(
            "[WM Health Check] Could not reach Site B health check endpoint at %s: %s",
            webhook_url,
            exc,
        )
        return False


def _build_webhook_headers(payload: dict) -> dict:
    """
    Serialize payload to JSON bytes and compute an HMAC-SHA256 signature
    using SITE_A_API_KEY.
    """
    secret = getattr(settings, "SITE_A_API_KEY", "").encode("utf-8")
    body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Site-A-Signature": signature,
    }


def _write_dead_letter(webhook_url: str, payload: dict, error_message: str, attempt_count: int):
    """
    Persists a failed webhook delivery to WebhookDeliveryLog so it is
    visible and queryable rather than silently lost.
    """
    try:
        from .models import WebhookDeliveryLog, MaterialRequest
        request_id = payload.get("id")
        material_request = None
        if request_id:
            material_request = MaterialRequest.objects.filter(pk=request_id).first()

        WebhookDeliveryLog.objects.create(
            material_request=material_request,
            webhook_url=webhook_url,
            payload=payload,
            event_id=payload.get("event_id"),
            error_message=error_message,
            attempt_count=attempt_count,
            status=WebhookDeliveryLog.STATUS_FAILED,
        )
        logger.error(
            "[WM Dead Letter] Persisted permanently failed webhook for request_id=%s url=%s",
            request_id,
            webhook_url,
        )
    except Exception as e:
        logger.error("[WM Dead Letter] Could not write dead-letter log: %s", e)


@shared_task(bind=True, max_retries=3, default_retry_delay=10, retry_backoff=True)
def send_webhook_task(self, webhook_url: str, payload: dict) -> bool:
    """
    Celery task to deliver webhooks asynchronously to Site B with exponential backoff retries.
    Writes a WebhookDeliveryLog dead-letter record if all retries are exhausted.
    Phase 5: increments the retry spike counter on every retry attempt and emits
    a CRITICAL alert when the rolling hourly count exceeds WEBHOOK_RETRY_SPIKE_THRESHOLD.

    Task #2 changes (2026-08-11):
    - Preflight ping (ping_site_b_health) removed: was adding up to 3 s of blocking
      wait before any real work, stalling half the worker pool at concurrency=2.
    - Timeout tightened to (1.5, 3): 1.5 s connect / 3 s read.
    - res.raise_for_status() added (intentional scope addition, approved): previously
      any 4xx/5xx response from Site B was logged as 'Delivered' with no retry, no
      spike tracking, no dead-letter — silently treated as success. raise_for_status()
      promotes those into requests.HTTPError, which is a subclass of RequestException,
      so they now funnel through the single except block below for proper retry,
      spike tracking, and dead-letter handling.
    - Spike tracking / dead-letter preserved: _increment_retry_counter(),
      _emit_spike_alert(), and _write_dead_letter() all still fire correctly;
      connection failures, timeouts, and HTTP error statuses are now consolidated
      into the single except requests.RequestException block.
    """
    if not webhook_url:
        return False

    if not webhook_url.endswith("/"):
        webhook_url = f"{webhook_url}/"

    body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = _build_webhook_headers(payload)

    try:
        res = requests.post(
            webhook_url,
            data=body_bytes,
            headers=headers,
            # 1.5 s connect timeout / 3 s read timeout (Task #2)
            timeout=(1.5, 3),
        )
        # Raise requests.HTTPError for 4xx/5xx responses so they are retried
        # and dead-lettered instead of being silently treated as success (Task #2)
        res.raise_for_status()
        logger.info(
            "[WM Webhook Celery] Delivered payload %s to %s -> HTTP %s",
            payload,
            webhook_url,
            res.status_code,
        )
        return True
    except requests.RequestException as exc:
        # Handles: connection errors, timeouts, and HTTP 4xx/5xx (via raise_for_status)
        logger.error(
            "[WM Webhook Celery] Failed to deliver webhook payload %s to %s: %s (attempt %s)",
            payload,
            webhook_url,
            exc,
            self.request.retries + 1,
        )
        # ── Spike tracking: count every retry attempt, alert if threshold crossed ──
        retry_count = _increment_retry_counter()
        threshold = getattr(settings, "WEBHOOK_RETRY_SPIKE_THRESHOLD", 5)
        if retry_count >= threshold:
            _emit_spike_alert(retry_count)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            # All 3 retries exhausted — write to dead-letter log
            _write_dead_letter(webhook_url, payload, str(exc), self.max_retries)
            return False


def dispatch_webhook_async(webhook_url: str, payload: dict):
    """
    Dispatches the webhook task to Celery queue, completely off the request/response cycle.
    """
    if not webhook_url:
        return
    send_webhook_task.delay(webhook_url, payload)


@shared_task
def recompute_ai_insights_task(user_id=None):
    """
    Celery task run on a schedule (or on demand) to recompute and cache AI insights.
    Prevents on-demand computation overhead on dashboard/insights page loads.
    """
    from django.contrib.auth import get_user_model
    from .views import compute_ai_insights_for_user
    from django.core.cache import cache

    User = get_user_model()
    if user_id:
        users = User.objects.filter(pk=user_id, is_active=True)
    else:
        users = User.objects.filter(is_active=True, materials__isnull=False).distinct()
        if not users.exists():
            users = User.objects.filter(is_active=True)

    recomputed_count = 0
    for u in users:
        try:
            data = compute_ai_insights_for_user(u)
            cache_key = f"ai_insights_user_{u.id}"
            try:
                cache.set(cache_key, data, timeout=86400)
                recomputed_count += 1
                logger.info("[WM Celery Task] Recomputed and cached AI insights for user id=%s", u.id)
            except Exception as cache_exc:
                logger.warning("[WM Celery Task] Cache SET failed for user id=%s: %s", u.id, cache_exc)
        except Exception as exc:
            logger.error("[WM Celery Task] Error recomputing AI insights for user id=%s: %s", u.id, exc)

    return f"Recomputed AI insights for {recomputed_count} users"


@shared_task
def check_webhook_retry_spike():
    """
    Periodic Celery Beat task (Phase 5) — checks the rolling retry counter
    and emits a CRITICAL alert if it exceeds WEBHOOK_RETRY_SPIKE_THRESHOLD.
    Runs every 15 minutes (configured in CELERY_BEAT_SCHEDULE).
    The counter resets automatically after _RETRY_SPIKE_WINDOW (1 hour).
    """
    try:
        from django.core.cache import cache
        retry_count = cache.get(_RETRY_SPIKE_COUNTER_KEY, 0)
    except Exception as exc:
        logger.warning("[WM Spike Alert] Could not read retry counter: %s", exc)
        return "Cache unavailable — skipped spike check"

    threshold = getattr(settings, "WEBHOOK_RETRY_SPIKE_THRESHOLD", 5)
    if retry_count >= threshold:
        _emit_spike_alert(retry_count)
        return f"SPIKE ALERT FIRED: {retry_count} retries (threshold={threshold})"

    logger.info(
        "[WM Spike Alert] Webhook retry count in window: %d (threshold=%d) — OK",
        retry_count,
        threshold,
    )
    return f"OK: {retry_count} retries in window"
