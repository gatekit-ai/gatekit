# Basic Secrets Filter

Detect and filter secrets, API keys, and tokens using pattern matching and entropy analysis.

> **Warning:** This plugin provides basic protection only and is NOT suitable for production use. Pattern-based detection can be bypassed with encoding, obfuscation, or novel formats. For production environments, use enterprise-grade secret detection solutions.

## Quick Reference

| Property | Value |
|----------|-------|
| Handler | `basic_secrets_filter` |
| Type | Security |
| Scope | Global (can be configured globally or per-server) |

## Detected Secret Types

| Type | Description | Enabled by Default |
|------|-------------|-------------------|
| `aws_access_keys` | AWS access key IDs (AKIA-prefixed) | Yes |
| `github_tokens` | GitHub tokens (ghp_, gho_, ghu_, ghs_, ghr_ prefixes) | Yes |
| `google_api_keys` | Google API keys (AIza-prefixed) | Yes |
| `jwt_tokens` | JWT tokens (three-part base64url structure) | Yes |
| `openai_api_keys` | OpenAI API keys (sk-, sk-proj-, sk-admin-) | Yes |
| `slack_tokens` | Slack tokens (xoxb-, xoxp-, xoxa-, xoxr-, xoxs-) | Yes |
| `ssh_private_keys` | SSH private key PEM headers | Yes |
| `private_keys` | General PKCS#8 private key headers | **No** (high false positives) |

## Configuration Reference

### action

What to do when a secret is detected.

| Value | Description |
|-------|-------------|
| `block` | Reject the request/response entirely |
| `redact` | Replace secrets with `[SECRET REDACTED by Gatekit]` |
| `audit_only` | Log detection but allow through unchanged |

**Default:** `redact`

### secret_types

Configure which secret types to detect. Each type has an `enabled` boolean.

**Default:** All types enabled except `private_keys`

### entropy_detection

Detect high-entropy strings that may be secrets even without matching known patterns.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable entropy-based detection |
| `threshold` | number | `5.0` | Minimum Shannon entropy to flag (4.0-5.0, higher = fewer false positives) |
| `min_length` | integer | `20` | Minimum string length to analyze |

> **Warning: High False Positive Rate at Low Thresholds**
>
> Entropy detection produces significant false positives at thresholds below 4.8. In testing:
> - At 4.0: Blocks/redacts nearly all content including simple messages
> - At 4.5: Still catches legitimate request metadata and UUIDs
> - At 5.0 (default): Most conservative, fewest false positives
>
> **Recommendation:** Start with the default threshold of 5.0 and only lower it if you need to catch more potential secrets and can tolerate the increased false positive rate. Consider using `action: audit_only` first to evaluate the impact before enabling blocking or redaction.

> **Note:** Entropy detection is disabled by default due to false positives. When enabled, it can catch unknown secret formats but may flag legitimate high-entropy data like UUIDs or encoded file content.

### scan_base64

Decode and scan base64-encoded content for secrets.

**Default:** `false`

> **Note:** Base64 content cannot be safely redacted (would corrupt data). When `scan_base64` is enabled and secrets are found in base64 content, the plugin forces blocking even if `action` is set to `redact`. Includes DoS protection: max 50 candidates, max 100KB total decoded.

## YAML Configuration

### Minimal Configuration

```yaml
plugins:
  - handler: basic_secrets_filter
    enabled: true
```

### Full Configuration

```yaml
plugins:
  - handler: basic_secrets_filter
    enabled: true
    priority: 10              # Run early in pipeline
    critical: true            # Block requests if plugin fails

    action: redact            # block | redact | audit_only
    scan_base64: false        # Decode and scan base64 content

    secret_types:
      aws_access_keys:
        enabled: true
      github_tokens:
        enabled: true
      google_api_keys:
        enabled: true
      jwt_tokens:
        enabled: true
      openai_api_keys:
        enabled: true
      slack_tokens:
        enabled: true
      ssh_private_keys:
        enabled: true
      private_keys:
        enabled: false        # Disabled due to high false positives

    entropy_detection:
      enabled: false          # Disabled by default
      threshold: 5.0          # Higher = fewer false positives (range: 4.0-5.0)
      min_length: 20          # Minimum string length to analyze
```

### Production Example (Maximum Protection)

```yaml
plugins:
  - handler: basic_secrets_filter
    enabled: true
    priority: 5
    action: block             # Never allow secrets through
    scan_base64: true         # Also check encoded content

    secret_types:
      aws_access_keys:
        enabled: true
      github_tokens:
        enabled: true
      openai_api_keys:
        enabled: true
      jwt_tokens:
        enabled: false        # JWTs are often legitimate in our API
      google_api_keys:
        enabled: true
      slack_tokens:
        enabled: true
      ssh_private_keys:
        enabled: true
      private_keys:
        enabled: true         # Enable despite false positives for max security

    entropy_detection:
      enabled: true
      threshold: 4.5          # More aggressive detection
      min_length: 16
```

## Limitations

This plugin will NOT detect:

- **Secrets in novel or proprietary formats** - Only known patterns are detected
- **Obfuscated secrets** - ROT13, custom encoding, split across fields
- **Context-dependent credentials** - Passwords without structure
- **AWS secret access keys** - Removed due to high false positive rate on file paths
- **High-entropy strings with special characters** - Special chars fragment tokens below min_length threshold

## Redaction Format

When `action: redact`, detected secrets are replaced with:

```
[SECRET REDACTED by Gatekit]
```
