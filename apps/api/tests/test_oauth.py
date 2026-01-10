"""
Tests for OAuth 2.1 Authorization Code + PKCE flow.

Tests cover:
- Successful PKCE flow
- Invalid code_verifier
- Expired authorization code
- Code reuse prevention
- Refresh token rotation
- Token revocation
"""
import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from main import app
from models import (
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthRefreshToken,
    User,
    UserCredential,
)


# Test database setup
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_test_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Override the database dependency
from app.api.oauth import get_db as oauth_get_db
from app.api.v1.deps import get_db as deps_get_db


@pytest.fixture(scope="function")
def db():
    """Create fresh database for each test."""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    """Create test client with database override."""
    app.dependency_overrides[oauth_get_db] = lambda: db
    app.dependency_overrides[deps_get_db] = lambda: db
    
    with TestClient(app) as c:
        yield c
    
    app.dependency_overrides.clear()


@pytest.fixture
def test_user(db):
    """Create a test user."""
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    user = User(
        id=str(uuid.uuid4()),
        email="test@example.com",
        name="Test User",
        role="developer",
        created_at=datetime.now(timezone.utc),
    )
    cred = UserCredential(
        user_id=user.id,
        password_hash=pwd_context.hash("testpass123"),
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.add(cred)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def oauth_client(db):
    """Create a test OAuth client."""
    client = OAuthClient(
        id="test-vscode-extension",
        name="Test VS Code Extension",
        client_type="public",
        redirect_uris=[
            "vscode://test.extension/auth-callback",
            "http://localhost:54321/callback",
        ],
        allowed_scopes=["openid", "profile", "email", "tasks:read", "tasks:write"],
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def generate_pkce():
    """Generate PKCE code_verifier and code_challenge."""
    code_verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def create_session_cookie(client_http, user):
    """Create a session cookie for the test user."""
    from jose import jwt
    import os
    
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    token = jwt.encode(
        {"sub": user.id, "exp": datetime.now(timezone.utc) + timedelta(days=1)},
        SECRET_KEY,
        algorithm="HS256",
    )
    client_http.cookies.set("access_token", token)
    return token


# ==============================================================================
# Authorization Endpoint Tests
# ==============================================================================

class TestAuthorizeEndpoint:
    """Tests for GET /oauth/authorize"""
    
    def test_authorize_requires_login(self, client, oauth_client, monkeypatch):
        """Should redirect to login if not authenticated."""
        monkeypatch.setenv("FRONTEND_LOGIN_URL", "http://localhost:5174/login")
        code_verifier, code_challenge = generate_pkce()
        
        response = client.get(
            "/api/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": oauth_client.id,
                "redirect_uri": "http://localhost:54321/callback",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "scope": "openid profile",
                "state": "test-state",
            },
            follow_redirects=False,
        )
        
        assert response.status_code == 302
        location = response.headers["location"]
        assert location.startswith("http://localhost:5174/login")
        assert "return_to=" in location
    
    def test_authorize_invalid_client(self, client):
        """Should error for unknown client."""
        code_verifier, code_challenge = generate_pkce()
        
        response = client.get(
            "/api/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": "nonexistent-client",
                "redirect_uri": "http://localhost:54321/callback",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        
        # Should redirect with error for unknown client
        assert response.status_code == 302
        assert "error=invalid_client" in response.headers["location"]
    
    def test_authorize_invalid_redirect_uri(self, client, oauth_client):
        """Should reject unregistered redirect URIs."""
        code_verifier, code_challenge = generate_pkce()
        
        response = client.get(
            "/api/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": oauth_client.id,
                "redirect_uri": "https://evil.com/callback",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
        )
        
        # Should return 400 for invalid redirect_uri (not redirect to prevent open redirect)
        assert response.status_code == 400
    
    def test_authorize_shows_approval_page(self, client, db, oauth_client, test_user):
        """Should show approval page when authenticated."""
        code_verifier, code_challenge = generate_pkce()
        create_session_cookie(client, test_user)
        
        response = client.get(
            "/api/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": oauth_client.id,
                "redirect_uri": "http://localhost:54321/callback",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "scope": "openid profile",
                "state": "test-state",
            },
        )
        
        assert response.status_code == 200
        assert "Authorize" in response.text
        assert oauth_client.name in response.text
        assert test_user.email in response.text


# ==============================================================================
# Token Exchange Tests (PKCE)
# ==============================================================================

class TestTokenEndpoint:
    """Tests for POST /oauth/token"""
    
    def test_successful_pkce_flow(self, client, db, oauth_client, test_user):
        """Complete PKCE flow should return tokens."""
        code_verifier, code_challenge = generate_pkce()
        
        # Create authorization code directly (simulating approved flow)
        auth_code = OAuthAuthorizationCode(
            id=secrets.token_urlsafe(32),
            client_id=oauth_client.id,
            user_id=test_user.id,
            redirect_uri="http://localhost:54321/callback",
            scope="openid profile",
            code_challenge=code_challenge,
            code_challenge_method="S256",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        db.add(auth_code)
        db.commit()
        
        # Exchange code for tokens
        response = client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": auth_code.id,
                "redirect_uri": "http://localhost:54321/callback",
                "code_verifier": code_verifier,
                "client_id": oauth_client.id,
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "Bearer"
        assert "expires_in" in data
        assert "scope" in data
    
    def test_invalid_code_verifier(self, client, db, oauth_client, test_user):
        """Should reject invalid PKCE verifier."""
        code_verifier, code_challenge = generate_pkce()
        
        # Create authorization code
        auth_code = OAuthAuthorizationCode(
            id=secrets.token_urlsafe(32),
            client_id=oauth_client.id,
            user_id=test_user.id,
            redirect_uri="http://localhost:54321/callback",
            scope="openid profile",
            code_challenge=code_challenge,
            code_challenge_method="S256",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        db.add(auth_code)
        db.commit()
        
        # Try with wrong verifier
        response = client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": auth_code.id,
                "redirect_uri": "http://localhost:54321/callback",
                "code_verifier": "wrong-verifier",
                "client_id": oauth_client.id,
            },
        )
        
        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "invalid_grant"
        assert "code_verifier" in data["error_description"]
    
    def test_expired_authorization_code(self, client, db, oauth_client, test_user):
        """Should reject expired authorization codes."""
        code_verifier, code_challenge = generate_pkce()
        
        # Create expired authorization code
        auth_code = OAuthAuthorizationCode(
            id=secrets.token_urlsafe(32),
            client_id=oauth_client.id,
            user_id=test_user.id,
            redirect_uri="http://localhost:54321/callback",
            scope="openid profile",
            code_challenge=code_challenge,
            code_challenge_method="S256",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),  # Expired
        )
        db.add(auth_code)
        db.commit()
        
        response = client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": auth_code.id,
                "redirect_uri": "http://localhost:54321/callback",
                "code_verifier": code_verifier,
                "client_id": oauth_client.id,
            },
        )
        
        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "invalid_grant"
        assert "expired" in data["error_description"]
    
    def test_code_reuse_prevention(self, client, db, oauth_client, test_user):
        """Should reject already-used authorization codes."""
        code_verifier, code_challenge = generate_pkce()
        
        # Create authorization code
        auth_code = OAuthAuthorizationCode(
            id=secrets.token_urlsafe(32),
            client_id=oauth_client.id,
            user_id=test_user.id,
            redirect_uri="http://localhost:54321/callback",
            scope="openid profile",
            code_challenge=code_challenge,
            code_challenge_method="S256",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        db.add(auth_code)
        db.commit()
        
        # First exchange (should succeed)
        response1 = client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": auth_code.id,
                "redirect_uri": "http://localhost:54321/callback",
                "code_verifier": code_verifier,
                "client_id": oauth_client.id,
            },
        )
        assert response1.status_code == 200
        
        # Second exchange (should fail - code already used)
        response2 = client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": auth_code.id,
                "redirect_uri": "http://localhost:54321/callback",
                "code_verifier": code_verifier,
                "client_id": oauth_client.id,
            },
        )
        
        assert response2.status_code == 400
        data = response2.json()
        assert data["error"] == "invalid_grant"
        assert "already used" in data["error_description"]


