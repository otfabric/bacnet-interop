// SPDX-License-Identifier: MIT

using System;
using Microsoft.Extensions.Logging;

namespace Otfabric.BacnetInterop.SysIoBacnet;

// Minimal stderr sink for the stack's Microsoft.Extensions.Logging output.
// SYSIOBACNET_LOG selects the level (trace|debug|information|warning|error|none);
// the default "warning" keeps the adapter quiet in normal runs.
internal sealed class StderrLoggerFactory : ILoggerFactory
{
    private readonly LogLevel _min;

    public StderrLoggerFactory(string level)
    {
        _min = Enum.TryParse<LogLevel>(level, ignoreCase: true, out var parsed) ? parsed : LogLevel.Warning;
    }

    public ILogger CreateLogger(string categoryName) => new StderrLogger(categoryName, _min);

    public void AddProvider(ILoggerProvider provider) { }

    public void Dispose() { }

    private sealed class StderrLogger : ILogger
    {
        private readonly string _category;
        private readonly LogLevel _min;

        public StderrLogger(string category, LogLevel min)
        {
            var dot = category.LastIndexOf('.');
            _category = dot >= 0 ? category[(dot + 1)..] : category;
            _min = min;
        }

        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

        public bool IsEnabled(LogLevel logLevel) => logLevel != LogLevel.None && logLevel >= _min;

        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception,
            Func<TState, Exception?, string> formatter)
        {
            if (!IsEnabled(logLevel)) return;
            var line = $"sysiobacnet {logLevel.ToString().ToLowerInvariant()} {_category}: {formatter(state, exception)}";
            if (exception != null) line += $" ({exception.GetType().Name}: {exception.Message})";
            Console.Error.WriteLine(line);
        }
    }
}
