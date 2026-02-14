#!/bin/bash

# Complete App Startup Script
# Starts both backend and frontend servers

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "PSL AI Application Startup"
echo "=========================================="
echo ""

# Function to check if a port is in use
check_port() {
    lsof -i :$1 > /dev/null 2>&1
}

# Check if backend port is available
if check_port 8000; then
    echo "⚠️  Port 8000 is already in use (backend may already be running)"
else
    echo "🚀 Starting backend server..."
    python3 main.py &
    BACKEND_PID=$!
    echo "✓ Backend started (PID: $BACKEND_PID)"
    echo "   Waiting for backend to be ready..."
    sleep 3
    
    # Wait for backend to be ready
    for i in {1..10}; do
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            echo "✓ Backend is ready!"
            break
        fi
        sleep 1
    done
fi

echo ""
echo "🚀 Starting frontend server..."
echo ""

# Start frontend
exec ./start_frontend.sh

