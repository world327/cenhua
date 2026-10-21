#!/usr/bin/env bash
# CENHUA 服务管理脚本（M5-1）— start/stop/restart/status
# 遵循 AGENTS.md 铁律：不用 set -e（防 minor 错误退出）、keep_alive 无限循环、
# 启动时显式建目录、PID 文件锁防重复。
#
# 用法：
#   deploy/service.sh start     启动 Web 服务（后台，nohup & disown）
#   deploy/service.sh stop      停止
#   deploy/service.sh restart   重启
#   deploy/service.sh status    状态
#
# 环境变量：
#   CENHUA_HOME         vault 存储根（默认 ~/.cenhua）
#   CENHUA_WEB_HOST/PORT 绑定地址/端口（默认 127.0.0.1:8765）
#   CENHUA_API_TOKEN    Web/API 鉴权 token（必填，fail-closed）
#   CENHUA_PYTHON       python 解释器（默认 python3）

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${CENHUA_PYTHON:-python3}"
HOST="${CENHUA_WEB_HOST:-127.0.0.1}"
PORT="${CENHUA_WEB_PORT:-8765}"
RUN_DIR="${CENHUA_RUN_DIR:-$ROOT/run}"
LOG_DIR="${CENHUA_LOG_DIR:-$ROOT/logs}"
PID_FILE="$RUN_DIR/cenhua-web.pid"
LOG_FILE="$LOG_DIR/web-service.log"

# 显式建目录（AGENTS.md 铁律）
mkdir -p "$RUN_DIR" "$LOG_DIR"

is_running() {
    [ -f "$PID_FILE" ] || return 1
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null)"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

start() {
    if is_running; then
        echo "cenhua web already running (pid $(cat "$PID_FILE"))"
        return 0
    fi
    if [ -z "${CENHUA_API_TOKEN:-}" ]; then
        echo "! CENHUA_API_TOKEN not set — Web/API will be fail-closed (all 401)."
        echo "  export CENHUA_API_TOKEN=... before start."
    fi
    echo "starting cenhua web on $HOST:$PORT ..."
    # nohup & disown（不用 setsid，见 AGENTS.md §5 沙箱坑）
    nohup "$PY" "$ROOT/scripts/m_webui.py" --vault "${CENHUA_VAULT:-}" \
        --host "$HOST" --port "$PORT" >> "$LOG_FILE" 2>&1 &
    local pid=$!
    disown "$pid" 2>/dev/null || true
    echo "$pid" > "$PID_FILE"
    echo "started (pid $pid) — log: $LOG_FILE"
    # 启动保护期：等待 /health 就绪（最多 20s）
    local i
    for i in $(seq 1 20); do
        if curl -fsS "http://$HOST:$PORT/health" >/dev/null 2>&1; then
            echo "health OK after ${i}s"
            return 0
        fi
        sleep 1
    done
    echo "! health not ready after 20s — check $LOG_FILE"
    return 1
}

stop() {
    if ! is_running; then
        echo "cenhua web not running"
        rm -f "$PID_FILE"
        return 0
    fi
    local pid
    pid="$(cat "$PID_FILE")"
    echo "stopping cenhua web (pid $pid) ..."
    kill "$pid" 2>/dev/null
    # 等待退出（最多 10s）
    local i
    for i in $(seq 1 10); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
    done
    kill -9 "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "stopped"
}

restart() {
    stop
    sleep 1
    start
}

status() {
    if is_running; then
        echo "cenhua web: RUNNING (pid $(cat "$PID_FILE"))"
        curl -fsS "http://$HOST:$PORT/health" 2>/dev/null && echo || echo "(health unreachable)"
        return 0
    fi
    echo "cenhua web: STOPPED"
    return 1
}

case "${1:-}" in
    start)   start ;;
    stop)    stop ;;
    restart) restart ;;
    status)  status ;;
    *) echo "usage: $0 {start|stop|restart|status}"; exit 2 ;;
esac
