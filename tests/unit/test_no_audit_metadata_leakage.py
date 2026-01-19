"""Test that audit metadata constants have been properly removed.

This test ensures that the removed _gatekit_audit metadata system
is not accidentally reintroduced or referenced anywhere in the codebase.
"""

import pytest


def test_audit_constants_not_importable():
    """Verify that removed audit constants cannot be imported."""
    # These constants were removed to prevent internal metadata leakage to clients
    with pytest.raises(ImportError):
        from gatekit.proxy.server import GATEKIT_AUDIT_KEY  # type: ignore  # noqa: F401

    with pytest.raises(ImportError):
        from gatekit.proxy.server import AUDIT_CATEGORY_PLUGIN_EXCEPTION  # type: ignore  # noqa: F401

    with pytest.raises(ImportError):
        from gatekit.proxy.server import AUDIT_CATEGORY_SECURITY_VIOLATION  # type: ignore  # noqa: F401

    with pytest.raises(ImportError):
        from gatekit.proxy.server import AUDIT_CATEGORY_UPSTREAM_UNAVAILABLE  # type: ignore  # noqa: F401

    with pytest.raises(ImportError):
        from gatekit.proxy.server import AUDIT_CATEGORY_RESPONSE_FILTER_BLOCK  # type: ignore  # noqa: F401

    with pytest.raises(ImportError):
        from gatekit.proxy.server import AUDIT_CATEGORY_RESPONSE_FILTER_EXCEPTION  # type: ignore  # noqa: F401

    with pytest.raises(ImportError):
        from gatekit.proxy.server import AUDIT_CATEGORY_UNEXPECTED_ERROR  # type: ignore  # noqa: F401


def test_error_responses_do_not_contain_audit_metadata():
    """Verify that error responses don't include _gatekit_audit metadata."""
    from gatekit.protocol.errors import create_error_response
    from gatekit.protocol.errors import MCPErrorCodes

    # Create an error response
    error_response = create_error_response(
        request_id="test-1",
        code=MCPErrorCodes.SECURITY_VIOLATION,
        message="Test security violation",
    )

    # The error should not have a data field with _gatekit_audit
    if error_response.error and error_response.error.get("data"):
        assert (
            "_gatekit_audit" not in error_response.error["data"]
        ), "Error responses should not contain _gatekit_audit metadata"
