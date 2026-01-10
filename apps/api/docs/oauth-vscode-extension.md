# OAuth 2.1 + PKCE for VS Code Extension

This document describes the OAuth 2.1 Authorization Code flow with PKCE (Proof Key for Code Exchange) implemented for the Parallel VS Code extension authentication.

## Overview

The authentication flow mirrors GitHub Copilot's approach:

1. User runs "Sign In" command in VS Code
2. Extension generates PKCE code_verifier and code_challenge
3. Extension opens browser to Parallel's `/oauth/authorize` endpoint
4. User approves (or logs in first if needed)
5. Browser redirects back to VS Code via deep link (`vscode://...`)
6. Extension exchanges authorization code for tokens using code_verifier
7. Extension stores tokens securely and uses access_token for API calls

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/oauth/authorize` | GET | Authorization endpoint (approval page) |
| `/api/oauth/authorize` | POST | Submit approval/denial |
| `/api/oauth/token` | POST | Exchange code for tokens / refresh |
| `/api/oauth/revoke` | POST | Revoke tokens |
| `/api/oauth/me` | GET | Get user info from access token |

## Environment Variables

```bash
# Required
SECRET_KEY=your-secret-key-here

# Optional (defaults shown)
# These are configured in the code, not env vars, but listed for reference
# ACCESS_TOKEN_EXPIRE_MINUTES=60
# REFRESH_TOKEN_EXPIRE_DAYS=30
# AUTH_CODE_EXPIRE_MINUTES=10
# OAUTH_REDIRECT_URI_ALLOWLIST=vscode://your.extension/auth-callback
# OAUTH_EXTRA_SCOPES=custom:scope
```

## Pre-registered OAuth Client

The VS Code extension client is automatically registered during migration:

| Property | Value |
|----------|-------|
| `client_id` | `vscode-extension` |
| `client_type` | `public` (PKCE required) |
| `redirect_uris` | `["vscode://parallel.parallel-vscode/auth-callback", "http://localhost:54321/callback"]` |
| `allowed_scopes` | `["openid", "profile", "email", "tasks:read", "tasks:write", "chats:read", "chats:write", "files:read", "files:search", "workspaces:read", "edits:propose", "edits:apply", "edits:undo", "commands:run", "terminal:write", "completions:read", "index:read", "index:write", "explain:read", "tests:write", "git:read"]` |

To register additional clients, insert directly into the `oauth_clients` table.

## PKCE Flow (Recommended for VS Code)

### 1. Generate PKCE Codes

The VS Code extension should generate:

```typescript
// TypeScript/JavaScript example
function generatePKCE() {
  // Generate random verifier (43-128 chars, base64url)
  const verifier = crypto.randomBytes(32).toString('base64url');
  
  // Generate S256 challenge
  const challenge = crypto
    .createHash('sha256')
    .update(verifier)
    .digest('base64url');
  
  return { verifier, challenge };
}
```

### 2. Open Authorization URL

```
GET /api/oauth/authorize?
  response_type=code&
  client_id=vscode-extension&
  redirect_uri=vscode://parallel.parallel-vscode/auth-callback&
  code_challenge=<S256_CHALLENGE>&
  code_challenge_method=S256&
  scope=openid%20profile%20tasks:read&
  state=<RANDOM_STATE>&
  workspace_id=<OPTIONAL_WORKSPACE_ID>
```

### 3. Handle Redirect

After user approves, browser redirects to:
```
vscode://parallel.parallel-vscode/auth-callback?code=<AUTH_CODE>&state=<STATE>
```

### 4. Exchange Code for Tokens

```bash
curl -X POST http://localhost:8000/api/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code" \
  -d "code=<AUTH_CODE>" \
  -d "redirect_uri=vscode://parallel.parallel-vscode/auth-callback" \
  -d "code_verifier=<ORIGINAL_VERIFIER>" \
  -d "client_id=vscode-extension"
```

Response:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4...",
  "scope": "openid profile tasks:read"
}
```

### 5. Refresh Tokens

```bash
curl -X POST http://localhost:8000/api/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=refresh_token" \
  -d "refresh_token=<REFRESH_TOKEN>" \
  -d "client_id=vscode-extension"
```

Note: Refresh tokens are rotated on each use. The old token becomes invalid.

### 6. Revoke Tokens

```bash
curl -X POST http://localhost:8000/api/oauth/revoke \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "token=<REFRESH_TOKEN>" \
  -d "client_id=vscode-extension"
```

### 7. Get User Info

