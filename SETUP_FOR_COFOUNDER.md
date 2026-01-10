# Setup Guide for Cofounder

This guide will help you get the MongoDB hackathon project running on your machine.

## 🗂️ What's in This Repo

This is a monorepo with:
- **Backend:** FastAPI + MongoDB Atlas + Fireworks AI + Voyage embeddings ([apps/api](apps/api))
- **Frontend:** React/Vite web app ([apps/web](apps/web))
- **Extension:** VS Code extension in separate repo: https://github.com/Nayab-23/ParallelVScodeMongo

## 📋 Prerequisites

**Install these first:**
- Python 3.12+ ([Download](https://www.python.org/downloads/))
- Node.js 18+ ([Download](https://nodejs.org/))
- MongoDB Atlas account ([Sign up free](https://www.mongodb.com/cloud/atlas/register))

**Get API keys from:**
- Fireworks AI: https://fireworks.ai/ (for LLM)
- Voyage AI: https://www.voyageai.com/ (for embeddings)

---

## 🚀 Quick Start (5 minutes)

### 1. Clone the repo

```bash
git clone https://github.com/Nayab-23/ParallleMongoDB.git
cd ParallleMongoDB
```

### 2. Set up Backend

```bash
cd apps/api

# Create virtual environment
python -m venv venv

# Activate it
source venv/bin/activate  # Mac/Linux
# OR
venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env

# Edit .env with your API keys and MongoDB URI
nano .env  # or use any text editor
```

**Required .env variables:**
```env
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/database_name
FIREWORKS_API_KEY=your_fireworks_key_here
FIREWORKS_BASE_URL=https://api.fireworks.ai/inference/v1
FIREWORKS_MODEL=accounts/fireworks/models/llama-v3p1-70b-instruct
VOYAGE_API_KEY=your_voyage_key_here
VOYAGE_MODEL=voyage-3
MONGODB_VECTOR_INDEX=memory_docs_embedding
```

**Start the backend:**
```bash
python -m uvicorn hack_main:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
```

**Test it:**
```bash
curl http://localhost:8000/api/health
# Should return: {"ok": true}
```

---

### 3. Set up Frontend

Open a **new terminal:**

```bash
cd apps/web

# Install dependencies
npm install

# Start dev server
npm run dev
```

You should see:
```
VITE ready in 500 ms
➜  Local:   http://localhost:5173/
```

**Open browser:**
```
http://localhost:5173
```

You should see the landing page!

---

## 🧪 Test the Full Stack

### 1. Check backend health
```bash
curl http://localhost:8000/api/health
# → {"ok": true}

curl http://localhost:8000/api/demo/health
# → {"ok": true, "mongodb": "ok"}
```

### 2. Test in browser
Open http://localhost:5173 and check:
- Landing page loads
- No console errors (F12 → Console)
- Can navigate to other pages

### 3. Test API from browser console
```javascript
fetch('/api/health').then(r => r.json()).then(console.log)
// → {ok: true}
```

---

## 🔧 Troubleshooting

### Backend won't start

**Error: `ModuleNotFoundError`**
```bash
# Make sure you activated venv:
source venv/bin/activate  # Mac/Linux
# OR
venv\Scripts\activate  # Windows

# Reinstall:
pip install -r requirements.txt
```

**Error: `MongoDB unavailable`**
- Check `.env` has correct `MONGODB_URI`
- Verify MongoDB Atlas cluster is running
- Check IP whitelist in Atlas (Network Access)
- Try connecting with mongosh:
  ```bash
  mongosh "YOUR_MONGODB_URI"
  ```

**Error: `Missing required env vars`**
- Verify `.env` exists in `apps/api/`
- Check all required variables are set:
  ```bash
  grep -E "(MONGODB_URI|FIREWORKS_API_KEY|VOYAGE_API_KEY)" apps/api/.env
  ```

---

### Frontend won't start

**Error: `npm: command not found`**
- Install Node.js: https://nodejs.org/

**Error: `ENOENT` or `Cannot find module`**
```bash
# Delete and reinstall:
rm -rf node_modules package-lock.json
npm install
```

**CORS errors in browser**
- Make sure backend is running on port 8000
- Check Vite proxy config in `apps/web/vite.config.js`

---

### API calls fail (404)

**Check backend logs:**
```bash
# In backend terminal, you should see:
{"tag":"REQUEST_START","method":"GET","path":"/api/health",...}
{"tag":"REQUEST_END","method":"GET","path":"/api/health","status":200,...}
```

**If not:** Backend crashed or not running
- Restart: `python -m uvicorn hack_main:app --reload --port 8000`

---

## 📚 Key Documentation

Once you're running, check these guides:

- **[DEBUG.md](DEBUG.md)** - Where to view logs, common issues
- **[OBSERVABILITY_SUMMARY.md](OBSERVABILITY_SUMMARY.md)** - Logging implementation details
- **[DEMO_KILLER_CHECKS.md](DEMO_KILLER_CHECKS.md)** - Pre-demo verification tests
- **[INTEGRATION_SUMMARY.md](INTEGRATION_SUMMARY.md)** - Architecture overview

---

## 🔑 Getting API Keys

### MongoDB Atlas (Free tier)
1. Sign up: https://www.mongodb.com/cloud/atlas/register
2. Create cluster (free M0 tier)
3. Database Access → Add user (username + password)
4. Network Access → Add IP (or 0.0.0.0/0 for testing)
5. Clusters → Connect → Copy connection string
6. Paste in `.env` as `MONGODB_URI`

### Fireworks AI
1. Sign up: https://fireworks.ai/
2. Get API key from dashboard
3. Paste in `.env` as `FIREWORKS_API_KEY`

### Voyage AI
1. Sign up: https://www.voyageai.com/
2. Get API key from dashboard
3. Paste in `.env` as `VOYAGE_API_KEY`

---

## 🎯 What to Test

### Basic Flow
1. **Backend health:** `curl http://localhost:8000/api/health`
2. **Frontend loads:** Open http://localhost:5173
3. **API calls work:** Browser console → `fetch('/api/health')`
4. **Logs visible:** Check backend terminal for JSON logs

### Chat Flow (if MongoDB is set up)
1. Create chat: `POST /api/chats {name: "Test"}`
2. Dispatch task: `POST /api/chats/{id}/dispatch {content: "..."}`
3. Check SSE: `curl -N http://localhost:8000/api/v1/events?workspace_id=1`
4. See event delivered within 5 seconds

### Error Handling
1. Trigger error: `fetch('/api/invalid')`
2. Red banner appears in top-right
3. Check console for `[API]` logs
4. Check backend for error logs

---

## 🆘 Need Help?

**Logs to check:**
- **Backend:** Terminal running uvicorn (JSON logs)
- **Frontend:** Browser DevTools → Console (look for `[API]`)
- **Network:** Browser DevTools → Network tab

**Common issues:**
- Port 8000 already in use → Change port or kill process
- Port 5173 already in use → Change in vite.config.js
- MongoDB connection fails → Check Atlas IP whitelist
- Missing .env → Copy from .env.example

**Still stuck?**
Run the verification tests:
```bash
# Quick health check
curl http://localhost:8000/api/health
curl http://localhost:8000/api/demo/health

# Check logs are working
python -m uvicorn hack_main:app --reload 2>&1 | grep REQUEST
```

---

## 🎉 Success Criteria

You know it's working when:

✅ Backend starts without errors
✅ `curl http://localhost:8000/api/health` returns `{"ok": true}`
✅ Frontend loads at http://localhost:5173
✅ Browser console shows no errors
✅ `fetch('/api/health')` works in browser console
✅ Backend logs show structured JSON

**Then you're ready to develop!** 🚀

---

## 📦 What's Next?

**For demo prep:**
1. Run verification tests in [VERIFY_OBSERVABILITY.md](VERIFY_OBSERVABILITY.md)
2. Test failure scenarios in [DEBUG.md](DEBUG.md)
3. Set up VS Code extension from: https://github.com/Nayab-23/ParallelVScodeMongo

**For development:**
- Backend code: `apps/api/hack_main.py` + `apps/api/hack_api.py`
- Frontend code: `apps/web/src/`
- Logs: See [DEBUG.md](DEBUG.md) for log locations

---

**Last updated:** 2026-01-10
