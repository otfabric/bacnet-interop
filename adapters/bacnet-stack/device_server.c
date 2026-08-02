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
#include "bacnet/bacapp.h"
#include "bacnet/bacdef.h"
#include "bacnet/bacdcode.h"
#include "bacnet/wp.h"
#include "bacnet/basic/binding/address.h"
#include "bacnet/basic/object/av.h"
#include "bacnet/basic/object/bacfile.h"
#include "bacnet/basic/object/bv.h"
#include "bacnet/basic/object/device.h"
#include "bacnet/basic/object/lsp.h"
#include "bacnet/basic/object/lsz.h"
#include "bacnet/basic/object/nc.h"
#include "bacnet/basic/object/netport.h"
#include "bacnet/basic/object/trendlog.h"
#include "bacnet/basic/services.h"
#include "bacnet/basic/service/h_lso.h"
#include "bacnet/basic/service/h_ts.h"
#include "bacnet/basic/service/h_upt.h"
#include "bacnet/basic/service/h_write_group.h"
#include "bacnet/basic/sys/mstimer.h"
#include "bacnet/basic/tsm/tsm.h"
#include "bacnet/datetime.h"
#include "bacnet/datalink/datalink.h"
#include "bacnet/datalink/dlenv.h"
#include "bacnet/dcc.h"
#include "bacnet/iam.h"
#include "bacnet/npdu.h"
#include "bacnet/version.h"
#include "bacnet/whoami.h"
#include "bacnet/youare.h"
#include "bacfile-posix.h"

#define MAX_FIXTURE_AVS 16
#define MAX_FIXTURE_BVS 8
#define MAX_FIXTURE_FILES 8
#define MAX_FIXTURE_LSPS 8
#define MAX_FIXTURE_LSZS 8

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

typedef struct {
    uint32_t instance;
    const char *name;
} fixture_named_object_t;

/* Device, Network Port, AV, BV, File, TrendLog, LSP, LSZ — terminator required by Device_Init.
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
        Analog_Value_Change_Of_Value_Clear,
#if defined(INTRINSIC_REPORTING)
        Analog_Value_Intrinsic_Reporting,
#else
        NULL,
#endif
        NULL, NULL, Analog_Value_Create, Analog_Value_Delete, NULL, NULL },
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
    { OBJECT_LIFE_SAFETY_POINT, Life_Safety_Point_Init, Life_Safety_Point_Count,
        Life_Safety_Point_Index_To_Instance, Life_Safety_Point_Valid_Instance,
        Life_Safety_Point_Object_Name, Life_Safety_Point_Read_Property,
        Life_Safety_Point_Write_Property, Life_Safety_Point_Property_Lists,
        NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, Life_Safety_Point_Create,
        Life_Safety_Point_Delete, NULL, Life_Safety_Point_Writable_Property_List },
    { OBJECT_LIFE_SAFETY_ZONE, Life_Safety_Zone_Init, Life_Safety_Zone_Count,
        Life_Safety_Zone_Index_To_Instance, Life_Safety_Zone_Valid_Instance,
        Life_Safety_Zone_Object_Name, Life_Safety_Zone_Read_Property,
        Life_Safety_Zone_Write_Property, Life_Safety_Zone_Property_Lists, NULL,
        NULL, NULL, NULL, NULL, NULL, NULL, NULL, Life_Safety_Zone_Create,
        Life_Safety_Zone_Delete, NULL, Life_Safety_Zone_Writable_Property_List },
    { MAX_BACNET_OBJECT_TYPE, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
        NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL },
};

static void on_signal(int signo)
{
    (void)signo;
    Running = 0;
}

#if defined(INTRINSIC_REPORTING)
/* bacnet-stack 1.6.0 declares Analog_Value_*_Set helpers but does not
 * implement them; configure intrinsic reporting through WriteProperty. */
