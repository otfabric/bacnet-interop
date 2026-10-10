// SPDX-License-Identifier: MIT
//
// System.IO.BACnet device server for bacnet-interop.
//
// Loads a device-baseline fixture, builds the upstream DeviceStorage object
// model from it, binds BACnet/IP, emits one JSON Lines ready event on stdout
// and serves until SIGTERM/SIGINT. Diagnostics go to stderr.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.BACnet;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Threading;

namespace Otfabric.BacnetInterop.SysIoBacnet;

internal static class Program
{
    internal const string AdapterName = "sysiobacnet";
    private const string FixtureDefault = "device-baseline-v2";
    private const string FixturePathDefault = "/fixtures/device/device-baseline-v2.json";
    private const int PortDefault = 0xBAC0;

    private static readonly object StdoutGate = new();

    private static int Main()
    {
        try
        {
            return Run();
        }
        catch (Exception ex) when (ex is InvalidOperationException or InvalidDataException or FormatException or FileNotFoundException)
        {
            // Configuration the adapter refuses: the message says it all.
            Console.Error.WriteLine($"{AdapterName} adapter failed to start: {ex.Message}");
            return 1;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"{AdapterName} adapter failed to start: {ex}");
            if (ex is System.Net.Sockets.SocketException)
                DumpUdpSockets();
            return 1;
        }
    }

    private static int Run()
    {
        // Modes other adapters offer that this one does not: refuse instead of
        // starting in a mode the caller did not ask for.
        foreach (var unsupported in new[] { "BACNET_BBMD", "BACNET_NETWORK" })
        {
            var v = Env(unsupported, "");
            if (v != "" && v != "0" && !v.Equals("false", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException($"{unsupported}={v} is not supported by the {AdapterName} adapter");
        }

        var port = int.Parse(Env("BACNET_IP_PORT", PortDefault.ToString(CultureInfo.InvariantCulture)), CultureInfo.InvariantCulture);
        var fixturePath = Env("DEVICE_FIXTURE_FILE", FixturePathDefault);
        var adapterVersion = Env("ADAPTER_VERSION", "dev");
        var peerVersion = UpstreamVersion();
        var bindIp = BindAddress(Env("BACNET_DEVICE_ADDRESS", ""));
        var maxApdu = MaxApdu(Env("BACNET_MAX_APDU", "0"));

        using var doc = JsonDocument.Parse(File.ReadAllText(fixturePath));
        var fixture = doc.RootElement;
        if (fixture.ValueKind != JsonValueKind.Object
            || !fixture.TryGetProperty("device_instance", out _)
            || !fixture.TryGetProperty("device_name", out _))
            throw new InvalidDataException("device fixture requires device_instance and device_name");
        var fixtureId = fixture.TryGetProperty("fixture", out var f) && f.ValueKind == JsonValueKind.String
            ? f.GetString()!
            : Env("FIXTURE", FixtureDefault);

        BacnetLogging.Factory = new StderrLoggerFactory(Env("SYSIOBACNET_LOG", "warning"));

        // One exclusive socket on the BACnet port: the container has a single
        // interface and nothing else binds 47808 in it.
        var transport = new BacnetIpUdpProtocolTransport(port, useExclusivePort: true,
            localEndpointIp: bindIp, maxApdu: maxApdu);
        // 999 is the vendor identifier every bacnet-interop adapter announces
        // (the stack's default, 260, belongs to another vendor).
        using var client = new BacnetClient(transport) { VendorId = 999 };

        var model = DeviceModel.FromFixture(fixture, client, adapterVersion, peerVersion);
        var emitEvent = Env("BACNET_EMIT_EVENT", "") is "1" or "true" or "yes";
        using var server = new DeviceServer(client, model, emitEvent);
        server.Start();

        EmitReady(adapterVersion, fixtureId, port, peerVersion);
        Console.Error.WriteLine(
            $"{AdapterName} listening bind={(bindIp == "" ? "0.0.0.0" : bindIp)}:{port} maxApdu={client.GetMaxApdu()} device={model.Storage.DeviceId}");

        using var stop = new ManualResetEventSlim(false);
        using var sigterm = PosixSignalRegistration.Create(PosixSignal.SIGTERM, ctx => { ctx.Cancel = true; stop.Set(); });
        using var sigint = PosixSignalRegistration.Create(PosixSignal.SIGINT, ctx => { ctx.Cancel = true; stop.Set(); });
        stop.Wait();
        return 0;
    }

    // A bind failure in a fresh container means something else in the network
    // namespace holds the port (on a user-defined Docker network the embedded
    // DNS resolver binds 127.0.0.11 on a random ephemeral UDP port, and 47808 is
    // inside the ephemeral range). Show who.
    private static void DumpUdpSockets()
    {
        try
        {
            Console.Error.WriteLine($"{AdapterName} UDP sockets in this network namespace (/proc/net/udp):");
            Console.Error.WriteLine(File.ReadAllText("/proc/net/udp"));
        }
        catch (Exception)
        {
            // diagnostics only
        }
    }

    internal static string Env(string name, string fallback)
    {
        var v = Environment.GetEnvironmentVariable(name);
        return string.IsNullOrWhiteSpace(v) ? fallback : v.Trim();
    }

    // BACNET_DEVICE_ADDRESS is a bind IP (optionally ip:port, as other adapters
    // accept); empty or a wildcard binds every interface.
    private static string BindAddress(string raw)
    {
        if (raw == "") return "";
        var host = raw;
        var slash = host.IndexOf('/');
        if (slash >= 0) host = host[..slash];
        var colon = host.LastIndexOf(':');
        if (colon >= 0) host = host[..colon];
        if (host is "" or "host" or "0.0.0.0") return "";
        if (!System.Net.IPAddress.TryParse(host, out var ip) || ip.AddressFamily != System.Net.Sockets.AddressFamily.InterNetwork)
            throw new InvalidOperationException($"BACNET_DEVICE_ADDRESS={raw}: expected an IPv4 address");
        return host;
    }

    // The stack only knows the six standard Max-APDU-Length-Accepted sizes.
    private static BacnetMaxAdpu MaxApdu(string raw)
    {
        var n = int.Parse(raw, CultureInfo.InvariantCulture);
        return n switch
        {
            0 or 1476 => BacnetMaxAdpu.MAX_APDU1476,
            1024 => BacnetMaxAdpu.MAX_APDU1024,
            480 => BacnetMaxAdpu.MAX_APDU480,
            206 => BacnetMaxAdpu.MAX_APDU206,
            128 => BacnetMaxAdpu.MAX_APDU128,
            50 => BacnetMaxAdpu.MAX_APDU50,
            _ => throw new InvalidOperationException(
                $"BACNET_MAX_APDU={raw}: System.IO.BACnet supports 50, 128, 206, 480, 1024 or 1476"),
        };
    }

    // The version of the BACnet assembly actually loaded, not a build argument.
    private static string UpstreamVersion()
    {
        var asm = typeof(BacnetClient).Assembly;
        var info = asm.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion;
        if (string.IsNullOrEmpty(info))
            return asm.GetName().Version?.ToString() ?? "unknown";
        var plus = info.IndexOf('+');
        return plus >= 0 ? info[..plus] : info;
    }

    private static void EmitReady(string version, string fixture, int port, string peerVersion)
    {
        WriteJsonLine(new Dictionary<string, string>
        {
            ["event"] = "ready",
            ["adapter"] = AdapterName,
            ["version"] = version,
            ["fixture"] = fixture,
            ["address"] = $"0.0.0.0:{port}",
            ["peer_version"] = peerVersion,
        });
    }

    // Adapter diagnostic JSON Lines event (not cross-stack semantics).
    internal static void EmitOperation(string operation, string result = "accepted")
    {
        WriteJsonLine(new Dictionary<string, string>
        {
            ["event"] = "operation",
            ["adapter"] = AdapterName,
            ["operation"] = operation,
            ["result"] = result,
        });
    }

    private static void WriteJsonLine(Dictionary<string, string> fields)
    {
        using var ms = new MemoryStream();
        using (var w = new Utf8JsonWriter(ms))
        {
            w.WriteStartObject();
            foreach (var kv in fields) w.WriteString(kv.Key, kv.Value);
            w.WriteEndObject();
        }
        var line = System.Text.Encoding.UTF8.GetString(ms.ToArray());
        lock (StdoutGate)
        {
            Console.Out.WriteLine(line);
            Console.Out.Flush();
        }
    }
}
