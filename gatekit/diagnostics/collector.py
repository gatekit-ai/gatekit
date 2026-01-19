#!/usr/bin/env python3
"""Gatekit Diagnostics Collector - User-facing utility for bug reporting and troubleshooting.

This module provides diagnostic data collection capabilities for Gatekit TUI sessions,
enabling users to generate comprehensive bug reports and support requests.
"""

import os
import glob
from pathlib import Path
import json
from datetime import datetime

from ..tui.platform_paths import get_user_log_dir


def get_debug_files() -> dict:
    """Get all current TUI debug files for diagnostic purposes.

    Returns:
        Dictionary with debug_logs and state_dumps lists for user diagnostics
    """
    log_dir = get_user_log_dir('gatekit')

    # Find debug log files
    debug_logs = glob.glob(os.path.join(log_dir, "gatekit_tui_debug*.log*"))

    # Find state dump files
    state_dumps = glob.glob(os.path.join(log_dir, "gatekit_tui_state_*.json"))

    return {
        "log_dir": str(log_dir),
        "debug_logs": sorted(debug_logs),
        "state_dumps": sorted(state_dumps, reverse=True),  # Most recent first
    }


def show_debug_files() -> None:
    """Show TUI diagnostic files to user for bug reporting."""
    files = get_debug_files()

    print("🔍 Gatekit TUI Diagnostic Files")
    print("=" * 50)
    print(f"Location: {files['log_dir']}")
    print("\nThese files can help with bug reports and troubleshooting.")

    # Check for active debug session info
    info_file = Path(files["log_dir"]) / "gatekit_debug_session.txt"
    if info_file.exists():
        print("\n📋 Active Debug Session:")
        try:
            with open(info_file, "r") as f:
                content = f.read()
            print(content)
        except Exception:
            print("  (Could not read session info)")

    print()

    # Show debug logs
    if files["debug_logs"]:
        print("📝 Activity Logs:")
        for log_file in files["debug_logs"]:
            path = Path(log_file)
            size = path.stat().st_size if path.exists() else 0
            mod_time = (
                datetime.fromtimestamp(path.stat().st_mtime)
                if path.exists()
                else "Unknown"
            )
            print(f"  - {path.name} ({size} bytes, {mod_time})")
    else:
        print("📝 Activity Logs: None found")

    print()

    # Show state dumps
    if files["state_dumps"]:
        print("🎯 State Snapshots:")
        for state_file in files["state_dumps"][:5]:  # Show most recent 5
            path = Path(state_file)
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    screen_type = data.get("screen_type", "Unknown")
                    timestamp = data.get("timestamp", "Unknown")
                print(f"  - {path.name} ({screen_type}, {timestamp})")
            except Exception:
                print(f"  - {path.name} (could not read)")

        if len(files["state_dumps"]) > 5:
            print(f"  ... and {len(files['state_dumps']) - 5} more")
    else:
        print("🎯 State Snapshots: None found")

    print()
    print("💡 For Bug Reports:")
    print("  Include activity logs and state snapshots with your issue description")
    print(f"  Files location: {files['log_dir']}")
    print()
    print("💡 Analysis Commands:")
    print("  gatekit --show-debug-files")
    print("  python -m gatekit.diagnostics.collector actions")
    print("  python -m gatekit.diagnostics.collector state")