static bool av_wp(
    uint32_t instance, BACNET_PROPERTY_ID prop, uint8_t *apdu, int apdu_len)
{
    BACNET_WRITE_PROPERTY_DATA wp = { 0 };

    if (apdu_len < 0 || apdu_len > (int)sizeof(wp.application_data)) {
        return false;
    }
    wp.object_type = OBJECT_ANALOG_VALUE;
    wp.object_instance = instance;
    wp.object_property = prop;
    wp.array_index = BACNET_ARRAY_ALL;
    memcpy(wp.application_data, apdu, (size_t)apdu_len);
    wp.application_data_len = apdu_len;
    return Analog_Value_Write_Property(&wp);
}

static bool av_wp_real(uint32_t instance, BACNET_PROPERTY_ID prop, float value)
{
    uint8_t apdu[16];
    int len = encode_application_real(&apdu[0], value);

    return len > 0 && av_wp(instance, prop, apdu, len);
}

static bool av_wp_unsigned(
    uint32_t instance, BACNET_PROPERTY_ID prop, uint32_t value)
{
    uint8_t apdu[16];
    int len = encode_application_unsigned(&apdu[0], value);

    return len > 0 && av_wp(instance, prop, apdu, len);
}

static bool av_wp_enum(
    uint32_t instance, BACNET_PROPERTY_ID prop, uint32_t value)
{
    uint8_t apdu[16];
    int len = encode_application_enumerated(&apdu[0], value);

    return len > 0 && av_wp(instance, prop, apdu, len);
}

static bool av_wp_bitstring(
    uint32_t instance, BACNET_PROPERTY_ID prop, uint8_t bits, uint8_t bits_used)
{
    BACNET_BIT_STRING bs;
    uint8_t apdu[16];
    int len;
    unsigned i;

    bitstring_init(&bs);
    for (i = 0; i < bits_used; i++) {
        bitstring_set_bit(&bs, (uint8_t)i, (bits & (1u << i)) != 0);
    }
    len = encode_application_bitstring(&apdu[0], &bs);
    return len > 0 && av_wp(instance, prop, apdu, len);
}

static bool configure_av_intrinsic_reporting(uint32_t instance)
{
    /* Match device-baseline-v3 / BACnet4J: PV>80 → Out_Of_Range alarm. */
    if (!av_wp_real(instance, PROP_HIGH_LIMIT, 80.0f)) {
        return false;
    }
    if (!av_wp_real(instance, PROP_LOW_LIMIT, 0.0f)) {
        return false;
    }
    if (!av_wp_real(instance, PROP_DEADBAND, 0.0f)) {
        return false;
    }
    if (!av_wp_unsigned(instance, PROP_TIME_DELAY, 0)) {
        return false;
    }
    if (!av_wp_unsigned(instance, PROP_NOTIFICATION_CLASS, 1)) {
        return false;
    }
    if (!av_wp_bitstring(instance, PROP_LIMIT_ENABLE,
            (uint8_t)(EVENT_LOW_LIMIT_ENABLE | EVENT_HIGH_LIMIT_ENABLE), 2)) {
        return false;
    }
    if (!av_wp_bitstring(instance, PROP_EVENT_ENABLE,
            (uint8_t)(EVENT_ENABLE_TO_OFFNORMAL | EVENT_ENABLE_TO_FAULT |
                EVENT_ENABLE_TO_NORMAL),
            3)) {
        return false;
    }
    if (!av_wp_enum(instance, PROP_NOTIFY_TYPE, NOTIFY_ALARM)) {
        return false;
    }
    if (!Analog_Value_Event_Detection_Enable_Set(instance, true)) {
        return false;
    }
    return true;
}
#endif

/* Adapter diagnostic JSON Lines on stdout (forwarded by run_server.py). */
static void emit_operation(const char *operation)
{
    printf("{\"event\":\"operation\",\"adapter\":\"bacnet-stack\","
           "\"operation\":\"%s\",\"result\":\"accepted\"}\n",
        operation);
    fflush(stdout);
}

