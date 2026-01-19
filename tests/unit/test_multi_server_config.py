import pytest
from gatekit.config.models import ProxyConfig, UpstreamConfig, TimeoutConfig


def test_single_server_requires_name():
    """Single server config now requires name field for consistent behavior"""
    with pytest.raises(
        TypeError, match="missing 1 required positional argument: 'name'"
    ):
        ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    command=["npx", "@modelcontextprotocol/server-filesystem", "/tmp"]
                )
            ],
            timeouts=TimeoutConfig(),
        )


def test_all_servers_require_names():
    """All servers must have names"""
    with pytest.raises(
        TypeError, match="missing 1 required positional argument: 'name'"
    ):
        ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(command=["cmd1"]),
                UpstreamConfig(command=["cmd2"]),
            ],
            timeouts=TimeoutConfig(),
        )


def test_server_names_must_be_unique():
    """Server names must be unique"""
    with pytest.raises(TypeError, match="must be unique"):
        ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="fs", command=["cmd1"]),
                UpstreamConfig(name="fs", command=["cmd2"]),
            ],
            timeouts=TimeoutConfig(),
        )


def test_server_names_cannot_contain_separator():
    """Server names cannot contain __ separator (namespace delimiter)"""
    with pytest.raises(ValueError, match="cannot contain '__'"):
        ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="fs__bad", command=["cmd"])],
            timeouts=TimeoutConfig(),
        )


def test_single_server_with_name_required():
    """Single server must have a name (unified behavior)"""
    config = ProxyConfig(
        transport="stdio",
        upstreams=[UpstreamConfig(name="fs", command=["cmd"])],
        timeouts=TimeoutConfig(),
    )
    assert len(config.upstreams) == 1
    assert config.upstreams[0].name == "fs"


def test_multi_server_valid_config():
    """Valid configuration with multiple servers should work"""
    config = ProxyConfig(
        transport="stdio",
        upstreams=[
            UpstreamConfig(name="fs", command=["cmd1"]),
            UpstreamConfig(name="github", command=["cmd2"]),
        ],
        timeouts=TimeoutConfig(),
    )
    assert len(config.upstreams) == 2
    assert config.upstreams[0].name == "fs"
    assert config.upstreams[1].name == "github"


def test_at_least_one_upstream_required():
    """At least one upstream server must be configured"""
    with pytest.raises(
        TypeError, match="At least one upstream server must be configured"
    ):
        ProxyConfig(transport="stdio", upstreams=[], timeouts=TimeoutConfig())


def test_upstream_transport_validation():
    """Upstream transport validation should work"""
    # stdio transport requires command
    with pytest.raises(ValueError, match="stdio transport requires 'command'"):
        UpstreamConfig(name="test", transport="stdio", command=None)

    # http transport requires url
    with pytest.raises(ValueError, match="http transport requires 'url'"):
        UpstreamConfig(name="test", transport="http", url=None)


def test_upstream_config_with_http():
    """HTTP upstream configuration should work"""
    upstream = UpstreamConfig(
        name="api", transport="http", url="https://api.example.com/mcp"
    )
    assert upstream.name == "api"
    assert upstream.transport == "http"
    assert upstream.url == "https://api.example.com/mcp"
