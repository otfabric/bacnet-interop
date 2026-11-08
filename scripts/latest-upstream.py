#!/usr/bin/env python3
"""Compares the upstream pin of one stack with the latest upstream.

    scripts/latest-upstream.py bacnet-stack|bacpypes3|bacnet4j|worldiety|sysiobacnet|cbsigma|cbsigma-sim|ulbios|bacpypes

Prints key=value lines (the format of $GITHUB_OUTPUT), for the Upstream
workflow and for `make candidate-<stack>`:

    pin=<the release pin>
    latest=<the latest stable upstream release; for worldiety and ulbios the HEAD commit>
    latest_sha=<the commit of latest, for a stack that is pinned by commit;
                for bacpypes the sha256 of the latest release's wheel>
    update=yes|no
    source=<where latest was looked up>

Only stable X.Y.Z releases count: alpha, beta, rc and snapshot versions are
never "latest". bacnet-stack follows its bacnet-stack-X.Y.Z release tags (not
master). Worldiety publishes no releases: its pin is a commit of upstream
HEAD. cB-Sigma's two modules (bacnet, bacnet-sim) are pinned by their vX.Y.Z
tags in adapters/cbsigma/go.mod, the source of truth (the Dockerfile ARGs
repeat them). ulbios/bacnet has no tags or releases either: its pin is a
commit of the default branch, as the pseudo-version in adapters/ulbios/go.mod
(the Dockerfile ARG ULBIOS_COMMIT repeats it). Legacy BACpypes (PyPI
bacpypes, not bacpypes3) is pinned by version and wheel sha256 in
adapters/bacpypes/requirements.txt. Commits are shown with 12 digits.
Nothing is modified.
"""

import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = "bacnet-interop latest-upstream (https://github.com/otfabric/bacnet-interop)"
STABLE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode()


def key(version, prefix=""):
    """Sort key of a stable X.Y.Z version; None for anything else."""
    match = STABLE.fullmatch(version.removeprefix(prefix)) if version.startswith(prefix) else None
    return tuple(int(part) for part in match.groups()) if match else None


def newest(versions, prefix=""):
    stable = [v for v in versions if key(v, prefix) is not None]
    if not stable:
        raise SystemExit("no stable X.Y.Z release found upstream")
    return max(stable, key=lambda v: key(v, prefix))


def arg(adapter, name):
    """ARG <name>=<value> of the adapter Dockerfile."""
    match = re.search(rf"^ARG {name}=(.+)$", (ROOT / "adapters" / adapter / "Dockerfile").read_text(), re.M)
    if not match:
        raise SystemExit(f"adapters/{adapter}/Dockerfile has no ARG {name}=<pin>")
    return match.group(1).strip()


def git_tags(repository):
    """Tags of repository as {tag: commit}; an annotated tag gives its commit."""
    out = subprocess.check_output(["git", "ls-remote", "--tags", repository], text=True)
    commits = {}
    for line in out.splitlines():
        sha, ref = line.split()
        tag = ref.removeprefix("refs/tags/")
        if tag.endswith("^{}"):
            commits[tag[:-3]] = sha
        else:
            commits.setdefault(tag, sha)
    return commits


def bacnet_stack():
    pin_sha = arg("bacnet-stack", "BACNET_STACK_SHA")
    pin = arg("bacnet-stack", "BACNET_STACK_VERSION")
    tags = git_tags("https://github.com/bacnet-stack/bacnet-stack.git")
    latest = newest(tags, "bacnet-stack-")
    return pin, latest, tags[latest], tags[latest] != pin_sha, "git tags of bacnet-stack/bacnet-stack"


def bacpypes3():
    text = (ROOT / "adapters/bacpypes3/requirements.txt").read_text()
    match = re.search(r"^bacpypes3==(\S+)", text, re.M)
    if not match:
        raise SystemExit("adapters/bacpypes3/requirements.txt has no bacpypes3==<pin>")
    pin = match.group(1)
    releases = json.loads(fetch("https://pypi.org/pypi/bacpypes3/json"))["releases"]
    live = [v for v, files in releases.items() if files and not all(f.get("yanked") for f in files)]
    latest = newest(live)
    return pin, latest, "", latest != pin, "PyPI"


