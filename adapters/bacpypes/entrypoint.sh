#!/bin/sh
# SPDX-License-Identifier: MIT
# "client" runs client mode (docs/CLIENT_DRIVER_CONTRACT.md); anything else
# is device mode. -I: the interpreter does not read the environment or the
# working directory for modules.
if [ "$1" = "client" ]; then
	shift
	exec python3 -I /usr/local/lib/bacpypes-adapter/client_driver.py "$@"
fi
exec python3 -I /usr/local/lib/bacpypes-adapter/device_server.py "$@"
