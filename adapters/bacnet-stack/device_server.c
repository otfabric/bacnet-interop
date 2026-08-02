/**
 * @file device_server.c
 * @brief Fixture-driven BACnet/IP device server for bacnet-interop.
 *
 * Builds against pinned bacnet-stack and exposes objects declared in
 * device-baseline fixtures (device + AV/BV + optional File + NC + TrendLog).
 * Unlike upstream bacserv, this adapter does not create the demo object zoo.
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
#include "bacnet/basic/object/bacfile.h"
#include "bacnet/basic/object/bv.h"
#include "bacnet/basic/object/device.h"
#include "bacnet/basic/object/nc.h"
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
#include "bacfile-posix.h"

#define MAX_FIXTURE_AVS 16
#define MAX_FIXTURE_BVS 8
#define MAX_FIXTURE_FILES 8

static uint8_t Rx_Buf[MAX_MPDU];
static struct mstimer BACnet_Task_Timer;
static struct mstimer BACnet_TSM_Timer;
static struct mstimer BACnet_Address_Timer;
static struct mstimer BACnet_Object_Timer;
static volatile sig_atomic_t Running = 1;

typedef struct {
    uint32_t instance;
    const char *name;
    const char *description;
    float value;
} fixture_av_t;

typedef struct {
    uint32_t instance;
    const char *name;
    BACNET_BINARY_PV value;
} fixture_bv_t;

typedef struct {
    uint32_t instance;
    const char *name;
    const char *pathname;
    bool stream_access;
} fixture_file_t;

/* Device, Network Port, AV, BV, File, TrendLog — terminator required by Device_Init.
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
    { OBJECT_FILE, bacfile_init, bacfile_count, bacfile_index_to_instance,
        bacfile_valid_instance, bacfile_object_name, bacfile_read_property,
        bacfile_write_property, BACfile_Property_Lists, NULL, NULL, NULL, NULL,
        NULL, NULL, NULL, NULL, bacfile_create, bacfile_delete, NULL,
        BACfile_Writable_Property_List },
#if defined(INTRINSIC_REPORTING)
    /* NC instances 0..MAX_NOTIFICATION_CLASSES-1 after Notification_Class_Init.
     * Recipient_List supports AddListElement / RemoveListElement. */
    { OBJECT_NOTIFICATION_CLASS, Notification_Class_Init,
        Notification_Class_Count, Notification_Class_Index_To_Instance,
        Notification_Class_Valid_Instance, Notification_Class_Object_Name,
        Notification_Class_Read_Property, Notification_Class_Write_Property,
        Notification_Class_Property_Lists, NULL, NULL, NULL, NULL, NULL, NULL,
        Notification_Class_Add_List_Element,
        Notification_Class_Remove_List_Element, NULL, NULL, NULL,
        Notification_Class_Writable_Property_List },
