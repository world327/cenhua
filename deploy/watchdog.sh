#!/usr/bin/env bash
# CENHUA 看门狗（M5-1）— 监控 Web 服务，异常时重启。
# 遵循 AGENTS.md §5 铁律：
#   * 端口检测精确匹配（curl /health，非裸端口探测）
#   * 不用 set -e（防 minor 错误退出）
#   * 启动保护期（服务刚起不误判）
#   * 重启冷却 + 上限（防崩溃风暴）
#   * PID 文件锁防重复监控
#
# 用法：deploy/watchdog.sh [--interval S] [--max-restarts N]
# 建议配合 systemd 或 cron 常驻。

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${CENHUA_WEB_HOST:-127.0.0.1}"
PORT="${CENHUA_WEB_PORT:-8765}"
RUN_DIR="${CENHUA_RUN_DIR:-$ROOT/run}"
LOCK_FILE="$RUN_DIR/watchdog.lock"
LOG_FILE="${CENHUA_LOG_DIR:-$ROOT/logs}/watchdog.log"
INTERVAL="${1:-10}"          # 监控间隔（秒）
MAX_RESTARTS="${2:-5}"       # 冷却窗口内最大重启次数
COOLDOWN=60                  # 冷却窗口（秒）
STARTUP_GRACE=20             # 启动保护期（秒）

mkdir -p "$RUN_DIR" "$(dirname "$LOG_FILE")"

# ---- PID 文件锁：只允许一个 watchdog ----
if [ -f "$LOCK_FILE" ]; then
    old="$(cat "$LOCK_FILE" 2>/dev/null)"
    if [ -n "$old" ] && kill -0 "$old" 2>/dev/null; then
        echo "watchdog already running (pid $old) — exit"
        exit 0
    fi
    rm -f "$LOCK_FILE"
fi
echo "$$" > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

log() { echo "$(date '+%F %T') $*" >> "$LOG_FILE"; }

health_ok() {
    curl -fsS "http://$HOST:$PORT/health" >/dev/null 2>&1
}

restart_service() {
    log "restarting cenhua web (health failed)"
    bash "$ROOT/deploy/service.sh" restart >> "$LOG_FILE" 2>&1
}

log "watchdog started (interval=${INTERVAL}s, max_restarts=${MAX_RESTARTS}/window)"
restarts=0
window_start="$(date +%s)"

while true; do
    sleep "$INTERVAL"
    if health_ok; then
        restarts=0
        window_start="$(date +%s)"
        continue
    fi
    # 启动保护期：服务刚重启，给足时间就绪，不误判
    now="$(date +%s)"
    if [ $((now - window_start)) -lt "$STARTUP_GRACE" ]; then
        continue
    fi
    # 冷却窗口重置
    if [ $((now - window_start)) -ge "$COOLDOWN" ]; then
        restarts=0
        window_start="$now"
    fi
    if [ "$restarts" -ge "$MAX_RESTARTS" ]; then
        log "restart limit reached ($MAX_RESTARTS) — giving up, manual intervention needed"
        exit 1
    fi
    restart_service
    restarts=$((restarts + 1))
    window_start="$(date +%s)"
done
