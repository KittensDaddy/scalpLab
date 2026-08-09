#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo "Run as root: sudo $0" >&2; exit 1; fi
install -m 0644 systemd/scalp-recorder.service /etc/systemd/system/scalp-recorder.service
install -m 0644 systemd/scalplab-web.service /etc/systemd/system/scalplab-web.service
systemctl daemon-reload
systemctl enable scalp-recorder.service scalplab-web.service
echo "Installed and enabled. Start with: systemctl start scalp-recorder scalplab-web"
