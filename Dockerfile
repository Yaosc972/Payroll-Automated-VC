# Reuse verified production #45 dependencies; dependency changes require a full rebuild.
FROM host-harbor.nwhm-internal.ztn.cn/dc-hras-aideploy/42141ddcae8f43b19aef63f95008442b-api:1-14675733-930@sha256:104c921f0a3dec46b59f536c92fc7f9edf3509b9d347187bdd73c69f85414cb1
USER root
WORKDIR /app
COPY requirements.txt /tmp/hras-release-requirements.txt
RUN echo "f3a7451c62b47efbcc36d0fd8379be13de6819cbfc551171b29802830cdbd1eb  /tmp/hras-release-requirements.txt" | sha256sum -c - \
    && cmp /tmp/hras-release-requirements.txt /app/requirements.txt \
    && rm /tmp/hras-release-requirements.txt
COPY . .
RUN chown -R app:app /app
USER app
EXPOSE 8000
CMD ["uvicorn", "bonus_platform.app:app", "--host", "0.0.0.0", "--port", "8000"]
