# bacnet-interop System.IO.BACnet adapter (fixture-driven device server).
#
# Build from repository root:
#   docker buildx build \
#       -f adapters/sysiobacnet/Dockerfile \
#       -t bacnet-interop-sysiobacnet:local .
#
# Upstream: https://github.com/ela-compil/BACnet (NuGet package id "BACnet",
# MIT). Nothing of it is vendored: the package is restored from nuget.org at
# build time at the exact version below. go-bacnet never links against it.

# mcr.microsoft.com/dotnet/sdk:10.0 and runtime:10.0 (multi-arch index digests).
ARG DOTNET_SDK_DIGEST=sha256:e70cdb7f80b0348f5cb85f19a8f670fca061f033d57eed12fa003d58b0e06317
ARG DOTNET_RUNTIME_DIGEST=sha256:b89586dc17781f25531909993658aa8161205ae38b8cec8847df4a8221a403d5

# The adapter is portable IL, so it is compiled once on the build platform and
# runs on the target platform's runtime image.
FROM --platform=$BUILDPLATFORM mcr.microsoft.com/dotnet/sdk:10.0@${DOTNET_SDK_DIGEST} AS build

ARG SYSIOBACNET_VERSION=4.0.0

ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    NUGET_XMLDOC_MODE=skip

WORKDIR /src
COPY adapters/sysiobacnet/nuget.config adapters/sysiobacnet/DeviceServer.csproj /src/
RUN dotnet restore DeviceServer.csproj -p:SysIoBacnetVersion=${SYSIOBACNET_VERSION}

COPY adapters/sysiobacnet/src /src/src
RUN dotnet publish DeviceServer.csproj -c Release --no-restore \
      -p:SysIoBacnetVersion=${SYSIOBACNET_VERSION} \
      -p:UseAppHost=false \
      -o /out \
    && test -f /out/BACnet.dll

FROM mcr.microsoft.com/dotnet/runtime:10.0@${DOTNET_RUNTIME_DIGEST} AS runtime

ARG ADAPTER_VERSION=dev
ARG SYSIOBACNET_VERSION=4.0.0

RUN groupadd --system --gid 10001 adapter \
    && useradd --system --uid 10001 --gid adapter --no-create-home --shell /usr/sbin/nologin adapter

ENV ADAPTER_VERSION=${ADAPTER_VERSION} \
    SYSIOBACNET_VERSION=${SYSIOBACNET_VERSION} \
    FIXTURE=device-baseline-v2 \
    DEVICE_FIXTURE_FILE=/fixtures/device/device-baseline-v2.json \
    BACNET_IP_PORT=47808 \
    DOTNET_EnableDiagnostics=0

COPY --from=build /out /usr/local/lib/sysiobacnet
COPY fixtures/device/device-baseline-v1.json /fixtures/device/device-baseline-v1.json
COPY fixtures/device/device-baseline-v2.json /fixtures/device/device-baseline-v2.json
COPY fixtures/device/device-baseline-v3.json /fixtures/device/device-baseline-v3.json
COPY fixtures/device/device-baseline-v4.json /fixtures/device/device-baseline-v4.json
COPY fixtures/device/device-baseline-v5.json /fixtures/device/device-baseline-v5.json
COPY fixtures/device/device-baseline-v6.json /fixtures/device/device-baseline-v6.json
COPY fixtures/device/device-baseline-v7.json /fixtures/device/device-baseline-v7.json
COPY fixtures/device/device-baseline-v8.json /fixtures/device/device-baseline-v8.json

USER adapter
EXPOSE 47808/udp

ENTRYPOINT ["dotnet", "/usr/local/lib/sysiobacnet/device_server.dll"]
CMD []
