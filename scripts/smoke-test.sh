#!/usr/bin/env bash
# smoke-test.sh — adapter self-tests for bacnet-interop.
#
# Verifies that each device-server image:
#   1. Starts without error.
#   2. Emits a valid JSON ready event on stdout/logs.
#   3. Ready event contains event/address/fixture/adapter/version.
#
# Usage:
#   BACNET_STACK_IMAGE=bacnet-interop-bacnet-stack:local \
#   BACPYPES3_IMAGE=bacnet-interop-bacpypes3:local \
#   ./scripts/smoke-test.sh

set -euo pipefail

BACNET_STACK_IMAGE="${BACNET_STACK_IMAGE:-bacnet-interop-bacnet-stack:local}"
BACPYPES3_IMAGE="${BACPYPES3_IMAGE:-bacnet-interop-bacpypes3:local}"
BACNET4J_IMAGE="${BACNET4J_IMAGE:-bacnet-interop-bacnet4j:local}"
BIP_ROUTER_IMAGE="${BIP_ROUTER_IMAGE:-bacnet-interop-bip-router:local}"

PASS=0
FAIL=0

if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RESET='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; RESET=''
fi

pass() { echo -e "${GREEN}PASS${RESET} $*"; PASS=$((PASS + 1)); }
fail() { echo -e "${RED}FAIL${RESET} $*"; FAIL=$((FAIL + 1)); }
info() { echo -e "${YELLOW}INFO${RESET} $*"; }

start_server() {
    local image="$1" host_port="$2"
    shift 2

    local cid
    # Extra args (e.g. -e BACNET_BBMD=1) are docker run options before the image.
    cid=$(docker run -d \
        -p "${host_port}:47808/udp" \
        "$@" \
        "${image}"
    )

    local ready=""
    local deadline=$((SECONDS + 45))
    while [ $SECONDS -lt $deadline ]; do
        ready=$(docker logs "$cid" 2>/dev/null | grep '"event":"ready"' | head -1 || true)
        [ -n "$ready" ] && break
        # Also check combined streams — some runtimes mix stdout into logs.
        ready=$(docker logs "$cid" 2>&1 | grep '"event":"ready"' | head -1 || true)
        [ -n "$ready" ] && break
        if ! docker inspect -f '{{.State.Running}}' "$cid" 2>/dev/null | grep -q true; then
            echo "container exited early:" >&2
            docker logs "$cid" >&2 || true
            break
        fi
        sleep 0.2
    done

    docker stop -t 2 "$cid" >/dev/null 2>&1 || true
    docker rm "$cid" >/dev/null 2>&1 || true

    printf '%s' "$ready"
}

start_bip_router_smoke() {
    local image="$1"
    local net_a="smoke-bip-a-$$"
    local net_b="smoke-bip-b-$$"
    local name="smoke-bip-router-$$"

    docker network create "$net_a" >/dev/null
    docker network create "$net_b" >/dev/null
    docker create --name "$name" --network "$net_a" \
        -e ADAPTER_VERSION=smoke \
        -e BACNET_NETWORKS=1,2 \
        "$image" >/dev/null
    docker network connect "$net_b" "$name"
    docker start "$name" >/dev/null

    local ready=""
    local deadline=$((SECONDS + 45))
    while [ $SECONDS -lt $deadline ]; do
        ready=$(docker logs "$name" 2>&1 | grep '"event":"ready"' | head -1 || true)
        [ -n "$ready" ] && break
        if ! docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null | grep -q true; then
            echo "bip-router exited early:" >&2
            docker logs "$name" >&2 || true
            break
        fi
        sleep 0.2
    done

    docker stop -t 2 "$name" >/dev/null 2>&1 || true
    docker rm "$name" >/dev/null 2>&1 || true
    docker network rm "$net_a" "$net_b" >/dev/null 2>&1 || true

    printf '%s' "$ready"
}

check_ready_event() {
    local label="$1" ready="$2" want_adapter="$3" want_fixture="$4"

    if [ -z "$ready" ]; then
        fail "${label}: no ready event received within timeout"
        return
    fi

    if ! echo "$ready" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
        fail "${label}: ready event is not valid JSON: ${ready}"
        return
    fi

    local missing=()
    for field in event address fixture adapter version; do
        value=$(echo "$ready" | python3 -c \
            "import sys,json; d=json.load(sys.stdin); print(d.get('${field}',''))" 2>/dev/null)
        [ -z "$value" ] && missing+=("$field")
    done
    # peer_version is optional until all images rebuild; warn only.
    peer_version=$(echo "$ready" | python3 -c \
        "import sys,json; print(json.load(sys.stdin).get('peer_version',''))" 2>/dev/null || true)
    if [ -z "$peer_version" ]; then
        info "${label}: ready event has no peer_version (optional)"
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        fail "${label}: ready event missing fields: ${missing[*]}"
        fail "  got: ${ready}"
        return
    fi

    local event adapter fixture
    event=$(echo "$ready" | python3 -c "import sys,json; print(json.load(sys.stdin)['event'])")
    adapter=$(echo "$ready" | python3 -c "import sys,json; print(json.load(sys.stdin)['adapter'])")
    fixture=$(echo "$ready" | python3 -c "import sys,json; print(json.load(sys.stdin)['fixture'])")

    if [ "$event" != "ready" ]; then
        fail "${label}: event=${event}, want ready"
        return
    fi
    if [ "$adapter" != "$want_adapter" ]; then
        fail "${label}: adapter=${adapter}, want ${want_adapter}"
        return
    fi
    if [ "$fixture" != "$want_fixture" ]; then
        fail "${label}: fixture=${fixture}, want ${want_fixture}"
        return
    fi

    pass "${label}: ready event OK — adapter=${adapter}, fixture=${fixture}"
}

