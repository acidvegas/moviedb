#!/usr/bin/env bash
# MovieDB setup - developed by acidvegas (https://github.com/acidvegas)
#
# ./setup.sh    full install: venv, deps, .env, systemd service
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

DIR="$(pwd)"
RUN_USER="${SUDO_USER:-$USER}"
SERVICE="moviedb"

make_env() {
	if [ -f .env ]; then
		echo "[*] .env exists, keeping it"
		return
	fi

	printf 'HOST=0.0.0.0\nPORT=5000\nADMIN_PASSWORD=\n' > .env
	echo "[+] wrote .env (HOST=0.0.0.0 PORT=5000)"
}

make_service() {
	sudo tee "/etc/systemd/system/$SERVICE.service" >/dev/null <<-EOF
		[Unit]
		Description=MovieDB
		After=network-online.target tailscaled.service
		Wants=network-online.target

		[Service]
		User=$RUN_USER
		WorkingDirectory=$DIR
		ExecStart=$DIR/venv/bin/python $DIR/app.py
		Restart=always
		RestartSec=10

		[Install]
		WantedBy=multi-user.target
	EOF
	sudo systemctl daemon-reload
	sudo systemctl enable --now "$SERVICE"
	echo "[+] systemd service $SERVICE enabled and started (journalctl -u $SERVICE -f)"
}

command -v python3 >/dev/null || { echo "[!] python3 is required"; exit 1; }

python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt
echo "[+] venv ready"

make_env
make_service

echo
echo "[*] Open http://<this machine's LAN or Tailscale IP>:$(grep -E '^PORT=' .env | cut -d= -f2)"
echo "[*] Set ADMIN_PASSWORD in .env, then: sudo systemctl restart $SERVICE"
echo "[*] The IMDb database builds automatically on first start (~30 min, ~12 GB)."
