# bacnet-interop BACnet4J adapter (fixture-driven device server).
#
# Build from repository root:
#   docker buildx build \
#       -f adapters/bacnet4j/Dockerfile \
#       -t bacnet-interop-bacnet4j:local .
#
# Peer code retains its upstream license inside the image. go-bacnet must
# never link against BACnet4J.

ARG TEMURIN_JDK_DIGEST=sha256:723151f3fc88ca2060153ee08ab8dbbea7983d6ed6f2622fe440acf178737c94
ARG TEMURIN_JRE_DIGEST=sha256:475d8e96b4b2bfe08999e5e854755c773af1581acdf959a4545d88f0696a2339

FROM eclipse-temurin:17-jdk-jammy@${TEMURIN_JDK_DIGEST} AS build

ARG BACNET4J_VERSION=6.1.0

RUN apt-get update && apt-get install -y --no-install-recommends maven \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY adapters/bacnet4j/pom.xml /src/pom.xml
COPY adapters/bacnet4j/src /src/src

RUN mvn -q -DskipTests -Dbacnet4j.version=${BACNET4J_VERSION} package \
    && cp target/bacnet4j-adapter-*.jar /tmp/device_server.jar

FROM eclipse-temurin:17-jre-jammy@${TEMURIN_JRE_DIGEST} AS runtime

ARG ADAPTER_VERSION=dev
ARG BACNET4J_VERSION=6.1.0

RUN addgroup --system --gid 10001 adapter \
    && adduser --system --uid 10001 --ingroup adapter --no-create-home adapter

ENV ADAPTER_VERSION=${ADAPTER_VERSION} \
    BACNET4J_VERSION=${BACNET4J_VERSION} \
    FIXTURE=device-baseline-v1 \
    DEVICE_FIXTURE_FILE=/fixtures/device/device-baseline-v1.json \
    BACNET_IP_PORT=47808 \
    JAVA_TOOL_OPTIONS="-Dorg.slf4j.simpleLogger.defaultLogLevel=warn"

COPY --from=build /tmp/device_server.jar /usr/local/lib/device_server.jar
COPY fixtures/device/device-baseline-v1.json /fixtures/device/device-baseline-v1.json

USER adapter
EXPOSE 47808/udp

ENTRYPOINT ["java", "-jar", "/usr/local/lib/device_server.jar"]
CMD []
