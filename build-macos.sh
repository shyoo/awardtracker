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

# Generate awardtracker.icns from static/favicon.png (macOS only, requires sips + iconutil)
if [ "$(uname)" == "Darwin" ]; then
    SOURCE_PNG="static/favicon.png"
    ICONSET_DIR="awardtracker.iconset"
    ICNS_FILE="awardtracker.icns"

    if [ ! -f "$SOURCE_PNG" ]; then
        echo -e "${RED}Error: Source icon not found at $SOURCE_PNG${NC}"
        exit 1
    fi

    echo -e "${YELLOW}Generating $ICNS_FILE from $SOURCE_PNG...${NC}"
    rm -rf "$ICONSET_DIR"
    mkdir -p "$ICONSET_DIR"

    for SIZE in 16 32 64 128 256 512; do
        sips -z $SIZE $SIZE "$SOURCE_PNG" --out "$ICONSET_DIR/icon_${SIZE}x${SIZE}.png" > /dev/null 2>&1
        DOUBLE=$((SIZE * 2))
        sips -z $DOUBLE $DOUBLE "$SOURCE_PNG" --out "$ICONSET_DIR/icon_${SIZE}x${SIZE}@2x.png" > /dev/null 2>&1
    done

    iconutil -c icns "$ICONSET_DIR" -o "$ICNS_FILE"
    rm -rf "$ICONSET_DIR"
    echo -e "${GREEN}Icon generated: $ICNS_FILE${NC}"
else
    echo -e "${YELLOW}Skipping .icns generation (not running on macOS).${NC}"
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
        echo -e "${YELLOW}Packaging into DMG Installer...${NC}"
        
        if command -v create-dmg &> /dev/null; then
            create-dmg \
              --volname "Award Tracker" \
              --window-pos 200 120 \
              --window-size 600 400 \
              --icon-size 100 \
              --icon "AwardTracker.app" 150 190 \
              --hide-extension "AwardTracker.app" \
              --app-drop-link 450 190 \
              "dist/AwardTracker.dmg" \
              "dist/AwardTracker.app"
        else
            echo "create-dmg not found, using hdiutil..."
            mkdir -p dist/dmg_root
            cp -R dist/AwardTracker.app dist/dmg_root/
            ln -s /Applications dist/dmg_root/Applications
            hdiutil create -volname "Award Tracker" -srcfolder dist/dmg_root -ov -format UDZO dist/AwardTracker.dmg
            rm -rf dist/dmg_root
        fi
        echo -e "Native macOS DMG Installer: ${GREEN}dist/AwardTracker.dmg${NC}"
    fi
    echo -e "Standalone Binary: ${GREEN}dist/awardtracker${NC}"
else
    echo -e "\n${RED}Error: PyInstaller compilation failed.${NC}"
    exit $RESULT
fi
