FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=30 \
    PIP_ONLY_BINARY=:all: \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple/ \
    PIP_TRUSTED_HOST="mirrors.aliyun.com pypi.tuna.tsinghua.edu.cn"

COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 30 --retries 5 --prefer-binary -r requirements.txt
COPY . .

RUN useradd --system --create-home --uid 10001 app \
    && mkdir -p /app/outputs \
    && chown -R app:app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "bonus_platform.app:app", "--host", "0.0.0.0", "--port", "8000"]
