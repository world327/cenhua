#!/usr/bin/env bash
# CENHUA installer (optional — `bin/cenhua setup` does the same bootstrap).
# Installs python deps and links `cenhua` onto your PATH.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> python deps (idempotent)"
./bin/cenhua setup

BIN="${CENHUA_BIN_DIR:-$HOME/.local/bin}"
if [ -t 0 ] && [ ! -e "$BIN/cenhua" ]; then
  read -r -p "link 'cenhua' into $BIN? [Y/n] " a || a=n
  case "${a:-y}" in
    [Yy]*) mkdir -p "$BIN" && ln -sf "$PWD/bin/cenhua" "$BIN/cenhua"
           echo "linked $BIN/cenhua -> $PWD/bin/cenhua"
           case ":$PATH:" in *":$BIN:"*) ;; *)
             echo "! add to your shell profile:  export PATH=\"$BIN:\$PATH\"";;
           esac ;;
    *) echo "skip PATH link — the skill calls $PWD/bin/cenhua directly" ;;
  esac
fi

echo
echo "done. verify:   ./bin/cenhua doctor"
echo
echo "as an OpenClaw skill (no install.sh needed there — agent runs setup):"
echo "  openclaw skills install git:github.com/world327/cenhua"
echo "  # or local:  openclaw skills install $PWD"
