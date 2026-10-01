"""Locate and download the monitored resource through the CKAN API."""

import hashlib
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "5ltep-layer3/0.1 (+https://github.com/lsp3cesarschool/5ltep-layer3)"
# (connect, read): a connection the portal refuses fails in 15 s instead of 120 s, and one keep-alive
# session reuses connections (some portals intermittently refuse new connections).
TIMEOUT = (15, 120)
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


def _get_with_retry(url: str, retries: int = 6, backoff: float = 15.0, **kwargs):
    """Portals go down for minutes at a time: 6 attempts spread over about 8 minutes."""
    for attempt in range(1, retries + 1):
        try:
            resp = SESSION.get(url, timeout=TIMEOUT, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            if attempt == retries:
                raise
            wait = backoff * 2 ** (attempt - 1)
            logger.warning("GET %s failed (%s); retrying in %.0fs", url, exc, wait)
            time.sleep(wait)


def resolve_resource(portal_url: str, dataset_id: str, resource_name: str, fmt: str = "CSV") -> dict:
    """Return the resource of `dataset_id` whose name and format match.

    The URL is looked up at every run instead of being stored in the profile,
    so the pipeline follows the portal when files move to another host.
    """
    url = f"{portal_url.rstrip('/')}/api/3/action/package_show?id={dataset_id}"
    package = _get_with_retry(url).json()["result"]
    for res in package["resources"]:
        if (res.get("name") or "").strip() == resource_name.strip() and (res.get("format") or "").upper() == fmt.upper():
            return {
                "dataset_id": dataset_id,
                "dataset_url": f"{portal_url.rstrip('/')}/dataset/{dataset_id}",
                "dataset_metadata_modified": package.get("metadata_modified"),
                "license": package.get("license_title"),
                "resource_id": res.get("id"),
                "resource_name": res.get("name"),
                "resource_url": res["url"],
            }
    names = [f"{r.get('name')} ({r.get('format')})" for r in package["resources"]]
    raise LookupError(f"{fmt} resource {resource_name!r} not found in dataset {dataset_id!r}; available: {names}")


def download(url: str, dest: Path) -> dict:
    """Stream `url` to `dest` and return its size and SHA-256."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256()
    size = 0
    started = datetime.now(timezone.utc)
    resp = _get_with_retry(url, stream=True)
    with open(dest, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            fh.write(chunk)
            sha.update(chunk)
            size += len(chunk)
    logger.info("Downloaded %s (%.1f MB)", url, size / 1e6)
    return {
        "download_started_at": started.isoformat(timespec="seconds"),
        "size_bytes": size,
        "checksum_sha256": sha.hexdigest(),
    }
