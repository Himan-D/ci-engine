# SPDX-License-Identifier: MIT
# CI Engine - Unit tests for secrets module

import pytest
from unittest.mock import MagicMock, patch
from ci_engine.core.secrets import (
    Secret,
    SecretCreate,
    SecretResponse,
    SecretService,
    _encrypt_value,
    _decrypt_value,
    _get_fernet,
)


class TestSecretEncryption:
    """Tests for secret encryption/decryption."""

    @pytest.fixture(autouse=True)
    def setup_fernet(self, monkeypatch):
        """Setup Fernet key for tests."""
        from cryptography.fernet import Fernet

        test_key = Fernet.generate_key()
        monkeypatch.setenv("CI_ENGINE_FERNET_KEY", test_key.decode())

    def test_encrypt_value(self):
        """Test encrypting a value."""
        encrypted, version = _encrypt_value("my-secret-value")
        assert isinstance(encrypted, str)
        assert version == 1

    def test_decrypt_value(self):
        """Test decrypting a value."""
        original = "my-secret-value"
        encrypted, version = _encrypt_value(original)
        decrypted = _decrypt_value(encrypted, version)
        assert decrypted == original

    def test_encrypt_produces_different_output(self):
        """Test encryption produces different ciphertext."""
        encrypted1, _ = _encrypt_value("same-value")
        encrypted2, _ = _encrypt_value("same-value")
        # Fernet produces different ciphertexts for same input due to random IV
        assert encrypted1 != encrypted2


class TestSecretService:
    """Tests for SecretService class."""

    @pytest.fixture(autouse=True)
    def setup_fernet(self, monkeypatch):
        """Setup Fernet key for tests."""
        from cryptography.fernet import Fernet

        test_key = Fernet.generate_key()
        monkeypatch.setenv("CI_ENGINE_FERNET_KEY", test_key.decode())

    def test_create_secret(self):
        """Test creating a secret."""
        mock_db = MagicMock()
        mock_secret = MagicMock()
        mock_db.add.return_value = mock_secret

        with patch("ci_engine.core.secrets._encrypt_value", return_value=("encrypted", 1)):
            SecretService.create_secret(mock_db, "TEST_KEY", "test-value", "testuser")

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_list_secrets(self):
        """Test listing secrets."""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = []

        secrets = SecretService.list_secrets(mock_db)
        assert secrets == []

    def test_get_build_env_vars_returns_dict(self):
        """Test that get_build_env_vars returns a dictionary."""
        mock_db = MagicMock()

        env_vars = SecretService.get_build_env_vars(mock_db, build_id=1)
        assert isinstance(env_vars, dict)


class TestSecretModels:
    """Tests for Secret Pydantic models."""

    def test_secret_create_validation(self):
        """Test SecretCreate validation."""
        secret = SecretCreate(name="API_KEY", value="secret123")
        assert secret.name == "API_KEY"
        assert secret.value == "secret123"

    def test_secret_create_with_description(self):
        """Test SecretCreate with optional description."""
        secret = SecretCreate(name="API_KEY", value="secret123", created_by="admin")
        assert secret.created_by == "admin"

    def test_secret_response_model(self):
        """Test SecretResponse model."""
        from datetime import datetime, timezone
        from pydantic import ConfigDict

        secret = SecretResponse(
            id=1,
            name="API_KEY",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            created_by="admin",
            is_active=True,
            key_version=1,
        )

        assert secret.id == 1
        assert secret.name == "API_KEY"
        assert secret.is_active is True
