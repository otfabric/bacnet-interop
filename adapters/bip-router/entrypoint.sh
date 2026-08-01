#!/bin/sh
# SPDX-License-Identifier: MIT
# Start the BIP↔BIP router with stable address→network bindings.
#
# Prefer BACNET_ADDR_NET1 / BACNET_ADDR_NET2 when set (explicit IPs). Falling
# back to eth0/eth1 is unsafe: Docker does not guarantee iface order after
# create+connect, which swaps BACnet network numbers and drops DNET forwards.
set -eu

NETWORKS="${BACNET_NETWORKS:-1,2}"
PORT="${BACNET_IP_PORT:-47808}"
NET_A=$(echo "$NETWORKS" | cut -d, -f1)
NET_B=$(echo "$NETWORKS" | cut -d, -f2)

ipv4_of() {
  iface="$1"
  ip -4 -o addr show dev "$iface" 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -1
}

addr_a="${BACNET_ADDR_NET1:-}"
addr_b="${BACNET_ADDR_NET2:-}"

if [ -z "$addr_a" ] || [ -z "$addr_b" ]; then
  deadline=$(( $(date +%s) + 30 ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    addr_a=$(ipv4_of eth0 || true)
    addr_b=$(ipv4_of eth1 || true)
    if [ -n "$addr_a" ] && [ -n "$addr_b" ]; then
      break
    fi
    sleep 0.2
  done
fi

if [ -z "$addr_a" ] || [ -z "$addr_b" ]; then
  echo "bip-router: timed out waiting for dual-homed addresses (net1=${addr_a:-none} net2=${addr_b:-none})" >&2
  echo "Connect the container to two docker networks, or set BACNET_ADDR_NET1 / BACNET_ADDR_NET2." >&2
  exit 1
fi

echo "bip-router: net=${NET_A} addr=${addr_a} net=${NET_B} addr=${addr_b}" >&2

exec python3 /usr/local/bin/bip_router.py \
  --port "name=net1,network=${NET_A},addr=${addr_a},port=${PORT}" \
  --port "name=net2,network=${NET_B},addr=${addr_b},port=${PORT}"
