#!/bin/sh
# Install mass80d as a systemd user service running from this checkout.
set -eu
repo=$(cd "$(dirname "$0")" && pwd)
dest="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$dest"
sed "s|@REPO@|$repo|g" "$repo/systemd/mass80d.service" > "$dest/mass80d.service"
systemctl --user daemon-reload
systemctl --user enable --now mass80d.service
systemctl --user --no-pager status mass80d.service | head -n 5
