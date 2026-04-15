# SPDX-License-Identifier: MIT
# CI Engine - Unit tests for auth module

from ci_engine.server.auth import (
    hash_password,
    verify_password,
    generate_api_token,
    hash_api_token,
    Permission,
)


class TestPasswordHashing:
    """Tests for password hashing functions."""

    def test_hash_password_returns_string(self):
        """Test that hash_password returns a string with salt."""
        result = hash_password("testpassword")
        assert isinstance(result, str)
        assert "$" in result  # Salt is separated by $

    def test_verify_password_correct(self):
        """Test verifying correct password."""
        password = "testpassword"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Test verifying incorrect password."""
        password = "testpassword"
        hashed = hash_password(password)
        assert verify_password("wrongpassword", hashed) is False

    def test_verify_password_invalid_hash(self):
        """Test verifying against invalid hash."""
        assert verify_password("password", "invalidhash") is False


class TestApiToken:
    """Tests for API token functions."""

    def test_generate_api_token_length(self):
        """Test token generation produces correct length."""
        token = generate_api_token()
        assert len(token) >= 32

    def test_hash_api_token_consistency(self):
        """Test token hashing is consistent."""
        token = "test_token_123"
        hash1 = hash_api_token(token)
        hash2 = hash_api_token(token)
        assert hash1 == hash2

    def test_hash_api_token_different_tokens(self):
        """Test different tokens produce different hashes."""
        hash1 = hash_api_token("token1")
        hash2 = hash_api_token("token2")
        assert hash1 != hash2


class TestPermissions:
    """Tests for permission system."""

    def test_admin_can_do_everything(self):
        """Test admin role has all permissions."""
        assert Permission.can_create_build("admin") is True
        assert Permission.can_cancel_build("admin") is True
        assert Permission.can_manage_agents("admin") is True
        assert Permission.can_manage_users("admin") is True

    def test_developer_can_build(self):
        """Test developer role has build permissions."""
        assert Permission.can_create_build("developer") is True
        assert Permission.can_cancel_build("developer") is True
        assert Permission.can_manage_agents("developer") is False

    def test_viewer_can_only_view(self):
        """Test viewer role has read-only access."""
        assert Permission.can_create_build("viewer") is False
        assert Permission.can_cancel_build("viewer") is False
        assert Permission.can_view_builds("viewer") is True
        assert Permission.can_manage_agents("viewer") is False