```bash
curl http://localhost:8000/api/oauth/me \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

Response:
```json
{
  "id": "user-uuid",
  "email": "user@example.com",
  "name": "User Name",
  "scope": "openid profile tasks:read"
}
```

## Using Access Tokens with Existing APIs

OAuth access tokens work with all existing `/api/v1/*` endpoints:

```bash
# Example: Get workspaces
curl http://localhost:8000/api/v1/me \
  -H "Authorization: Bearer <ACCESS_TOKEN>"

# Example: List tasks
curl http://localhost:8000/api/v1/tasks \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

## Security Features

### PKCE (Required for Public Clients)
- `code_challenge_method`: Only `S256` is supported
- `code_verifier` must be 43-128 characters

### Token Security
- Access tokens: JWT with 1-hour expiry
- Refresh tokens: Opaque, 30-day expiry, hashed in database
- Refresh token rotation: Each refresh invalidates the old token
- Token reuse detection: Reusing old refresh tokens revokes entire chain

### Rate Limiting
- `/oauth/authorize`: 30 requests/minute per IP
- `/oauth/token`: 20 requests/minute per IP
- `/oauth/login`: 10 requests/minute per IP

### CSRF Protection
- Approval form includes CSRF token
- `state` parameter for redirect validation

### Open Redirect Prevention
- `redirect_uri` must exactly match registered URIs
- Invalid URIs return 400 (not redirect)

## Scopes

| Scope | Description |
|-------|-------------|
| `openid` | Required for OIDC compliance |
| `profile` | Access to user's name |
| `email` | Access to user's email |
| `tasks:read` | Read tasks |
| `tasks:write` | Create/update tasks |
| `chats:read` | Read chat messages |
| `chats:write` | Send chat messages |
| `messages:read` | Read chat message bodies |
| `files:read` | Read workspace files provided by the extension |
| `files:search` | Use workspace search results provided by the extension |
| `workspaces:read` | List workspaces |
| `edits:propose` | Submit edit proposals |
| `edits:apply` | Apply edits/diffs in the workspace |
| `edits:undo` | Undo previously applied agent edits |
| `commands:run` | Run developer commands in the workspace |
| `terminal:write` | Log terminal output for agent context |
| `completions:read` | Request inline completions (ghost text) |
| `index:read` | Query semantic code index |
| `index:write` | Update semantic code index |
| `explain:read` | Request code explanations |
| `tests:write` | Generate tests |
| `git:read` | Read git context metadata |

## Connected Apps

Users can manage connected VS Code sessions from the web app:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/oauth/apps` | GET | List active OAuth clients for the current user |
| `/api/oauth/apps/revoke` | POST | Revoke a specific OAuth client for the current user |

Example revoke:
```bash
curl -X POST http://localhost:8000/api/oauth/apps/revoke \
  -H "Content-Type: application/json" \
  -d '{"client_id":"vscode-extension"}'
```

## VS Code Chat Endpoint

The extension should call a single chat endpoint for AI responses:

`POST /api/v1/vscode/chat`

Request body:
```json
{
  "workspace_id": "workspace-uuid",
  "chat_id": "optional-chat-uuid",
  "message": "Summarize these changes for me."
}
```

Response body:
```json
{
  "request_id": "uuid",
  "workspace_id": "workspace-uuid",
  "chat_id": "chat-uuid",
  "user_message_id": "uuid",
  "assistant_message_id": "uuid",
  "reply": "Here is the summary...",
  "model": "gpt-4o-mini",
  "created_at": "2026-01-01T00:00:00Z",
  "duration_ms": 1234
}
```

## Manual Test Plan

### Test 1: Complete PKCE Flow

1. Generate PKCE codes:
```bash
# Using Python
python3 -c "
import secrets, hashlib, base64
verifier = secrets.token_urlsafe(32)
challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
print(f'verifier: {verifier}')
print(f'challenge: {challenge}')
"
```

2. Open in browser (logged in):
```
http://localhost:8000/api/oauth/authorize?response_type=code&client_id=vscode-extension&redirect_uri=http://localhost:54321/callback&code_challenge=<CHALLENGE>&code_challenge_method=S256&scope=openid%20profile&state=test123
```

3. Approve and copy the `code` from redirect URL

4. Exchange code:
```bash
curl -X POST http://localhost:8000/api/oauth/token \
  -d "grant_type=authorization_code" \
  -d "code=<CODE>" \
  -d "redirect_uri=http://localhost:54321/callback" \
  -d "code_verifier=<VERIFIER>" \
  -d "client_id=vscode-extension"
```

### Test 2: Invalid Verifier

Use a different verifier than the one used to generate the challenge:
```bash
curl -X POST http://localhost:8000/api/oauth/token \
  -d "grant_type=authorization_code" \
  -d "code=<CODE>" \
  -d "redirect_uri=http://localhost:54321/callback" \
  -d "code_verifier=wrong-verifier" \
  -d "client_id=vscode-extension"
```

Expected: `{"error": "invalid_grant", "error_description": "Invalid code_verifier"}`

### Test 3: Code Reuse

Try to use the same authorization code twice. Second attempt should fail.

### Test 4: Refresh Token Rotation

1. Get initial tokens
2. Refresh tokens
3. Try to use old refresh token again

Expected: Second refresh fails (token reuse detection)

### Test 5: Revoke and Verify

1. Get tokens
2. Revoke refresh token
3. Try to use revoked refresh token

Expected: Token refresh fails

## Backwards Compatibility

- **PAT (Personal Access Tokens)**: Still supported for developer/CLI use
- **Cookie auth**: Still works for web app
- **Existing `/api/v1/*` endpoints**: Accept both PAT and OAuth tokens

## VS Code Extension Integration

See the VS Code extension's `src/api/client.ts` for implementation details. The extension should:

1. Store tokens securely using VS Code's `SecretStorage`
2. Automatically refresh tokens before expiry
3. Handle token revocation gracefully (prompt re-auth)
4. Use the deep link URI scheme for callbacks

## Troubleshooting

### "Invalid redirect_uri"
- Ensure the exact URI is registered in `oauth_clients.redirect_uris`
- Check for trailing slashes, protocol, etc.

### "Invalid code_verifier"
- Ensure the verifier matches the one used to generate the challenge
- Verifier must be base64url encoded

### "Authorization code expired"
- Codes expire in 10 minutes
- Complete the exchange promptly

### "Refresh token already used"
- Token rotation means old tokens are invalidated
- Get new tokens via full auth flow
