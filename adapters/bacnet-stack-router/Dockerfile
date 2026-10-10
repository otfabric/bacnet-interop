# bacnet-interop native BACnet/IP router: upstream bacnet-stack apps/router.
#
# Build from repository root:
#   docker buildx build \
#       -f adapters/bacnet-stack-router/Dockerfile \
#       -t bacnet-interop-bacnet-stack-router:local .
#
# The router is upstream code, built unpatched at the same pinned commit as
# adapters/bacnet-stack/Dockerfile (keep BACNET_STACK_SHA identical in both).
# Peer code retains its upstream license inside the image. go-bacnet must
# never link against bacnet-stack.

ARG DEBIAN_DIGEST=sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818

# ---------------------------------------------------------------------------
# Stage 1: build upstream apps/router against pinned bacnet-stack
# ---------------------------------------------------------------------------
FROM debian:bookworm-slim@${DEBIAN_DIGEST} AS bacnet-stack-router-build

ARG BACNET_STACK_REPO=https://github.com/bacnet-stack/bacnet-stack.git
# Tag bacnet-stack-1.6.1 (latest official release tag)
ARG BACNET_STACK_SHA=7a53f0a72a92de1621d30fc63703a29afe12bfaf
ARG BACNET_STACK_VERSION=bacnet-stack-1.6.1

# tmpfs /tmp: Docker Desktop's default /tmp breaks apt-key/gpgv status-fd.
RUN --mount=type=tmpfs,target=/tmp \
    apt-get update && apt-get install -y --no-install-recommends \
      binutils \
      ca-certificates \
      gcc \
      git \
      libc6-dev \
      libconfig-dev \
      make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --filter=blob:none "${BACNET_STACK_REPO}" bacnet-stack \
    && cd bacnet-stack \
    && git checkout --detach "${BACNET_STACK_SHA}" \
    && test "$(git rev-parse HEAD)" = "${BACNET_STACK_SHA}"

# Build configuration only (no source patch):
#   BACNET_IP_BROADCAST_USE_INADDR_ANY  bind each port socket to INADDR_ANY
#       (still SO_BINDTODEVICE per interface). Bound to the unicast address,
#       as upstream does by default, a Linux socket never receives the subnet
#       broadcasts that carry Who-Is-Router-To-Network, Who-Is and I-Am.
#   DEBUG_LEVEL=2  upstream PRINT(ERROR|INFO) diagnostics on stderr.
#   -O1  apps/router/ipmodule.c notes an fd_set failure when built with -Os.
RUN make -C /src/bacnet-stack/apps/router \
      BACNET_PORT=linux \
      BACNET_PORT_DIR=/src/bacnet-stack/ports/linux \
      OPTIMIZATION=-O1 \
      DEBUGGING="-DBACNET_IP_BROADCAST_USE_INADDR_ANY -DDEBUG_LEVEL=2" \
    && test -x /src/bacnet-stack/apps/router/router

# ---------------------------------------------------------------------------
# Stage 2: minimal runtime image
# ---------------------------------------------------------------------------
FROM debian:bookworm-slim@${DEBIAN_DIGEST} AS runtime

RUN --mount=type=tmpfs,target=/tmp \
    apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      libconfig9 \
      python3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=bacnet-stack-router-build /src/bacnet-stack/apps/router/router /usr/local/bin/bacnet-router
COPY --from=bacnet-stack-router-build /src/bacnet-stack/apps/router/readme.txt /usr/local/share/bacnet-stack-router/readme.txt
COPY adapters/bacnet-stack-router/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY adapters/bacnet-stack-router/run_router.py /usr/local/bin/run_router.py

RUN chmod 755 /usr/local/bin/entrypoint.sh /usr/local/bin/bacnet-router /usr/local/bin/run_router.py

ARG ADAPTER_VERSION=dev
ARG BACNET_STACK_VERSION=bacnet-stack-1.6.1
ENV ADAPTER_VERSION=${ADAPTER_VERSION} \
    BACNET_IP_PORT=47808 \
    BACNET_NETWORKS=1,2 \
    BACNET_STACK_VERSION=${BACNET_STACK_VERSION} \
    PYTHONUNBUFFERED=1

# SO_BINDTODEVICE needs CAP_NET_RAW: run as root (Docker's default capability
# set includes it). Topology fixture only; not a production image.
USER root
EXPOSE 47808/udp

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
