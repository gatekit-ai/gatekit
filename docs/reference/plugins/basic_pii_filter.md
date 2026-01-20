# Basic PII Filter

Detect and filter personally identifiable information (PII) using regex-based pattern matching.

> **Warning:** This plugin provides basic protection only and is NOT suitable for production use. Regex-based detection can be bypassed with encoding, obfuscation, or novel formats. For production environments, use enterprise-grade PII detection solutions like Microsoft Presidio.

## Quick Reference

| Property | Value |
|----------|-------|
| Handler | `basic_pii_filter` |
| Type | Security |
| Scope | Global (can be configured globally or per-server) |

## Detected PII Types

| Type | Description | Example Patterns |
|------|-------------|------------------|
| `email` | RFC 5322 compliant email addresses | `user@example.com` |
| `phone` | US phone numbers only | `(555) 123-4567`, `555-123-4567`, `555.123.4567` |
| `credit_card` | Major card brands with Luhn validation | Visa, MasterCard, Amex, Discover |
| `ip_address` | IPv4 and IPv6 addresses | `192.168.1.1`, `2001:db8::1` |
| `national_id` | US SSN, UK NI, Canadian SIN | `123-45-6789` (formatted only) |

> **Credit card Luhn validation:** Only credit card numbers that pass the [Luhn checksum](https://en.wikipedia.org/wiki/Luhn_algorithm) are detected. Numbers that look like credit cards but fail validation (e.g., test numbers, typos) will not be flagged.

## Configuration Reference

### action

What to do when PII is detected.

| Value | Description |
|-------|-------------|
| `block` | Reject the request/response entirely |
| `redact` | Replace PII with `[TYPE REDACTED by Gatekit]` placeholders |
| `audit_only` | Log detection but allow through unchanged |

**Default:** `redact`

### pii_types

Configure which PII types to detect. Each type has an `enabled` boolean.

**Default:** All types enabled

### scan_base64

Decode and scan base64-encoded content for PII.

**Default:** `false`

> **Note:** Base64 content cannot be safely redacted (would corrupt data). When `scan_base64` is enabled and PII is found in base64 content, the plugin forces blocking even if `action` is set to `redact`.

## YAML Configuration

### Minimal Configuration

```yaml
plugins:
  - handler: basic_pii_filter
    enabled: true
```

### Full Configuration

```yaml
plugins:
  - handler: basic_pii_filter
    enabled: true
    priority: 10              # Run early in pipeline
    critical: true            # Block requests if plugin fails

    action: redact            # block | redact | audit_only
    scan_base64: false        # Decode and scan base64 content

    pii_types:
      email:
        enabled: true
      phone:
        enabled: true
      credit_card:
        enabled: true
      ip_address:
        enabled: true
      national_id:
        enabled: true
```

### Production Example (Block Mode)

```yaml
plugins:
  - handler: basic_pii_filter
    enabled: true
    priority: 5
    action: block             # Reject any content with PII
    scan_base64: true         # Also check encoded content
    pii_types:
      email:
        enabled: true
      credit_card:
        enabled: true
      national_id:
        enabled: true
      phone:
        enabled: false        # Too many false positives for our use case
      ip_address:
        enabled: false        # We legitimately work with IPs
```

## Limitations

This plugin will NOT detect:

- **Context-dependent PII** - Names, addresses without clear patterns
- **Obfuscated or encoded PII** - ROT13, custom encoding schemes
- **Novel or region-specific formats** - Non-US phone numbers, other countries' IDs
- **PII split across multiple fields** - First name in one field, last name in another
- **Unformatted SSNs** - `123456789` without dashes (too many false positives)

## Redaction Format

When `action: redact`, detected PII is replaced with:

```
[EMAIL REDACTED by Gatekit]
[PHONE REDACTED by Gatekit]
[CREDIT_CARD REDACTED by Gatekit]
[IP_ADDRESS REDACTED by Gatekit]
[NATIONAL_ID REDACTED by Gatekit]
```
