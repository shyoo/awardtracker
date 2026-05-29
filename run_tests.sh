#!/bin/bash
# Award Tracker - Test Runner for macOS/Linux

# Colors for terminal
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}==================================================${NC}"
echo -e "${CYAN}      Award Tracker Unit Test Runner              ${NC}"
echo -e "${CYAN}==================================================${NC}"

# Detect virtual environment
if [ -d "venv" ]; then
    echo -e "${GREEN}Activating virtual environment...${NC}"
    source venv/bin/activate
    PYTHON_CMD="python"
else
    echo -e "${YELLOW}Warning: 'venv' directory not found. Running with global system python3...${NC}"
    PYTHON_CMD="python3"
fi

echo -e "${YELLOW}Starting unit tests discovery and execution...\n${NC}"

# Run tests
$PYTHON_CMD -m unittest discover -s tests -p "test_*.py"
RESULT=$?

if [ $RESULT -eq 0 ]; then
    echo -e "\n${GREEN}==================================================${NC}"
    echo -e "${GREEN}          ALL TESTS PASSED SUCCESSFULLY!           ${NC}"
    echo -e "${GREEN}==================================================${NC}"
else
    echo -e "\n${RED}==================================================${NC}"
    echo -e "${RED}               SOME TESTS FAILED!                  ${NC}"
    echo -e "${RED}==================================================${NC}"
    exit $RESULT
fi
