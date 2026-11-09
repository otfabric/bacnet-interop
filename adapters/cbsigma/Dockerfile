# bacnet-interop adapter for cB-Sigma/bacnet (device role) and
# cB-Sigma/bacnet-sim (simulated device).
#
# Build from the repository root:
#   docker buildx build --platform=linux/amd64 \
#       -f adapters/cbsigma/Dockerfile \
#       -t bacnet-interop-cbsigma:local .
#
# Both upstreams are Apache-2.0 Go modules; bacnet also links
# cB-Sigma/tlsx (Apache-2.0), coder/websocket (ISC) and golang.org/x/crypto
# and x/sys (BSD-3-Clause). The binary links them statically; the licence
# and NOTICE of every linked module are copied to /licenses. The pins are
# the ARGs below, adapters/cbsigma/go.mod (with go.sum) and versions.yaml.
# The modules need Go 1.27.1 or later. No library under test may import
# this adapter module.

ARG GOLANG_DIGEST=sha256:e58d6f83b3416618d8bcac2b3dde1b7f7e3c4a77d25e88637f8bbae81536c48d
ARG DEBIAN_DIGEST=sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818

FROM golang:1.27.2-trixie@${GOLANG_DIGEST} AS build

# The release pins (tags). "make candidate-cbsigma" / "candidate-cbsigma-sim"
# override one to try another upstream tag without touching the pin.
ARG BACNET_VERSION=v0.2.0
ARG BACNET_SIM_VERSION=v0.1.0
ARG ADAPTER_VERSION=dev

ENV CGO_ENABLED=0 GOFLAGS=-mod=mod
WORKDIR /src
COPY adapters/cbsigma/go.mod adapters/cbsigma/go.sum ./

# At the pins the modules must match go.sum; anything else is a candidate.
RUN if [ "$(go list -m -f '{{.Version}}' github.com/cB-Sigma/bacnet)" = "${BACNET_VERSION}" ] \
       && [ "$(go list -m -f '{{.Version}}' github.com/cB-Sigma/bacnet-sim)" = "${BACNET_SIM_VERSION}" ]; then \
         GOFLAGS=-mod=readonly go mod download && go mod verify; \
       else \
         go get "github.com/cB-Sigma/bacnet@${BACNET_VERSION}" "github.com/cB-Sigma/bacnet-sim@${BACNET_SIM_VERSION}"; \
       fi

COPY adapters/cbsigma/*.go ./
RUN test -z "$(gofmt -l .)" \
    && go vet ./... \
    && go test ./... \
    && go build -trimpath -ldflags "-s -w \
         -X main.adapterVersion=${ADAPTER_VERSION} \
         -X main.bacnetVersion=$(go list -m -f '{{.Version}}' github.com/cB-Sigma/bacnet) \
         -X main.simVersion=$(go list -m -f '{{.Version}}' github.com/cB-Sigma/bacnet-sim)" \
         -o /out/device_server . \
    && for m in $(go list -deps -f '{{with .Module}}{{if not .Main}}{{.Path}}{{end}}{{end}}' . | sort -u); do \
         dir="$(go list -m -f '{{.Dir}}' "$m")" && mkdir -p "/out/licenses/$m" \
         && cp "$dir"/LICENSE* "$dir"/NOTICE* "/out/licenses/$m/" 2>/dev/null; \
         ls "/out/licenses/$m" | grep -q . || { echo "no licence in $m"; exit 1; }; \
       done

FROM debian:bookworm-slim@${DEBIAN_DIGEST} AS runtime

ARG ADAPTER_VERSION=dev

RUN addgroup --system --gid 10001 adapter \
    && adduser --system --uid 10001 --ingroup adapter --no-create-home adapter

ENV ADAPTER_VERSION=${ADAPTER_VERSION} \
    FIXTURE=device-baseline-v2 \
    DEVICE_FIXTURE_FILE=/fixtures/device/device-baseline-v2.json \
    BACNET_IP_PORT=47808 \
    CBSIGMA_ROLE=device

COPY --from=build /out/device_server /usr/local/bin/device_server
COPY --from=build /out/licenses /licenses
COPY LICENSE /licenses/bacnet-interop/LICENSE
COPY THIRD_PARTY_NOTICES.md /licenses/THIRD_PARTY_NOTICES.md
COPY fixtures/device /fixtures/device

LABEL org.opencontainers.image.title="bacnet-interop-cbsigma" \
      org.opencontainers.image.description="BACnet/IP device peer built on cB-Sigma/bacnet (device role) and cB-Sigma/bacnet-sim (simulated device)" \
      org.opencontainers.image.source="https://github.com/otfabric/bacnet-interop" \
      org.opencontainers.image.licenses="MIT AND Apache-2.0" \
      org.opencontainers.image.version="${ADAPTER_VERSION}"

USER adapter
EXPOSE 47808/udp

ENTRYPOINT ["/usr/local/bin/device_server"]
CMD []
