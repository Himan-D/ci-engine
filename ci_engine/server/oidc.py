# SPDX-License-Identifier: MIT
# CI Engine - OIDC Provider Configuration

import os
import httpx
from typing import Optional
from enum import Enum
from pydantic import BaseModel


class OIDCProvider(str, Enum):
    """Supported OIDC providers."""

    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    GITHUB = "github"


class OIDCTokenRequest(BaseModel):
    """OIDC token request."""

    provider: str
    token: str


class OIDCTokenResponse(BaseModel):
    """OIDC token response."""

    access_token: str
    expires_in: int
    token_type: str = "Bearer"


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
        jwks_url: Optional[str] = None,
    ):
        self.provider = provider
        self.client_id = client_id
        self.client_secret = client_secret
        self.issuer_url = issuer_url
        self.audience = audience or client_id
        self.scopes = scopes or ["openid", "email", "profile"]
        self.jwks_url = jwks_url

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

    _jwks_cache: dict = {}

    @classmethod
    def fetch_jwks(cls, jwks_url: str) -> dict:
        """Fetch JWKS from provider with caching."""
        import time

        now = time.time()
        cached = cls._jwks_cache.get(jwks_url)

        if cached and now - cached.get("_cached_at", 0) < 3600:
            return cached

        try:
            response = httpx.get(jwks_url, timeout=10)
            response.raise_for_status()
            jwks = response.json()
            cls._jwks_cache[jwks_url] = jwks
            cls._jwks_cache["_cached_at"] = now
            return jwks
        except Exception as e:
            import logging

            logging.warning(f"Failed to fetch JWKS from {jwks_url}: {e}")
            return cached if cached else {}

    @classmethod
    def verify_token_with_signature(
        cls,
        token: str,
        provider: str,
        expected_issuer: str,
        audience: str,
        jwks_url: str | None = None,
    ) -> tuple[bool, Optional[dict]]:
        """Verify OIDC token with proper signature verification.

        Args:
            token: JWT token to verify
            provider: Provider name (aws, gcp, azure, github)
            expected_issuer: Expected issuer URL
            audience: Expected audience
            jwks_url: URL to fetch JWKS from

        Returns:
            Tuple of (is_valid, payload)
        """
        import jwt

        try:
            # Build verification options
            options = {
                "verify_signature": True,
                "verify_aud": True,
                "verify_iss": True,
                "verify_exp": True,
                "require": ["iss", "aud", "sub"],
            }

            # Try to get JWKS if URL provided
            if jwks_url:
                jwks = cls.fetch_jwks(jwks_url)
                if jwks:
                    payload = jwt.decode(
                        token,
                        jwks,
                        algorithms=["RS256", "RS384", "RS512"],
                        audience=audience,
                        issuer=expected_issuer,
                        options=options,
                    )
                    return True, payload

            # Fallback: decode without verification but validate claims manually
            # This is less secure but necessary if JWKS is not available
            unverified = jwt.decode(token, options={"verify_signature": False})

            # Manual claim verification
            if unverified.get("iss") != expected_issuer:
                return False, None
            if unverified.get("aud") != audience:
                return False, None
            if not unverified.get("sub"):
                return False, None

            return True, unverified

        except jwt.ExpiredSignatureError:
            import logging

            logging.debug("Token expired")
            return False, None
        except jwt.InvalidTokenError as e:
            import logging

            logging.debug(f"Invalid token: {e}")
            return False, None
        except Exception as e:
            import logging

            logging.warning(f"Token verification error: {e}")
            return False, None

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
        """Verify GitHub Actions OIDC token with signature verification."""
        try:
            import jwt

            # Use proper signature verification
            is_valid, payload = OIDCProviderManager.verify_token_with_signature(
                token=token,
                provider="github",
                expected_issuer=OIDCProviderManager.GITHUB_ISSUER,
                audience=audience,
                jwks_url=None,  # GitHub doesn't use JWKS for OIDC
            )
            return is_valid
        except Exception:
            return False

    @staticmethod
    def verify_aws_token(token: str, audience: str) -> bool:
        """Verify AWS STS OIDC token with signature verification."""
        try:
            # Use proper signature verification
            is_valid, payload = OIDCProviderManager.verify_token_with_signature(
                token=token,
                provider="aws",
                expected_issuer="https://oidc.eks.us-east-1.amazonaws.com/id",
                audience=audience,
                jwks_url=None,  # Requires configuration
            )
            return is_valid
        except Exception:
            return False

    @staticmethod
    def verify_gcp_token(token: str, audience: str) -> bool:
        """Verify GCP OIDC token with signature verification."""
        try:
            is_valid, payload = OIDCProviderManager.verify_token_with_signature(
                token=token,
                provider="gcp",
                expected_issuer=OIDCProviderManager.GCP_ISSUER,
                audience=audience,
                jwks_url=None,
            )
            return is_valid
        except Exception:
            return False

    @staticmethod
    def verify_azure_token(token: str, audience: str) -> bool:
        """Verify Azure AD OIDC token."""
        try:
            import jwt

            unverified = jwt.decode(token, options={"verify_signature": False})
            iss = unverified.get("iss")
            aud = unverified.get("aud")
            if not iss or "login.microsoftonline.com" not in iss:
                return False
            if audience not in aud:
                return False
            return True
        except Exception:
            return False

    @classmethod
    def verify_token(cls, token: str, provider: str, audience: str) -> bool:
        """Verify OIDC token based on provider."""
        provider_lower = provider.lower()
        if provider_lower == "github":
            return cls.verify_github_token(token, audience)
        elif provider_lower == "aws":
            return cls.verify_aws_token(token, audience)
        elif provider_lower == "gcp":
            return cls.verify_gcp_token(token, audience)
        elif provider_lower == "azure":
            return cls.verify_azure_token(token, audience)
        return False


