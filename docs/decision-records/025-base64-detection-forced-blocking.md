# ADR-025: Base64 Detection Forced Blocking

## Context

The PII filter and secrets filter plugins support scanning base64-encoded content for sensitive data via the `scan_base64` configuration option. When enabled, these plugins decode base64 strings and scan the decoded content for patterns.

Both plugins also support an `action` configuration that determines what happens when sensitive data is detected:
- `block`: Reject the message entirely
- `redact`: Replace sensitive data with placeholder text, allow message to proceed
- `audit_only`: Log the detection, allow message to proceed unchanged

### The Problem

When `scan_base64: true` and `action: redact` are both configured, the plugin detects sensitive data within base64-encoded content and attempts to redact it. However, **redaction is impossible for base64-encoded content**.

Base64 encoding represents binary data (images, files, etc.) as ASCII text. Any modification to the base64 string - even replacing a single character - corrupts the underlying binary data:

1. Inserting `[REDACTED]` introduces non-base64 characters, making the string invalid
2. Even keeping valid base64 characters would decode to corrupted binary data
3. The resulting image/file would be unusable or cause downstream errors

## Decision

**When sensitive data is detected within base64-encoded content and the configured action is `redact`, the plugin MUST block instead.**

Redaction is impossible for base64 content, so attempting it would corrupt the data. The `audit_only` action is unaffected since it doesn't modify content. For base64 detections:

| Configured Action | Plain Text Detection | Base64 Detection |
|-------------------|---------------------|------------------|
| `block` | Block | Block |
| `redact` | Redact | **Block** (forced) |
| `audit_only` | Allow + log | Allow + log |

Note: `audit_only` still allows the message through because no modification is attempted.

### Implementation

Both plugins check if any detection has base64 encoding metadata:
- Secrets filter: `encoding_type: "base64"`
- PII filter: `encoding: "base64"`

When base64 detections are present and the action would be `redact`, the effective action is forced to `block`. The metadata includes `base64_force_block: true` to indicate this override occurred.

## Consequences

### Positive

- **Data integrity preserved**: Binary data is never corrupted by failed redaction attempts
- **Predictable behavior**: Users understand that base64 content cannot be redacted
- **Clear audit trail**: Metadata indicates when blocking was forced due to base64 content
- **Security maintained**: Sensitive data in base64 is still prevented from transmission

### Negative

- **Less granular control**: Users cannot choose to "redact" base64 content (but this was never actually possible)
- **Potential for more blocking**: Content that would have been "redacted" (corrupted) is now blocked entirely

### User Guidance

Users who want to allow base64 content through while still detecting sensitive data should use `action: audit_only`. This logs detections without modifying content.

For users who need base64 content to pass through unexamined, disable base64 scanning with `scan_base64: false` (the default).

## Related ADRs

- **ADR-024**: Security Plugin Detection Option Defaults - Establishes that `scan_base64` defaults to `false`