def show_recent_actions(lines: int = 20) -> None:
    """Show recent user actions for troubleshooting TUI issues.

    This function provides a user-friendly summary of TUI interactions
    that can help identify what led to a problem or unexpected behavior.

    Args:
        lines: Number of recent events to analyze
    """
    files = get_debug_files()

    if not files["debug_logs"]:
        print("❌ No activity logs found")
        print("\n💡 To generate activity logs:")
        print("  1. Run: gatekit --debug")
        print("  2. Reproduce your issue in the TUI")
        print("  3. Run this command again")
        return

    # Use the most recent debug log
    latest_log = files["debug_logs"][-1]

    try:
        with open(latest_log, "r") as f:
            log_lines = f.readlines()

        print(f"🎬 Recent User Actions (last {lines} events):")
        print("=" * 60)
        print("This shows what you did in the TUI that might help troubleshoot issues.")
        print()

        # Focus on the most interesting events for user analysis
        interesting_events = []

        for line in log_lines[-lines:]:
            try:
                event = json.loads(line.strip())
                event_type = event.get("event_type", "unknown")
                timestamp = event.get("timestamp", "No timestamp")[
                    -8:
                ]  # Last 8 chars (time)
                context = event.get("context", {})
                data = event.get("data", {})

                # Focus on user actions and value changes
                if event_type == "checkbox_toggle":
                    context.get("plugin_name", "unknown")
                    context.get("plugin_type", "unknown")
                    action_desc = context.get("action_description", "toggled")
                    data.get("old_checked", False)
                    data.get("new_checked", False)
                    interesting_events.append(f"  {timestamp} 🔘 {action_desc}")

                elif event_type == "input_change":
                    context.get("field_name", "input")
                    action_desc = context.get("action_description", "changed")
                    data.get("old_text", "")
                    data.get("new_text", "")
                    text_change = context.get("text_length_change", 0)
                    change_desc = (
                        f"(+{text_change} chars)"
                        if text_change > 0
                        else (
                            f"({text_change} chars)"
                            if text_change < 0
                            else "(same length)"
                        )
                    )
                    interesting_events.append(
                        f"  {timestamp} ⌨️  {action_desc} {change_desc}"
                    )

                elif event_type == "navigation":
                    direction = context.get("direction", "?")
                    from_container = context.get("from_container", "?")
                    to_container = context.get("to_container", "?")
                    interesting_events.append(
                        f"  {timestamp} 🧭 navigated {direction}: {from_container} → {to_container}"
                    )

                elif event_type == "user_input":
                    context.get("input_type", "?")
                    key = context.get("key", "?")
                    if key in ["space", "enter", "tab"]:
                        interesting_events.append(f"  {timestamp} ⌨️  pressed {key}")

                elif event_type == "state_dump":
                    interesting_events.append(
                        f"  {timestamp} 📸 created state snapshot (Ctrl+Shift+D)"
                    )

            except json.JSONDecodeError:
                continue

        # Display the interesting events
        if interesting_events:
            for event in interesting_events:
                print(event)
        else:
            print("  No significant user actions found in recent events")

        print(f"\n💡 For detailed technical logs, use: tail_debug_log({lines})")
        print(
            "💡 Include this action summary in bug reports to help support understand what happened"
        )

    except Exception as e:
        print(f"❌ Error reading activity log: {e}")


def tail_debug_log(lines: int = 10) -> None:
    """Show detailed technical debug log entries.

    This provides raw technical data for advanced troubleshooting.

    Args:
        lines: Number of lines to show
    """
    files = get_debug_files()

    if not files["debug_logs"]:
        print("❌ No debug log files found")
        return

    # Use the most recent debug log
    latest_log = files["debug_logs"][-1]

    try:
        with open(latest_log, "r") as f:
            log_lines = f.readlines()

        print(f"📝 Technical Debug Log (last {lines} events):")
        print("=" * 60)
        print("This is detailed technical data for advanced troubleshooting.")
        print()

        for line in log_lines[-lines:]:
            try:
                event = json.loads(line.strip())
                timestamp = event.get("timestamp", "No timestamp")
                event_type = event.get("event_type", "unknown")
                context = event.get("context", {})

                # Format context info
                context_str = ""
                if context:
                    if "key" in context:
                        context_str = f" (key={context['key']})"
                    elif "direction" in context:
                        context_str = f" ({context['direction']}: {context.get('from_container', '?')} → {context.get('to_container', '?')})"
                    elif "component" in context:
                        context_str = f" ({context['component']})"

                print(f"  {timestamp} - {event_type}{context_str}")

            except json.JSONDecodeError:
                print(f"  {line.strip()}")

    except Exception as e:
        print(f"❌ Error reading debug log: {e}")


