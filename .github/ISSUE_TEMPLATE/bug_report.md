---
name: Bug report
about: Create a report to help us improve
title: ''
labels: ''
assignees: dougbright

---

Body:
  **What happened?**
  Describe the issue you encountered.

  **Environment**
  - OS: (macOS / Windows / Linux)
  - Python version: (`python --version`)
  - Gatekit version: (`gatekit --version`)

**If this is a TUI issue:**
  - Terminal: (e.g., Terminal.app, iTerm2, Windows Terminal, Alacritty)
  - Running over SSH: (yes/no)

**How to reproduce**
  Steps to trigger the bug, if known.

**Error output or logs**

For TUI issues, run with `gatekit --debug`. When you quit, it will print the location of the debug log file. Attach that file or paste relevant sections here.

For gateway issues, check your config file's `logging:` section for `file_path` to find the gateway log location.

Paste any error messages or relevant log output here.

**Configuration (if relevant)**

Paste the relevant YAML snippet (remove sensitive values), or attach a screenshot from the TUI.
