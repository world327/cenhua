# CENHUA 容器化部署（M5-1）
# 面向生产可用：Web UI + 局域网 API 常驻服务。
# 用法：docker compose -f deploy/docker-compose.yml up -d
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CENHUA_HOME=/data/cenhua

# 系统依赖：pymupdf 渲染 + Playwright chromium 系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 libnss3 libnspr4 libdbus-1-3 libatk1.0-0 \
        libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
        libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 \
        libcairo2 libgdk-pixbuf-2.0-0 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用层缓存）
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt \
    && playwright install chromium --with-deps || true

# 应用代码
COPY . .

# 数据卷：vault 存储（CENHUA_HOME=/data/cenhua）
VOLUME ["/data/cenhua"]

# 默认启动 Web 服务（端口 8765）
EXPOSE 8765
CMD ["bash", "deploy/service.sh", "start"]
