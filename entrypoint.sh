#!/bin/sh
# 容器入口：WebUI 常驻服务（浏览器搜索/点选下载）
set -e
mkdir -p "$OUT_DIR"
echo "[entrypoint] out=$OUT_DIR manifest=$MANIFEST proxy=${HG_PROXY:-无} port=${WEBUI_PORT:-8765}"
exec python -m hgcatcher \
    --config /app/config.json \
    --out "$OUT_DIR" \
    --manifest "$MANIFEST" \
    --log "${LOG_FILE:-$OUT_DIR/download.log}" \
    --workers "${WORKERS:-3}" \
    --serve \
    --port "${WEBUI_PORT:-8765}"
