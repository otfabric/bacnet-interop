#!/bin/sh
# SPDX-License-Identifier: MIT
# "client" runs client mode (docs/CLIENT_DRIVER_CONTRACT.md); anything else
# is device mode.
if [ "$1" = "client" ]; then
	shift
	exec java -cp /usr/local/lib/device_server.jar com.otfabric.bacnetinterop.ClientDriver "$@"
fi
exec java -jar /usr/local/lib/device_server.jar "$@"