static void interop_timesync_callback(
    BACNET_DATE *bdate, BACNET_TIME *btime, bool utc)
{
    (void)bdate;
    (void)btime;
    emit_operation(utc ? "utc-time-synchronization" : "time-synchronization");
}

static void interop_unconfirmed_private_transfer(
    uint8_t *service_request, uint16_t service_len, BACNET_ADDRESS *src)
{
    handler_unconfirmed_private_transfer(service_request, service_len, src);
    emit_operation("unconfirmed-private-transfer");
}

static void interop_write_group(
    uint8_t *service_request, uint16_t service_len, BACNET_ADDRESS *src)
{
    handler_write_group(service_request, service_len, src);
    emit_operation("write-group");
}

static void interop_who_am_i(
    uint8_t *service_request, uint16_t service_len, BACNET_ADDRESS *src)
{
    uint16_t vendor_id = 0;
    BACNET_CHARACTER_STRING model_name = { 0 };
    BACNET_CHARACTER_STRING serial_number = { 0 };
    int len;

    (void)src;
    len = who_am_i_request_decode(
        service_request, service_len, &vendor_id, &model_name, &serial_number);
    if (len > 0) {
        emit_operation("who-am-i");
    }
}

static void interop_you_are(
    uint8_t *service_request, uint16_t service_len, BACNET_ADDRESS *src)
{
    uint32_t device_id = 0;
    uint16_t vendor_id = 0;
    BACNET_CHARACTER_STRING model_name = { 0 };
    BACNET_CHARACTER_STRING serial_number = { 0 };
    BACNET_OCTET_STRING mac_address = { 0 };
    int len;

    (void)src;
    len = you_are_request_decode(service_request, service_len, &device_id,
        &vendor_id, &model_name, &serial_number, &mac_address);
    if (len > 0) {
        emit_operation("you-are");
    }
}

