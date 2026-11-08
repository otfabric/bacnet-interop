# bacnet-interop adapter for @bacnet-js/client (bacnet-js): device mode and
# client mode.
#
# Build from the repository root:
#   docker buildx build --platform=linux/amd64 \
#       -f adapters/bacnet-js/Dockerfile \
#       -t bacnet-interop-bacnet-js:local .
#
# @bacnet-js/client (MIT) and its runtime dependencies debug, ms, iconv-lite
# and safer-buffer (all MIT) are installed from the npm registry with
# package-lock.json (versions and integrity hashes) and their licences are
# copied to /licenses. The pin is adapters/bacnet-js/package.json with
# package-lock.json; BACNETJS_VERSION repeats it. No install scripts run.

ARG NODE_DIGEST=sha256:01d566e8d94d8c619591d78652babfccd3c6992a3dffa9ed5ab39e11cf6c70e9

FROM node:24.22.2-bookworm-slim@${NODE_DIGEST} AS build

# The release pin. "make candidate-bacnet-js CANDIDATE_VERSION=X.Y.Z" passes
# another version: it is installed over the lock without changing it.
ARG BACNETJS_VERSION=3.3.2

WORKDIR /opt/adapter
COPY adapters/bacnet-js/package.json adapters/bacnet-js/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund \
    && if [ "$(node -p 'require("@bacnet-js/client/package.json").version')" != "${BACNETJS_VERSION}" ]; then \
         npm install --no-save --omit=dev --ignore-scripts --no-audit --no-fund "@bacnet-js/client@${BACNETJS_VERSION}"; \
       fi \
    && test "$(node -p 'require("@bacnet-js/client/package.json").version')" = "${BACNETJS_VERSION}"

COPY adapters/bacnet-js/*.js adapters/bacnet-js/entrypoint.sh ./
COPY fixtures/device /fixtures/device
# The adapter's unit tests, then the licence of every installed package
# (npm ls lists the installed tree; the first line is the adapter itself).
RUN FIXTURES_DIR=/fixtures/device node --test adapter.test.js \
    && rm adapter.test.js \
    && npm ls --omit=dev --all --parseable | tail -n +2 | while read -r d; do \
         n="${d#/opt/adapter/node_modules/}"; mkdir -p "/out/licenses/${n}" \
         && cp "${d}"/LICENSE* "${d}"/license* "/out/licenses/${n}/" 2>/dev/null; \
         ls "/out/licenses/${n}" | grep -q . || { echo "no licence in ${n}"; exit 1; }; \
       done

FROM node:24.22.2-bookworm-slim@${NODE_DIGEST} AS runtime

ARG ADAPTER_VERSION=dev

RUN groupadd --system --gid 10001 adapter \
    && useradd --system --uid 10001 --gid adapter --no-create-home --shell /usr/sbin/nologin adapter

ENV ADAPTER_VERSION=${ADAPTER_VERSION} \
    FIXTURE=device-baseline-v2 \
    DEVICE_FIXTURE_FILE=/fixtures/device/device-baseline-v2.json \
    BACNET_IP_PORT=47808 \
    NODE_ENV=production \
    TZ=UTC

COPY --from=build /opt/adapter /opt/adapter
COPY --from=build /out/licenses /licenses
COPY LICENSE /licenses/bacnet-interop/LICENSE
COPY THIRD_PARTY_NOTICES.md /licenses/THIRD_PARTY_NOTICES.md
COPY fixtures/device /fixtures/device
# Client mode (docs/CLIENT_DRIVER_CONTRACT.md): the published scenario files.
COPY fixtures/scenarios /scenarios

LABEL org.opencontainers.image.title="bacnet-interop-bacnet-js" \
      org.opencontainers.image.description="BACnet/IP device and client peer built on @bacnet-js/client" \
      org.opencontainers.image.source="https://github.com/otfabric/bacnet-interop" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${ADAPTER_VERSION}"

USER adapter
EXPOSE 47808/udp

# "client" as the first argument selects client mode; device mode is the
# default.
ENTRYPOINT ["/opt/adapter/entrypoint.sh"]
CMD []
