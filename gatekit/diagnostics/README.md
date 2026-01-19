# Gatekit Diagnostics

User-facing diagnostic tools for Gatekit TUI bug reporting and troubleshooting.

## Purpose

This module provides tools to help users:
- Understand what happened when TUI issues occur
- Generate comprehensive bug reports
- Troubleshoot configuration and navigation problems
- Share diagnostic data with support teams

## Files

### `collector.py`
Main diagnostic data collection and analysis tool. Can be run as:

```bash
# Show all diagnostic files
python -m gatekit.diagnostics.collector

# Show recent user actions (great for bug reports)
python -m gatekit.diagnostics.collector actions

# View latest state snapshot
python -m gatekit.diagnostics.collector state

# Show technical debug log
python -m gatekit.diagnostics.collector tail

# Clean up old files
python -m gatekit.diagnostics.collector cleanup
```

### Integration with main CLI

```bash
# Show diagnostic files
gatekit --diagnostics
gatekit --show-debug-files  # Same as above

# Generate diagnostic data
gatekit --debug  # Run TUI with enhanced logging
```

## Workflow for Bug Reports

1. **Enable diagnostics**: `gatekit --debug`
2. **Reproduce the issue** in the TUI
3. **Collect data**: `gatekit --diagnostics`
4. **Get action summary**: `python -m gatekit.diagnostics.collector actions`
5. **Include both in bug report** along with config file

## Future Enhancements

This structure is designed to support:
- Automatic issue detection ("You navigated in circles 5 times")
- Config validation and suggestions
- Data sanitization for privacy
- One-click bug report generation
- Integration with support ticketing systems