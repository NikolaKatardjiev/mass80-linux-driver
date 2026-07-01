#!/usr/bin/env bash

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_NAME="script.py"
SERVICE_NAME="mass80.service"
BIN_DIR="$HOME/.local/bin"
SYSTEMD_DIR="$HOME/.config/systemd/user"
SYMLINK_TARGET="$BIN_DIR/mass80-driver.py"

echo -e "${BLUE}=== Mass80 Linux Driver Installer ===${NC}"

if [ ! -f "$SCRIPT_NAME" ]; then
    echo -e "${RED}Error: $SCRIPT_NAME not found in the current directory!${NC}"
    echo "Please run this script from inside your development folder."
    exit 1
fi

DEV_SCRIPT_PATH=$(realpath "$SCRIPT_NAME")
echo -e "Found development script at: ${YELLOW}$DEV_SCRIPT_PATH${NC}"

echo -e "Preparing local directories..."
mkdir -p "$BIN_DIR"
mkdir -p "$SYSTEMD_DIR"

echo -e "Fixing home directory traversal permissions..."
chmod +x "$HOME"
chmod +x "$(dirname "$DEV_SCRIPT_PATH")"

chmod +x "$DEV_SCRIPT_PATH"

if [ -L "$SYMLINK_TARGET" ] || [ -f "$SYMLINK_TARGET" ]; then
    echo -e "${YELLOW}Existing binary/symlink found. Removing old target...${NC}"
    rm -f "$SYMLINK_TARGET"
fi

echo -e "Creating absolute symlink..."
ln -s "$DEV_SCRIPT_PATH" "$SYMLINK_TARGET"
echo -e "${GREEN}✓ Symlink created successfully.${NC}"

echo -e "Deploying systemd user service..."
cat << EOF > "$SYSTEMD_DIR/$SERVICE_NAME"
[Unit]
Description=MWKeys Mass80 Linux Touchscreen Driver
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $SYMLINK_TARGET
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

echo -e "Reloading systemd manager configuration..."
systemctl --user daemon-reload

echo -e "Enabling and starting $SERVICE_NAME..."
systemctl --user enable --now "$SERVICE_NAME"

echo -e "\n${BLUE}=== Verification ===${NC}"
if systemctl --user is-active --quiet "$SERVICE_NAME"; then
    echo -e "${GREEN}★ Mass80 Driver is up and running in the background! ★${NC}"
    echo -e "You can modify ${YELLOW}$DEV_SCRIPT_PATH${NC} and restart using:"
    echo -e "  ${BLUE}systemctl --user restart $SERVICE_NAME${NC}"
else
    echo -e "${RED}⚠ Service started but is currently inactive. Check logs using:${NC}"
    echo "  journalctl --user -u $SERVICE_NAME -n 20"
fi
