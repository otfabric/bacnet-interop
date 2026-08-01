/**
 * @file device_server.c
 * @brief Fixture-driven BACnet/IP device server for bacnet-interop.
 *
 * Builds against pinned bacnet-stack and exposes the objects declared in
 * device-baseline-v2 (device + AV + BV + TrendLog). Unlike upstream bacserv,
 * this adapter does not create the demo object zoo.
 *
 * SPDX-License-Identifier: MIT
 */
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bacnet/apdu.h"
#include "bacnet/bacdef.h"
#include "bacnet/bacdcode.h"
#include "bacnet/basic/binding/address.h"
#include "bacnet/basic/object/av.h"
#include "bacnet/basic/object/bv.h"
#include "bacnet/basic/object/device.h"
#include "bacnet/basic/object/netport.h"
#include "bacnet/basic/object/trendlog.h"
#include "bacnet/basic/services.h"
#include "bacnet/basic/sys/mstimer.h"
#include "bacnet/basic/tsm/tsm.h"
#include "bacnet/datalink/datalink.h"
#include "bacnet/datalink/dlenv.h"
#include "bacnet/dcc.h"
#include "bacnet/iam.h"
#include "bacnet/npdu.h"
#include "bacnet/version.h"

static uint8_t Rx_Buf[MAX_MPDU];
static struct mstimer BACnet_Task_Timer;
static struct mstimer BACnet_TSM_Timer;
static struct mstimer BACnet_Address_Timer;
static struct mstimer BACnet_Object_Timer;
static volatile sig_atomic_t Running = 1;

/* Device, Network Port, AV, BV, TrendLog — terminator required by Device_Init.
 * Field order matches object_functions_t through Object_Writable_Property_List. */
static object_functions_t Interop_Object_Table[] = {
    { OBJECT_DEVICE, NULL, Device_Count, Device_Index_To_Instance,
        Device_Valid_Object_Instance_Number, Device_Object_Name,
        Device_Read_Property_Local, Device_Write_Property_Local,
        Device_Property_Lists, DeviceGetRRInfo, NULL, NULL, NULL, NULL, NULL,
        NULL, NULL, NULL, NULL, NULL, NULL },
#if (BACNET_PROTOCOL_REVISION >= 17)
    { OBJECT_NETWORK_PORT, Network_Port_Init, Network_Port_Count,
        Network_Port_Index_To_Instance, Network_Port_Valid_Instance,
        Network_Port_Object_Name, Network_Port_Read_Property,
        Network_Port_Write_Property, Network_Port_Property_Lists, NULL, NULL,
        NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL },
#endif
    { OBJECT_ANALOG_VALUE, Analog_Value_Init, Analog_Value_Count,
        Analog_Value_Index_To_Instance, Analog_Value_Valid_Instance,
        Analog_Value_Object_Name, Analog_Value_Read_Property,
        Analog_Value_Write_Property, Analog_Value_Property_Lists, NULL, NULL,
        Analog_Value_Encode_Value_List, Analog_Value_Change_Of_Value,
        Analog_Value_Change_Of_Value_Clear, NULL, NULL, NULL,
        Analog_Value_Create, Analog_Value_Delete, NULL, NULL },
    { OBJECT_BINARY_VALUE, Binary_Value_Init, Binary_Value_Count,
        Binary_Value_Index_To_Instance, Binary_Value_Valid_Instance,
        Binary_Value_Object_Name, Binary_Value_Read_Property,
        Binary_Value_Write_Property, Binary_Value_Property_Lists, NULL, NULL,
        Binary_Value_Encode_Value_List, Binary_Value_Change_Of_Value,
        Binary_Value_Change_Of_Value_Clear, NULL, NULL, NULL,
        Binary_Value_Create, Binary_Value_Delete, NULL, NULL },
    { OBJECT_TRENDLOG, Trend_Log_Init, Trend_Log_Count,
        Trend_Log_Index_To_Instance, Trend_Log_Valid_Instance,
        Trend_Log_Object_Name, Trend_Log_Read_Property,
        Trend_Log_Write_Property, Trend_Log_Property_Lists, TrendLogGetRRInfo,
        NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL },
    { MAX_BACNET_OBJECT_TYPE, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
        NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL },
};

static void on_signal(int signo)
{
    (void)signo;
    Running = 0;
}

