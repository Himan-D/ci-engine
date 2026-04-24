# SPDX-License-Identifier: MIT
# CI Engine - Build Cache System

import os
import json
import hashlib
import shutil
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from pathlib import Path


logger = logging.getLogger(__name__)


class CacheError(Exception):
    """Base exception for cache errors."""

    pass


class CacheNotFoundError(CacheError):
    """Cache entry not found."""

    pass


class CacheBackendUnavailableError(CacheError):
    """Cache backend is unavailable."""

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
                if datetime.now(timezone.utc) > expires:
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
        expires_at = (datetime.now(timezone.utc) + timedelta(days=ttl)).isoformat()

        meta = {
            "key": key,
            "size": size,
            "created_at": datetime.now(timezone.utc).isoformat(),
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

        total_size = sum(f.stat().st_size for f in self.cache_dir.rglob("*") if f.is_file())

        if total_size <= max_bytes:
            return

        entries = sorted(self.list(), key=lambda e: e.created_at)

        for entry in entries:
            if total_size <= max_bytes * 0.9:
                break
            self.delete(entry.key)
            total_size -= entry.size


class RemoteCache:
    """Remote cache backend using S3-compatible storage.

    Supports AWS S3, Google Cloud Storage (via gcs hook), MinIO, and other S3-compatible backends.

    Environment variables:
        CI_ENGINE_CACHE_BUCKET: S3 bucket name (default: ci-engine-cache)
        AWS_REGION: AWS region (default: us-east-1)
        AWS_ACCESS_KEY_ID: AWS access key (optional, uses IAM if not provided)
        AWS_SECRET_ACCESS_KEY: AWS secret key (optional, uses IAM if not provided)
        S3_ENDPOINT_URL: S3-compatible endpoint URL (for MinIO, etc.)
    """

    def __init__(
        self,
        bucket: Optional[str] = None,
        region: Optional[str] = None,
    ):
        self.bucket = bucket or os.environ.get("CI_ENGINE_CACHE_BUCKET", "ci-engine-cache")
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.endpoint_url = os.environ.get("S3_ENDPOINT_URL")
        self.access_key = os.environ.get("AWS_ACCESS_KEY_ID")
        self.secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
        self._client = None

    def _get_client(self):
        """Get or create S3 client."""
        if self._client is not None:
            return self._client

        try:
            import boto3
            from botocore.config import Config

            config = Config(
                retries={"max_attempts": 3},
                connect_timeout=5,
                read_timeout=30,
            )

            client_kwargs = {
                "service_name": "s3",
                "region_name": self.region,
                "config": config,
            }

            if self.access_key and self.secret_key:
                client_kwargs["aws_access_key_id"] = self.access_key
                client_kwargs["aws_secret_access_key"] = self.secret_key

            if self.endpoint_url:
                client_kwargs["endpoint_url"] = self.endpoint_url

            self._client = boto3.client(**client_kwargs)
            logger.info(f"Initialized S3 client for bucket: {self.bucket}")
            return self._client
        except ImportError:
            logger.warning("boto3 not available, RemoteCache disabled")
            return None
        except Exception as e:
            logger.warning(f"Failed to initialize S3 client: {e}")
            return None

    def get(self, key: str) -> Optional[bytes]:
        """Get cache entry from remote storage.

        Args:
            key: Cache key to retrieve

        Returns:
            Cache data as bytes, or None if not found
        """
        try:
            client = self._get_client()
            if client is None:
                return None

            response = client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except client.exceptions.NoSuchKey if client else None:
            return None
        except Exception as e:
            logger.error(f"RemoteCache.get failed for key {key}: {e}")
            return None

    def put(self, key: str, data: bytes, ttl_days: int = 7) -> str:
        """Store cache entry in remote storage.

        Args:
            key: Cache key
            data: Data to store
            ttl_days: Time to live in days (uses bucket lifecycle if available)

        Returns:
            The cache key on success
        """
        try:
            client = self._get_client()
            if client is None:
                logger.warning("RemoteCache not available, skipping put")
                return key

            client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
            )
            logger.debug(f"Stored cache key {key} ({len(data)} bytes)")
            return key
        except Exception as e:
            logger.error(f"RemoteCache.put failed for key {key}: {e}")
            return key

    def delete(self, key: str) -> bool:
        """Delete cache entry from remote storage.

        Args:
            key: Cache key to delete

        Returns:
            True if deleted successfully
        """
        try:
            client = self._get_client()
            if client is None:
                return False

            client.delete_object(Bucket=self.bucket, Key=key)
            logger.debug(f"Deleted cache key {key}")
            return True
        except Exception as e:
            logger.error(f"RemoteCache.delete failed for key {key}: {e}")
            return False

    def exists(self, key: str) -> bool:
        """Check if cache entry exists in remote storage.

        Args:
            key: Cache key to check

        Returns:
            True if exists, False otherwise
        """
        try:
            client = self._get_client()
            if client is None:
                return False

            client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def list_keys(self, prefix: str = "") -> list[str]:
        """List all cache keys with optional prefix filter.

        Args:
            prefix: Optional prefix to filter keys

        Returns:
            List of cache keys
        """
        try:
            client = self._get_client()
            if client is None:
                return []

            paginator = client.get_paginator("list_objects_v2")
            keys = []

            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    keys.append(obj["Key"])

            return keys
        except Exception as e:
            logger.error(f"RemoteCache.list_keys failed: {e}")
            return []

    def close(self):
        """Close the S3 client."""
        self._client = None

    def cleanup_expired(self, prefix: str = "", max_age_days: int = 7) -> int:
        """Clean up expired cache entries.

        Args:
            prefix: Only delete keys with this prefix
            max_age_days: Delete keys older than this many days

        Returns:
            Number of entries deleted
        """
        try:
            keys = self.list_keys(prefix)
            deleted = 0
            cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

            client = self._get_client()
            if client is None:
                return 0

            for key in keys:
                try:
                    response = client.head_object(Bucket=self.bucket, Key=key)
                    last_modified = response["LastModified"]

                    if last_modified.tzinfo:
                        last_modified = last_modified.replace(tzinfo=None)
                    if last_modified < cutoff:
                        self.delete(key)
                        deleted += 1
                except Exception:
                    continue

            logger.info(f"Cleaned up {deleted} expired cache entries")
            return deleted
        except Exception as e:
            logger.error(f"RemoteCache.cleanup_expired failed: {e}")
            return 0


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


