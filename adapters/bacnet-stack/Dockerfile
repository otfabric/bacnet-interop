# bacnet-interop bacnet-stack adapter (fixture-driven device server).
#
# Build from repository root:
#   docker buildx build \
#       -f adapters/bacnet-stack/Dockerfile \
#       -t bacnet-interop-bacnet-stack:local .
#
# Peer code retains its upstream license inside the image. go-bacnet must
# never link against bacnet-stack.

ARG DEBIAN_DIGEST=sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818

# ---------------------------------------------------------------------------
# Stage 1: build fixture-driven device_server against pinned bacnet-stack
# ---------------------------------------------------------------------------
FROM debian:bookworm-slim@${DEBIAN_DIGEST} AS bacnet-stack-build

ARG BACNET_STACK_REPO=https://github.com/bacnet-stack/bacnet-stack.git
# Tag bacnet-stack-1.6.0 (latest official release tag)
ARG BACNET_STACK_SHA=9bc3cfa07aab98852de432fa24079f4b4b6b7eed
ARG BACNET_STACK_VERSION=bacnet-stack-1.6.0

# tmpfs /tmp: Docker Desktop's default /tmp breaks apt-key/gpgv status-fd
# ("At least one invalid signature was encountered" despite good InRelease).
RUN --mount=type=tmpfs,target=/tmp \
    apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      gcc \
      git \
      libc6-dev \
      make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --filter=blob:none "${BACNET_STACK_REPO}" bacnet-stack \
    && cd bacnet-stack \
    && git checkout --detach "${BACNET_STACK_SHA}" \
    && test "$(git rev-parse HEAD)" = "${BACNET_STACK_SHA}"

COPY adapters/bacnet-stack/device_server.c /src/adapter/device_server.c
COPY adapters/bacnet-stack/Makefile /src/adapter/Makefile

RUN make -C /src/adapter BACNET_STACK_ROOT=/src/bacnet-stack \
    && test -x /src/adapter/device_server

# ---------------------------------------------------------------------------
# Stage 2: minimal runtime image
# ---------------------------------------------------------------------------
FROM debian:bookworm-slim@${DEBIAN_DIGEST} AS runtime

RUN --mount=type=tmpfs,target=/tmp \
    apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      python3 \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system --gid 10001 adapter \
    && adduser --system --uid 10001 --ingroup adapter --no-create-home adapter

COPY --from=bacnet-stack-build /src/adapter/device_server /usr/local/bin/device_server
COPY adapters/bacnet-stack/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY adapters/bacnet-stack/run_server.py /usr/local/bin/run_server.py
COPY fixtures/device/device-baseline-v1.json /fixtures/device/device-baseline-v1.json
COPY fixtures/device/device-baseline-v2.json /fixtures/device/device-baseline-v2.json

RUN chmod 755 /usr/local/bin/entrypoint.sh /usr/local/bin/device_server /usr/local/bin/run_server.py

ARG ADAPTER_VERSION=dev
ARG BACNET_STACK_VERSION=bacnet-stack-1.6.0
ENV ADAPTER_VERSION=${ADAPTER_VERSION} \
    FIXTURE=device-baseline-v2 \
    DEVICE_FIXTURE_FILE=/fixtures/device/device-baseline-v2.json \
    BACNET_IP_PORT=47808 \
    BACNET_STACK_VERSION=${BACNET_STACK_VERSION}

USER adapter
EXPOSE 47808/udp

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
