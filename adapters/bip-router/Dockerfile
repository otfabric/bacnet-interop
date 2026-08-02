# bacnet-interop BIP↔BIP topology router.
#
# Build from repository root:
#   docker buildx build --platform=linux/amd64 \
#       -f adapters/bip-router/Dockerfile \
#       -t bacnet-interop-bip-router:local .

ARG DEBIAN_DIGEST=sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818

FROM debian:bookworm-slim@${DEBIAN_DIGEST}

ARG ADAPTER_VERSION=dev

# tmpfs /tmp: Docker Desktop's default /tmp breaks apt-key/gpgv status-fd.
RUN --mount=type=tmpfs,target=/tmp \
    apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      iproute2 \
      python3 \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system --gid 10001 adapter \
    && adduser --system --uid 10001 --ingroup adapter --no-create-home adapter

ENV ADAPTER_VERSION=${ADAPTER_VERSION} \
    BACNET_IP_PORT=47808 \
    BACNET_NETWORKS=1,2 \
    PYTHONUNBUFFERED=1

COPY adapters/bip-router/bip_router.py /usr/local/bin/bip_router.py
COPY adapters/bip-router/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod 755 /usr/local/bin/bip_router.py /usr/local/bin/entrypoint.sh

# Cap_net_bind / broadcast: run as root for SO_BROADCAST on dual interfaces.
# Topology fixture only; not a production image.
USER root
EXPOSE 47808/udp

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
