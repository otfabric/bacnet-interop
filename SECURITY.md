# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in `bacnet-interop`, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, please email **security@otfabric.io**, or open a private advisory on GitHub (the [Security](https://github.com/otfabric/bacnet-interop/security) tab → **Advisories** → **Report a vulnerability**), with a description, steps to reproduce and the affected image tag or digest.

Vulnerabilities in the bundled implementations themselves (bacnet-stack, BACpypes3, BACnet4J, System.IO.BACnet, worldiety/bacnet) belong upstream; report them there, and tell us so that the pin can be moved.

## Supported Versions

| Version | Supported |
|---------|-----------|
| Latest release | Yes |
| Older releases | No; pull the latest images |

## Security Considerations

### These are test fixtures, not products

The images run **unauthenticated, unencrypted BACnet/IP devices and routers** on UDP port 47808. They answer Who-Is and accept writes and, depending on the stack, DeviceCommunicationControl and ReinitializeDevice from anyone who can reach them. That is their purpose.

- **Never attach an image to a building automation, plant or other production network.** The devices answer broadcasts, and the BBMD modes and router images forward traffic between networks
- DeviceCommunicationControl and ReinitializeDevice need no password by default: the bacnet-stack adapter clears the stack's default passwords, and BACpypes3 and BACnet4J check one only when `BACNET_DCC_PASSWORD` is set. Such a password is a test value, not access control
- `scripts/smoke-test.sh` publishes each device's UDP port on all host interfaces while it runs. Run it on a host whose network you trust, or behind a host firewall

### Image hardening

- The device images (bacnet-stack, BACpypes3, BACnet4J, System.IO.BACnet, Worldiety) run as a non-root user (uid 10001)
- The two router images (`bip-router`, `bacnet-stack-router`) run as root, because they need broadcast and `SO_BINDTODEVICE` on several interfaces. Run them only on private Docker networks
- Runtime base images are pinned by digest. The Worldiety build stage (`golang:1.26-bookworm`) is pinned by tag only; it does not ship in the runtime image
- The images are rebuilt, not patched: a base image or upstream fix arrives with a new release

### Supply chain

- Upstream sources are fetched during the image build at pinned versions: bacnet-stack from GitHub, checked out and verified against the pinned commit hash; BACpypes3 from PyPI at an exact version; BACnet4J from the Mango Automation Maven repository at an exact version; System.IO.BACnet from nuget.org at an exact version; worldiety/bacnet from the Go module proxy, verified against `go.sum`
- The adapters never patch an upstream stack; adapter code is in this repository
- Consumers should pin images by digest, taken from the `manifest.json` of a release
