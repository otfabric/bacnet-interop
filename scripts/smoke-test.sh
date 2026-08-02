#!/usr/bin/env bash
# smoke-test.sh — adapter self-tests for bacnet-interop.
#
# Verifies that each device-server image:
#   1. Starts without error.
#   2. Emits a valid JSON ready event on stdout/logs.
#   3. Ready event contains event/address/fixture/adapter/version.
#   4. (optional) Answers a directed Who-Is with an I-Am (SMOKE_WHOIS=1).
#
# Usage:
#   BACNET_STACK_IMAGE=bacnet-interop-bacnet-stack:local \
#   BACPYPES3_IMAGE=bacnet-interop-bacpypes3:local \
#   ./scripts/smoke-test.sh
#
# Single-adapter / candidate mode:
#   SMOKE_ONLY=bacnet-stack BACNET_STACK_IMAGE=…:candidate ./scripts/smoke-test.sh
#
# Env:
#   SMOKE_ONLY     comma list: bacnet-stack,bacpypes3,bacnet4j,bip-router
#                  (empty = all present images; missing peers fail unless filtered)
#   SMOKE_WHOIS    1 (default) run directed Who-Is→I-Am probe on default-mode peers
#                  0 skip protocol probe
#   BIP_ROUTER_REQUIRED  if set, missing bip-router image is a failure

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WHOIS_PROBE="${SCRIPT_DIR}/whois-probe.py"

BACNET_STACK_IMAGE="${BACNET_STACK_IMAGE:-bacnet-interop-bacnet-stack:local}"
BACPYPES3_IMAGE="${BACPYPES3_IMAGE:-bacnet-interop-bacpypes3:local}"
BACNET4J_IMAGE="${BACNET4J_IMAGE:-bacnet-interop-bacnet4j:local}"
BIP_ROUTER_IMAGE="${BIP_ROUTER_IMAGE:-bacnet-interop-bip-router:local}"
SMOKE_ONLY="${SMOKE_ONLY:-}"
SMOKE_WHOIS="${SMOKE_WHOIS:-1}"

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

want_adapter() {
    local name="$1"
    if [ -z "$SMOKE_ONLY" ]; then
        return 0
    fi
    case ",${SMOKE_ONLY}," in
        *",${name},"*) return 0 ;;
        *) return 1 ;;
    esac
}

image_exists() {
    docker image inspect "$1" >/dev/null 2>&1
}

# Run directed Who-Is→I-Am against peer_ip on $net. Echoes ok|fail|skip.
#
# Peers often answer with a broadcast I-Am to UDP/47808 (not the Who-Is source
# port). The probe therefore runs in a same-network container bound to 47808.
run_whois_probe() {
    local net="$1" peer_ip="$2"
    if [ -z "$peer_ip" ] || [ ! -f "$WHOIS_PROBE" ]; then
        echo "whois-probe skipped (no peer IP or probe script)" >&2
        printf '%s' "skip"
        return
    fi

    if docker run --rm --network "$net" \
        -v "${WHOIS_PROBE}:/whois-probe.py:ro" \
        python:3.12-alpine \
        python /whois-probe.py --host "$peer_ip" --port 47808 --bind-port 47808 --timeout 5 \
        >&2
    then
        echo "whois-probe OK via docker network (${peer_ip}:47808)" >&2
        printf '%s' "ok"
    else
        echo "whois-probe FAILED for ${peer_ip}:47808" >&2
        printf '%s' "fail"
    fi
}

# Start peer on a dedicated Docker network, wait for ready, optional Who-Is,
# then tear down. Prints:
#   <ready JSON line>
#   WHOIS:<ok|fail|skip>
# Diagnostics go to stderr. Callers must parse both lines (command substitution
# runs in a subshell, so globals cannot carry Who-Is status).
start_server() {
    local image="$1" host_port="$2"
    shift 2

    local net="smoke-net-${host_port}-$$"
    local name="smoke-peer-${host_port}-$$"
    local cid=""
    local ready=""
    local peer_ip=""
    local whois_status="skip"

    docker network create "$net" >/dev/null
    # Extra args (e.g. -e BACNET_BBMD=1) are docker run options before the image.
    cid=$(docker run -d \
        --name "$name" \
        --network "$net" \
        -p "${host_port}:47808/udp" \
        "$@" \
        "${image}"
    )

    local deadline=$((SECONDS + 45))
    while [ $SECONDS -lt $deadline ]; do
        ready=$(docker logs "$cid" 2>/dev/null | grep '"event":"ready"' | head -1 || true)
        [ -n "$ready" ] && break
        ready=$(docker logs "$cid" 2>&1 | grep '"event":"ready"' | head -1 || true)
        [ -n "$ready" ] && break
        if ! docker inspect -f '{{.State.Running}}' "$cid" 2>/dev/null | grep -q true; then
            echo "container exited early:" >&2
            docker logs "$cid" >&2 || true
            break
        fi
        sleep 0.2
    done

    if [ -n "$ready" ] && [ "$SMOKE_WHOIS" = "1" ]; then
        # Skip Who-Is when BBMD mode is requested (foreign-device topology).
        local bbmd=0
        local prev="" arg
        for arg in "$@"; do
            if [ "$prev" = "-e" ] && [ "$arg" = "BACNET_BBMD=1" ]; then
                bbmd=1
            fi
            case "$arg" in
                BACNET_BBMD=1) bbmd=1 ;;
            esac
            prev="$arg"
        done

        if [ "$bbmd" -eq 0 ]; then
            peer_ip=$(docker inspect -f \
                '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$cid" 2>/dev/null || true)
            whois_status=$(run_whois_probe "$net" "$peer_ip")
        fi
    fi

    docker stop -t 2 "$cid" >/dev/null 2>&1 || true
    docker rm "$cid" >/dev/null 2>&1 || true
    docker network rm "$net" >/dev/null 2>&1 || true

    printf '%s\nWHOIS:%s\n' "$ready" "$whois_status"
}

# Capture start_server output into ready + whois_status locals via namerefs.
# Usage: run_start_server ready whois image port [docker args...]
run_start_server() {
    local _ready_var="$1" _whois_var="$2"
    shift 2
    local _out _ready _whois
    _out=$(start_server "$@")
    _ready=$(printf '%s\n' "$_out" | sed '/^WHOIS:/d' | head -1)
    _whois=$(printf '%s\n' "$_out" | sed -n 's/^WHOIS://p' | head -1)
    printf -v "$_ready_var" '%s' "$_ready"
    printf -v "$_whois_var" '%s' "${_whois:-skip}"
}

start_bip_router_smoke() {
    local image="$1"
    local net_a="smoke-bip-a-$$"
    local net_b="smoke-bip-b-$$"
    local name="smoke-bip-router-$$"
    # Static addressing avoids Docker eth0/eth1 reorder swapping BACnet nets.
    local subnet_a="10.230.1.0/24" gw_a="10.230.1.1" addr_a="10.230.1.2"
    local subnet_b="10.230.2.0/24" gw_b="10.230.2.1" addr_b="10.230.2.2"

    docker network create --subnet "$subnet_a" --gateway "$gw_a" "$net_a" >/dev/null
    docker network create --subnet "$subnet_b" --gateway "$gw_b" "$net_b" >/dev/null
    docker create --name "$name" --network "$net_a" --ip "$addr_a" \
        -e ADAPTER_VERSION=smoke \
        -e BACNET_NETWORKS=1,2 \
        -e "BACNET_ADDR_NET1=${addr_a}" \
        -e "BACNET_ADDR_NET2=${addr_b}" \
        "$image" >/dev/null
    docker network connect --ip "$addr_b" "$net_b" "$name"
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

check_whois() {
    local label="$1" status="$2"
    case "${status:-skip}" in
        ok) pass "${label}: directed Who-Is → I-Am" ;;
        fail) fail "${label}: directed Who-Is → I-Am" ;;
        skip) info "${label}: Who-Is probe skipped" ;;
        *) info "${label}: Who-Is probe status unknown (${status})" ;;
    esac
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

# ===========================================================================
if [ -n "$SMOKE_ONLY" ]; then
    info "SMOKE_ONLY=${SMOKE_ONLY}"
fi
if [ "$SMOKE_WHOIS" = "1" ]; then
    info "SMOKE_WHOIS=1 (directed Who-Is probe enabled)"
else
    info "SMOKE_WHOIS=0 (directed Who-Is probe disabled)"
fi

info "=== Images ==="
if want_adapter bacnet-stack; then
    if image_exists "$BACNET_STACK_IMAGE"; then
        pass "image present: ${BACNET_STACK_IMAGE}"
    else
        fail "image missing: ${BACNET_STACK_IMAGE}"
    fi
fi
if want_adapter bacpypes3; then
    if image_exists "$BACPYPES3_IMAGE"; then
        pass "image present: ${BACPYPES3_IMAGE}"
    else
        fail "image missing: ${BACPYPES3_IMAGE}"
    fi
fi
if want_adapter bacnet4j; then
    if image_exists "$BACNET4J_IMAGE"; then
        pass "image present: ${BACNET4J_IMAGE}"
    else
        fail "image missing: ${BACNET4J_IMAGE}"
    fi
fi
if want_adapter bip-router; then
    if image_exists "$BIP_ROUTER_IMAGE"; then
        pass "image present: ${BIP_ROUTER_IMAGE}"
    elif [ "${BIP_ROUTER_REQUIRED:-}" != "" ]; then
        fail "image missing: ${BIP_ROUTER_IMAGE}"
    else
        info "bip-router image absent; skipping"
    fi
fi

if want_adapter bacnet-stack && image_exists "$BACNET_STACK_IMAGE"; then
    info ""
    info "=== bacnet-stack ==="
    check_binary "$BACNET_STACK_IMAGE" device_server
    if docker run --rm --entrypoint sh "$BACNET_STACK_IMAGE" -c "test -f /usr/local/bin/run_server.py" >/dev/null 2>&1; then
        pass "run_server.py in ${BACNET_STACK_IMAGE}"
    else
        fail "run_server.py MISSING in ${BACNET_STACK_IMAGE}"
    fi
    check_fixture_file "$BACNET_STACK_IMAGE" /fixtures/device/device-baseline-v2.json
    ready=""; whois=""
    run_start_server ready whois "$BACNET_STACK_IMAGE" 47881
    check_ready_event "bacnet-stack device server" "$ready" "bacnet-stack" "device-baseline-v2"
    check_whois "bacnet-stack device server" "$whois"
fi

if want_adapter bacpypes3 && image_exists "$BACPYPES3_IMAGE"; then
    info ""
    info "=== BACpypes3 ==="
    check_fixture_file "$BACPYPES3_IMAGE" /fixtures/device/device-baseline-v2.json
    if docker run --rm --entrypoint sh "$BACPYPES3_IMAGE" -c "test -f /usr/local/bin/device_server.py" >/dev/null 2>&1; then
        pass "device_server.py in ${BACPYPES3_IMAGE}"
    else
        fail "device_server.py MISSING in ${BACPYPES3_IMAGE}"
    fi
    ready=""; whois=""
    run_start_server ready whois "$BACPYPES3_IMAGE" 47882
    check_ready_event "bacpypes3 device server" "$ready" "bacpypes3" "device-baseline-v2"
    check_whois "bacpypes3 device server" "$whois"
    ready=""; whois=""
    run_start_server ready whois "$BACPYPES3_IMAGE" 47883 -e BACNET_BBMD=1
    check_ready_event "bacpypes3 BBMD device server" "$ready" "bacpypes3" "device-baseline-v2"
    check_whois "bacpypes3 BBMD device server" "$whois"
fi

if want_adapter bacnet4j && image_exists "$BACNET4J_IMAGE"; then
    info ""
    info "=== BACnet4J ==="
    check_fixture_file "$BACNET4J_IMAGE" /fixtures/device/device-baseline-v2.json
    if docker run --rm --entrypoint sh "$BACNET4J_IMAGE" -c "test -f /usr/local/lib/device_server.jar" >/dev/null 2>&1; then
        pass "device_server.jar in ${BACNET4J_IMAGE}"
    else
        fail "device_server.jar MISSING in ${BACNET4J_IMAGE}"
    fi
    ready=""; whois=""
    run_start_server ready whois "$BACNET4J_IMAGE" 47884
    check_ready_event "bacnet4j device server" "$ready" "bacnet4j" "device-baseline-v2"
    check_whois "bacnet4j device server" "$whois"
    ready=""; whois=""
    run_start_server ready whois "$BACNET4J_IMAGE" 47885 -e BACNET_BBMD=1
    check_ready_event "bacnet4j BBMD device server" "$ready" "bacnet4j" "device-baseline-v2"
    check_whois "bacnet4j BBMD device server" "$whois"
fi

if want_adapter bip-router && image_exists "$BIP_ROUTER_IMAGE"; then
    info ""
    info "=== bip-router ==="
    if docker run --rm --entrypoint sh "$BIP_ROUTER_IMAGE" -c "test -f /usr/local/bin/bip_router.py" >/dev/null 2>&1; then
        pass "bip_router.py in ${BIP_ROUTER_IMAGE}"
    else
        fail "bip_router.py MISSING in ${BIP_ROUTER_IMAGE}"
    fi
    ready=$(start_bip_router_smoke "$BIP_ROUTER_IMAGE")
    check_ready_event "bip-router" "$ready" "bip-router" "topology-router-v1"
elif want_adapter bip-router && [ "${BIP_ROUTER_REQUIRED:-}" != "" ]; then
    : # already failed above when required
elif [ -z "$SMOKE_ONLY" ] && ! image_exists "$BIP_ROUTER_IMAGE"; then
    info "bip-router image absent; skipping topology router smoke (build with make build-bip-router)"
fi

echo ""
echo -e "Results: ${GREEN}${PASS} passed${RESET}  ${RED}${FAIL} failed${RESET}"
[ "$FAIL" -eq 0 ]
