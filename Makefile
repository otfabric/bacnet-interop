.PHONY: help validate-fixtures dissect-fixtures build build-bacnet-stack build-bacpypes3 build-bacnet4j build-worldiety build-sysiobacnet build-bip-router build-bacnet-stack-router smoke ci FORCE

SCHEMA              := fixtures/schema/fixture.schema.json
MANIFEST            := fixtures/manifest.json
# Native host platform by default (avoids amd64-on-arm64 QEMU warnings locally).
# CI/release can override: PLATFORM=linux/amd64 make build
PLATFORM            ?= $(shell docker version -f '{{.Server.Os}}/{{.Server.Arch}}' 2>/dev/null || echo linux/amd64)
ADAPTER_VERSION     ?= $(shell git rev-parse --short=12 HEAD 2>/dev/null || echo dev)
BACNET_STACK_IMAGE  ?= bacnet-interop-bacnet-stack:local
BACPYPES3_IMAGE     ?= bacnet-interop-bacpypes3:local
BACNET4J_IMAGE      ?= bacnet-interop-bacnet4j:local
WORLDIETY_IMAGE     ?= bacnet-interop-worldiety:local
SYSIOBACNET_IMAGE   ?= bacnet-interop-sysiobacnet:local
BIP_ROUTER_IMAGE    ?= bacnet-interop-bip-router:local
BACNET_STACK_ROUTER_IMAGE ?= bacnet-interop-bacnet-stack-router:local
REGISTRY            ?= ghcr.io/otfabric

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_%-]+:.*?## / {printf "\033[36m%-24s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---------------------------------------------------------------------------
# Fixture validation (no Docker required)
# ---------------------------------------------------------------------------

VENV := .venv

validate-fixtures: ## Validate manifest + fixture metadata against JSON Schema; check RELEASE.md has the notes of adapter_version
	@python3 scripts/check-versions.py
	@scripts/release-notes.sh > /dev/null && echo "ok   RELEASE.md has the notes of adapter_version"
	@python3 -m unittest discover -q -s scripts -p 'test_*.py'
	@set -e; \
	if [ ! -f scripts/validate-fixtures.py ] || ! command -v python3 >/dev/null 2>&1; then \
	  echo "ERROR: python3 and scripts/validate-fixtures.py are required"; exit 1; \
	fi; \
	if [ ! -x "$(VENV)/bin/python" ]; then \
	  python3 -m venv "$(VENV)"; \
	fi; \
	"$(VENV)/bin/pip" install -q -r requirements-dev.txt; \
	"$(VENV)/bin/python" scripts/validate-fixtures.py

dissect-fixtures: ## Check the codec vectors against Wireshark's dissector (needs tshark)
	@command -v tshark >/dev/null || { echo "ERROR: tshark is required (Wireshark)"; exit 1; }
	@python3 scripts/dissect-fixtures.py

# ---------------------------------------------------------------------------
# Adapter images (Docker when Dockerfile exists; stub otherwise)
# ---------------------------------------------------------------------------

build: build-bacnet-stack build-bacpypes3 build-bacnet4j build-worldiety build-sysiobacnet build-bip-router build-bacnet-stack-router ## Build all adapter images

build-bacnet-stack: ## Build bacnet-stack adapter image
	@if [ -f adapters/bacnet-stack/Dockerfile ]; then \
	  echo "Building bacnet-stack adapter image (ADAPTER_VERSION=$(ADAPTER_VERSION))..."; \
	  docker buildx build --platform=$(PLATFORM) --load \
	    --build-arg ADAPTER_VERSION=$(ADAPTER_VERSION) \
	    -f adapters/bacnet-stack/Dockerfile \
	    -t $(BACNET_STACK_IMAGE) .; \
	else \
	  echo "adapter images TBD: bacnet-stack (see adapters/bacnet-stack/README.md)"; \
	fi

build-bacpypes3: ## Build BACpypes3 adapter image
	@if [ -f adapters/bacpypes3/Dockerfile ]; then \
	  echo "Building BACpypes3 adapter image (ADAPTER_VERSION=$(ADAPTER_VERSION))..."; \
	  docker buildx build --platform=$(PLATFORM) --load \
	    --build-arg ADAPTER_VERSION=$(ADAPTER_VERSION) \
	    -f adapters/bacpypes3/Dockerfile \
	    -t $(BACPYPES3_IMAGE) .; \
	else \
	  echo "adapter images TBD: bacpypes3 (see adapters/bacpypes3/README.md)"; \
	fi

build-bacnet4j: ## Build BACnet4J adapter image
	@if [ -f adapters/bacnet4j/Dockerfile ]; then \
	  echo "Building BACnet4J adapter image (ADAPTER_VERSION=$(ADAPTER_VERSION))..."; \
	  docker buildx build --platform=$(PLATFORM) --load \
	    --build-arg ADAPTER_VERSION=$(ADAPTER_VERSION) \
	    -f adapters/bacnet4j/Dockerfile \
	    -t $(BACNET4J_IMAGE) .; \
	else \
	  echo "adapter images TBD: bacnet4j (see adapters/bacnet4j/README.md)"; \
	fi

