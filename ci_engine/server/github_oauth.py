# SPDX-License-Identifier: MIT
# CI Engine - GitHub OAuth Authentication

import os
from typing import Optional

import requests
from fastapi import HTTPException, status
from pydantic import BaseModel

from ci_engine.server.auth import User


class GitHubOAuthConfig:
    """GitHub OAuth configuration."""

    CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
    CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
    CALLBACK_URL = os.environ.get(
        "GITHUB_CALLBACK_URL", "http://localhost:8000/api/auth/github/callback"
    )

    SCOPE = "read:user user:email"

    AUTHORIZATION_URL = "https://github.com/login/oauth/authorize"
    TOKEN_URL = "https://github.com/login/oauth/access_token"
    API_URL = "https://api.github.com"


class GitHubUser(BaseModel):
    """GitHub user information."""

    id: int
    login: str
    name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None


class GitHubOAuthService:
    """GitHub OAuth authentication service."""

    def __init__(self):
        self.config = GitHubOAuthConfig()
        self.enabled = bool(self.config.CLIENT_ID and self.config.CLIENT_SECRET)

    def get_authorization_url(self, state: str) -> str:
        """Get GitHub OAuth authorization URL."""
        if not self.enabled:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="GitHub OAuth not configured",
            )

        params = {
            "client_id": self.config.CLIENT_ID,
            "redirect_uri": self.config.CALLBACK_URL,
            "scope": self.config.SCOPE,
            "state": state,
        }

        import urllib.parse

        query = urllib.parse.urlencode(params)
        return f"{self.config.AUTHORIZATION_URL}?{query}"

    def exchange_code_for_token(self, code: str) -> str:
        """Exchange OAuth code for access token."""
        if not self.enabled:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="GitHub OAuth not configured",
            )

        response = requests.post(
            self.config.TOKEN_URL,
            data={
                "client_id": self.config.CLIENT_ID,
                "client_secret": self.config.CLIENT_SECRET,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange code for token",
            )

        data = response.json()
        return data.get("access_token")

    def get_user_info(self, access_token: str) -> GitHubUser:
        """Get user information from GitHub API."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        user_response = requests.get(f"{self.config.API_URL}/user", headers=headers)
        if user_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to get user information",
            )

        user_data = user_response.json()

        email = user_data.get("email")
        if not email:
            emails_response = requests.get(f"{self.config.API_URL}/user/emails", headers=headers)
            if emails_response.status_code == 200:
                emails = emails_response.json()
                primary = next((e["email"] for e in emails if e.get("primary")), None)
                email = primary or (emails[0]["email"] if emails else None)

        return GitHubUser(
            id=user_data["id"],
            login=user_data["login"],
            name=user_data.get("name"),
            email=email,
            avatar_url=user_data.get("avatar_url"),
        )

    def find_or_create_user(self, github_user: GitHubUser) -> User:
        """Find or create user based on GitHub information."""
        from ci_engine.server.db import SessionLocal

        db = SessionLocal()
        try:
            from ci_engine.server.auth import User as AuthUser

            user = db.query(AuthUser).filter(AuthUser.email == github_user.email).first()

            if not user:
                username = github_user.login
                existing = db.query(AuthUser).filter(AuthUser.username == username).first()
                if existing:
                    username = f"{github_user.login}_{github_user.id}"

                user = AuthUser(
                    username=username,
                    password_hash=f"github_{github_user.id}",
                    role="developer",
                    is_active=True,
                )
                db.add(user)
                db.commit()
                db.refresh(user)

            return user
        finally:
            db.close()


github_oauth = GitHubOAuthService()


def get_github_oauth_url(state: str) -> str:
    """Get GitHub OAuth URL for login."""
    return github_oauth.get_authorization_url(state)


def handle_github_callback(code: str, state: str) -> dict:
    """Handle GitHub OAuth callback."""
    token = github_oauth.exchange_code_for_token(code)
    github_user = github_oauth.get_user_info(token)
    user = github_oauth.find_or_create_user(github_user)

    from ci_engine.server.middleware import create_access_token, create_refresh_token

    access_token = create_access_token(user.id, user.username)
    refresh_token = create_refresh_token(user.id)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
        },
    }