def bacpypes():
    """Legacy BACpypes (PyPI bacpypes, not bacpypes3): the pin is installed by
    its wheel hash, so latest_sha is the sha256 of the latest wheel."""
    text = (ROOT / "adapters/bacpypes/requirements.txt").read_text()
    match = re.search(r"^bacpypes==(\S+)", text, re.M)
    if not match:
        raise SystemExit("adapters/bacpypes/requirements.txt has no bacpypes==<pin>")
    pin = match.group(1)
    releases = json.loads(fetch("https://pypi.org/pypi/bacpypes/json"))["releases"]
    live = {v: files for v, files in releases.items() if files and not all(f.get("yanked") for f in files)}
    latest = newest(live)
    wheels = [f for f in live[latest] if f.get("packagetype") == "bdist_wheel" and not f.get("yanked")]
    if len(wheels) != 1:
        raise SystemExit(f"bacpypes {latest}: {len(wheels)} wheels on PyPI, the candidate build needs exactly one")
    return pin, latest, wheels[0]["digests"]["sha256"], latest != pin, "PyPI"


def bacnet4j():
    pin = arg("bacnet4j", "BACNET4J_VERSION")
    # <release> and <latest> of the metadata may name an alpha.
    meta = fetch("https://maven.mangoautomation.net/repository/ias-release/"
                 "com/infiniteautomation/bacnet4j/maven-metadata.xml")
    latest = newest(re.findall(r"<version>([^<]+)</version>", meta))
    return pin, latest, "", latest != pin, "Mango Maven repository (ias-release)"


def worldiety():
    pin = arg("worldiety", "WORLDIETY_COMMIT")
    out = subprocess.check_output(["git", "ls-remote", "https://github.com/worldiety/bacnet.git", "HEAD"], text=True)
    tip = out.split()[0]
    return pin[:12], tip[:12], tip, not tip.startswith(pin), "HEAD of worldiety/bacnet"


def sysiobacnet():
    pin = arg("sysiobacnet", "SYSIOBACNET_VERSION")
    # Every version of the NuGet package "BACnet"; 4-part legacy versions and
    # pre-releases are not X.Y.Z.
    index = json.loads(fetch("https://api.nuget.org/v3-flatcontainer/bacnet/index.json"))
    latest = newest(index["versions"])
    return pin, latest, "", latest != pin, "nuget.org (BACnet)"


def cbsigma_module(module):
    gomod = (ROOT / "adapters/cbsigma/go.mod").read_text()
    match = re.search(rf"^\s*(?:require\s+)?github\.com/cB-Sigma/{module} (v\S+)$", gomod, re.M)
    if not match:
        raise SystemExit(f"adapters/cbsigma/go.mod does not require github.com/cB-Sigma/{module}")
    pin = match.group(1)
    tags = git_tags(f"https://github.com/cB-Sigma/{module}.git")
    latest = newest(tags, "v")
    return pin, latest, tags[latest], latest != pin, f"git tags of cB-Sigma/{module}"


def ulbios():
    pin = arg("ulbios", "ULBIOS_COMMIT")
    out = subprocess.check_output(["git", "ls-remote", "https://github.com/ulbios/bacnet.git", "HEAD"], text=True)
    tip = out.split()[0]
    return pin[:12], tip[:12], tip, not tip.startswith(pin), "HEAD of ulbios/bacnet"


RESOLVERS = {
    "bacnet-stack": bacnet_stack,
    "bacpypes3": bacpypes3,
    "bacpypes": bacpypes,
    "bacnet4j": bacnet4j,
    "worldiety": worldiety,
    "sysiobacnet": sysiobacnet,
    "cbsigma": lambda: cbsigma_module("bacnet"),
    "cbsigma-sim": lambda: cbsigma_module("bacnet-sim"),
    "ulbios": ulbios,
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in RESOLVERS:
        raise SystemExit(f"usage: latest-upstream.py {'|'.join(RESOLVERS)}")
    pin, latest, latest_sha, behind, source = RESOLVERS[sys.argv[1]]()
    print(f"pin={pin}")
    print(f"latest={latest}")
    print(f"latest_sha={latest_sha}")
    print(f"update={'yes' if behind else 'no'}")
    print(f"source={source}")


if __name__ == "__main__":
    main()