static void Init_Service_Handlers(void)
{
    Device_Init(Interop_Object_Table);

    apdu_set_unconfirmed_handler(SERVICE_UNCONFIRMED_WHO_IS, handler_who_is);
    apdu_set_unconfirmed_handler(SERVICE_UNCONFIRMED_WHO_HAS, handler_who_has);
    apdu_set_unrecognized_service_handler_handler(handler_unrecognized_service);

    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_READ_PROPERTY, handler_read_property);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_READ_PROP_MULTIPLE, handler_read_property_multiple);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_WRITE_PROPERTY, handler_write_property);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_WRITE_PROP_MULTIPLE, handler_write_property_multiple);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_SUBSCRIBE_COV, handler_cov_subscribe);
    apdu_set_unconfirmed_handler(
        SERVICE_UNCONFIRMED_COV_NOTIFICATION, handler_ucov_notification);
    apdu_set_confirmed_handler(SERVICE_CONFIRMED_DEVICE_COMMUNICATION_CONTROL,
        handler_device_communication_control);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_READ_RANGE, handler_read_range);
    /* Stock Device_Reinitialize only sets a flag; it does not exit the process. */
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_REINITIALIZE_DEVICE, handler_reinitialize_device);
#if defined(INTRINSIC_REPORTING)
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_ACKNOWLEDGE_ALARM, handler_alarm_ack);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_GET_EVENT_INFORMATION, handler_get_event_information);
#endif

    mstimer_set(&BACnet_Task_Timer, 1000UL);
    mstimer_set(&BACnet_TSM_Timer, 50UL);
    mstimer_set(&BACnet_Address_Timer, 60UL * 1000UL);
    mstimer_set(&BACnet_Object_Timer, 100UL);
}

static void usage(const char *prog)
{
    fprintf(stderr,
        "Usage: %s --instance N --name NAME "
        "[--av-instance N --av-name NAME --av-value F --av-description TEXT] "
        "[--bv-instance N --bv-name NAME --bv-value inactive|active]\n",
        prog);
}

