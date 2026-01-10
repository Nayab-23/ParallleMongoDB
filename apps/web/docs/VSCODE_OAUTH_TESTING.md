# VS Code OAuth Integration - Manual Test Checklist

This document provides a checklist for testing the VS Code extension OAuth flow.

## Environment Setup

### Required Environment Variables
```bash
# Backend (.env)
WEB_BASE_URL=http://localhost:5173
API_BASE_URL=http://localhost:8000

# Frontend (.env.local)
VITE_API_BASE_URL=http://localhost:8000
```

### Endpoint Roles
- Frontend entry: `/vscode/connect` (renders consent UI)
- Backend authorize: `/oauth/authorize` or `/api/oauth/authorize` (issues code + redirects to VS Code)

## Test Scenarios

### 1. OAuth Authorization - Logged In User

**Steps:**
1. Sign in to Parallel at `/app`
2. Open VS Code and run "Parallel: Sign In" from Command Palette
3. Browser opens to `/vscode/connect?client_id=...&redirect_uri=...&response_type=code&scope=...&state=...&code_challenge=...&code_challenge_method=S256`
4. Verify approval screen shows:
   - [ ] App name "Parallel VS Code"
   - [ ] Your logged-in user badge (name + email)
   - [ ] Requested scopes/permissions list
   - [ ] "Authorize" and "Cancel" buttons
   - [ ] Terms/Privacy links in footer

**Expected:**
- [ ] Clean, professional OAuth consent UI
- [ ] User can review permissions before approving

### 2. OAuth Authorization - Click Approve

**Steps:**
1. From the approval screen, click "Authorize"
2. Observe the loading state

**Expected:**
- [ ] Browser redirects to backend `/oauth/authorize` (or `/api/oauth/authorize`) with PKCE params
- [ ] Backend redirects to `vscode://parallel.parallel-vscode/...`
- [ ] VS Code completes the token exchange

### 3. OAuth Authorization - Not Logged In

**Steps:**
1. Sign out of Parallel (or use incognito)
2. Navigate directly to `/vscode/connect?client_id=...&redirect_uri=...`

**Expected:**
- [ ] Browser redirects to the login screen
- [ ] After login, you are returned to the same `/vscode/connect` URL

### 4. OAuth Authorization - After Login Redirect

**Steps:**
1. Start from not-logged-in `/vscode/connect` flow
2. Complete login
3. Should return to the same `/vscode/connect` URL

**Expected:**
- [ ] After login, user is returned to approval screen
- [ ] User info is correctly populated

### 5. OAuth Authorization - Cancel Flow

**Steps:**
1. From approval screen, click "Cancel"

**Expected:**
- [ ] If redirect_uri exists: redirect with `error=access_denied`
- [ ] If no redirect_uri: navigate to `/app/vscode`

### 6. OAuth Error Handling

**Steps:**
1. Simulate backend errors (e.g., stop backend)
2. Try to approve authorization or simulate backend redirecting back with `error` params

**Expected:**
- [ ] Error message appears with a "Try again" button
- [ ] Retry returns to `/vscode/connect` with params preserved
- [ ] App doesn't "soft-brick"

### 7. VS Code Settings Page - Not Connected

**Steps:**
1. Navigate to `/app/vscode` when not connected

**Expected:**
- [ ] Status pill shows "Not connected"
- [ ] "Get started" card with install/connect instructions
- [ ] "Connect from VS Code" is the recommended option
- [ ] Permissions card visible

### 8. VS Code Settings Page - Connected

**Steps:**
1. Complete OAuth flow successfully
2. Navigate to `/app/vscode`

**Expected:**
- [ ] Status pill shows "Connected" (green)
- [ ] Sessions table lists active connections
- [ ] "Disconnect all" button works
- [ ] Individual "Revoke" buttons work
- [ ] After revoke, status updates

### 9. Error Boundary - Render Crash

**Steps:**
1. (Dev) Intentionally break OAuthAuthorize component
2. Navigate to `/vscode/connect`

**Expected:**
- [ ] Error boundary shows friendly error
- [ ] "Try Again" and "Go to Dashboard" buttons work
- [ ] App doesn't white-screen

### 10. Logout/Login Cycle

**Steps:**
1. Be logged in at `/app`
2. Log out
3. Log back in
4. Navigate around the app

**Expected:**
- [ ] No "soft-brick" (app doesn't get stuck)
- [ ] All pages load correctly after re-login

## API Endpoints Required

The following backend endpoints should exist:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/me` | GET | Get current user |
| `/oauth/authorize` or `/api/oauth/authorize` | GET | Process OAuth approval (browser redirect) |
| `/api/oauth/apps` | GET | List connected OAuth apps |
| `/api/oauth/apps/revoke` | POST | Revoke OAuth app access |
| `/api/v1/oauth/sessions` | GET | Legacy list OAuth sessions (fallback) |
| `/api/v1/oauth/revoke` | POST | Legacy revoke OAuth token (fallback) |
| `/api/v1/integrations/vscode/status` | GET | Get VS Code status |
| `/api/v1/integrations/vscode/sessions` | GET | List sessions |
| `/api/v1/integrations/vscode/sessions/:id/revoke` | POST | Revoke session |
| `/api/v1/integrations/vscode/disconnect` | POST | Disconnect all |

## Browser Compatibility

Test on:
- [ ] Chrome (latest)
- [ ] Firefox (latest)
- [ ] Safari (latest)
- [ ] Edge (latest)

## Accessibility

- [ ] Keyboard navigation works
- [ ] Focus states are visible
- [ ] Screen reader announces content correctly
- [ ] Color contrast is sufficient

## Notes

- The OAuth flow is initiated from VS Code and opens `/vscode/connect` in the browser
- The frontend forwards to the backend authorize endpoint and does not mint tokens
- Connected Apps uses `/api/oauth/apps` (or legacy `/api/v1/oauth/*`) for revoke/list