def compute_step_cache_key(
    build_id: int,
    step_key: str,
    branch: str = "main",
) -> str:
    """Compute cache key for a pipeline step.

    This enables cross-step caching by computing a consistent key
    based on the step configuration and branch.

    Args:
        build_id: Build ID
        step_key: Unique identifier for the step (e.g., "npm-deps")
        branch: Git branch name

    Returns:
        Cache key string
    """
    components = [str(build_id), step_key, branch]
    combined = "|".join(components)
    return f"cache/{build_id}/{step_key}/{hashlib.sha256(combined.encode()).hexdigest()[:16]}"


class BuildCacheManager:
    """Manages cross-step cache for builds.

    Usage:
        manager = BuildCacheManager(build_id=123, branch="main")

        # Check if cache exists for step
        if await manager.restore("npm-deps"):
            # Use cached node_modules
            pass

        # After step completes, save cache
        await manager.save("npm-deps", "/path/to/node_modules")
    """

    def __init__(
        self, build_id: int, branch: str = "main", remote_cache: RemoteCache | None = None
    ):
        self.build_id = build_id
        self.branch = branch
        self.remote_cache = remote_cache or get_remote_cache()
        self.local_cache = get_cache()

    async def restore(self, step_key: str, path: str) -> bool:
        """Restore cache for a step.

        Args:
            step_key: Unique identifier for the step
            path: Local path to restore cache to

        Returns:
            True if cache was restored
        """
        cache_key = compute_step_cache_key(self.build_id, step_key, self.branch)

        # Try remote first
        try:
            data = self.remote_cache.get(cache_key)
            if data:
                import tempfile
                import tarfile
                import io

                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(data)
                    tmp.flush()

                    with tarfile.open(tmp.name, "r:gz") as tar:
                        tar.extractall(path)

                logger.info(f"Restored cache for step {step_key} from remote")
                return True
        except Exception as e:
            logger.debug(f"Remote cache restore failed: {e}")

        # Try local cache
        local_path = self.local_cache.get(cache_key)
        if local_path and os.path.exists(local_path):
            import shutil

            shutil.copytree(local_path, path, dirs_exist_ok=True)
            logger.info(f"Restored cache for step {step_key} from local")
            return True

        return False

    async def save(self, step_key: str, path: str) -> bool:
        """Save cache for a step.

        Args:
            step_key: Unique identifier for the step
            path: Local path to cache

        Returns:
            True if cache was saved
        """
        if not os.path.exists(path):
            return False

        cache_key = compute_step_cache_key(self.build_id, step_key, self.branch)

        # Save to remote
        try:
            import tempfile
            import tarfile
            import io

            with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as tmp:
                with tarfile.open(tmp.name, "w:gz") as tar:
                    tar.add(path, arcname=os.path.basename(path))
                tmp.flush()

                with open(tmp.name, "rb") as f:
                    data = f.read()

            self.remote_cache.put(cache_key, data)
            logger.info(f"Saved cache for step {step_key} to remote")
        except Exception as e:
            logger.debug(f"Remote cache save failed: {e}")

        # Also save to local
        try:
            self.local_cache.put(cache_key, path)
            logger.info(f"Saved cache for step {step_key} to local")
        except Exception as e:
            logger.debug(f"Local cache save failed: {e}")

        return True

    async def clear(self) -> bool:
        """Clear all cache for this build.

        Returns:
            True if cleared
        """
        cache_prefix = f"cache/{self.build_id}/"

        try:
            keys = self.remote_cache.list_keys(cache_prefix)
            for key in keys:
                self.remote_cache.delete(key)
        except Exception:
            pass

        local_entries = self.local_cache.list()
        for entry in local_entries:
            if str(self.build_id) in entry.key:
                self.local_cache.delete(entry.key)

        logger.info(f"Cleared cache for build {self.build_id}")
        return True


_cache: Optional[LocalCache] = None
_remote_cache: Optional[RemoteCache] = None


def get_cache() -> LocalCache:
    """Get the local cache singleton."""
    global _cache
    if _cache is None:
        _cache = LocalCache()
    return _cache


def get_remote_cache() -> RemoteCache:
    """Get the remote cache singleton (S3-compatible)."""
    global _remote_cache
    if _remote_cache is None:
        _remote_cache = RemoteCache()
    return _remote_cache
