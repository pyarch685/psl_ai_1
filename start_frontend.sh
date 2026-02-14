#!/bin/bash

# Frontend Startup Script for PSL AI App
# This script checks for Node.js and starts the frontend dev server

set -e

FRONTEND_DIR="web/vuvuzela-vibes-predictor"
BACKEND_URL="http://localhost:8000"

echo "=========================================="
echo "PSL AI Frontend Startup Script"
echo "=========================================="
echo ""

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed."
    echo ""
    echo "Please install Node.js using one of these methods:"
    echo ""
    echo "OPTION 1: Install via official installer (Recommended)"
    echo "  1. Visit: https://nodejs.org/"
    echo "  2. Download the LTS version for macOS"
    echo "  3. Run the installer"
    echo "  4. Restart your terminal"
    echo ""
    echo "OPTION 2: Install via Homebrew (if you have it)"
    echo "  brew install node"
    echo ""
    echo "OPTION 3: Install via nvm (Node Version Manager)"
    echo "  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash"
    echo "  nvm install --lts"
    echo "  nvm use --lts"
    echo ""
    exit 1
fi

# Check Node.js version
NODE_VERSION=$(node --version | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "⚠️  Warning: Node.js version 18+ recommended. Current: $(node --version)"
    echo ""
fi

echo "✓ Node.js found: $(node --version)"
echo "✓ npm found: $(npm --version)"
echo ""

# Navigate to frontend directory
if [ ! -d "$FRONTEND_DIR" ]; then
    echo "❌ Frontend directory not found: $FRONTEND_DIR"
    exit 1
fi

cd "$FRONTEND_DIR"

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "📦 Installing dependencies (this may take a few minutes)..."
    echo ""
    npm install
    echo ""
fi

# Check if backend is running
echo "🔍 Checking if backend is running..."
if curl -s "$BACKEND_URL/health" > /dev/null 2>&1; then
    echo "✓ Backend is running on $BACKEND_URL"
else
    echo "⚠️  Backend is not running on $BACKEND_URL"
    echo "   Start it with: python3 main.py"
    echo ""
fi

echo ""
echo "=========================================="
echo "Starting Frontend Development Server"
echo "=========================================="
echo ""
echo "Frontend will be available at: http://localhost:8080"
echo "Backend API: $BACKEND_URL"
echo ""
echo "Opening browser in 3 seconds..."
echo "Press Ctrl+C to stop the server"
echo ""

# Wait a moment for server to start, then open browser
(sleep 3 && open http://localhost:8080 2>/dev/null || echo "Please open http://localhost:8080 in your browser") &

# Start the dev server
npm run dev