# ==============================================================================
# Refresh Token Tests
# ==============================================================================

class TestRefreshToken:
    """Tests for refresh token functionality."""
    
    def test_refresh_token_rotation(self, client, db, oauth_client, test_user):
        """Refresh should return new tokens and rotate refresh token."""
        from app.api.oauth import _hash_token
        
        # Create initial refresh token
        refresh_value = secrets.token_urlsafe(32)
        refresh_token = OAuthRefreshToken(
            id=str(uuid.uuid4()),
            token_hash=_hash_token(refresh_value),
            client_id=oauth_client.id,
            user_id=test_user.id,
            scope="openid profile",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(refresh_token)
        db.commit()
        
        # Refresh tokens
        response = client.post(
            "/api/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_value,
                "client_id": oauth_client.id,
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        # New refresh token should be different
        assert data["refresh_token"] != refresh_value
        
        # Old refresh token should be marked as replaced
        db.refresh(refresh_token)
        assert refresh_token.replaced_by_id is not None
    
    def test_refresh_token_reuse_detection(self, client, db, oauth_client, test_user):
        """Reusing old refresh token should revoke entire chain."""
        from app.api.oauth import _hash_token
        
        # Create initial refresh token
        refresh_value = secrets.token_urlsafe(32)
        refresh_token = OAuthRefreshToken(
            id=str(uuid.uuid4()),
            token_hash=_hash_token(refresh_value),
            client_id=oauth_client.id,
            user_id=test_user.id,
            scope="openid profile",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(refresh_token)
        db.commit()
        old_token_id = refresh_token.id
        
        # First refresh (should succeed)
        response1 = client.post(
            "/api/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_value,
                "client_id": oauth_client.id,
            },
        )
        assert response1.status_code == 200
        new_refresh = response1.json()["refresh_token"]
        
        # Try to reuse old refresh token (should fail and revoke chain)
        response2 = client.post(
            "/api/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_value,
                "client_id": oauth_client.id,
            },
        )
        
        assert response2.status_code == 400
        data = response2.json()
        assert data["error"] == "invalid_grant"
    
    def test_scope_narrowing_on_refresh(self, client, db, oauth_client, test_user):
        """Should allow narrowing scope on refresh but not expanding."""
        from app.api.oauth import _hash_token
        
        # Create refresh token with multiple scopes
        refresh_value = secrets.token_urlsafe(32)
        refresh_token = OAuthRefreshToken(
            id=str(uuid.uuid4()),
            token_hash=_hash_token(refresh_value),
            client_id=oauth_client.id,
            user_id=test_user.id,
            scope="openid profile tasks:read tasks:write",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(refresh_token)
        db.commit()
        
        # Refresh with narrower scope (should succeed)
        response = client.post(
            "/api/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_value,
                "client_id": oauth_client.id,
                "scope": "openid tasks:read",
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "tasks:read" in data["scope"]
        assert "tasks:write" not in data["scope"]


# ==============================================================================
# Revocation Tests
# ==============================================================================

class TestRevocation:
    """Tests for token revocation."""
    
    def test_revoke_refresh_token(self, client, db, oauth_client, test_user):
        """Should revoke refresh token and associated chain."""
        from app.api.oauth import _hash_token
        
        # Create refresh token
        refresh_value = secrets.token_urlsafe(32)
        refresh_token = OAuthRefreshToken(
            id=str(uuid.uuid4()),
            token_hash=_hash_token(refresh_value),
            client_id=oauth_client.id,
            user_id=test_user.id,
            scope="openid profile",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(refresh_token)
        db.commit()
        
        # Revoke
        response = client.post(
            "/api/oauth/revoke",
            data={
                "token": refresh_value,
                "client_id": oauth_client.id,
            },
        )
        
        # RFC 7009: always return 200
        assert response.status_code == 200
        
        # Token should be revoked
        db.refresh(refresh_token)
        assert refresh_token.revoked_at is not None
        
        # Trying to use it should fail
        response2 = client.post(
            "/api/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_value,
                "client_id": oauth_client.id,
            },
        )
        assert response2.status_code == 400
    
    def test_revoke_unknown_token(self, client, oauth_client):
        """Revoking unknown token should still return 200 (RFC 7009)."""
        response = client.post(
            "/api/oauth/revoke",
            data={
                "token": "nonexistent-token",
                "client_id": oauth_client.id,
            },
        )
        
        # Per RFC 7009, should return 200 even for unknown tokens
        assert response.status_code == 200


# ==============================================================================
# Me Endpoint Tests
# ==============================================================================

class TestMeEndpoint:
    """Tests for GET /oauth/me"""
    
    def test_me_with_valid_token(self, client, db, oauth_client, test_user):
        """Should return user info with valid access token."""
        code_verifier, code_challenge = generate_pkce()
        
        # Create authorization code
        auth_code = OAuthAuthorizationCode(
            id=secrets.token_urlsafe(32),
            client_id=oauth_client.id,
            user_id=test_user.id,
            redirect_uri="http://localhost:54321/callback",
            scope="openid profile email",
            code_challenge=code_challenge,
            code_challenge_method="S256",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        db.add(auth_code)
        db.commit()
        
        # Get tokens
        token_response = client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": auth_code.id,
                "redirect_uri": "http://localhost:54321/callback",
                "code_verifier": code_verifier,
                "client_id": oauth_client.id,
            },
        )
        access_token = token_response.json()["access_token"]
        
        # Call /me
        response = client.get(
            "/api/oauth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_user.id
        assert data["email"] == test_user.email
        assert data["name"] == test_user.name
    
    def test_me_with_invalid_token(self, client):
        """Should return 401 with invalid token."""
        response = client.get(
            "/api/oauth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )
        
        assert response.status_code == 401


# ==============================================================================
# Integration with Existing API
# ==============================================================================

class TestAPIIntegration:
    """Test that OAuth tokens work with existing API endpoints."""
    
    def test_oauth_token_works_with_v1_me(self, client, db, oauth_client, test_user):
        """OAuth access token should work with /api/v1/me endpoint."""
        code_verifier, code_challenge = generate_pkce()
        
        # Create authorization code
        auth_code = OAuthAuthorizationCode(
            id=secrets.token_urlsafe(32),
            client_id=oauth_client.id,
            user_id=test_user.id,
            redirect_uri="http://localhost:54321/callback",
            scope="openid profile email tasks:read",
            code_challenge=code_challenge,
            code_challenge_method="S256",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        db.add(auth_code)
        db.commit()
        
        # Get tokens
        token_response = client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": auth_code.id,
                "redirect_uri": "http://localhost:54321/callback",
                "code_verifier": code_verifier,
                "client_id": oauth_client.id,
            },
        )
        access_token = token_response.json()["access_token"]
        
        # Use with /api/v1/me
        response = client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_user.id
        assert data["email"] == test_user.email


