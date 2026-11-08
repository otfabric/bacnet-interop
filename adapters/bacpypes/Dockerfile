# bacnet-interop legacy BACpypes adapter (device server, BBMD and client mode).
#
# Legacy BACpypes (PyPI "bacpypes", the asyncore code base that BACpypes3
# replaced), not BACpypes3 (adapters/bacpypes3). BACpypes 0.x needs asyncore,
# which Python 3.12 removed: Debian bookworm ships Python 3.11.
#
# Build from repository root:
#   docker buildx build --platform=linux/amd64 \
#       -f adapters/bacpypes/Dockerfile \
#       -t bacnet-interop-bacpypes:local .

ARG DEBIAN_DIGEST=sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818

FROM debian:bookworm-slim@${DEBIAN_DIGEST} AS runtime

ARG BACPYPES_VERSION=0.19.0
ARG ADAPTER_VERSION=dev

# tmpfs /tmp: Docker Desktop's default /tmp breaks apt-key/gpgv status-fd.
RUN --mount=type=tmpfs,target=/tmp \
    apt-get update && apt-get install -y --no-install-recommends \
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
    BACPYPES_VERSION=${BACPYPES_VERSION} \
    PYTHONUNBUFFERED=1 \
    PYTHONWARNINGS=ignore::DeprecationWarning

# The wheel is installed by its sha256 (--require-hashes); the version check
# fails the build when requirements.txt and BACPYPES_VERSION disagree, and the
# interpreter check when the base image no longer has asyncore (Python 3.12+).
COPY adapters/bacpypes/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --no-deps --only-binary=:all: --require-hashes -r /tmp/requirements.txt \
    && test "$(pip show bacpypes | sed -n 's/^Version: //p')" = "${BACPYPES_VERSION}" \
    && python3 -I -c "import asyncore, sys; print(sys.version)" \
    && rm /tmp/requirements.txt

COPY adapters/bacpypes/common.py /usr/local/lib/bacpypes-adapter/common.py
COPY adapters/bacpypes/device_server.py /usr/local/lib/bacpypes-adapter/device_server.py
COPY adapters/bacpypes/client_driver.py /usr/local/lib/bacpypes-adapter/client_driver.py
COPY adapters/bacpypes/entrypoint.sh /usr/local/bin/entrypoint.sh
# Client mode (docs/CLIENT_DRIVER_CONTRACT.md): the published scenario files.
COPY fixtures/scenarios/ /scenarios/
COPY fixtures/device/ /fixtures/device/

RUN chmod 755 /usr/local/bin/entrypoint.sh

USER adapter
EXPOSE 47808/udp

# "client" as the first argument selects client mode; the device server is the
# default.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD []
