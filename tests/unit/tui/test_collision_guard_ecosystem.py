"""Comprehensive tests for collision guard in expanding plugin ecosystem."""

from pathlib import Path
from gatekit.tui.screens.config_editor import ConfigEditorScreen
from gatekit.config import ProxyConfig, UpstreamConfig, TimeoutConfig


class TestEcosystemExpansion:
    """Tests simulating real-world plugin ecosystem expansion scenarios."""

    def test_realistic_plugin_ecosystem(self):
        """Test collision handling with realistic plugin names from various sources."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["test"])],
            timeouts=TimeoutConfig(),
        )
        screen = ConfigEditorScreen(Path("test.yaml"), config)

        # Simulate plugins from different sources that might have naming conflicts
        # These represent realistic plugin names from npm, GitHub, enterprise, etc.
        plugin_scenarios = [
            # npm-style packages (often use hyphens)
            ("@company/auth-handler", "security"),
            ("@company/auth.handler", "security"),  # Alternative naming
            ("@company/auth_handler", "security"),  # Yet another style
            # GitHub-style (often use underscores or hyphens)
            ("github-webhook-handler", "middleware"),
            ("github_webhook_handler", "middleware"),
            ("github.webhook.handler", "middleware"),
            # Enterprise naming (might use dots for namespacing)
            ("com.company.security.handler", "security"),
            ("com.company.security-handler", "security"),
            ("com_company_security_handler", "security"),
            # Common generic names likely to collide
            ("auth", "security"),
            ("auth", "middleware"),  # Same name, different type
            ("auth", "auditing"),  # Same name, third type
            # Filesystem-related plugins
            ("file-system", "security"),
            ("file_system", "security"),
            ("file.system", "security"),
            ("filesystem", "security"),  # Different but related
            # API gateway patterns
            ("api-gateway", "middleware"),
            ("api_gateway", "middleware"),
            ("api.gateway", "middleware"),
            ("apigateway", "middleware"),
            # Rate limiting variants
            ("rate-limit", "middleware"),
            ("rate_limit", "middleware"),
            ("rate.limit", "middleware"),
            ("ratelimit", "middleware"),
            # Logging/audit variants
            ("audit-log", "auditing"),
            ("audit_log", "auditing"),
            ("audit.log", "auditing"),
            ("auditlog", "auditing"),
        ]

        # Track all generated IDs to ensure uniqueness
        seen_ids = set()
        id_to_original = {}

        for handler_name, plugin_type in plugin_scenarios:
            sanitized = screen._sanitize_handler_for_id(handler_name, plugin_type)

            # Ensure no duplicates
            assert sanitized not in seen_ids, (
                f"Collision! '{handler_name}' ({plugin_type}) generated duplicate ID '{sanitized}' "
                f"(already used by '{id_to_original.get(sanitized, 'unknown')}')"
            )

            seen_ids.add(sanitized)
            id_to_original[sanitized] = f"{handler_name} ({plugin_type})"

        # Verify we handled all the plugins
        assert len(seen_ids) == len(plugin_scenarios)

    def test_malicious_collision_attempts(self):
        """Test that malicious attempts to cause collisions are handled."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["test"])],
            timeouts=TimeoutConfig(),
        )
        screen = ConfigEditorScreen(Path("test.yaml"), config)

        # Attempt to create intentional collisions
        malicious_names = [
            "legitimate_handler",
            "legitimate-handler",  # Dash vs underscore
            "legitimate.handler",  # Dot vs underscore
            "legitimate handler",  # Space vs underscore
            "legitimate@handler",  # Special char
            "legitimate#handler",  # Another special
            "legitimate$handler",  # Dollar sign
            "legitimate%handler",  # Percent
            "legitimate^handler",  # Caret
            "legitimate&handler",  # Ampersand
            "legitimate*handler",  # Asterisk
            "legitimate(handler",  # Parenthesis
            "legitimate)handler",  # Close paren
            "legitimate[handler",  # Bracket
            "legitimate]handler",  # Close bracket
            "legitimate{handler",  # Brace
            "legitimate}handler",  # Close brace
            "legitimate|handler",  # Pipe
            "legitimate\\handler",  # Backslash
            "legitimate/handler",  # Forward slash
            "legitimate:handler",  # Colon
            "legitimate;handler",  # Semicolon
            "legitimate'handler",  # Single quote
            'legitimate"handler',  # Double quote
            "legitimate<handler",  # Less than
            "legitimate>handler",  # Greater than
            "legitimate?handler",  # Question mark
            "legitimate~handler",  # Tilde
            "legitimate`handler",  # Backtick
        ]

        seen_ids = set()
        for name in malicious_names:
            result = screen._sanitize_handler_for_id(name, "security")
            assert result not in seen_ids, f"Collision for '{name}' -> '{result}'"
            seen_ids.add(result)

        # All malicious attempts should produce unique IDs
        assert len(seen_ids) == len(malicious_names)

    def test_unicode_and_international_names(self):
        """Test handling of Unicode and international plugin names."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["test"])],
            timeouts=TimeoutConfig(),
        )
        screen = ConfigEditorScreen(Path("test.yaml"), config)

        # International naming that might be used in global teams
        international_names = [
            "日本-handler",  # Japanese
            "中文-handler",  # Chinese
            "한글-handler",  # Korean
            "العربية-handler",  # Arabic
            "עברית-handler",  # Hebrew
            "ελληνικά-handler",  # Greek
            "русский-handler",  # Russian
            "emoji-😀-handler",  # Emoji
            "café-handler",  # Accented characters
            "naïve-handler",  # Diaeresis
            "résumé-handler",  # Acute accent
            "piñata-handler",  # Tilde
        ]

        seen_ids = set()
        for name in international_names:
            result = screen._sanitize_handler_for_id(name, "middleware")
            # These should all sanitize but remain unique
            assert result not in seen_ids, f"Collision for '{name}' -> '{result}'"
            seen_ids.add(result)

    def test_ecosystem_growth_simulation(self):
        """Simulate ecosystem growing over time with various naming patterns."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["test"])],
            timeouts=TimeoutConfig(),
        )

        # Simulate multiple companies/teams adding plugins over time
        waves_of_plugins = [
            # Wave 1: Initial core plugins
            [
                ("auth", "security"),
                ("rate_limit", "middleware"),
                ("audit_log", "auditing"),
            ],
            # Wave 2: Company A adds their variants
            [
                ("company_a_auth", "security"),
                ("company-a-auth", "security"),
                ("companya.auth", "security"),
            ],
            # Wave 3: Company B adds similar plugins
            [
                ("company_b_auth", "security"),
                ("company-b-auth", "security"),
                ("companyb.auth", "security"),
            ],
            # Wave 4: Generic expansions
            [
                ("auth_v2", "security"),
                ("auth-v2", "security"),
                ("auth.v2", "security"),
                ("auth2", "security"),
            ],
            # Wave 5: Feature-specific variants
            [
                ("auth_jwt", "security"),
                ("auth-oauth", "security"),
                ("auth.saml", "security"),
            ],
        ]

        # Each wave should work with fresh screen (simulating restarts)
        for wave_index, wave in enumerate(waves_of_plugins):
            screen = ConfigEditorScreen(Path("test.yaml"), config)
            seen_in_wave = set()

            # Process all previous waves first (simulating persistent state)
            for prev_wave_idx in range(wave_index):
                for handler_name, plugin_type in waves_of_plugins[prev_wave_idx]:
                    result = screen._sanitize_handler_for_id(handler_name, plugin_type)
                    seen_in_wave.add(result)

            # Now process current wave
            for handler_name, plugin_type in wave:
                result = screen._sanitize_handler_for_id(handler_name, plugin_type)
                assert (
                    result not in seen_in_wave
                ), f"Wave {wave_index + 1}: Collision for '{handler_name}' -> '{result}'"
                seen_in_wave.add(result)

    def test_collision_performance(self):
        """Test that collision detection performs well with many plugins."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["test"])],
            timeouts=TimeoutConfig(),
        )
        screen = ConfigEditorScreen(Path("test.yaml"), config)

        import time

        # Generate many similar names that will cause collisions
        num_iterations = 200
        plugin_names = []
        for i in range(num_iterations):
            # Create variations that will collide
            base = f"handler_{i % 100}"  # Only 100 unique bases, will repeat
            variations = [
                (base, "security"),
                (base.replace("_", "-"), "security"),
                (base.replace("_", "."), "security"),
                (base.replace("_", " "), "security"),
                (base.replace("_", "@"), "security"),
            ]
            plugin_names.extend(variations)

        # Also create unique names to track
        seen_combinations = set()
        results_map = {}

        # Time the sanitization with collision detection
        start_time = time.time()
        for name, plugin_type in plugin_names:
            result = screen._sanitize_handler_for_id(name, plugin_type)

            # Track the combination
            combo = (name, plugin_type)
            if combo in seen_combinations:
                # Same name+type should give same result
                assert (
                    results_map[combo] == result
                ), f"Inconsistent result for '{name}' ({plugin_type}): {result} vs {results_map[combo]}"
            else:
                seen_combinations.add(combo)
                results_map[combo] = result

        elapsed = time.time() - start_time

        # Should handle 1000 plugins in under 1 second
        assert (
            elapsed < 1.0
        ), f"Too slow: {elapsed:.2f}s for {len(plugin_names)} plugins"

        # Check we got unique IDs for unique name+type combinations
        unique_results = set(results_map.values())
        assert len(unique_results) == len(
            results_map
        ), f"Got {len(unique_results)} unique IDs for {len(results_map)} unique name+type combos"
