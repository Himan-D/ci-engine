# SPDX-License-Identifier: MIT
# CI Engine - OIDC Provider Configuration

import os
from typing import Optional
from enum import Enum


class OIDCProvider(str, Enum):
    """Supported OIDC providers."""

    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    GITHUB = "github"


class OIDCConfig:
    """Configuration for an OIDC provider."""

    def __init__(
        self,
        provider: OIDCProvider,
        client_id: str,
        client_secret: str,
        issuer_url: str,
        audience: Optional[str] = None,
        scopes: list[str] | None = None,
    ):
        self.provider = provider
        self.client_id = client_id
        self.client_secret = client_secret
        self.issuer_url = issuer_url
        self.audience = audience or client_id
        self.scopes = scopes or ["openid", "email", "profile"]

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "provider": self.provider.value,
            "client_id": self.client_id,
            "issuer_url": self.issuer_url,
            "audience": self.audience,
            "scopes": self.scopes,
        }


class OIDCProviderManager:
    """Manage OIDC provider configurations."""

    AWS_ISSUER = "https://oidc.eks.us-east-1.amazonaws.com/id"
    GCP_ISSUER = "https://accounts.google.com"
    AZURE_ISSUER = "https://login.microsoftonline.com/common/v2.0"
    GITHUB_ISSUER = "https://token.actions.githubusercontent.com"

    @classmethod
    def aws(
        cls,
        client_id: str | None = None,
        client_secret: str | None = None,
        issuer_url: str | None = None,
    ) -> OIDCConfig:
        """Create AWS EKS OIDC configuration."""
        return OIDCConfig(
            provider=OIDCProvider.AWS,
            client_id=client_id or os.getenv("AWS_OIDC_CLIENT_ID", "ci-engine"),
            client_secret=client_secret or os.getenv("AWS_OIDC_CLIENT_SECRET", ""),
            issuer_url=issuer_url or os.getenv("AWS_OIDC_ISSUER_URL", cls.AWS_ISSUER),
            audience=os.getenv("AWS_OIDC_AUDIENCE", "sts.amazonaws.com"),
        )

    @classmethod
    def gcp(
        cls,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> OIDCConfig:
        """Create GCP OIDC configuration."""
        return OIDCConfig(
            provider=OIDCProvider.GCP,
            client_id=client_id
            or os.getenv("GCP_OIDC_CLIENT_ID", "").removesuffix(".apps.googleusercontent.com")
            + ".apps.googleusercontent.com",
            client_secret=client_secret or os.getenv("GCP_OIDC_CLIENT_SECRET", ""),
            issuer_url=cls.GCP_ISSUER,
        )

    @classmethod
    def azure(
        cls,
        client_id: str | None = None,
        client_secret: str | None = None,
        tenant_id: str | None = None,
    ) -> OIDCConfig:
        """Create Azure AD OIDC configuration."""
        tenant = tenant_id or os.getenv("AZURE_TENANT_ID", "common")
        return OIDCConfig(
            provider=OIDCProvider.AZURE,
            client_id=client_id or os.getenv("AZURE_OIDC_CLIENT_ID", ""),
            client_secret=client_secret or os.getenv("AZURE_OIDC_CLIENT_SECRET", ""),
            issuer_url=f"https://login.microsoftonline.com/{tenant}/v2.0",
        )

    @classmethod
    def github(
        cls,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> OIDCConfig:
        """Create GitHub Actions OIDC configuration."""
        return OIDCConfig(
            provider=OIDCProvider.GITHUB,
            client_id=client_id or os.getenv("GITHUB_OIDC_CLIENT_ID", ""),
            client_secret=client_secret or os.getenv("GITHUB_OIDC_CLIENT_SECRET", ""),
            issuer_url=cls.GITHUB_ISSUER,
            scopes=["openid", "repo", "workflow"],
        )

    @classmethod
    def from_env(cls, provider: str) -> Optional[OIDCConfig]:
        """Load OIDC configuration from environment."""
        provider_lower = provider.lower()
        if provider_lower == "aws":
            return cls.aws()
        elif provider_lower == "gcp":
            return cls.gcp()
        elif provider_lower == "azure":
            return cls.azure()
        elif provider_lower == "github":
            return cls.github()
        return None

    @classmethod
    def get_all_providers(cls) -> list[OIDCConfig]:
        """Get all configured providers from environment."""
        providers = []
        for provider in OIDCProvider:
            config = cls.from_env(provider.value)
            if config and config.client_id:
                providers.append(config)
        return providers


class OIDCTokenVerifier:
    """Verify OIDC tokens from cloud providers."""

    @staticmethod
    def verify_github_token(token: str, audience: str) -> bool:
        """Verify GitHub Actions OIDC token."""
        try:
            import jwt

            # GitHub uses JWT tokens for OIDC
            unverified = jwt.decode(token, options={"verify_signature": False})
            iss = unverified.get("iss")
            aud = unverified.get("aud")
            sub = unverified.get("sub")
            # Verify issuer and audience
            if iss != OIDCProviderManager.GITHUB_ISSUER:
                return False
            if aud != audience:
                return False
            if not sub:
                return False
            return True
        except Exception:
            return False

    @staticmethod
    def verify_aws_token(token: str, audience: str) -> bool:
        """Verify AWS STS OIDC token."""
        try:
            import jwt

            unverified = jwt.decode(token, options={"verify_signature": False})
            iss = unverified.get("iss")
            aud = unverified.get("aud")
            sub = unverified.get("sub")
            if not iss or not iss.startswith("https://oidc.eks."):
                return False
            if aud != audience:
                return False
            if not sub:
                return False
            return True
        except Exception:
            return False
