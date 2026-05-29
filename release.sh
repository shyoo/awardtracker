#!/bin/bash
# Award Tracker - Premium Release Packaging Script for macOS

# Colors for terminal
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}==================================================${NC}"
echo -e "${CYAN}      Award Tracker Release Builder Tool (macOS)   ${NC}"
echo -e "${CYAN}==================================================${NC}"

# 1. Verify build script
if [ ! -f "./build.sh" ]; then
    echo -e "${RED}Error: Build script './build.sh' not found.${NC}"
    exit 1
fi

# 2. Call build.sh to compile application
echo -e "${YELLOW}Step 1: Compiling application via build.sh...${NC}"
./build.sh
RESULT=$?
if [ $RESULT -ne 0 ]; then
    echo -e "${RED}Error: Compilation failed.${NC}"
    exit 1
fi

APP_PATH="dist/AwardTracker.app"
BIN_PATH="dist/awardtracker"

if [ ! -d "$APP_PATH" ]; then
    echo -e "${RED}Error: App bundle '$APP_PATH' was not generated.${NC}"
    exit 1
fi

# 3. Create Portable ZIP Distribution
echo -e "\n${YELLOW}Step 2: Packaging Portable ZIP Distribution...${NC}"
PORTABLE_DIR="dist/AwardTracker-Portable"
rm -rf "$PORTABLE_DIR"
mkdir -p "$PORTABLE_DIR"

if [ -f "$BIN_PATH" ]; then
    cp "$BIN_PATH" "$PORTABLE_DIR/awardtracker"
else
    # Fallback to copy the binary from within .app bundle
    cp "$APP_PATH/Contents/MacOS/awardtracker" "$PORTABLE_DIR/awardtracker"
fi

if [ -f "settings.json" ]; then
    cp "settings.json" "$PORTABLE_DIR/settings.json"
fi

PORTABLE_ZIP="dist/awardtracker-portable.zip"
rm -f "$PORTABLE_ZIP"
(cd dist && zip -r -q "awardtracker-portable.zip" "AwardTracker-Portable")
rm -rf "$PORTABLE_DIR"

if [ -f "$PORTABLE_ZIP" ]; then
    ZIP_SIZE=$(du -h "$PORTABLE_ZIP" | cut -f1)
    echo -e "${GREEN}Portable ZIP created successfully at: $PORTABLE_ZIP ($ZIP_SIZE)${NC}"
else
    echo -e "${RED}Warning: Failed to generate portable ZIP archive.${NC}"
fi

# 4. Create native macOS DMG Setup Installer
echo -e "\n${YELLOW}Step 3: Packaging Setup Disk Image (DMG)...${NC}"
DMG_TEMP="dist/dmg_temp"
rm -rf "$DMG_TEMP"
mkdir -p "$DMG_TEMP"

# Copy the .app bundle to temporary disk image staging area
cp -R "$APP_PATH" "$DMG_TEMP/"

# Create standard Applications symlink inside DMG staging area for drag-and-drop installation
ln -s /Applications "$DMG_TEMP/Applications"

DMG_OUT="dist/AwardTracker-Setup.dmg"
rm -f "$DMG_OUT"

echo -e "Creating disk image (hdiutil)..."
hdiutil create -volname "Award Tracker" -srcfolder "$DMG_TEMP" -ov -format UDZO "$DMG_OUT" > /dev/null
RESULT=$?

# Clean up staging area
rm -rf "$DMG_TEMP"

if [ $RESULT -eq 0 ] && [ -f "$DMG_OUT" ]; then
    DMG_SIZE=$(du -h "$DMG_OUT" | cut -f1)
    echo -e "${GREEN}Setup DMG generated successfully at: $DMG_OUT ($DMG_SIZE)${NC}"
else
    echo -e "${RED}Error: Failed to generate DMG installer.${NC}"
    exit 1
fi

echo -e "\n${CYAN}==================================================${NC}"
echo -e "${CYAN}            DISTRIBUTION SUMMARY                  ${NC}"
echo -e "${CYAN}==================================================${NC}"
if [ -f "$PORTABLE_ZIP" ]; then
    echo -e "  [Portable]  $PORTABLE_ZIP ($ZIP_SIZE)"
fi
if [ -f "$DMG_OUT" ]; then
    echo -e "  [Installer] $DMG_OUT ($DMG_SIZE)"
fi
echo -e "${CYAN}==================================================${NC}"