#endif
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
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_ATOMIC_READ_FILE, handler_atomic_read_file);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_ATOMIC_WRITE_FILE, handler_atomic_write_file);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_CREATE_OBJECT, handler_create_object);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_DELETE_OBJECT, handler_delete_object);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_ADD_LIST_ELEMENT, handler_add_list_element);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_REMOVE_LIST_ELEMENT, handler_remove_list_element);
#if defined(INTRINSIC_REPORTING)
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_ACKNOWLEDGE_ALARM, handler_alarm_ack);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_GET_EVENT_INFORMATION, handler_get_event_information);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_GET_ALARM_SUMMARY, handler_get_alarm_summary);
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
        "[--av-instance N --av-name NAME --av-value F --av-description TEXT]... "
        "[--bv-instance N --bv-name NAME --bv-value inactive|active]... "
        "[--file-instance N --file-name NAME --file-path PATH "
        "--file-access stream|record]...\n",
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
    fixture_av_t avs[MAX_FIXTURE_AVS];
    fixture_bv_t bvs[MAX_FIXTURE_BVS];
    fixture_file_t files[MAX_FIXTURE_FILES];
    int av_count = 0;
    int bv_count = 0;
    int file_count = 0;
    bool default_av = true;
    bool default_bv = true;
    int i;

    memset(avs, 0, sizeof(avs));
    memset(bvs, 0, sizeof(bvs));
    memset(files, 0, sizeof(files));

    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--help") == 0) {
            usage(argv[0]);
            return 0;
        }
        if (strcmp(argv[i], "--version") == 0) {
            fprintf(stderr, "bacnet-interop-device-server %s\n",
                BACNET_VERSION_TEXT);
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
            if (av_count >= MAX_FIXTURE_AVS) {
                fprintf(stderr, "too many --av-instance\n");
                return 2;
            }
            avs[av_count].instance = (uint32_t)strtoul(argv[++i], NULL, 0);
            if (avs[av_count].name == NULL) {
                avs[av_count].name = "AV";
            }
            if (avs[av_count].description == NULL) {
                avs[av_count].description = "";
            }
            av_count++;
            default_av = false;
            continue;
        }
        if (strcmp(argv[i], "--av-name") == 0 && i + 1 < argc) {
            if (av_count == 0) {
                fprintf(stderr, "--av-name before --av-instance\n");
                return 2;
            }
            avs[av_count - 1].name = argv[++i];
            continue;
        }
        if (strcmp(argv[i], "--av-value") == 0 && i + 1 < argc) {
            if (av_count == 0) {
                fprintf(stderr, "--av-value before --av-instance\n");
                return 2;
            }
            avs[av_count - 1].value = strtof(argv[++i], NULL);
            continue;
        }
        if (strcmp(argv[i], "--av-description") == 0 && i + 1 < argc) {
            if (av_count == 0) {
                fprintf(stderr, "--av-description before --av-instance\n");
                return 2;
            }
            avs[av_count - 1].description = argv[++i];
            continue;
        }
        if (strcmp(argv[i], "--no-av") == 0) {
            default_av = false;
            av_count = 0;
            continue;
        }
        if (strcmp(argv[i], "--bv-instance") == 0 && i + 1 < argc) {
            if (bv_count >= MAX_FIXTURE_BVS) {
                fprintf(stderr, "too many --bv-instance\n");
                return 2;
            }
            bvs[bv_count].instance = (uint32_t)strtoul(argv[++i], NULL, 0);
            if (bvs[bv_count].name == NULL) {
                bvs[bv_count].name = "BV";
            }
            bvs[bv_count].value = BINARY_INACTIVE;
            bv_count++;
            default_bv = false;
            continue;
        }
        if (strcmp(argv[i], "--bv-name") == 0 && i + 1 < argc) {
            if (bv_count == 0) {
                fprintf(stderr, "--bv-name before --bv-instance\n");
                return 2;
            }
            bvs[bv_count - 1].name = argv[++i];
            continue;
        }
        if (strcmp(argv[i], "--bv-value") == 0 && i + 1 < argc) {
            if (bv_count == 0) {
                fprintf(stderr, "--bv-value before --bv-instance\n");
                return 2;
            }
            i++;
            if (strcmp(argv[i], "active") == 0 || strcmp(argv[i], "1") == 0) {
                bvs[bv_count - 1].value = BINARY_ACTIVE;
            } else {
                bvs[bv_count - 1].value = BINARY_INACTIVE;
            }
            continue;
        }
        if (strcmp(argv[i], "--no-bv") == 0) {
            default_bv = false;
            bv_count = 0;
            continue;
        }
        if (strcmp(argv[i], "--file-instance") == 0 && i + 1 < argc) {
            if (file_count >= MAX_FIXTURE_FILES) {
                fprintf(stderr, "too many --file-instance\n");
                return 2;
            }
            files[file_count].instance = (uint32_t)strtoul(argv[++i], NULL, 0);
            if (files[file_count].name == NULL) {
                files[file_count].name = "FILE";
            }
            files[file_count].stream_access = true;
            file_count++;
            continue;
        }
        if (strcmp(argv[i], "--file-name") == 0 && i + 1 < argc) {
            if (file_count == 0) {
                fprintf(stderr, "--file-name before --file-instance\n");
                return 2;
            }
            files[file_count - 1].name = argv[++i];
            continue;
        }
        if (strcmp(argv[i], "--file-path") == 0 && i + 1 < argc) {
            if (file_count == 0) {
                fprintf(stderr, "--file-path before --file-instance\n");
                return 2;
            }
            files[file_count - 1].pathname = argv[++i];
            continue;
        }
        if (strcmp(argv[i], "--file-access") == 0 && i + 1 < argc) {
            if (file_count == 0) {
                fprintf(stderr, "--file-access before --file-instance\n");
                return 2;
            }
            i++;
            files[file_count - 1].stream_access =
                !(strcmp(argv[i], "record") == 0);
            continue;
        }
        fprintf(stderr, "unknown argument: %s\n", argv[i]);
        usage(argv[0]);
        return 2;
    }

    if (default_av && av_count == 0) {
        avs[0].instance = 1;
        avs[0].name = "AV-1";
        avs[0].description = "Interop AV-1";
        avs[0].value = 21.5f;
        av_count = 1;
    }
    if (default_bv && bv_count == 0) {
        bvs[0].instance = 1;
        bvs[0].name = "BV-1";
        bvs[0].value = BINARY_INACTIVE;
        bv_count = 1;
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

    /* Posix file I/O callbacks for AtomicRead/WriteFile. */
    bacfile_posix_init();

    for (i = 0; i < av_count; i++) {
        if (Analog_Value_Create(avs[i].instance) != avs[i].instance) {
            fprintf(stderr, "Analog_Value_Create(%u) failed\n",
                (unsigned)avs[i].instance);
            return 1;
        }
        Analog_Value_Name_Set(avs[i].instance, (char *)avs[i].name);
        if (avs[i].description && avs[i].description[0]) {
            Analog_Value_Description_Set(
                avs[i].instance, (char *)avs[i].description);
        }
        Analog_Value_Present_Value_Set(avs[i].instance, avs[i].value, 0);
        Analog_Value_COV_Increment_Set(avs[i].instance, 0.1f);
    }
    for (i = 0; i < bv_count; i++) {
        if (Binary_Value_Create(bvs[i].instance) != bvs[i].instance) {
            fprintf(stderr, "Binary_Value_Create(%u) failed\n",
                (unsigned)bvs[i].instance);
            return 1;
        }
        Binary_Value_Name_Set(bvs[i].instance, (char *)bvs[i].name);
        Binary_Value_Write_Enable(bvs[i].instance);
        Binary_Value_Present_Value_Set(bvs[i].instance, bvs[i].value);
    }
    for (i = 0; i < file_count; i++) {
        if (!files[i].pathname || !files[i].pathname[0]) {
            fprintf(stderr, "file:%u missing --file-path\n",
                (unsigned)files[i].instance);
            return 1;
        }
        if (bacfile_create(files[i].instance) != files[i].instance) {
            fprintf(stderr, "bacfile_create(%u) failed\n",
                (unsigned)files[i].instance);
            return 1;
        }
        bacfile_object_name_set(files[i].instance, files[i].name);
        bacfile_pathname_set(files[i].instance, files[i].pathname);
        bacfile_file_access_stream_set(
            files[i].instance, files[i].stream_access);
        bacfile_read_only_set(files[i].instance, false);
        fprintf(stderr, "  file:%u %s path=%s access=%s\n",
            (unsigned)files[i].instance, files[i].name, files[i].pathname,
            files[i].stream_access ? "stream" : "record");
    }

    dlenv_init();
    atexit(datalink_cleanup);

    fprintf(stderr,
        "bacnet-interop device server\n"
        "  bacnet-stack %s\n"
        "  device %u %s\n"
        "  max APDU %d\n",
        BACNET_VERSION_TEXT, (unsigned)device_instance, device_name, MAX_APDU);
    for (i = 0; i < av_count; i++) {
        fprintf(stderr, "  analog-value:%u %s = %g\n",
            (unsigned)avs[i].instance, avs[i].name, (double)avs[i].value);
    }
    for (i = 0; i < bv_count; i++) {
        fprintf(stderr, "  binary-value:%u %s = %s\n",
            (unsigned)bvs[i].instance, bvs[i].name,
            bvs[i].value == BINARY_ACTIVE ? "active" : "inactive");
    }
    fprintf(stderr, "  file count=%d\n", file_count);
    fprintf(stderr, "  trend-log count=%u (MAX_TREND_LOGS)\n",
        (unsigned)Trend_Log_Count());
    fprintf(stderr,
        "  services: AtomicRead/WriteFile, CreateObject, DeleteObject\n");

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
