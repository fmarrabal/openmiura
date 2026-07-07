FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OPENMIURA_CONFIG=configs/openmiura.yaml \
    OPENMIURA_SERVER_HOST=0.0.0.0 \
    OPENMIURA_SERVER_PORT=8081

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && addgroup --system openmiura \
    && adduser --system --ingroup openmiura --home /app openmiura \
    && mkdir -p /app/data /app/data/sandbox \
    && chown -R openmiura:openmiura /app

USER openmiura

EXPOSE 8081 8091

# Single-line health probe: a shell heredoc after HEALTHCHECK CMD is NOT valid
# in a Dockerfile (buildkit reads each following line as its own instruction),
# so use one self-contained `python -c` command.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import os,sys,urllib.request as u; sys.exit(0 if u.urlopen('http://%s:%s/health' % (os.environ.get('OPENMIURA_HEALTHCHECK_HOST','127.0.0.1'), os.environ.get('OPENMIURA_SERVER_PORT','8081')), timeout=3).status==200 else 1)"

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD []
