#!/usr/bin/env bash
# candidate.sh — builds one stack on another upstream version than its release
# pin and smoke-tests it: readiness and the directed Who-Is probe of
# scripts/smoke-test.sh. bacnet-stack builds and smokes the router image too
# (the same pin). Used by the Upstream workflow through make candidate-<stack>;
# scripts/latest-upstream.py <stack> gives the version and the commit.
#
# Usage:
#   scripts/candidate.sh <stack> <version> [<commit>]
#     bacnet-stack  <bacnet-stack-X.Y.Z tag> <its commit>
#     bacpypes3     <PyPI version>
#     bacnet4j      <Maven version>
#     worldiety     <any> <commit of worldiety/bacnet>   (needs Go)
#     sysiobacnet   <NuGet version>
#
# The release pins stay as they are: bacpypes3 requirements.txt and worldiety
# go.mod/go.sum are edited for the build and restored afterwards. Images are
# tagged bacnet-interop-<image>:candidate.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

stack="${1:-}"
version="${2:-}"
commit="${3:-}"
[ -n "${stack}" ] && [ -n "${version}" ] || { echo "usage: candidate.sh <stack> <version> [<commit>]" >&2; exit 2; }

PLATFORM="${PLATFORM:-$(docker version -f '{{.Server.Os}}/{{.Server.Arch}}' 2>/dev/null || echo linux/amd64)}"

# Files edited for the build, restored on exit.
backup="$(mktemp -d)"
restore() {
    for f in "${backup}"/*; do
        [ -e "$f" ] || continue
        cp "$f" "adapters/${stack}/$(basename "$f")"
    done
    rm -rf "${backup}"
}
trap restore EXIT
keep() { cp "adapters/${stack}/$1" "${backup}/$1"; }

build() {  # build <adapter> <build args...>
    local adapter="$1"; shift
    echo "Building ${adapter} candidate on ${version} ${commit}..."
    docker buildx build --platform="${PLATFORM}" --load \
        --build-arg ADAPTER_VERSION=candidate "$@" \
        -f "adapters/${adapter}/Dockerfile" \
        -t "bacnet-interop-${adapter}:candidate" .
}

need_commit() {
    [ -n "${commit}" ] || { echo "candidate.sh: ${stack} needs the commit" >&2; exit 2; }
}

case "${stack}" in
    bacnet-stack)
        need_commit
        build bacnet-stack --build-arg "BACNET_STACK_SHA=${commit}" --build-arg "BACNET_STACK_VERSION=${version}"
        build bacnet-stack-router --build-arg "BACNET_STACK_SHA=${commit}" --build-arg "BACNET_STACK_VERSION=${version}"
        export SMOKE_ONLY=bacnet-stack,bacnet-stack-router BACNET_STACK_ROUTER_REQUIRED=1 \
            BACNET_STACK_IMAGE=bacnet-interop-bacnet-stack:candidate \
            BACNET_STACK_ROUTER_IMAGE=bacnet-interop-bacnet-stack-router:candidate
        ;;
    bacpypes3)
        keep requirements.txt
        echo "bacpypes3==${version}" > adapters/bacpypes3/requirements.txt
        build bacpypes3 --build-arg "BACPYPES3_VERSION=${version}"
        export SMOKE_ONLY=bacpypes3 BACPYPES3_IMAGE=bacnet-interop-bacpypes3:candidate
        ;;
    bacnet4j)
        build bacnet4j --build-arg "BACNET4J_VERSION=${version}"
        export SMOKE_ONLY=bacnet4j BACNET4J_IMAGE=bacnet-interop-bacnet4j:candidate
        ;;
    worldiety)
        need_commit
        keep go.mod
        keep go.sum
        (cd adapters/worldiety && go get "github.com/worldiety/bacnet@${commit}" && go mod tidy)
        build worldiety --build-arg "WORLDIETY_COMMIT=${commit}"
        export SMOKE_ONLY=worldiety WORLDIETY_IMAGE=bacnet-interop-worldiety:candidate
        ;;
    sysiobacnet)
        build sysiobacnet --build-arg "SYSIOBACNET_VERSION=${version}"
        export SMOKE_ONLY=sysiobacnet SYSIOBACNET_IMAGE=bacnet-interop-sysiobacnet:candidate
        ;;
    *)
        echo "candidate.sh: unknown stack '${stack}'" >&2
        exit 2
        ;;
esac

SMOKE_WHOIS=1 scripts/smoke-test.sh