check_binary() {
    local image="$1" bin="$2"
    if docker run --rm --entrypoint sh "${image}" -c "command -v ${bin}" >/dev/null 2>&1; then
        pass "binary ${bin} in ${image}"
    else
        fail "binary ${bin} MISSING in ${image}"
    fi
}

check_fixture_file() {
    local image="$1" path="$2"
    if docker run --rm --entrypoint sh "${image}" -c "test -f ${path}" >/dev/null 2>&1; then
        pass "fixture ${path} in ${image}"
    else
        fail "fixture ${path} MISSING in ${image}"
    fi
}

image_exists() {
    docker image inspect "$1" >/dev/null 2>&1
}

# ===========================================================================
info "=== Images ==="
if image_exists "$BACNET_STACK_IMAGE"; then
    pass "image present: ${BACNET_STACK_IMAGE}"
else
    fail "image missing: ${BACNET_STACK_IMAGE}"
fi
if image_exists "$BACPYPES3_IMAGE"; then
    pass "image present: ${BACPYPES3_IMAGE}"
else
    fail "image missing: ${BACPYPES3_IMAGE}"
fi
if image_exists "$BACNET4J_IMAGE"; then
    pass "image present: ${BACNET4J_IMAGE}"
else
    fail "image missing: ${BACNET4J_IMAGE}"
fi

if image_exists "$BACNET_STACK_IMAGE"; then
    info ""
    info "=== bacnet-stack ==="
    check_binary "$BACNET_STACK_IMAGE" device_server
    if docker run --rm --entrypoint sh "$BACNET_STACK_IMAGE" -c "test -f /usr/local/bin/run_server.py" >/dev/null 2>&1; then
        pass "run_server.py in ${BACNET_STACK_IMAGE}"
    else
        fail "run_server.py MISSING in ${BACNET_STACK_IMAGE}"
    fi
    check_fixture_file "$BACNET_STACK_IMAGE" /fixtures/device/device-baseline-v2.json
    ready=$(start_server "$BACNET_STACK_IMAGE" 47881)
    check_ready_event "bacnet-stack device server" "$ready" "bacnet-stack" "device-baseline-v2"
fi

if image_exists "$BACPYPES3_IMAGE"; then
    info ""
    info "=== BACpypes3 ==="
    check_fixture_file "$BACPYPES3_IMAGE" /fixtures/device/device-baseline-v2.json
    if docker run --rm --entrypoint sh "$BACPYPES3_IMAGE" -c "test -f /usr/local/bin/device_server.py" >/dev/null 2>&1; then
        pass "device_server.py in ${BACPYPES3_IMAGE}"
    else
        fail "device_server.py MISSING in ${BACPYPES3_IMAGE}"
    fi
    ready=$(start_server "$BACPYPES3_IMAGE" 47882)
    check_ready_event "bacpypes3 device server" "$ready" "bacpypes3" "device-baseline-v2"
    ready=$(start_server "$BACPYPES3_IMAGE" 47883 -e BACNET_BBMD=1)
    check_ready_event "bacpypes3 BBMD device server" "$ready" "bacpypes3" "device-baseline-v2"
fi

if image_exists "$BACNET4J_IMAGE"; then
    info ""
    info "=== BACnet4J ==="
    check_fixture_file "$BACNET4J_IMAGE" /fixtures/device/device-baseline-v2.json
    if docker run --rm --entrypoint sh "$BACNET4J_IMAGE" -c "test -f /usr/local/lib/device_server.jar" >/dev/null 2>&1; then
        pass "device_server.jar in ${BACNET4J_IMAGE}"
    else
        fail "device_server.jar MISSING in ${BACNET4J_IMAGE}"
    fi
    ready=$(start_server "$BACNET4J_IMAGE" 47884)
    check_ready_event "bacnet4j device server" "$ready" "bacnet4j" "device-baseline-v2"
    ready=$(start_server "$BACNET4J_IMAGE" 47885 -e BACNET_BBMD=1)
    check_ready_event "bacnet4j BBMD device server" "$ready" "bacnet4j" "device-baseline-v2"
fi

if image_exists "$BIP_ROUTER_IMAGE"; then
    info ""
    info "=== bip-router ==="
    if docker run --rm --entrypoint sh "$BIP_ROUTER_IMAGE" -c "test -f /usr/local/bin/bip_router.py" >/dev/null 2>&1; then
        pass "bip_router.py in ${BIP_ROUTER_IMAGE}"
    else
        fail "bip_router.py MISSING in ${BIP_ROUTER_IMAGE}"
    fi
    ready=$(start_bip_router_smoke "$BIP_ROUTER_IMAGE")
    check_ready_event "bip-router" "$ready" "bip-router" "topology-router-v1"
elif [ "${BIP_ROUTER_REQUIRED:-}" != "" ]; then
    fail "image missing: ${BIP_ROUTER_IMAGE}"
else
    info "bip-router image absent; skipping topology router smoke (build with make build-bip-router)"
fi

echo ""
echo -e "Results: ${GREEN}${PASS} passed${RESET}  ${RED}${FAIL} failed${RESET}"
[ "$FAIL" -eq 0 ]