build-worldiety: ## Build Worldiety adapter image
	@if [ -f adapters/worldiety/Dockerfile ]; then \
	  echo "Building Worldiety adapter image (ADAPTER_VERSION=$(ADAPTER_VERSION))..."; \
	  docker buildx build --platform=$(PLATFORM) --load \
	    --build-arg ADAPTER_VERSION=$(ADAPTER_VERSION) \
	    -f adapters/worldiety/Dockerfile \
	    -t $(WORLDIETY_IMAGE) .; \
	else \
	  echo "adapter images TBD: worldiety (see adapters/worldiety/README.md)"; \
	fi

build-sysiobacnet: ## Build System.IO.BACnet adapter image
	@if [ -f adapters/sysiobacnet/Dockerfile ]; then \
	  echo "Building System.IO.BACnet adapter image (ADAPTER_VERSION=$(ADAPTER_VERSION))..."; \
	  docker buildx build --platform=$(PLATFORM) --load \
	    --build-arg ADAPTER_VERSION=$(ADAPTER_VERSION) \
	    -f adapters/sysiobacnet/Dockerfile \
	    -t $(SYSIOBACNET_IMAGE) .; \
	else \
	  echo "adapter images TBD: sysiobacnet (see adapters/sysiobacnet/README.md)"; \
	fi

build-bip-router: ## Build BIP↔BIP topology router image
	@if [ -f adapters/bip-router/Dockerfile ]; then \
	  echo "Building bip-router image (ADAPTER_VERSION=$(ADAPTER_VERSION))..."; \
	  docker buildx build --platform=$(PLATFORM) --load \
	    --build-arg ADAPTER_VERSION=$(ADAPTER_VERSION) \
	    -f adapters/bip-router/Dockerfile \
	    -t $(BIP_ROUTER_IMAGE) .; \
	else \
	  echo "adapter images TBD: bip-router (see adapters/bip-router/README.md)"; \
	fi

build-bacnet-stack-router: ## Build native bacnet-stack BACnet/IP router image (upstream apps/router)
	@if [ -f adapters/bacnet-stack-router/Dockerfile ]; then \
	  echo "Building bacnet-stack-router image (ADAPTER_VERSION=$(ADAPTER_VERSION))..."; \
	  docker buildx build --platform=$(PLATFORM) --load \
	    --build-arg ADAPTER_VERSION=$(ADAPTER_VERSION) \
	    -f adapters/bacnet-stack-router/Dockerfile \
	    -t $(BACNET_STACK_ROUTER_IMAGE) .; \
	else \
	  echo "adapter images TBD: bacnet-stack-router (see adapters/bacnet-stack-router/README.md)"; \
	fi

# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------

smoke: ## Smoke-test adapter ready events
	@BACNET_STACK_IMAGE=$(BACNET_STACK_IMAGE) BACPYPES3_IMAGE=$(BACPYPES3_IMAGE) BACNET4J_IMAGE=$(BACNET4J_IMAGE) WORLDIETY_IMAGE=$(WORLDIETY_IMAGE) SYSIOBACNET_IMAGE=$(SYSIOBACNET_IMAGE) BIP_ROUTER_IMAGE=$(BIP_ROUTER_IMAGE) BACNET_STACK_ROUTER_IMAGE=$(BACNET_STACK_ROUTER_IMAGE) ./scripts/smoke-test.sh

# ---------------------------------------------------------------------------
# Upstream candidates
# ---------------------------------------------------------------------------
# Builds one stack on another upstream version than its release pin and
# smoke-tests it (readiness + directed Who-Is). The Upstream workflow runs this
# for every stack whose pin is behind; scripts/latest-upstream.py <stack>
# prints the version (latest) and the commit (latest_sha). candidate-% is a
# pattern rule, which make ignores for .PHONY targets: it depends on FORCE.

CANDIDATE_VERSION ?=
CANDIDATE_SHA     ?=

candidate-%: FORCE ## Build one stack on CANDIDATE_VERSION (and CANDIDATE_SHA) and smoke it, e.g. candidate-bacpypes3 CANDIDATE_VERSION=0.0.110
	@test -n "$(CANDIDATE_VERSION)" || { echo "Error: CANDIDATE_VERSION=<upstream version> is required"; exit 1; }
	@PLATFORM=$(PLATFORM) scripts/candidate.sh $* "$(CANDIDATE_VERSION)" "$(CANDIDATE_SHA)"

FORCE:

# ---------------------------------------------------------------------------
# Local CI mirror
# ---------------------------------------------------------------------------

ci: validate-fixtures build smoke ## Local CI gate (fixtures + adapter images)
	@echo "ci: ok"
