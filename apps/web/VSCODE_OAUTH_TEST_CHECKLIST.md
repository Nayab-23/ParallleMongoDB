# VS Code OAuth Integration - Test Checklist

## Environment Setup

Before testing, ensure:
- [ ] Backend is running on `http://localhost:8000`
- [ ] Frontend is running on `http://localhost:5174` (or configured port)
- [ ] VS Code extension is installed (if testing full flow)

### Environment Variables

```bash
# Frontend (.env or inline)
VITE_API_BASE_URL=http://localhost:8000
VITE_ENABLE_DEV_PAT=true  # Only set for testing PAT feature

# Backend
ALLOW_SQLITE_FALLBACK=true
SECRET_KEY=local-dev-secret
DATABASE_URL=sqlite:///./parallel.db
DEPLOYMENT_MODE=development
```

---

## Test Cases

### 1. OAuth Approval Page - Logged In User

**Steps:**
1. Log in to the web app at `/app`
2. Navigate to `/oauth/authorize?client_id=parallel-vscode&scope=read:tasks%20read:chat&state=test123`
3. Verify approval page shows:
   - [ ] "Parallel VS Code wants to access your account" header
   - [ ] Signed in as user's email
   - [ ] Permission list (tasks, chat, workspace, offline access)
   - [ ] Security note about code changes
   - [ ] "Authorize VS Code" button
   - [ ] "Cancel" button

**Expected:** Page renders without errors, buttons are clickable.

---

### 2. OAuth Approval Page - Not Logged In

**Steps:**
1. Clear cookies / log out
2. Navigate directly to `/oauth/authorize?client_id=parallel-vscode`
3. Verify redirect to login

**Expected:** 
- [ ] User is redirected to `/app` with `return_to` parameter
- [ ] After logging in, user should be returned to OAuth page

---

### 3. OAuth Approval - Click Approve

**Steps:**
1. While logged in, go to OAuth page
2. Click "Authorize VS Code"
3. Observe behavior

**Expected:**
- [ ] Button shows "Authorizing..." state
- [ ] Success screen appears: "Authorization Complete"
- [ ] Countdown shows "Returning to VS Code in 3..."
- [ ] (DEV MODE) Console shows successful mock approval

---

### 4. OAuth Approval - Click Cancel

**Steps:**
1. While logged in, go to OAuth page
2. Click "Cancel"

**Expected:**
- [ ] "Authorization Cancelled" message appears
- [ ] Redirects back to VS Code settings or redirect_uri with error

---

### 5. VS Code Settings Page - Not Connected

**Steps:**
1. Log in to web app
2. Navigate to `/app/vscode`
3. Verify UI shows:
   - [ ] "Not connected" pill/badge
   - [ ] "Get started" card with 3 steps
   - [ ] Step 1: Install extension (links to marketplace)
   - [ ] Step 2: Connect (OAuth flow instructions)
   - [ ] Step 3: Default workspace picker (if multiple workspaces)
   - [ ] Permissions card explaining access
   - [ ] "How it works" OAuth flow diagram

**In DEV mode:**
- [ ] PAT generator section is visible
- [ ] "Dev Only" label on PAT section

**In PRODUCTION mode (VITE_ENABLE_DEV_PAT not set):**
- [ ] PAT generator section is NOT visible

---

### 6. VS Code Settings Page - Connected

**Steps:**
1. Simulate connected state (via backend or mock)
2. Navigate to `/app/vscode`

**Expected:**
- [ ] "Connected" pill/badge (green)
- [ ] Sessions table visible
- [ ] "Disconnect all" button available
- [ ] "Revoke" button per session

---

### 7. Error States

**Test error boundary:**
1. Force a JavaScript error in OAuthAuthorize component
2. Verify error boundary catches it
3. Check that:
   - [ ] Friendly error message appears
   - [ ] "Try Again" button works
   - [ ] "Go to Dashboard" button works

**Test API errors:**
1. Simulate 401/403 from backend
2. Verify:
   - [ ] DEV MODE: Page continues with mock data
   - [ ] PROD MODE: Redirect to login or show error

---

### 8. Responsive Design

**Test on:**
- [ ] Desktop (>1100px)
- [ ] Tablet (768px - 1100px)
- [ ] Mobile (<768px)

**Verify:**
- [ ] Grid layouts adjust properly
- [ ] OAuth approval page is centered and readable
- [ ] Buttons are full-width on mobile

---

### 9. VS Code Extension Integration (Full Flow)

**Prerequisites:** VS Code with Parallel extension installed

**Steps:**
1. Open VS Code
2. Run Command Palette → "Parallel: Sign In"
3. Browser opens to OAuth approval page
4. Click "Authorize VS Code"
5. Return to VS Code

**Expected:**
- [ ] VS Code receives authorization
- [ ] Extension shows "Connected" status
- [ ] Web app shows session in sessions table

---

## Known Dev Mode Behaviors

When `import.meta.env.DEV` is true:
- PAT generator is always visible
- Auth errors return mock data instead of blocking
- OAuth approval simulates success without backend call
- Console logs show "[DEV MODE]" prefixes

---

## API Endpoints Used

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/me` | GET | Verify current user session |
| `/api/oauth/authorize` | POST | Submit OAuth approval |
| `/api/v1/integrations/vscode/status` | GET | Get VS Code connection status |
| `/api/v1/integrations/vscode/sessions` | GET | List active sessions |
| `/api/v1/integrations/vscode/sessions/:id/revoke` | POST | Revoke a session |
| `/api/v1/integrations/vscode/disconnect` | POST | Disconnect all sessions |

---

## Troubleshooting

**OAuth page shows "Verifying your identity..." forever:**
- Check browser console for network errors
- Verify `/api/me` endpoint is reachable
- Check CORS configuration on backend

**PAT generator not visible:**
- Ensure `VITE_ENABLE_DEV_PAT=true` in environment
- Or run in development mode (`npm run dev`)

**"Authorization Failed" error:**
- Check backend logs for OAuth endpoint errors
- Verify user has valid session cookie
- Check CORS allows credentials

**VS Code not receiving authorization:**
- Verify redirect_uri matches VS Code's expected callback
- Check state parameter is preserved
- Verify code exchange endpoint is working









