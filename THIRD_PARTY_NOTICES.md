# Third-party notices

The repository's own adapters, fixtures, scripts and documentation are MIT ([LICENSE](LICENSE)). Each published image also contains its upstream stack under that stack's licence. Consumers talk to the images over the network and are not linked to them.

| Image | Upstream | Pin | Upstream licence | Source |
|---|---|---|---|---|
| `bacnet-interop-bacnet-stack` | bacnet-stack | 1.6.1, `7a53f0a` | GPL-2.0-or-later with GCC-exception-2.0, per file | https://github.com/bacnet-stack/bacnet-stack |
| `bacnet-interop-bacnet-stack-router` | bacnet-stack `apps/router` | 1.6.1, `7a53f0a` | MIT (`apps/router`) | https://github.com/bacnet-stack/bacnet-stack |
| `bacnet-interop-bacpypes3` | BACpypes3 | 0.0.110 | MIT (PyPI licence expression) | https://github.com/JoelBender/BACpypes3 |
| `bacnet-interop-bacnet4j` | BACnet4J | 6.1.1 | GPL-3.0 | https://github.com/RadixIoT/BACnet4J |
| `bacnet-interop-sysiobacnet` | System.IO.BACnet, NuGet `BACnet` | 4.0.0 | MIT | https://github.com/ela-compil/BACnet |
| `bacnet-interop-worldiety` | worldiety/bacnet | `3cb2aa8` | BSD-2-Clause | https://github.com/worldiety/bacnet |
| `bacnet-interop-bip-router` | none | topology-router-v1 | MIT (this repository) | adapters/bip-router |

Redistributing an image means keeping the upstream notices and meeting the source obligations of its licence. The images do not yet carry licence texts under `/licenses/`.
