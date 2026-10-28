# Extend the pinned company base with the complete current dependency set.
FROM host-harbor.nwhm-internal.ztn.cn/dc-hras-aideploy/42141ddcae8f43b19aef63f95008442b-api:1-14675733-930@sha256:104c921f0a3dec46b59f536c92fc7f9edf3509b9d347187bdd73c69f85414cb1
USER root
WORKDIR /app
COPY requirements.txt /tmp/hras-release-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/hras-release-requirements.txt \
    && python -m pip check \
    && python -m pip freeze > /app/requirements.resolved.txt \
    && rm /tmp/hras-release-requirements.txt
COPY . .
RUN chown -R app:app /app
USER app
RUN python -m pip check \
    && python -c "import os, platform; print('OCR_FINAL_IMAGE_IDENTITY', os.getuid(), platform.system(), platform.machine())" \
    && python -m bonus_platform.engine.recruitment_ocr --check
EXPOSE 8000
CMD ["uvicorn", "bonus_platform.app:app", "--host", "0.0.0.0", "--port", "8000"]
