FROM python:3.11-slim

# ffmpeg 用于 HLS(AES-128) 合成 mp4
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 包结构
COPY hgcatcher/ ./hgcatcher/
COPY config.json .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# 输出目录：挂载到 NAS 介质盘
ENV OUT_DIR=/data/huangguoai
ENV MANIFEST=/data/huangguoai/manifest.json
ENV LOG_FILE=/data/huangguoai/download.log
VOLUME ["/data"]

# 常驻运行（每次容器启动即扫一遍+补新）
CMD ["/app/entrypoint.sh"]
