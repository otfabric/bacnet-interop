# bacnet-interop adapter for ulbios/bacnet (device and client mode).
#
# Build from the repository root:
#   docker buildx build --platform=linux/amd64 \
#       -f adapters/ulbios/Dockerfile \
#       -t bacnet-interop-ulbios:local .
#
# github.com/ulbios/bacnet is an MIT Go module with no tags or releases; it is
# pinned by commit as a Go pseudo-version in adapters/ulbios/go.mod (with
# go.sum), the source of truth; the ULBIOS_COMMIT ARG below and versions.yaml
# repeat it and scripts/check-versions.py cross-checks them. The binary links
# no other module (its go.mod also names cobra, pflag, mousetrap and go-cmp,
# used only by its examples and tests). The licence of every linked module
# is copied to /licenses. No library under test may import this adapter module.

ARG GOLANG_DIGEST=sha256:23ce71337b726608afb1bc00986e630a05034a87a87ea1fc2cd1ae5cf33387eb
ARG DEBIAN_DIGEST=sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818

FROM golang:1.26-bookworm@${GOLANG_DIGEST} AS build

# The release pin (a commit of the default branch). "make candidate-ulbios
# CANDIDATE_VERSION=<any> CANDIDATE_SHA=<commit>" overrides it to try another
# commit without touching the pin.
ARG ULBIOS_COMMIT=227d62272ce9cedcfe47c1621a8cb4e0d2470ee0
ARG ADAPTER_VERSION=dev

ENV CGO_ENABLED=0 GOFLAGS=-mod=mod GOTOOLCHAIN=local
WORKDIR /src
COPY adapters/ulbios/go.mod adapters/ulbios/go.sum ./

# At the pin the module must match go.sum; any other commit is a candidate.
RUN pinned="$(go list -m -f '{{.Version}}' github.com/ulbios/bacnet)"; \
    case "${pinned}" in \
      *-"$(printf '%.12s' "${ULBIOS_COMMIT}")") GOFLAGS=-mod=readonly go mod download && go mod verify ;; \
      *) go get "github.com/ulbios/bacnet@${ULBIOS_COMMIT}" ;; \
    esac

COPY adapters/ulbios/*.go ./
RUN test -z "$(gofmt -l .)" \
    && go vet ./... \
    && go test ./... \
    && go build -trimpath -ldflags "-s -w \
         -X main.adapterVersion=${ADAPTER_VERSION} \
         -X main.ulbiosVersion=$(go list -m -f '{{.Version}}' github.com/ulbios/bacnet)" \
         -o /out/ulbios . \
    && for m in $(go list -deps -f '{{with .Module}}{{if not .Main}}{{.Path}}{{end}}{{end}}' . | sort -u); do \
         dir="$(go list -m -f '{{.Dir}}' "$m")" && mkdir -p "/out/licenses/$m" \
         && cp "$dir"/LICENSE* "/out/licenses/$m/" 2>/dev/null; \
         ls "/out/licenses/$m" | grep -q . || { echo "no licence in $m"; exit 1; }; \
       done

FROM debian:bookworm-slim@${DEBIAN_DIGEST} AS runtime

ARG ADAPTER_VERSION=dev

RUN addgroup --system --gid 10001 adapter \
    && adduser --system --uid 10001 --ingroup adapter --no-create-home adapter

ENV ADAPTER_VERSION=${ADAPTER_VERSION} \
    FIXTURE=device-baseline-v2 \
    DEVICE_FIXTURE_FILE=/fixtures/device/device-baseline-v2.json \
    BACNET_IP_PORT=47808

COPY --from=build /out/ulbios /usr/local/bin/ulbios
COPY --from=build /out/licenses /licenses
COPY LICENSE /licenses/bacnet-interop/LICENSE
COPY THIRD_PARTY_NOTICES.md /licenses/THIRD_PARTY_NOTICES.md
COPY fixtures/device /fixtures/device
COPY fixtures/scenarios/ /scenarios/

LABEL org.opencontainers.image.title="bacnet-interop-ulbios" \
      org.opencontainers.image.description="BACnet/IP device and client peer built on ulbios/bacnet" \
      org.opencontainers.image.source="https://github.com/otfabric/bacnet-interop" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${ADAPTER_VERSION}"

USER adapter
EXPOSE 47808/udp

ENTRYPOINT ["/usr/local/bin/ulbios"]
CMD []