static void interop_lso(
    uint8_t *service_request,
    uint16_t service_len,
    BACNET_ADDRESS *src,
    BACNET_CONFIRMED_SERVICE_DATA *service_data)
{
    handler_lso(service_request, service_len, src, service_data);
    emit_operation("life-safety-operation");
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

    /* Messaging / time / group (device-baseline-v6). TextMessage and
     * ConfirmedPrivateTransfer are unsupported-upstream at bacnet-stack 1.6.0. */
    apdu_set_unconfirmed_handler(
        SERVICE_UNCONFIRMED_TIME_SYNCHRONIZATION, handler_timesync);
    apdu_set_unconfirmed_handler(
        SERVICE_UNCONFIRMED_UTC_TIME_SYNCHRONIZATION, handler_timesync_utc);
    handler_timesync_init();
    handler_timesync_set_callback_set(interop_timesync_callback);
    apdu_set_unconfirmed_handler(SERVICE_UNCONFIRMED_PRIVATE_TRANSFER,
        interop_unconfirmed_private_transfer);
    apdu_set_unconfirmed_handler(
        SERVICE_UNCONFIRMED_WRITE_GROUP, interop_write_group);

    /* Identity + life safety (device-baseline-v7 / v8). */
    apdu_set_unconfirmed_handler(SERVICE_UNCONFIRMED_WHO_AM_I, interop_who_am_i);
    apdu_set_unconfirmed_handler(SERVICE_UNCONFIRMED_YOU_ARE, interop_you_are);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_LIFE_SAFETY_OPERATION, interop_lso);

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
        "--file-access stream|record]... "
        "[--lsp-instance N --lsp-name NAME]... "
        "[--lsz-instance N --lsz-name NAME]...\n",
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
    fixture_named_object_t lsps[MAX_FIXTURE_LSPS];
    fixture_named_object_t lszs[MAX_FIXTURE_LSZS];
    int av_count = 0;
    int bv_count = 0;
    int file_count = 0;
    int lsp_count = 0;
    int lsz_count = 0;
    bool default_av = true;
    bool default_bv = true;
    int i;

    memset(avs, 0, sizeof(avs));
    memset(bvs, 0, sizeof(bvs));
    memset(files, 0, sizeof(files));
    memset(lsps, 0, sizeof(lsps));
    memset(lszs, 0, sizeof(lszs));

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
        if (strcmp(argv[i], "--lsp-instance") == 0 && i + 1 < argc) {
            if (lsp_count >= MAX_FIXTURE_LSPS) {
                fprintf(stderr, "too many --lsp-instance\n");
                return 2;
            }
            lsps[lsp_count].instance = (uint32_t)strtoul(argv[++i], NULL, 0);
            if (lsps[lsp_count].name == NULL) {
                lsps[lsp_count].name = "LSP";
            }
            lsp_count++;
            continue;
        }
        if (strcmp(argv[i], "--lsp-name") == 0 && i + 1 < argc) {
            if (lsp_count == 0) {
                fprintf(stderr, "--lsp-name before --lsp-instance\n");
                return 2;
            }
            lsps[lsp_count - 1].name = argv[++i];
            continue;
        }
        if (strcmp(argv[i], "--lsz-instance") == 0 && i + 1 < argc) {
            if (lsz_count >= MAX_FIXTURE_LSZS) {
                fprintf(stderr, "too many --lsz-instance\n");
                return 2;
            }
            lszs[lsz_count].instance = (uint32_t)strtoul(argv[++i], NULL, 0);
            if (lszs[lsz_count].name == NULL) {
                lszs[lsz_count].name = "LSZ";
            }
            lsz_count++;
            continue;
        }
        if (strcmp(argv[i], "--lsz-name") == 0 && i + 1 < argc) {
            if (lsz_count == 0) {
                fprintf(stderr, "--lsz-name before --lsz-instance\n");
                return 2;
            }
            lszs[lsz_count - 1].name = argv[++i];
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
#if defined(INTRINSIC_REPORTING)
        if (!configure_av_intrinsic_reporting(avs[i].instance)) {
            fprintf(stderr,
                "Analog_Value intrinsicReporting configure failed for %u\n",
                (unsigned)avs[i].instance);
            return 1;
        }
        fprintf(stderr,
            "  analog-value:%u intrinsicReporting highLimit=80 nc=1\n",
            (unsigned)avs[i].instance);
#endif
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
    for (i = 0; i < lsp_count; i++) {
        if (Life_Safety_Point_Create(lsps[i].instance) != lsps[i].instance) {
            fprintf(stderr, "Life_Safety_Point_Create(%u) failed\n",
                (unsigned)lsps[i].instance);
            return 1;
        }
        Life_Safety_Point_Name_Set(lsps[i].instance, lsps[i].name);
        fprintf(stderr, "  life-safety-point:%u %s\n",
            (unsigned)lsps[i].instance, lsps[i].name);
    }
    for (i = 0; i < lsz_count; i++) {
        if (Life_Safety_Zone_Create(lszs[i].instance) != lszs[i].instance) {
            fprintf(stderr, "Life_Safety_Zone_Create(%u) failed\n",
                (unsigned)lszs[i].instance);
            return 1;
        }
        Life_Safety_Zone_Name_Set(lszs[i].instance, lszs[i].name);
        fprintf(stderr, "  life-safety-zone:%u %s\n",
            (unsigned)lszs[i].instance, lszs[i].name);
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
        "  services: AtomicRead/WriteFile, CreateObject, DeleteObject"
#if defined(INTRINSIC_REPORTING)
        ", GetAlarmSummary"
#endif
        ", Who-Am-I, You-Are, LifeSafetyOperation"
        "\n");

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
#if defined(INTRINSIC_REPORTING)
            /* Run AV/AI intrinsic Out_Of_Range evaluation (not done by Device_Timer). */
            Device_local_reporting();
#endif
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
