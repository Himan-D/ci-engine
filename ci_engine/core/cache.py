# SPDX-License-Identifier: MIT
# CI Engine - Build Cache System

import os
import json
import hashlib
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path


class CacheError(Exception):
    """Base exception for cache errors."""

    pass


class CacheNotFoundError(CacheError):
    """Cache entry not found."""

    pass


@dataclass
class CacheEntry:
    """Cache entry metadata."""

    key: str
    path: str
    size: int
    created_at: datetime
    expires_at: Optional[datetime]
    hit_count: int = 0


class LocalCache:
    """Local filesystem cache for build dependencies."""

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = Path(
            cache_dir
            or os.environ.get("CI_ENGINE_CACHE_DIR", os.path.expanduser("~/.ci-engine/cache"))
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_size_gb = float(os.environ.get("CI_ENGINE_CACHE_MAX_GB", "10"))
        self.default_ttl_days = int(os.environ.get("CI_ENGINE_CACHE_TTL_DAYS", "7"))

    def _get_cache_path(self, key: str) -> Path:
        """Get filesystem path for cache key."""
        key_hash = hashlib.sha256(key.encode()).hexdigest()[:16]
        return self.cache_dir / key_hash[:2] / key_hash

    def _get_meta_path(self, key: str) -> Path:
        """Get metadata path for cache key."""
        return self._get_cache_path(key).with_suffix(".meta")

    def get(self, key: str) -> Optional[str]:
        """Get cache entry. Returns path to cached files or None."""
        cache_path = self._get_cache_path(key)
        meta_path = self._get_meta_path(key)

        if not cache_path.exists():
            return None

        try:
            with open(meta_path, "r") as f:
                meta = json.load(f)

            expires_at = meta.get("expires_at")
            if expires_at:
                expires = datetime.fromisoformat(expires_at)
                if datetime.utcnow() > expires:
                    self.delete(key)
                    return None

            meta["hit_count"] = meta.get("hit_count", 0) + 1
            with open(meta_path, "w") as f:
                json.dump(meta, f)

            return str(cache_path)
        except (json.JSONDecodeError, FileNotFoundError):
            return None

    def put(
        self,
        key: str,
        source_path: str,
        ttl_days: Optional[int] = None,
    ) -> str:
        """Store files in cache. Returns cache key."""
        cache_path = self._get_cache_path(key)
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        if cache_path.exists():
            shutil.rmtree(cache_path)

        if os.path.isdir(source_path):
            shutil.copytree(source_path, cache_path)
            size = sum(f.stat().st_size for f in cache_path.rglob("*") if f.is_file())
        else:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, cache_path)
            size = os.path.getsize(cache_path)

        ttl = ttl_days or self.default_ttl_days
        expires_at = (datetime.utcnow() + timedelta(days=ttl)).isoformat()

        meta = {
            "key": key,
            "size": size,
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": expires_at,
            "hit_count": 0,
        }

        with open(self._get_meta_path(key), "w") as f:
            json.dump(meta, f)

        self._enforce_max_size()
        return key

    def delete(self, key: str) -> bool:
        """Delete cache entry. Returns True if deleted."""
        cache_path = self._get_cache_path(key)
        meta_path = self._get_meta_path(key)

        deleted = False
        if cache_path.exists():
            if cache_path.is_dir():
                shutil.rmtree(cache_path)
            else:
                cache_path.unlink()
            deleted = True

        if meta_path.exists():
            meta_path.unlink()

        return deleted

    def clear(self) -> int:
        """Clear all cache entries. Returns count cleared."""
        count = 0
        for item in self.cache_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
                count += 1
            elif item.suffix == ".meta":
                item.unlink()
                count += 1
        return count

    def list(self) -> list[CacheEntry]:
        """List all cache entries."""
        entries = []
        for meta_path in self.cache_dir.rglob("*.meta"):
            try:
                with open(meta_path, "r") as f:
                    meta = json.load(f)

                cache_path = meta_path.with_suffix("")
                entries.append(
                    CacheEntry(
                        key=meta["key"],
                        path=str(cache_path),
                        size=meta["size"],
                        created_at=datetime.fromisoformat(meta["created_at"]),
                        expires_at=datetime.fromisoformat(meta["expires_at"])
                        if meta.get("expires_at")
                        else None,
                        hit_count=meta.get("hit_count", 0),
                    )
                )
            except (json.JSONDecodeError, FileNotFoundError):
                continue
        return entries

    def _enforce_max_size(self):
        """Remove oldest entries if cache exceeds max size."""
        max_bytes = int(self.max_size_gb * 1024 * 1024 * 1024)

        total_size = sum(sum(f.stat().st_size for f in self.cache_dir.rglob("*") if f.is_file()))

        if total_size <= max_bytes:
            return

        entries = sorted(self.list(), key=lambda e: e.created_at)

        for entry in entries:
            if total_size <= max_bytes * 0.9:
                break
            self.delete(entry.key)
            total_size -= entry.size


class RemoteCache:
    """Remote cache backend (S3-compatible)."""

    def __init__(
        self,
        bucket: Optional[str] = None,
        region: Optional[str] = None,
    ):
        self.bucket = bucket or os.environ.get("CI_ENGINE_CACHE_BUCKET", "ci-engine-cache")
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")

    async def get(self, key: str) -> Optional[bytes]:
        """Get cache entry from remote storage."""
        return None

    async def put(self, key: str, data: bytes, ttl_days: int = 7) -> str:
        """Store cache entry in remote storage."""
        return key

    async def delete(self, key: str) -> bool:
        """Delete cache entry from remote storage."""
        return True

    async def exists(self, key: str) -> bool:
        """Check if cache entry exists in remote storage."""
        return False


def compute_cache_key(
    build_id: int,
    job_id: int,
    cache_key: str,
    files: Optional[list[str]] = None,
) -> str:
    """Compute cache key from components."""
    components = [str(build_id), str(job_id), cache_key]
    if files:
        components.extend(sorted(files))

    combined = "|".join(components)
    return hashlib.sha256(combined.encode()).hexdigest()


_cache: Optional[LocalCache] = None


def get_cache() -> LocalCache:
    """Get the cache singleton."""
    global _cache
    if _cache is None:
        _cache = LocalCache()
    return _cache
