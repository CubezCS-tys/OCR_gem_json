#!/usr/bin/env bash
# Watchdog for run_batch_large.py — restarts it if it dies.
# Logs to watchdog_batch_large.log in the same directory.

DIR="$(cd "$(dirname "$0")" && pwd)"
CMD="python run_batch_large.py batch33-add --api-workers 1 --render-workers 8"
LOG="$DIR/watchdog_batch_large.log"
BATCH_LOG="$DIR/batch_large_$(date +%Y%m%d_%H%M%S).log"

cd "$DIR" || exit 1

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"
}

log "Watchdog started. Monitoring: $CMD"
log "Batch output log: $BATCH_LOG"

while true; do
    if pgrep -f "run_batch_large.py" > /dev/null; then
        log "Process is alive (PID $(pgrep -f run_batch_large.py | head -1))"
    else
        log "Process not found — starting: $CMD"
        source "$DIR/venv/bin/activate" 2>/dev/null || true
        nohup $CMD >> "$BATCH_LOG" 2>&1 &
        NEW_PID=$!
        log "Restarted with PID $NEW_PID"
    fi
    sleep 30
done