def view_latest_state_dump() -> None:
    """View the most recent TUI state snapshot for troubleshooting."""
    files = get_debug_files()

    if not files["state_dumps"]:
        print("❌ No state snapshots found")
        print("\n💡 To create state snapshots:")
        print("  1. Run: gatekit --debug")
        print("  2. In the TUI, press Ctrl+Shift+D to capture state")
        print("  3. Run this command again")
        return

    latest_dump = files["state_dumps"][0]  # Most recent first

    try:
        with open(latest_dump, "r") as f:
            data = json.load(f)

        print(f"🎯 Latest TUI State Snapshot: {Path(latest_dump).name}")
        print("=" * 60)
        print("This shows the TUI state when you pressed Ctrl+Shift+D")
        print()
        print(f"Session ID: {data.get('session_id', 'Unknown')}")
        print(f"Captured At: {data.get('timestamp', 'Unknown')}")
        print(f"Screen: {data.get('screen_type', 'Unknown')}")

        # Show focused widget
        focused = data.get("focused_widget")
        if focused:
            print(
                f"Focused Element: {focused.get('class', 'Unknown')} (id={focused.get('id', 'None')})"
            )

        # Show navigation state
        nav_state = data.get("navigation_state", {})
        if nav_state:
            current_idx = nav_state.get("current_container_index", 0)
            containers = nav_state.get("container_names", [])
            if containers:
                current_container = (
                    containers[current_idx]
                    if current_idx < len(containers)
                    else "Unknown"
                )
                print(
                    f"Current Section: {current_container} ({current_idx + 1}/{len(containers)})"
                )

        # Show focus memory
        focus_memory = data.get("focus_memory", {})
        if focus_memory:
            print(f"Focus Memory: {len(focus_memory)} remembered positions")
            for container, widget_info in focus_memory.items():
                if isinstance(widget_info, dict):
                    widget_class = widget_info.get("class", "Unknown")
                    widget_id = widget_info.get("id", "None")
                    print(f"  - {container}: {widget_class} (id={widget_id})")

        print(
            "\n💡 Include this state information in bug reports if the issue is related to"
        )
        print("    navigation, focus, or unexpected TUI behavior.")

    except Exception as e:
        print(f"❌ Error reading state snapshot: {e}")


def cleanup_old_files(days: int = 7) -> None:
    """Clean up old diagnostic files to save disk space.

    Args:
        days: Remove files older than this many days
    """
    files = get_debug_files()

    import time

    cutoff_time = time.time() - (days * 24 * 60 * 60)

    removed_logs = 0
    removed_dumps = 0

    # Clean up debug logs
    for log_file in files["debug_logs"]:
        try:
            if os.path.getmtime(log_file) < cutoff_time:
                os.remove(log_file)
                removed_logs += 1
        except Exception:  # noqa: S110
            pass  # Best-effort cleanup - ignore file deletion failures

    # Clean up state dumps
    for dump_file in files["state_dumps"]:
        try:
            if os.path.getmtime(dump_file) < cutoff_time:
                os.remove(dump_file)
                removed_dumps += 1
        except Exception:  # noqa: S110
            pass  # Best-effort cleanup - ignore file deletion failures

    print(
        f"🧹 Cleaned up {removed_logs} activity logs and {removed_dumps} state snapshots older than {days} days"
    )


def main():
    """User-friendly command line interface for Gatekit diagnostics."""
    import sys

    print("🔧 Gatekit Diagnostics")
    print("Help diagnose TUI issues and create better bug reports")
    print()

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "show":
            show_debug_files()
        elif command == "actions":
            lines = int(sys.argv[2]) if len(sys.argv) > 2 else 20
            show_recent_actions(lines)
        elif command == "tail":
            lines = int(sys.argv[2]) if len(sys.argv) > 2 else 10
            tail_debug_log(lines)
        elif command == "state":
            view_latest_state_dump()
        elif command == "cleanup":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
            cleanup_old_files(days)
        else:
            print("❌ Unknown command")
            print("\n📋 Available commands:")
            print("  show           - List all diagnostic files")
            print("  actions [N]    - Show recent user actions (default: 20)")
            print("  state          - View latest state snapshot")
            print("  tail [N]       - Show technical debug log (default: 10)")
            print("  cleanup [N]    - Remove files older than N days (default: 7)")
            print("\n💡 To generate diagnostic data:")
            print("  1. Run: gatekit --debug")
            print("  2. Use the TUI and reproduce your issue")
            print("  3. Use these commands to analyze what happened")
    else:
        show_debug_files()


if __name__ == "__main__":
    main()
