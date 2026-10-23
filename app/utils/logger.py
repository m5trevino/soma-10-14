"""PEA (Post-Execution Analytics) SDK callback notifier.

After a PEA file is written to the vault, notify an external SDK endpoint
so downstream analytics can index and process the new artifact.

Usage — caller writes the PEA file, then calls notify_pea_on_vault_write:

    from app.utils.logger import notify_pea_on_vault_write

    vault_file.write_text(content)
    notify_pea_on_vault_write(vault_file, tag="my-tag")

The callback is fire-and-forget: runs in a background thread, never raises,
and never blocks the calling code.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def notify_pea_on_vault_write(
    vault_file_path: str | os.PathLike[str],
    *,
    tag: str = "",
    success: bool = True,
) -> None:
    """Fire-and-forget POST of a PEA write event to the SDK callback URL.

    Reads ``PEA_SDK_CALLBACK_URL`` from the environment.  When set and the
    POST succeeds (or returns any HTTP status), the event is delivered.  When
    the URL is empty or the request fails, the caller continues without error.

    Parameters
    ----------
    vault_file_path : str | PathLike
        Absolute or relative path of the PEA file just written.
    tag : str
        Business tag for the PEA file (e.g. stage name, session id, etc.).
    success : bool
        Whether the PEA write completed successfully.
    """
    callback_url = os.environ.get("PEA_SDK_CALLBACK_URL", "").strip()
    event = {
        "path": str(vault_file_path),
        "tag": tag or "",
        "success": success,
    }

    _print_scp(vault_file_path, tag=tag, success=success)

    if not callback_url:
        return  # No URL configured — quiet no-op

    _send(callback_url, event)


# ---------------------------------------------------------------------------
# SCP notification
# ---------------------------------------------------------------------------


def _print_scp(vault_file_path: str | os.PathLike[str], *, tag: str = "", success: bool = True) -> None:
    """Print a ready-to-copy scp command to stdout after a PEA file is written.

    Parameters
    ----------
    vault_file_path : str | PathLike
        Path of the PEA file just written.
    tag : str
        PEA tag (e.g. ``"PEA-001"``).
    success : bool
        Whether the strike completed successfully.
    """
    filename = os.path.basename(str(vault_file_path))
    sub_dir = "successful" if success else "failed"
    scp_cmd = f'scp -i ~/.ssh/hetzner {filename} root@204.168.184.49:vault/{sub_dir}/{filename}'
    print(f"{tag}: {scp_cmd}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _send(url: str, payload: dict) -> None:
    """POST *payload* as JSON to *url* in a background thread."""
    t = threading.Thread(
        target=_post,
        args=(url, payload),
        daemon=True,
        name="pea-callback",
    )
    t.start()


def _post(url: str, payload: dict) -> None:
    """Actually perform the HTTP POST (runs in background thread).

    Never raises — every exception is swallowed and logged.
    """
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            logger.debug(
                "PEA callback OK: %s status=%d", url, resp.status,
            )
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        logger.debug(
            "PEA callback failed (non-fatal): %s — %s", url, exc,
        )
    except Exception:
        # Catch-all: we absolutely must not let the callback bubble up.
        logger.debug(
            "PEA callback unexpected error (non-fatal): %s", url,
            exc_info=True,
        )
