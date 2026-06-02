# HA add-on build: BUILD_FROM is overridden by build.json per architecture
# Standalone test: uses python:3.12-slim default
ARG BUILD_FROM=python:3.12-slim
FROM ${BUILD_FROM}

LABEL \
    io.hass.name="MG4 Mate" \
    io.hass.description="Trip tracking and statistics for MG4 via Home Assistant" \
    io.hass.type="addon" \
    io.hass.version="1.0.2"

WORKDIR /app

COPY poller/requirements.txt /tmp/poller-req.txt
COPY web/requirements.txt /tmp/web-req.txt
RUN pip install --no-cache-dir \
    -r /tmp/poller-req.txt \
    -r /tmp/web-req.txt

COPY poller/ /app/poller/
COPY web/    /app/web/
COPY run.sh  /run.sh
RUN chmod a+x /run.sh

ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/data/mg4_mate.db

CMD ["/run.sh"]
