# Basic Prompt Injection Defense

Detect and filter obvious prompt injection patterns using regex-based detection.

> **Warning:** This plugin provides basic protection only and is NOT suitable for production use. Regex-based detection can be bypassed by sophisticated attacks. For production environments, implement AI-based detection or human review processes.

## Quick Reference

| Property | Value |
|----------|-------|
| Handler | `basic_prompt_injection_defense` |
| Type | Security |
| Scope | Global (can be configured globally or per-server) |

## Detection Categories

The plugin detects three categories of prompt injection patterns:

| Category | Description | Examples |
|----------|-------------|----------|
| `delimiter_injection` | Attempts to break out of context using delimiters | Triple quotes, markdown code blocks, XML tags with system/admin keywords |
| `role_manipulation` | Attempts to change the AI's role or persona | "you are now an admin", "act as system", "ignore previous role" |
| `context_hijacking` | Attempts to reset or override context | "ignore all previous instructions", "forget everything", "reset context" |

## Configuration Reference

### action

What to do when a prompt injection is detected.

| Value | Description |
|-------|-------------|
| `block` | Reject the request/response entirely |
| `redact` | Replace injection patterns with `[PROMPT INJECTION REDACTED by Gatekit]` |
| `audit_only` | Log detection but allow through unchanged |

**Default:** `redact`

### sensitivity

Controls pattern matching aggressiveness.

| Value | Description |
|-------|-------------|
| `relaxed` | Fewer patterns, only the most obvious attacks. Minimizes false positives. |
| `standard` | Balanced detection with good coverage and acceptable false positive rate. |
| `strict` | Maximum protection with more patterns. May have higher false positive rate. |

**Default:** `standard`

### detection_methods

Configure which detection categories to enable. Each has an `enabled` boolean.

| Method | Description | Default |
|--------|-------------|---------|
| `delimiter_injection` | Detect delimiter-based attacks | Enabled |
| `role_manipulation` | Detect role/persona manipulation | Enabled |
| `context_hijacking` | Detect context reset attempts | Enabled |

## YAML Configuration

### Minimal Configuration

```yaml
plugins:
  - handler: basic_prompt_injection_defense
    enabled: true
```

### Full Configuration

```yaml
plugins:
  - handler: basic_prompt_injection_defense
    enabled: true
    priority: 15              # Run early, after PII/secrets filters
    critical: true            # Block requests if plugin fails

    action: redact            # block | redact | audit_only
    sensitivity: standard     # relaxed | standard | strict

    detection_methods:
      delimiter_injection:
        enabled: true
      role_manipulation:
        enabled: true
      context_hijacking:
        enabled: true
```

### High-Security Example (Block Mode)

```yaml
plugins:
  - handler: basic_prompt_injection_defense
    enabled: true
    priority: 5
    action: block             # Never allow injections through
    sensitivity: strict       # Maximum detection (accept more false positives)

    detection_methods:
      delimiter_injection:
        enabled: true
      role_manipulation:
        enabled: true
      context_hijacking:
        enabled: true
```

### Low False-Positive Example

```yaml
plugins:
  - handler: basic_prompt_injection_defense
    enabled: true
    action: audit_only        # Log but don't interfere
    sensitivity: relaxed      # Only the most obvious attacks

    detection_methods:
      delimiter_injection:
        enabled: true
      role_manipulation:
        enabled: true
      context_hijacking:
        enabled: false        # Many legitimate uses of "start fresh"
```

## Pattern Examples by Sensitivity

### Relaxed Mode
- `[SYSTEM]...[/SYSTEM]` delimiters
- `<system>...</system>` XML tags
- "you are now an admin/administrator/root/superuser/DAN"
- "you are now operating as root/admin/system"
- "ignore all previous instructions"
- "forget everything you were told"
- "override/bypass all safety protocols"

### Standard Mode (adds)
- Triple quotes with injection keywords
- Markdown code blocks with system/admin keywords
- "ignore/disregard previous instructions/commands"
- "act as admin" patterns
- "with elevated privileges"
- "reset context/conversation/session"
- "start fresh and ignore"

### Strict Mode (adds)
- Double quotes with bypass keywords
- Shorter "you are admin" patterns
- "admin mode/access/override"
- "new conversation/session" (may catch legitimate uses)

## Limitations

This plugin will NOT detect:

- **Semantic injections** - Attacks that use meaning rather than keywords
- **Encoded attacks** - Base64, ROT13, or other encoding schemes (ROT13 was removed due to false positives)
- **Synonym-based evasion** - Using alternative words with same meaning
- **Multi-turn attacks** - Gradual context manipulation across messages
- **Context-dependent manipulation** - Attacks that depend on prior conversation
- **Advanced jailbreaking** - Sophisticated techniques that don't match simple patterns
- **Injections in responses** - Detection works on both requests and responses, but file contents from upstream servers may contain injection patterns that trigger false positives

## Redaction Format

When `action: redact`, detected patterns are replaced with:

```
[PROMPT INJECTION REDACTED by Gatekit]
```

## Security Note

Matched injection text is intentionally excluded from audit logs to prevent "log replay attacks" where an AI reviewing logs could be affected by injection patterns stored in the logs.