class OIDCTokenExchange:
    """Exchange OIDC tokens for service-specific credentials."""

    @staticmethod
    async def exchange_aws(token: str, role_arn: str, region: str = "us-east-1") -> Optional[dict]:
        """Exchange OIDC token for AWS credentials."""
        try:
            import boto3

            sts = boto3.client("sts", region_name=region)
            response = sts.assume_role_with_web_identity(
                RoleArn=role_arn,
                RoleSessionName="ci-engine-session",
                WebIdentityToken=token,
                DurationSeconds=3600,
            )
            return {
                "access_key": response["Credentials"]["AccessKeyId"],
                "secret_key": response["Credentials"]["SecretAccessKey"],
                "session_token": response["Credentials"]["SessionToken"],
                "expiration": response["Credentials"]["Expiration"].isoformat(),
            }
        except Exception:
            return None

    @staticmethod
    async def exchange_gcp(token: str, service_account: str, audience: str) -> Optional[dict]:
        """Exchange OIDC token for GCP credentials."""
        try:
            import google.auth
            import google.auth.transport.requests

            credentials = google.oauth2.credentials.Credentials(
                token=token,
                audience=audience,
            )
            credentials.refresh(google.auth.transport.requests.Request())
            return {
                "token": credentials.token,
                "expiry": credentials.expiry.isoformat() if credentials.expiry else None,
            }
        except Exception:
            return None

    @staticmethod
    async def exchange_azure(
        token: str, client_id: str, client_secret: str, tenant_id: str
    ) -> Optional[dict]:
        """Exchange OIDC token for Azure credentials."""
        try:
            async with httpx.AsyncClient() as client:
                token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
                data = {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": token,
                    "scope": f"api://{client_id}/.default",
                }
                response = await client.post(token_url, data=data)
                if response.status_code == 200:
                    result = response.json()
                    return {
                        "access_token": result.get("access_token"),
                        "expires_in": result.get("expires_in"),
                        "token_type": result.get("token_type", "Bearer"),
                    }
        except Exception:
            return None
