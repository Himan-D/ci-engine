#!/bin/bash
# CI Engine - Quick Start Demo Script
# This script starts all components for a quick demo

set -e

echo "=========================================="
echo "  CI Engine - Quick Start Demo"
echo "=========================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is required${NC}"
    exit 1
fi

# Check for venv
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]" > /dev/null 2>&1
fi

source .venv/bin/activate

# Stop existing processes
echo "Stopping existing processes..."
pkill -f "uvicorn ci_engine" 2>/dev/null || true
sleep 1

# Start server
echo "Starting API server..."
export DATABASE_URL=sqlite:///ci-engine.db
uvicorn ci_engine.server.main:app --host 127.0.0.1 --port 8000 &
SERVER_PID=$!

# Wait for server
echo "Waiting for server..."
for i in {1..30}; do
    if curl -s -f http://127.0.0.1:8000/health > /dev/null 2>&1; then
        echo -e "${GREEN}Server ready!${NC}"
        break
    fi
    sleep 0.5
done

# Create demo builds
echo "Creating demo builds..."

# Demo build 1: Successful
curl -s -X POST http://127.0.0.1:8000/api/builds \
    -H "Content-Type: application/json" \
    -d '{
        "pipeline": "steps:\n  - label: Build\n    command: npm run build\n  - label: Test\n    command: npm test\n  - label: Deploy\n    command: npm run deploy",
        "branch": "main",
        "repository": "https://github.com/acme/myapp"
    }' > /dev/null

# Demo build 2: Running
curl -s -X POST http://127.0.0.1:8000/api/builds \
    -H "Content-Type: application/json" \
    -d '{
        "pipeline": "steps:\n  - label: Lint\n    command: npm run lint\n  - label: Type Check\n    command: npm run typecheck",
        "branch": "feature/new-ui",
        "repository": "https://github.com/acme/myapp"
    }' > /dev/null

# Start frontend dev server (in background)
echo "Starting frontend..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo -e "${GREEN}=========================================="
echo "  CI Engine is running!"
echo "==========================================${NC}"
echo ""
echo "  API Server:    http://localhost:8000"
echo "  Dashboard:    http://localhost:3000"
echo "  Health:      http://localhost:8000/health"
echo "  API Docs:    http://localhost:8000/docs"
echo ""
echo "Demo Builds:"
echo "  - Build #1: main branch (pending)"
echo "  - Build #2: feature/new-ui (pending)"
echo ""
echo "To start an agent:"
echo "  python -m ci_engine.agent.agent --name my-agent --server http://localhost:8000"
echo ""
echo "Press Ctrl+C to stop all services"

# Wait for Ctrl+C
trap "echo 'Stopping...'; kill \$SERVER_PID \$FRONTEND_PID 2>/dev/null; exit 0" SIGINT SIGTERM
wait