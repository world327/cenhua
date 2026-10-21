#!/usr/bin/env bash
# End-to-end smoke test WITHOUT any LLM gateway.
# Verifies: init -> inbox drop -> offline intake (M5-4 zero-gateway fallback)
# -> text layer -> find/read/status/doctor. Exits non-zero on first broken step.
set -euo pipefail
cd "$(dirname "$0")/.."

export CENHUA_HOME="$(mktemp -d)"
trap 'rm -rf "$CENHUA_HOME"' EXIT
ok() { printf '\033[32m✓\033[0m %s\n' "$1"; }
bad() { printf '\033[31mx\033[0m %s\n' "$1"; exit 1; }

echo "== CENHUA smoke (offline, zero-gateway)"
./bin/cenhua init demo --title "smoke" --yes >/dev/null || bad "init"
ok "init demo"

V="$CENHUA_HOME/vaults/demo"
D="$V/engine/docs/pi-smoke0001"
mkdir -p "$D"
cat > "$D/pages.json" <<'JSON'
[{"page_index": 1, "markdown": "# Cen Hua notes\n\nThe Kunlun tree marks the seasons."},
 {"page_index": 2, "markdown": "第二大脑：违约金的约定见附录。联系 13800138000。"}]
JSON
echo '{"docs":{"pi-smoke0001":{"name":"notes.pdf"}}}' > "$V/engine/manifest.json"

./bin/cenhua flatten --vault demo | grep -q "1 docs ready" || bad "flatten"
ok "flatten -> text layer"

./bin/cenhua find 违约金 --vault demo | grep -q "P2" || bad "find cjk+page"
./bin/cenhua find Kunlun --vault demo | grep -q "P1" || bad "find en+page"
ok "find exact + page citations (en/cjk)"

./bin/cenhua find absent-xyz --vault demo >/dev/null 2>&1 && bad "find miss rc" || true
ok "not-found exit code"

# M5-4 离线降级：无网关时 intake 成功（不是失败），文件进 .processed
echo "drop" > "$V/inbox/loose.txt"
./bin/cenhua add --inbox --vault demo > /tmp/cenhua-smoke.log 2>&1 || true
grep -q "offline" /tmp/cenhua-smoke.log || bad "intake must report offline fallback"
[ -d "$V/inbox/.processed" ] && [ -n "$(ls -A "$V/inbox/.processed")" ] || bad "processed file kept"
ok "offline intake succeeds, file moved to .processed"

./bin/cenhua ask --all "q?" --dry-run --vault demo | grep -q "nothing was sent" || bad "dry-run"
ok "ask --dry-run costs nothing"

./bin/cenhua read pi-smoke -p 2 --vault demo | grep -q "违约金" || bad "read"
ok "read page verification"

./bin/cenhua doctor --vault demo | grep -q "PI_BASE/PI_KEY not set" || bad "doctor"
ok "doctor reports missing gateway (non-fatal for offline)"

echo; echo -e "\033[32mALL SMOKE CHECKS PASSED\033[0m"
