# SPDX-License-Identifier: MIT
#
# The bacnet-interop-otfabric image, from the repository root:
#   make -f own/go-bacnet/Makefile image smoke matrix
#
# Apart from the top-level Makefile on purpose: this image is not in the
# release of the harness and not in manifest.json (README.md).

IMAGE ?= ghcr.io/otfabric/bacnet-interop-otfabric:dev
# The reference images to test against: those of the latest harness release
# (image tags have no leading v),
# or :local images built with `make build`.
VERSION ?= $(shell git tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | head -1)
REFERENCE_TAG ?= $(patsubst v%,%,$(VERSION))
REGISTRY ?= ghcr.io/otfabric
REFERENCES ?= bacnet-stack bacnet4j bacpypes3 bacpypes ulbios bacnet-js
PLATFORM ?= $(shell docker version -f '{{.Server.Os}}/{{.Server.Arch}}' 2>/dev/null || echo linux/amd64)

# The latest go-bacnet release, as the workflow builds it.
UPSTREAM_VERSION ?= $(shell git ls-remote --tags --refs https://github.com/otfabric/go-bacnet.git 'v[0-9]*' | sed 's,.*refs/tags/,,' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$$' | sort -V | tail -1)
UPSTREAM_SHA ?= $(shell git ls-remote --tags https://github.com/otfabric/go-bacnet.git 'refs/tags/$(UPSTREAM_VERSION)^{}' | cut -f1)

export ADAPTER_IMAGE_otfabric = $(IMAGE)

# REFERENCE_TAG=local uses bacnet-interop-<name>:local.
ref = $(if $(filter local,$(REFERENCE_TAG)),bacnet-interop-$(1):local,$(REGISTRY)/bacnet-interop-$(1):$(REFERENCE_TAG))

.PHONY: image smoke matrix pull

image:
	docker buildx build --platform=$(PLATFORM) --load \
	  --build-arg UPSTREAM_VERSION=$(UPSTREAM_VERSION) --build-arg UPSTREAM_SHA=$(UPSTREAM_SHA) \
	  --build-arg ADAPTER_VERSION=$(UPSTREAM_VERSION) \
	  --tag $(IMAGE) --file own/go-bacnet/Dockerfile .

pull:
	@if [ "$(REFERENCE_TAG)" != local ]; then for a in $(REFERENCES); do docker pull --quiet $(call ref,$$a) || exit 1; done; fi

smoke:
	SMOKE_ONLY=otfabric scripts/smoke-test.sh

# The cross-stack self-test: server-baseline-v1 with every client against
# every device, the pairs with otfabric gating, their expected differences
# in expected-differences.json.
matrix: pull
	BACNET_STACK_IMAGE=$(call ref,bacnet-stack) BACNET4J_IMAGE=$(call ref,bacnet4j) \
	BACPYPES3_IMAGE=$(call ref,bacpypes3) BACPYPES_IMAGE=$(call ref,bacpypes) \
	ULBIOS_IMAGE=$(call ref,ulbios) BACNET_JS_IMAGE=$(call ref,bacnet-js) \
	  python3 scripts/client-matrix.py --all-devices --gate otfabric \
	  --extra-differences own/go-bacnet/expected-differences.json
