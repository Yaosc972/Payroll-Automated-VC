FROM python:3.11-slim

WORKDIR /app

# 使用清华镜像源加速 apt
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true && \
    sed -i 's|http://deb.debian.org|http://mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list 2>/dev/null || true && \
    apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖（使用清华 pip 镜像）
COPY requirements.txt .
RUN pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --trusted-host pypi.tuna.tsinghua.edu.cn \
    -r requirements.txt gunicorn

# 复制项目代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/outputs

EXPOSE 8001

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8001/api/auth/shell/config || exit 1

# 生产模式：gunicorn + uvicorn worker
CMD ["gunicorn", "bonus_platform.app:app", \
     "--workers", "4", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8001", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
