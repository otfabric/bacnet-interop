#!/bin/sh
# SPDX-License-Identifier: MIT
# Wait for dual-homed eth0/eth1, then start the BIP↔BIP router.
set -eu

NETWORKS="${BACNET_NETWORKS:-1,2}"
PORT="${BACNET_IP_PORT:-47808}"
NET_A=$(echo "$NETWORKS" | cut -d, -f1)
NET_B=$(echo "$NETWORKS" | cut -d, -f2)

ipv4_of() {
  iface="$1"
  ip -4 -o addr show dev "$iface" 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -1
}

deadline=$(( $(date +%s) + 30 ))
addr_a=""
addr_b=""
while [ "$(date +%s)" -lt "$deadline" ]; do
  addr_a=$(ipv4_of eth0 || true)
  addr_b=$(ipv4_of eth1 || true)
  if [ -n "$addr_a" ] && [ -n "$addr_b" ]; then
    break
  fi
  sleep 0.2
done

if [ -z "$addr_a" ] || [ -z "$addr_b" ]; then
  echo "bip-router: timed out waiting for eth0/eth1 addresses (got eth0=${addr_a:-none} eth1=${addr_b:-none})" >&2
  echo "Connect the container to two docker networks before/at start." >&2
  exit 1
fi

echo "bip-router: eth0=${addr_a} net=${NET_A} eth1=${addr_b} net=${NET_B}" >&2

exec python3 /usr/local/bin/bip_router.py \
  --port "name=eth0,network=${NET_A},addr=${addr_a},port=${PORT}" \
  --port "name=eth1,network=${NET_B},addr=${addr_b},port=${PORT}"
