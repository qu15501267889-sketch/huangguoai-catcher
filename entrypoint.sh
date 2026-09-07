#!/bin/sh
# 容器入口：常驻循环，每隔 INTERVAL_SEC 扫描一次并补下载新增分集
set -e
mkdir -p "$OUT_DIR"
INTERVAL="${INTERVAL_SEC:-21600}"   # 默认 6 小时
echo "[entrypoint] out=$OUT_DIR manifest=$MANIFEST interval=${INTERVAL}s"
run_once() {
    echo "[entrypoint] scan @ $(date '+%F %T')"
    python -m hgcatcher \
        --config /app/config.json \
        --out "$OUT_DIR" \
        --manifest "$MANIFEST" \
        --log "${LOG_FILE:-$OUT_DIR/download.log}" \
        --workers "${WORKERS:-3}" \
        --with-meta \
        --mode "${MODE:-ffmpeg}" \
        ${ONLY:+--only "$ONLY"} \
        ${MAX_EPS:+--max-eps "$MAX_EPS"}
}
run_once
# 之后循环。若只想跑一次：传 ONCE=1
if [ "${ONCE:-0}" = "1" ]; then
    echo "[entrypoint] ONCE=1 结束"
    exit 0
fi
while true; do
    sleep "$INTERVAL"
    run_once
done
