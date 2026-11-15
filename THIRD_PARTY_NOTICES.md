# Third-party notices

The repository's own adapters, fixtures, scripts and documentation are MIT ([LICENSE](LICENSE)). Each published image also contains its upstream stack under that stack's licence. Consumers talk to the images over the network and are not linked to them.

| Image | Upstream | Pin | Upstream licence | Source |
|---|---|---|---|---|
| `bacnet-interop-bacnet-stack` | bacnet-stack | 1.6.1, `7a53f0a` | GPL-2.0-or-later with GCC-exception-2.0, per file | https://github.com/bacnet-stack/bacnet-stack |
| `bacnet-interop-bacnet-stack-router` | bacnet-stack `apps/router` | 1.6.1, `7a53f0a` | MIT (`apps/router`) | https://github.com/bacnet-stack/bacnet-stack |
| `bacnet-interop-bacpypes3` | BACpypes3 | 0.0.110, wheel sha256 `02abc0c9…4911` (tag `v0.0.110`, `48beeba`) | MIT (the licence expression of its `pyproject.toml`; the source tree has no licence file, see [licenses/bacpypes3/README.md](licenses/bacpypes3/README.md)) | https://github.com/JoelBender/BACpypes3 |
| `bacnet-interop-bacpypes` | BACpypes (legacy, PyPI `bacpypes`; not BACpypes3) | 0.19.0, wheel sha256 `317fbe44…131b` (source: `py34/bacpypes` at `86288e6`, untagged) | MIT (`LICENSE` in the wheel, kept in the image under `/opt/venv/lib/python3.11/site-packages/bacpypes-0.19.0.dist-info/`) | https://github.com/JoelBender/bacpypes |
| `bacnet-interop-bacnet4j` | BACnet4J | 6.1.1 | GPL-3.0 | https://github.com/RadixIoT/BACnet4J |
| `bacnet-interop-sysiobacnet` | System.IO.BACnet, NuGet `BACnet` | 4.0.0 | MIT | https://github.com/ela-compil/BACnet |
| `bacnet-interop-cbsigma` | cB-Sigma bacnet (device role) and bacnet-sim, Go modules | bacnet `v0.2.0` (`43314a7`), bacnet-sim `v0.1.0` (`8ca57e1`) | Apache-2.0 (both; NOTICE files); linked: cB-Sigma/tlsx Apache-2.0, coder/websocket ISC, golang.org/x/crypto and x/sys BSD-3-Clause | https://github.com/cB-Sigma/bacnet, https://github.com/cB-Sigma/bacnet-sim |
| `bacnet-interop-ulbios` | ulbios/bacnet, Go module | `v0.0.0-20230910233229-227d62272ce9` (`227d622`, no tags upstream) | MIT; links no other module (its go.mod also requires spf13/cobra Apache-2.0, spf13/pflag BSD-3-Clause, inconshreveable/mousetrap Apache-2.0 and google/go-cmp BSD-3-Clause, for its examples and tests only; none of them is in the image) | https://github.com/ulbios/bacnet |
| `bacnet-interop-bacnet-js` | @bacnet-js/client (npm), with its runtime dependencies debug, ms, iconv-lite and safer-buffer | @bacnet-js/client 3.3.2 (`43fbd92`); debug 4.4.3, ms 2.1.3, iconv-lite 0.6.3, safer-buffer 2.1.2 (package-lock.json) | MIT, all five: @bacnet-js/client (c) Innovation-System (2025-present), PLUS for Node-RED (2022-2024), Fabio Huser (2017-2021); debug (c) TJ Holowaychuk; ms (c) Vercel; iconv-lite (c) Alexander Shtuchkin; safer-buffer (c) Nikita Skovoroda. Node.js runtime from the `node` base image (MIT) | https://github.com/bacnet-js/client |
| `bacnet-interop-worldiety` | worldiety/bacnet | `3cb2aa8` | BSD-2-Clause | https://github.com/worldiety/bacnet |
| `bacnet-interop-bip-router` | none | topology-router-v1 | MIT (this repository) | adapters/bip-router |
| `bacnet-interop-otfabric` (own stack, not a reference: [own/go-bacnet](own/go-bacnet/README.md)) | go-bacnet, Go module | the latest go-bacnet release when the image is built by hand | MIT; links no other module (go-bacnet uses the standard library only) | https://github.com/otfabric/go-bacnet |

Redistributing an image means keeping the upstream notices and meeting the source obligations of its licence. Every image carries this repository's licence under `/licenses/bacnet-interop/` and this file as `/licenses/THIRD_PARTY_NOTICES.md`, and the upstream licence texts as follows:

- `cbsigma`, `ulbios`, `worldiety` and `otfabric`: the LICENSE and NOTICE of every Go module linked into the binary, under `/licenses/<module path>/`, copied from the module at build time.
- `bacnet-js`: the licence file of each npm package it installs, under `/licenses/<package>/` (`@bacnet-js/client/LICENSE`, `debug/LICENSE`, `ms/license.md`, `iconv-lite/LICENSE`, `safer-buffer/LICENSE`), copied from the installed packages at build time.
- `bacnet-stack`, `bacnet-stack-router`, `bacpypes3`, `bacpypes`, `bacnet4j` and `sysiobacnet`: the texts of [`licenses/<component>/`](licenses/) under `/licenses/<component>/` (`bacnet-stack` for both bacnet-stack images). The `bacpypes` image also keeps the wheel's `LICENSE` where pip installs it.
- `bip-router`: none; it is this repository's code only.

[`licenses/`](licenses/) holds the upstream texts of every implementation in `versions.yaml`, taken from the upstream at the pin: `bacnet-stack/` (the `license/` directory of bacnet-stack at `7a53f0a`), `bacpypes3/` (no upstream text; [README](licenses/bacpypes3/README.md)), `bacpypes/` (`86288e6`), `bacnet4j/` (`license.txt` at tag `v6.1.0`, `11116fd`, the newest tag; 6.1.1 has none, and its pom names the GPL-3.0 `license.txt` of the repository), `sysiobacnet/` (`af0e6c0`), `worldiety/`, `ulbios/`, `cbsigma/` and `cbsigma-sim/` (the modules at their pins, with the modules cB-Sigma bacnet links), and `bacnet-js/` (`@bacnet-js/client` at `43fbd92`, with debug 4.4.3, ms 2.1.3, iconv-lite 0.6.3 and safer-buffer 2.1.2 at their release tags). `scripts/check-versions.py` fails when an implementation has no texts there.

Corresponding source of the GPL images: `bacnet-interop-bacnet-stack` is built from bacnet-stack at commit `7a53f0a72a92de1621d30fc63703a29afe12bfaf` (tag `bacnet-stack-1.6.1`, https://github.com/bacnet-stack/bacnet-stack) and `adapters/bacnet-stack/` of this repository at the release tag, and `bacnet-interop-bacnet-stack-router` from `apps/router` at the same commit; `bacnet-interop-bacnet4j` contains BACnet4J 6.1.1, whose source is `com.infiniteautomation:bacnet4j:6.1.1` (`bacnet4j-6.1.1-sources.jar`) in https://maven.mangoautomation.net/repository/ias-release/, with `adapters/bacnet4j/` of this repository at the release tag.

cB-Sigma's NOTICE: BACnet is a registered trademark of ASHRAE, used to name the protocol; cB-Sigma's code makes no claim of BACnet conformance and is not affiliated with ASHRAE or BACnet International.
