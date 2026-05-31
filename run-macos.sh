#!/bin/bash
# Award Tracker - Run Script for macOS/Linux

# Colors for terminal
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}Starting Award Tracker...${NC}"

# Detect virtual environment
if [ -d "venv" ]; then
    echo -e "Activating virtual environment..."
    source venv/bin/activate
else
    echo -e "${YELLOW}Warning: 'venv' directory not found. Running with system python3...${NC}"
fi

# Run the app
python3 tray.py
