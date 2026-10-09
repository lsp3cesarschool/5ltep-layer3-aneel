"""Locate and download the monitored resource through the CKAN API."""

import hashlib
import logging
import re
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


def resolve_resources(source: dict) -> tuple[dict, list[dict]]:
    """Return the dataset metadata and the resources of a profile's `source`, in name order.

    `resource_name` matches one resource exactly; `resource_pattern` (a regular expression,
    case-insensitive, matching the whole name) matches every resource of a dataset published
    as one file per year, as some portals do. The URLs are looked up at every run instead of
    being stored in the profile, so the pipeline follows the portal when files move to another
    host, and a pattern picks up the files of new years by itself.
    """
    portal_url, dataset_id = source["portal_url"].rstrip("/"), source["dataset_id"]
    fmt = source.get("resource_format", "CSV").upper()
    package = _get_with_retry(f"{portal_url}/api/3/action/package_show?id={dataset_id}").json()["result"]
    if source.get("resource_pattern"):
        pattern = re.compile(source["resource_pattern"], re.IGNORECASE)
        wanted, label = (lambda name: pattern.fullmatch(name) is not None), f"matching {source['resource_pattern']!r}"
    else:
        wanted, label = (lambda name: name == source["resource_name"].strip()), repr(source["resource_name"])
    found = sorted(({"resource_id": r.get("id"), "resource_name": r.get("name"), "resource_url": r["url"]}
                    for r in package["resources"]
                    if wanted((r.get("name") or "").strip()) and (r.get("format") or "").upper() == fmt),
                   key=lambda r: r["resource_name"])
    if not found:
        names = [f"{r.get('name')} ({r.get('format')})" for r in package["resources"]]
        raise LookupError(f"No {fmt} resource {label} in dataset {dataset_id!r}; available: {names}")
    dataset = {
        "dataset_id": dataset_id,
        "dataset_url": f"{portal_url}/dataset/{dataset_id}",
        "dataset_metadata_modified": package.get("metadata_modified"),
        "license": package.get("license_title"),
    }
    return dataset, found


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
