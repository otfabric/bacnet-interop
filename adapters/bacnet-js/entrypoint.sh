#!/bin/sh
# SPDX-License-Identifier: MIT
# "client" runs client mode (docs/CLIENT_DRIVER_CONTRACT.md); anything else
# is device mode.
if [ "$1" = "client" ]; then
	shift
	exec node /opt/adapter/client.js "$@"
fi
exec node /opt/adapter/device.js "$@"