int main(int argc, char *argv[])
{
    BACNET_ADDRESS src = { 0 };
    uint16_t pdu_len = 0;
    uint32_t elapsed_milliseconds = 0;
    uint32_t elapsed_seconds = 0;
    uint32_t device_instance = 1234;
    const char *device_name = "InteropDevice";
    uint32_t av_instance = 1;
    const char *av_name = "AV-1";
    const char *av_description = "Interop AV-1";
    float av_value = 21.5f;
    bool have_av = true;
    uint32_t bv_instance = 1;
    const char *bv_name = "BV-1";
    BACNET_BINARY_PV bv_value = BINARY_INACTIVE;
    bool have_bv = true;
    int i;

    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--help") == 0) {
            usage(argv[0]);
            return 0;
        }
        if (strcmp(argv[i], "--version") == 0) {
            fprintf(stderr, "bacnet-interop-device-server %s\n", BACNET_VERSION_TEXT);
            return 0;
        }
        if (strcmp(argv[i], "--instance") == 0 && i + 1 < argc) {
            device_instance = (uint32_t)strtoul(argv[++i], NULL, 0);
            continue;
        }
        if (strcmp(argv[i], "--name") == 0 && i + 1 < argc) {
            device_name = argv[++i];
            continue;
        }
        if (strcmp(argv[i], "--av-instance") == 0 && i + 1 < argc) {
            av_instance = (uint32_t)strtoul(argv[++i], NULL, 0);
            have_av = true;
            continue;
        }
        if (strcmp(argv[i], "--av-name") == 0 && i + 1 < argc) {
            av_name = argv[++i];
            continue;
        }
        if (strcmp(argv[i], "--av-value") == 0 && i + 1 < argc) {
            av_value = strtof(argv[++i], NULL);
            continue;
        }
        if (strcmp(argv[i], "--av-description") == 0 && i + 1 < argc) {
            av_description = argv[++i];
            continue;
        }
        if (strcmp(argv[i], "--no-av") == 0) {
            have_av = false;
            continue;
        }
        if (strcmp(argv[i], "--bv-instance") == 0 && i + 1 < argc) {
            bv_instance = (uint32_t)strtoul(argv[++i], NULL, 0);
            have_bv = true;
            continue;
        }
        if (strcmp(argv[i], "--bv-name") == 0 && i + 1 < argc) {
            bv_name = argv[++i];
            continue;
        }
        if (strcmp(argv[i], "--bv-value") == 0 && i + 1 < argc) {
            i++;
            if (strcmp(argv[i], "active") == 0 || strcmp(argv[i], "1") == 0) {
                bv_value = BINARY_ACTIVE;
            } else {
                bv_value = BINARY_INACTIVE;
            }
            continue;
        }
        if (strcmp(argv[i], "--no-bv") == 0) {
            have_bv = false;
            continue;
        }
        fprintf(stderr, "unknown argument: %s\n", argv[i]);
        usage(argv[0]);
        return 2;
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);

    Device_Set_Object_Instance_Number(device_instance);

    address_init();
    Init_Service_Handlers();
    /* Device_Init resets the object-name; set it after handlers are installed. */
    Device_Object_Name_ANSI_Init(device_name);
    /* Default stack passwords are "filister"; clear so no-password DCC/Reinit works. */
    Device_Reinitialize_Password_Set("");
    handler_dcc_password_set(NULL);

    if (have_av) {
        if (Analog_Value_Create(av_instance) != av_instance) {
            fprintf(stderr, "Analog_Value_Create(%u) failed\n",
                (unsigned)av_instance);
            return 1;
        }
        Analog_Value_Name_Set(av_instance, (char *)av_name);
        Analog_Value_Description_Set(av_instance, (char *)av_description);
        Analog_Value_Present_Value_Set(av_instance, av_value, 0);
        Analog_Value_COV_Increment_Set(av_instance, 0.1f);
    }
    if (have_bv) {
        if (Binary_Value_Create(bv_instance) != bv_instance) {
            fprintf(stderr, "Binary_Value_Create(%u) failed\n",
                (unsigned)bv_instance);
            return 1;
        }
        Binary_Value_Name_Set(bv_instance, (char *)bv_name);
        Binary_Value_Write_Enable(bv_instance);
        Binary_Value_Present_Value_Set(bv_instance, bv_value);
    }

    dlenv_init();
    atexit(datalink_cleanup);

    fprintf(stderr,
        "bacnet-interop device server\n"
        "  bacnet-stack %s\n"
        "  device %u %s\n"
        "  max APDU %d\n",
        BACNET_VERSION_TEXT, (unsigned)device_instance, device_name, MAX_APDU);
    if (have_av) {
        fprintf(stderr, "  analog-value:%u %s = %g\n", (unsigned)av_instance,
            av_name, (double)av_value);
    }
    if (have_bv) {
        fprintf(stderr, "  binary-value:%u %s = %s\n", (unsigned)bv_instance,
            bv_name, bv_value == BINARY_ACTIVE ? "active" : "inactive");
    }
    fprintf(stderr, "  trend-log count=%u (MAX_TREND_LOGS)\n",
        (unsigned)Trend_Log_Count());

    Send_I_Am(&Handler_Transmit_Buffer[0]);

    while (Running) {
        pdu_len = datalink_receive(&src, &Rx_Buf[0], MAX_MPDU, 1);
        if (pdu_len) {
            npdu_handler(&src, &Rx_Buf[0], pdu_len);
        }
        if (mstimer_expired(&BACnet_Task_Timer)) {
            mstimer_reset(&BACnet_Task_Timer);
            elapsed_milliseconds = mstimer_interval(&BACnet_Task_Timer);
            elapsed_seconds = elapsed_milliseconds / 1000;
            dcc_timer_seconds(elapsed_seconds);
            datalink_maintenance_timer(elapsed_seconds);
            dlenv_maintenance_timer(elapsed_seconds);
            handler_cov_timer_seconds(elapsed_seconds);
            trend_log_timer((uint16_t)elapsed_seconds);
        }
        if (mstimer_expired(&BACnet_TSM_Timer)) {
            mstimer_reset(&BACnet_TSM_Timer);
            tsm_timer_milliseconds(mstimer_interval(&BACnet_TSM_Timer));
        }
        if (mstimer_expired(&BACnet_Address_Timer)) {
            mstimer_reset(&BACnet_Address_Timer);
            address_cache_timer(mstimer_interval(&BACnet_Address_Timer) / 1000);
        }
        handler_cov_task();
        if (mstimer_expired(&BACnet_Object_Timer)) {
            mstimer_reset(&BACnet_Object_Timer);
            Device_Timer(mstimer_interval(&BACnet_Object_Timer));
        }
    }

    return 0;
}
