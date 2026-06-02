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
if [ ! -f "./build-macos.sh" ]; then
    echo -e "${RED}Error: Build script './build-macos.sh' not found.${NC}"
    exit 1
fi

# 1.4. Parse command line arguments
UNIVERSAL_BUILD=false
for arg in "$@"; do
    if [ "$arg" == "--universal" ]; then
        UNIVERSAL_BUILD=true
    fi
done

# 1.5. Activate virtual environment if present to inspect correct context
if [ -d "venv" ]; then
    echo -e "${GREEN}Activating virtual environment...${NC}"
    source venv/bin/activate
fi

# 1.6. Validate Universal2 compatibility if requested
if [ "$UNIVERSAL_BUILD" = true ] && [ "$(uname)" == "Darwin" ]; then
    export AWARDTRACKER_BUILD_UNIVERSAL=1

    echo -e "\n${CYAN}==================================================${NC}"
    echo -e "${CYAN}      Universal2 Compatibility Verification       ${NC}"
    echo -e "${CYAN}==================================================${NC}"

    PYTHON_PATH=$(python -c "import sys; print(sys.executable)")
    PYTHON_REAL_PATH=$(python -c "import os; print(os.path.realpath('$PYTHON_PATH'))")
    
    echo -e "Checking Python Interpreter at $PYTHON_REAL_PATH..."
    ARCHS=$(lipo -info "$PYTHON_REAL_PATH" 2>/dev/null)
    IS_UNIVERSAL_PYTHON=true
    if [[ $ARCHS == *"x86_64"* && $ARCHS == *"arm64"* ]]; then
        echo -e "  Python: ${GREEN}✓ Universal2 ($ARCHS)${NC}"
    else
        echo -e "  Python: ${RED}✗ NOT Universal2 ($ARCHS)${NC}"
        IS_UNIVERSAL_PYTHON=false
    fi

    echo -e "\nChecking installed site-packages dependencies..."
    NON_UNIVERSAL_DEPS=$(python -c "
import os
import sys
import subprocess

site_packages = [p for p in sys.path if 'site-packages' in p]
if not site_packages:
    sys.exit(0)

non_universal = []
for sp_dir in site_packages:
    if not os.path.exists(sp_dir):
        continue
    for root, dirs, files in os.walk(sp_dir):
        for file in files:
            if file.endswith('.so') or file.endswith('.dylib'):
                full_path = os.path.join(root, file)
                try:
                    out = subprocess.check_output(['lipo', '-info', full_path], stderr=subprocess.DEVNULL).decode('utf-8')
                    if 'x86_64' not in out or 'arm64' not in out:
                        rel_path = os.path.relpath(full_path, sp_dir)
                        parts = rel_path.split(os.sep)
                        package_name = parts[0] if parts else rel_path
                        non_universal.append((package_name, rel_path, out.strip().split(': ')[-1]))
                except Exception:
                    pass

if non_universal:
    seen = set()
    for pkg, path, arch in non_universal:
        if pkg not in seen:
            print(f'  - Package: {pkg} ({path}) -> {arch}')
            seen.add(pkg)
    sys.exit(1)
else:
    sys.exit(0)
" 2>&1)
    
    DEPS_RESULT=$?
    if [ $DEPS_RESULT -eq 0 ]; then
        echo -e "  Dependencies: ${GREEN}✓ Universal2${NC}"
        IS_UNIVERSAL_DEPS=true
    else
        echo -e "${RED}✗ Incompatible dependencies found:${NC}"
        echo "$NON_UNIVERSAL_DEPS"
        IS_UNIVERSAL_DEPS=false
    fi

    if [ "$IS_UNIVERSAL_PYTHON" = false ] || [ "$IS_UNIVERSAL_DEPS" = false ]; then
        echo -e "\n${YELLOW}⚠️ WARNING: Your environment is NOT fully compatible with Universal2 builds.${NC}"
        echo -e "If you proceed, the built app may crash on either Intel or Apple Silicon Macs."
        echo -e "\nAdvice:"
        if [ "$IS_UNIVERSAL_PYTHON" = false ]; then
            echo -e "  - Install the official Universal2 Python installer from Python.org."
        fi
        if [ "$IS_UNIVERSAL_DEPS" = false ]; then
            echo -e "  - Reinstall dependencies with universal2 support (e.g. 'pip install --force-reinstall --no-binary :all: <package>')"
            echo -e "    or ensure you are downloading universal2 wheels."
        fi
        
        echo -e "\nWould you like to build anyway? (y/n)"
        read -r ANSWER
        if [ "$ANSWER" != "y" ] && [ "$ANSWER" != "Y" ]; then
            echo -e "${RED}Build aborted by user.${NC}"
            exit 1
        fi
    else
        echo -e "\n${GREEN}✓ Environment is fully compatible with Universal2 builds!${NC}"
    fi
elif [ "$(uname)" == "Darwin" ]; then
    echo -e "\n${YELLOW}Building for local architecture only (use '--universal' flag to compile for both Intel and Apple Silicon).${NC}"
fi

# 2. Call build-macos.sh to compile application
echo -e "\n${YELLOW}Step 1: Compiling application via build-macos.sh...${NC}"
./build-macos.sh
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

PORTABLE_ZIP="dist/awardtracker-macos-portable.zip"
rm -f "$PORTABLE_ZIP"
(cd dist && zip -r -q "awardtracker-macos-portable.zip" "AwardTracker-Portable")
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

DMG_OUT="dist/awardtracker-macos-setup.dmg"
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
