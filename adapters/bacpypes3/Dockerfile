# bacnet-interop BACpypes3 adapter (device server).
#
# Build from repository root:
#   docker buildx build --platform=linux/amd64 \
#       -f adapters/bacpypes3/Dockerfile \
#       -t bacnet-interop-bacpypes3:local .

ARG DEBIAN_DIGEST=sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818

FROM debian:bookworm-slim@${DEBIAN_DIGEST} AS runtime

ARG BACPYPES3_VERSION=0.0.98
ARG ADAPTER_VERSION=dev

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      python3 \
      python3-pip \
      python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system --gid 10001 adapter \
    && adduser --system --uid 10001 --ingroup adapter --no-create-home adapter \
    && python3 -m venv /opt/venv

ENV PATH="/opt/venv/bin:${PATH}" \
    ADAPTER_VERSION=${ADAPTER_VERSION} \
    FIXTURE=device-baseline-v2 \
    DEVICE_FIXTURE_FILE=/fixtures/device/device-baseline-v2.json \
    BACNET_IP_PORT=47808 \
    DEVICE_INSTANCE=1234 \
    DEVICE_NAME=InteropDevice \
    BACPYPES3_VERSION=${BACPYPES3_VERSION} \
    PYTHONUNBUFFERED=1

COPY adapters/bacpypes3/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip show bacpypes3 | grep -E '^Version:' \
    && rm /tmp/requirements.txt

COPY adapters/bacpypes3/device_server.py /usr/local/bin/device_server.py
COPY fixtures/device/device-baseline-v1.json /fixtures/device/device-baseline-v1.json
COPY fixtures/device/device-baseline-v2.json /fixtures/device/device-baseline-v2.json

RUN chmod 755 /usr/local/bin/device_server.py

USER adapter
EXPOSE 47808/udp

ENTRYPOINT ["python3", "/usr/local/bin/device_server.py"]
CMD []
