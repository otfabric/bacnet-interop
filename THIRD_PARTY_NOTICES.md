# Third-party notices

The repository's own adapters, fixtures, scripts and documentation are MIT ([LICENSE](LICENSE)). Each published image also contains its upstream stack under that stack's licence. Consumers talk to the images over the network and are not linked to them.

| Image | Upstream | Pin | Upstream licence | Source |
|---|---|---|---|---|
| `bacnet-interop-bacnet-stack` | bacnet-stack | 1.6.1, `7a53f0a` | GPL-2.0-or-later with GCC-exception-2.0, per file | https://github.com/bacnet-stack/bacnet-stack |
| `bacnet-interop-bacnet-stack-router` | bacnet-stack `apps/router` | 1.6.1, `7a53f0a` | MIT (`apps/router`) | https://github.com/bacnet-stack/bacnet-stack |
| `bacnet-interop-bacpypes3` | BACpypes3 | 0.0.110 | MIT (PyPI licence expression) | https://github.com/JoelBender/BACpypes3 |
| `bacnet-interop-bacpypes` | BACpypes (legacy, PyPI `bacpypes`; not BACpypes3) | 0.19.0, wheel sha256 `317fbe44…131b` (source: `py34/bacpypes` at `86288e6`, untagged) | MIT (`LICENSE` in the wheel, kept in the image under `/opt/venv/lib/python3.11/site-packages/bacpypes-0.19.0.dist-info/`) | https://github.com/JoelBender/bacpypes |
| `bacnet-interop-bacnet4j` | BACnet4J | 6.1.1 | GPL-3.0 | https://github.com/RadixIoT/BACnet4J |
| `bacnet-interop-sysiobacnet` | System.IO.BACnet, NuGet `BACnet` | 4.0.0 | MIT | https://github.com/ela-compil/BACnet |
| `bacnet-interop-cbsigma` | cB-Sigma bacnet (device role) and bacnet-sim, Go modules | bacnet `v0.2.0` (`43314a7`), bacnet-sim `v0.1.0` (`8ca57e1`) | Apache-2.0 (both; NOTICE files); linked: cB-Sigma/tlsx Apache-2.0, coder/websocket ISC, golang.org/x/crypto and x/sys BSD-3-Clause | https://github.com/cB-Sigma/bacnet, https://github.com/cB-Sigma/bacnet-sim |
| `bacnet-interop-ulbios` | ulbios/bacnet, Go module | `v0.0.0-20230910233229-227d62272ce9` (`227d622`, no tags upstream) | MIT; links no other module (its go.mod also requires spf13/cobra Apache-2.0, spf13/pflag BSD-3-Clause, inconshreveable/mousetrap Apache-2.0 and google/go-cmp BSD-3-Clause, for its examples and tests only; none of them is in the image) | https://github.com/ulbios/bacnet |
| `bacnet-interop-bacnet-js` | @bacnet-js/client (npm), with its runtime dependencies debug, ms, iconv-lite and safer-buffer | @bacnet-js/client 3.3.2 (`43fbd92`); debug 4.4.3, ms 2.1.3, iconv-lite 0.6.3, safer-buffer 2.1.2 (package-lock.json) | MIT, all five: @bacnet-js/client (c) Innovation-System (2025-present), PLUS for Node-RED (2022-2024), Fabio Huser (2017-2021); debug (c) TJ Holowaychuk; ms (c) Vercel; iconv-lite (c) Alexander Shtuchkin; safer-buffer (c) Nikita Skovoroda. Node.js runtime from the `node` base image (MIT) | https://github.com/bacnet-js/client |
| `bacnet-interop-worldiety` | worldiety/bacnet | `3cb2aa8` | BSD-2-Clause | https://github.com/worldiety/bacnet |
| `bacnet-interop-bip-router` | none | topology-router-v1 | MIT (this repository) | adapters/bip-router |

Redistributing an image means keeping the upstream notices and meeting the source obligations of its licence. The `cbsigma` and `ulbios` images carry the LICENSE and NOTICE of every Go module linked into their binary under `/licenses/<module path>/`, this repository's licence under `/licenses/bacnet-interop/` and this file. The `bacnet-js` image carries the licence file of each npm package it installs under `/licenses/<package>/` (`@bacnet-js/client/LICENSE`, `debug/LICENSE`, `ms/license.md`, `iconv-lite/LICENSE`, `safer-buffer/LICENSE`), this repository's licence under `/licenses/bacnet-interop/` and this file. The other images do not yet carry licence texts under `/licenses/` (the `bacpypes` image keeps the wheel's `LICENSE` where pip installs it).

cB-Sigma's NOTICE: BACnet is a registered trademark of ASHRAE, used to name the protocol; cB-Sigma's code makes no claim of BACnet conformance and is not affiliated with ASHRAE or BACnet International.
