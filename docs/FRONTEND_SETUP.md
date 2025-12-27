# Frontend Setup Guide

## Quick Start

The frontend is a React + Vite application that requires Node.js to run.

### Step 1: Install Node.js

**Easiest Method (Recommended):**
1. Visit https://nodejs.org/
2. Download the **LTS version** (Long Term Support)
3. Run the installer
4. Restart your terminal

**Alternative Methods:**
- **Homebrew**: `brew install node` (if you have Homebrew)
- **nvm**: `curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash` then `nvm install --lts`

### Step 2: Verify Installation

```bash
node --version  # Should show v18.x.x or higher
npm --version   # Should show 9.x.x or higher
```

### Step 3: Start the Application

**Option A: Start everything at once (Backend + Frontend)**
```bash
./start_app.sh
```

**Option B: Start separately**

Terminal 1 (Backend):
```bash
python3 main.py
```

Terminal 2 (Frontend):
```bash
./start_frontend.sh
```

### Step 4: Access the App

Once started, the app will be available at:
- **Frontend**: http://localhost:8080
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

The browser should open automatically. If not, manually navigate to http://localhost:8080

## Troubleshooting

### "Node.js not found"
- Make sure Node.js is installed (see Step 1)
- Restart your terminal after installation
- Verify with `node --version`

### "Port 8000 already in use"
- Backend is already running
- Just start the frontend: `./start_frontend.sh`

### "Port 8080 already in use"
- Another app is using port 8080
- Kill the process: `lsof -ti:8080 | xargs kill`
- Or change the port in `web/vuvuzela-vibes-predictor/vite.config.ts`

### Frontend can't connect to backend
- Make sure backend is running: `python3 main.py`
- Check backend health: `curl http://localhost:8000/health`
- Verify CORS is enabled (already configured in `app/api.py`)

## Development

The frontend uses:
- **Vite** for fast development server
- **React 18** with TypeScript
- **shadcn/ui** components
- **Tailwind CSS** for styling

Hot reloading is enabled - changes will automatically refresh in the browser.

