#!/usr/bin/env bash

# Simple restart script for your DnD server backend

echo "Stopping any existing uvicorn processes..."
pkill -f "uvicorn" 2>/dev/null

echo "Starting server..."
python -m app.main --debug
