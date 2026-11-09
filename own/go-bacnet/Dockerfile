# SPDX-License-Identifier: MIT
#
# bacnet-interop-otfabric: OT Fabric's own BACnet/IP stack, go-bacnet, behind
# the container contract (device and client mode). Not an independent
# implementation: see README.md.
#
# Build from the repository root:
#   make -f own/go-bacnet/Makefile image
#
# The build takes the go-bacnet release as UPSTREAM_VERSION (the released git
# tag, which is the Go module version) and its commit as UPSTREAM_SHA. There
# is no pin in this repository: the workflow passes the latest release. A
# build never uses main. go.mod and go.sum here are only a starting point for
# local work.

# golang:1.26-bookworm and debian:bookworm-slim, the digests the adapters use
# (versions.yaml base_images), multi-arch indexes (linux/amd64, linux/arm64).
ARG GOLANG_DIGEST=sha256:23ce71337b726608afb1bc00986e630a05034a87a87ea1fc2cd1ae5cf33387eb
ARG DEBIAN_DIGEST=sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818

FROM golang:1.26-bookworm@${GOLANG_DIGEST} AS build

ARG UPSTREAM_VERSION
ARG UPSTREAM_SHA
ARG ADAPTER_VERSION=dev
ARG GOPROXY=https://proxy.golang.org

ENV CGO_ENABLED=0 GOPROXY=${GOPROXY} GOSUMDB=sum.golang.org GOTOOLCHAIN=local GOFLAGS=-mod=mod
WORKDIR /src
COPY own/go-bacnet/go.mod own/go-bacnet/go.sum own/go-bacnet/*.go ./

RUN set -eu; \
    test -n "${UPSTREAM_VERSION}" || { echo "UPSTREAM_VERSION is required" >&2; exit 1; }; \
    echo "${UPSTREAM_SHA}" | grep -Eq '^[0-9a-f]{40}$' || { echo "UPSTREAM_SHA must be a commit" >&2; exit 1; }; \
    go get "github.com/otfabric/go-bacnet@${UPSTREAM_VERSION}"; \
    go mod tidy; \
    built="$(go list -m -f '{{.Version}}' github.com/otfabric/go-bacnet)"; \
    test "${built}" = "${UPSTREAM_VERSION}" || { echo "go.mod has go-bacnet ${built}, want ${UPSTREAM_VERSION}" >&2; exit 1; }; \
    go mod download && go mod verify; \
    origin="$(go mod download -json "github.com/otfabric/go-bacnet@${UPSTREAM_VERSION}" \
        | sed -nE 's/^[[:space:]]*"Hash": "([0-9a-f]{40})".*/\1/p')"; \
    if [ -n "${origin}" ] && [ "${origin}" != "${UPSTREAM_SHA}" ]; then \
        echo "go-bacnet ${UPSTREAM_VERSION} is commit ${origin}, not ${UPSTREAM_SHA}" >&2; exit 1; \
    fi

# The self-test runs every scenario file against the image's own device over
# loopback UDP, so it needs the fixtures.
COPY fixtures /fixtures-src
RUN set -eu; \
    test -z "$(gofmt -l .)"; \
    go vet ./...; \
    FIXTURES_DIR=/fixtures-src go test -count=1 ./...; \
    go build -trimpath -ldflags "-s -w \
        -X main.adapterVersion=${ADAPTER_VERSION} \
        -X main.upstreamVersion=${UPSTREAM_VERSION} \
        -X main.upstreamRevision=${UPSTREAM_SHA}" \
        -o /out/bacnet-interop .; \
    mkdir -p /out/licenses/go; \
    cp "$(go env GOROOT)/LICENSE" /out/licenses/go/LICENSE; \
    go version -m /out/bacnet-interop | awk '$1 == "dep" { print $2, $3 }' > /out/licenses/BUNDLED-MODULES.txt; \
    test -s /out/licenses/BUNDLED-MODULES.txt; \
    while read -r module modversion; do \
        dir="$(go list -m -f '{{.Dir}}' "${module}")"; \
        mkdir -p "/out/licenses/${module}"; \
        for file in "${dir}"/LICENSE* "${dir}"/LICENCE* "${dir}"/COPYING* "${dir}"/NOTICE*; do \
            if [ -f "${file}" ]; then cp "${file}" "/out/licenses/${module}/"; fi; \
        done; \
        test -n "$(ls "/out/licenses/${module}")" || { echo "no licence file in ${module} ${modversion}" >&2; exit 1; }; \
    done < /out/licenses/BUNDLED-MODULES.txt

FROM debian:bookworm-slim@${DEBIAN_DIGEST} AS runtime

ARG ADAPTER_VERSION=dev
ARG UPSTREAM_VERSION

RUN addgroup --system --gid 10001 adapter \
    && adduser --system --uid 10001 --ingroup adapter --no-create-home adapter

ENV ADAPTER_VERSION=${ADAPTER_VERSION} \
    FIXTURE=device-baseline-v2 \
    DEVICE_FIXTURE_FILE=/fixtures/device/device-baseline-v2.json \
    BACNET_IP_PORT=47808

COPY --from=build /out/bacnet-interop /usr/local/bin/bacnet-interop
COPY --from=build /out/licenses /licenses
COPY LICENSE /licenses/bacnet-interop/LICENSE
COPY fixtures/device /fixtures/device
COPY fixtures/scenarios/ /scenarios/

LABEL org.opencontainers.image.title="bacnet-interop-otfabric" \
      org.opencontainers.image.description="OT Fabric go-bacnet behind the bacnet-interop container contract, for testing. Not an independent implementation." \
      org.opencontainers.image.source="https://github.com/otfabric/bacnet-interop" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${UPSTREAM_VERSION}"

USER adapter
EXPOSE 47808/udp

ENTRYPOINT ["/usr/local/bin/bacnet-interop"]
CMD []
