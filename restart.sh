#!/usr/bin/env bash

# Simple restart script for your DnD server backend

echo "Stopping any existing server processes on port 5000..."
# Kill any process listening on port 5000
lsof -ti:5000 | xargs kill -9 2>/dev/null

# Also fallback to kill by python module name just in case
pkill -f "python -m app.main" 2>/dev/null

# Give it a second to free up the socket
sleep 1

echo "Starting server..."
python -m app.main --debug