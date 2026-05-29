#!/bin/bash
# Award Tracker - executable builder for macOS/Linux

# Colors for terminal
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}==================================================${NC}"
echo -e "${CYAN}      Award Tracker Executable Builder            ${NC}"
echo -e "${CYAN}==================================================${NC}"

SPEC_FILE="awardtracker.spec"

# Detect virtual environment
if [ -d "venv" ]; then
    echo -e "${GREEN}Activating virtual environment...${NC}"
    source venv/bin/activate
else
    echo -e "${YELLOW}Warning: 'venv' directory not found. Trying global environment...${NC}"
fi

# Check for PyInstaller
if ! command -v pyinstaller &> /dev/null; then
    echo -e "${RED}Error: PyInstaller is not installed. Please run 'pip install pyinstaller' first.${NC}"
    exit 1
fi

# Clean previous build artifacts
echo -e "${YELLOW}Cleaning previous build directories...${NC}"
rm -rf build dist

# Build standalone executable / app bundle
echo -e "${YELLOW}Starting PyInstaller compilation (this may take a minute)...${NC}"
pyinstaller --clean -y "$SPEC_FILE"
RESULT=$?

if [ $RESULT -eq 0 ]; then
    echo -e "\n${GREEN}==================================================${NC}"
    echo -e "${GREEN}          BUILD COMPLETED SUCCESSFULLY!           ${NC}"
    echo -e "${GREEN}==================================================${NC}"
    if [ "$(uname)" == "Darwin" ]; then
        echo -e "Native macOS App Bundle: ${GREEN}dist/AwardTracker.app${NC}"
    fi
    echo -e "Standalone Binary: ${GREEN}dist/awardtracker${NC}"
else
    echo -e "\n${RED}Error: PyInstaller compilation failed.${NC}"
    exit $RESULT
fi
