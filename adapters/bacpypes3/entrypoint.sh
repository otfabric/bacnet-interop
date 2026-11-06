#!/bin/sh
# SPDX-License-Identifier: MIT
# "client" runs client mode (docs/CLIENT_DRIVER_CONTRACT.md); anything else
# is device mode.
if [ "$1" = "client" ]; then
	shift
	exec python3 /usr/local/bin/client_driver.py "$@"
fi
exec python3 /usr/local/bin/device_server.py "$@"
