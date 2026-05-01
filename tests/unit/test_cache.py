# SPDX-License-Identifier: MIT
# CI Engine - Unit tests for cache module

import pytest
from ci_engine.core.cache import (
    LocalCache,
    RemoteCache,
    compute_cache_key,
    compute_step_cache_key,
    BuildCacheManager,
)


class TestLocalCache:
    """Tests for LocalCache class."""

    @pytest.fixture
    def cache(self, tmp_path):
        """Create cache instance with temp directory."""
        return LocalCache(cache_dir=str(tmp_path / "cache"))

    @pytest.fixture
    def real_file(self, tmp_path):
        """Create a real file for testing."""
        f = tmp_path / "testfile.txt"
        f.write_text("test content")
        return str(f)

    def test_cache_put_and_get(self, cache, real_file):
        """Test putting and getting cache entries."""
        cache.put("test-key", real_file)
        result = cache.get("test-key")
        assert result is not None

    def test_cache_get_missing(self, cache):
        """Test getting non-existent key returns None."""
        result = cache.get("missing-key")
        assert result is None

    def test_cache_delete(self, cache, real_file):
        """Test deleting cache entries."""
        cache.put("delete-key", real_file)
        result = cache.delete("delete-key")
        assert result is True

    def test_cache_list(self, cache):
        """Test listing cache entries."""
        entries = cache.list()
        assert isinstance(entries, list)

    def test_cache_clear(self, cache):
        """Test clearing all cache entries."""
        count = cache.clear()
        assert isinstance(count, int)


class TestRemoteCache:
    """Tests for RemoteCache class."""

    @pytest.fixture
    def remote_cache(self):
        """Create remote cache instance."""
        return RemoteCache(bucket="test-bucket")

    def test_remote_cache_init(self, remote_cache):
        """Test remote cache initialization."""
        assert remote_cache.bucket == "test-bucket"
        assert remote_cache.region == "us-east-1"

    def test_remote_cache_with_custom_region(self):
        """Test remote cache with custom region."""
        cache = RemoteCache(bucket="my-bucket", region="us-west-2")
        assert cache.bucket == "my-bucket"
        assert cache.region == "us-west-2"


class TestComputeCacheKey:
    """Tests for cache key computation."""

    def test_compute_cache_key_basic(self):
        """Test basic cache key computation."""
        key = compute_cache_key(build_id=1, job_id=1, cache_key="npm-deps")
        assert isinstance(key, str)
        assert len(key) > 0

    def test_compute_cache_key_with_files(self):
        """Test cache key with files list."""
        key = compute_cache_key(
            build_id=1, job_id=1, cache_key="npm-deps", files=["package.json", "package-lock.json"]
        )
        assert isinstance(key, str)

    def test_compute_step_cache_key(self):
        """Test step cache key computation."""
        key = compute_step_cache_key(build_id=1, step_key="npm-deps", branch="main")
        assert isinstance(key, str)
        assert key.startswith("cache/")

    def test_compute_step_cache_key_different_branches(self):
        """Test different branches produce different keys."""
        key1 = compute_step_cache_key(build_id=1, step_key="npm", branch="main")
        key2 = compute_step_cache_key(build_id=1, step_key="npm", branch="develop")
        assert key1 != key2


class TestBuildCacheManager:
    """Tests for BuildCacheManager class."""

    def test_manager_init(self):
        """Test manager initialization."""
        manager = BuildCacheManager(build_id=123, branch="main")
        assert manager.build_id == 123
        assert manager.branch == "main"

    def test_manager_with_remote(self):
        """Test manager with remote cache."""
        remote = RemoteCache(bucket="test")
        manager = BuildCacheManager(build_id=1, branch="main", remote_cache=remote)
        assert manager.remote_cache is remote
