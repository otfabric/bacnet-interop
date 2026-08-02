.PHONY: help validate-fixtures build build-bacnet-stack build-bacpypes3 build-bacnet4j build-worldiety build-bip-router smoke ci

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
BIP_ROUTER_IMAGE    ?= bacnet-interop-bip-router:local
REGISTRY            ?= ghcr.io/otfabric

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "\033[36m%-24s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---------------------------------------------------------------------------
# Fixture validation (no Docker required)
# ---------------------------------------------------------------------------

VENV := .venv

validate-fixtures: ## Validate manifest + fixture metadata against JSON Schema
	@set -e; \
	if [ ! -f scripts/validate-fixtures.py ] || ! command -v python3 >/dev/null 2>&1; then \
	  echo "ERROR: python3 and scripts/validate-fixtures.py are required"; exit 1; \
	fi; \
	if [ ! -x "$(VENV)/bin/python" ]; then \
	  python3 -m venv "$(VENV)"; \
	fi; \
	"$(VENV)/bin/pip" install -q -r requirements-dev.txt; \
	"$(VENV)/bin/python" scripts/validate-fixtures.py

# ---------------------------------------------------------------------------
# Adapter images (Docker when Dockerfile exists; stub otherwise)
# ---------------------------------------------------------------------------

build: build-bacnet-stack build-bacpypes3 build-bacnet4j build-worldiety build-bip-router ## Build all adapter images

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

# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------

smoke: ## Smoke-test adapter ready events
	@BACNET_STACK_IMAGE=$(BACNET_STACK_IMAGE) BACPYPES3_IMAGE=$(BACPYPES3_IMAGE) BACNET4J_IMAGE=$(BACNET4J_IMAGE) WORLDIETY_IMAGE=$(WORLDIETY_IMAGE) BIP_ROUTER_IMAGE=$(BIP_ROUTER_IMAGE) ./scripts/smoke-test.sh

# ---------------------------------------------------------------------------
# Local CI mirror
# ---------------------------------------------------------------------------

ci: validate-fixtures build smoke ## Local CI gate (fixtures + adapter images)
	@echo "ci: ok"
