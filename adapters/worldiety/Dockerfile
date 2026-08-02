# bacnet-interop Worldiety adapter (fixture-driven device server).
#
# Build from repository root:
#   docker buildx build --platform=linux/amd64 \
#       -f adapters/worldiety/Dockerfile \
#       -t bacnet-interop-worldiety:local .
#
# Peer code retains its upstream license inside the image. go-bacnet must
# never link against or import this adapter module.

ARG DEBIAN_DIGEST=sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818

# Pin Worldiety exact commit (plan: 3cb2aa80efbb8a489abb9978c7f6e5dc603535a7).
ARG WORLDIETY_COMMIT=3cb2aa80efbb8a489abb9978c7f6e5dc603535a7
ARG ADAPTER_VERSION=dev

FROM golang:1.26-bookworm AS build

ARG WORLDIETY_COMMIT
ARG ADAPTER_VERSION

WORKDIR /src
COPY adapters/worldiety/go.mod adapters/worldiety/go.sum ./
RUN go mod download

COPY adapters/worldiety/ ./
ENV CGO_ENABLED=0
RUN go build -trimpath -ldflags="-s -w" -o /out/device_server ./cmd/device-server

FROM debian:bookworm-slim@${DEBIAN_DIGEST} AS runtime

ARG ADAPTER_VERSION
ARG WORLDIETY_COMMIT

# tmpfs /tmp: Docker Desktop's default /tmp breaks apt-key/gpgv status-fd.
RUN --mount=type=tmpfs,target=/tmp \
    apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system --gid 10001 adapter \
    && adduser --system --uid 10001 --ingroup adapter --no-create-home adapter

ENV ADAPTER_VERSION=${ADAPTER_VERSION} \
    WORLDIETY_COMMIT=${WORLDIETY_COMMIT} \
    FIXTURE=device-baseline-v2 \
    DEVICE_FIXTURE_FILE=/fixtures/device/device-baseline-v2.json \
    BACNET_IP_PORT=47808

COPY --from=build /out/device_server /usr/local/bin/device_server
COPY fixtures/device/device-baseline-v1.json /fixtures/device/device-baseline-v1.json
COPY fixtures/device/device-baseline-v2.json /fixtures/device/device-baseline-v2.json
COPY fixtures/device/device-baseline-v3.json /fixtures/device/device-baseline-v3.json
COPY fixtures/device/device-baseline-v4.json /fixtures/device/device-baseline-v4.json
COPY fixtures/device/device-baseline-v5.json /fixtures/device/device-baseline-v5.json
COPY fixtures/device/device-baseline-v6.json /fixtures/device/device-baseline-v6.json
COPY fixtures/device/device-baseline-v7.json /fixtures/device/device-baseline-v7.json
COPY fixtures/device/device-baseline-v8.json /fixtures/device/device-baseline-v8.json

RUN chmod 755 /usr/local/bin/device_server

USER adapter
EXPOSE 47808/udp

ENTRYPOINT ["/usr/local/bin/device_server"]
CMD []
