FROM python:3.11-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pyserial==3.5 paho-mqtt PyYAML

WORKDIR /opt/dantherm-passivelink-webui
COPY VERSION gateway/*.py ./
COPY gateway/webui ./webui

ENV DANTHERM_WEBUI_AUTH_FILE=/var/lib/dantherm-hch5-ha/webui-auth.json \
    TZ=Europe/Copenhagen \
    PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "dantherm_controller_gateway.py", "-c", "/etc/dantherm-passivelink-webui/controller.yaml"]
