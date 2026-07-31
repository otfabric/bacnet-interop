# Build fixture-driven device_server against a bacnet-stack apps/ tree.
# Object sources match apps/server so device.c's default table links; runtime
# uses Interop_Object_Table and only creates fixture AV/BV instances.

TARGET = device_server
BACNET_STACK_ROOT ?= /src/bacnet-stack
BACNET_SRC_DIR = $(BACNET_STACK_ROOT)/src
BACNET_PORT_DIR = $(BACNET_STACK_ROOT)/ports/linux
BACNET_OBJECT_DIR = $(BACNET_SRC_DIR)/bacnet/basic/object
BACNET_LIB_DIR = $(BACNET_STACK_ROOT)/apps/lib
BACNET_LIB = -L$(BACNET_LIB_DIR) -lbacnet

BACDL_DEFINE = -DBACDL_BIP=1
BBMD_DEFINE = -DBBMD_ENABLED=1 -DBBMD_CLIENT_ENABLED
BACNET_DEFINES = $(BACDL_DEFINE) $(BBMD_DEFINE) -DWEAK_FUNC=
BACNET_DEFINES += -DPRINT_ENABLED=1
BACNET_DEFINES += -DBACAPP_ALL
BACNET_DEFINES += -DBACFILE
BACNET_DEFINES += -DINTRINSIC_REPORTING
BACNET_DEFINES += -DBACNET_TIME_MASTER
BACNET_DEFINES += -DBACNET_PROPERTY_LISTS=1
BACNET_DEFINES += -DBACNET_PROPERTY_ARRAY_LISTS=1
BACNET_DEFINES += -DBACNET_PROTOCOL_REVISION=24

CSTANDARD = -std=gnu89
WARNINGS = -Wall -Wextra -Wno-sign-conversion -Wno-conversion -Wno-sign-compare
WARNINGS += -Wno-long-long -Wno-attributes -Wno-implicit-fallthrough
OPTIMIZATION ?= -Os

INCLUDES = -I$(BACNET_SRC_DIR) -I$(BACNET_PORT_DIR)
CFLAGS = $(WARNINGS) $(OPTIMIZATION) $(BACNET_DEFINES) $(INCLUDES) $(CSTANDARD)
CFLAGS += -ffunction-sections -fdata-sections
PFLAGS = -pthread
LFLAGS = $(BACNET_LIB) -Wl,-lc,-lgcc,-lrt,-lm -Wl,--gc-sections

# Same object set as apps/server so device.c My_Object_Table resolves.
SRC = device_server.c \
	$(BACNET_OBJECT_DIR)/device.c \
	$(BACNET_OBJECT_DIR)/ai.c \
	$(BACNET_OBJECT_DIR)/ao.c \
	$(BACNET_OBJECT_DIR)/av.c \
	$(BACNET_OBJECT_DIR)/bi.c \
	$(BACNET_OBJECT_DIR)/bitstring_value.c \
	$(BACNET_OBJECT_DIR)/bo.c \
	$(BACNET_OBJECT_DIR)/blo.c \
	$(BACNET_OBJECT_DIR)/bv.c \
	$(BACNET_OBJECT_DIR)/calendar.c \
	$(BACNET_OBJECT_DIR)/channel.c \
	$(BACNET_OBJECT_DIR)/color_object.c \
	$(BACNET_OBJECT_DIR)/color_temperature.c \
	$(BACNET_OBJECT_DIR)/command.c \
	$(BACNET_OBJECT_DIR)/csv.c \
	$(BACNET_OBJECT_DIR)/iv.c \
	$(BACNET_OBJECT_DIR)/lc.c \
	$(BACNET_OBJECT_DIR)/lo.c \
	$(BACNET_OBJECT_DIR)/lsp.c \
	$(BACNET_OBJECT_DIR)/lsz.c \
	$(BACNET_OBJECT_DIR)/ms-input.c \
	$(BACNET_OBJECT_DIR)/mso.c \
	$(BACNET_OBJECT_DIR)/msv.c \
	$(BACNET_OBJECT_DIR)/osv.c \
	$(BACNET_OBJECT_DIR)/piv.c \
	$(BACNET_OBJECT_DIR)/nc.c \
	$(BACNET_OBJECT_DIR)/netport.c \
	$(BACNET_OBJECT_DIR)/time_value.c \
	$(BACNET_OBJECT_DIR)/trendlog.c \
	$(BACNET_OBJECT_DIR)/schedule.c \
	$(BACNET_OBJECT_DIR)/structured_view.c \
	$(BACNET_OBJECT_DIR)/access_credential.c \
	$(BACNET_OBJECT_DIR)/access_door.c \
	$(BACNET_OBJECT_DIR)/access_point.c \
	$(BACNET_OBJECT_DIR)/access_rights.c \
	$(BACNET_OBJECT_DIR)/access_user.c \
	$(BACNET_OBJECT_DIR)/access_zone.c \
	$(BACNET_OBJECT_DIR)/credential_data_input.c \
	$(BACNET_OBJECT_DIR)/acc.c \
	$(BACNET_OBJECT_DIR)/bacfile.c

OBJS = $(SRC:.c=.o)

.PHONY: all clean lib

all: $(TARGET)

lib:
	$(MAKE) -C $(BACNET_STACK_ROOT)/apps lib

$(TARGET): lib $(OBJS)
	$(CC) $(PFLAGS) $(OBJS) $(LFLAGS) -o $@

%.o: %.c
	$(CC) -c $(CFLAGS) $< -o $@

clean:
	rm -f $(TARGET) $(OBJS)
