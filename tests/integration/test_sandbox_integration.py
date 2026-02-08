"""Integration tests for OS-native sandbox functionality.

These tests verify actual sandbox behavior on the current platform.
They are marked as slow and use OS-specific collection markers so they
don't appear as skipped on other platforms.
"""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest


def _python_read_only_paths() -> list:
    """Return read-only paths needed to execute the current Python binary.

    When running from a venv under the home directory, the sandbox's
    home-directory deny blocks reading the binary itself.  This helper
    mirrors the auto-detection that resolve_and_wrap() does in production,
    which adds the venv root, the cwd, and cache dirs (including ~/.local
    which covers uv-managed Python installs).

    For tests we include both the unresolved venv path (so sandbox-exec
    can follow the symlink) and the resolved real binary path (so the
    actual interpreter is readable).
    """
    paths = []
    home = Path.home()
    binary = Path(sys.executable)

    # Unresolved path: the venv itself (mirrors _infer_command_read_paths)
    try:
        binary.relative_to(home)
        binary_dir = binary.parent
        if binary_dir.name == "bin":
            paths.append(binary_dir.parent)
        else:
            paths.append(binary_dir)
    except ValueError:
        pass

    # Resolved path: the real interpreter (may be in ~/.local/share/uv/ etc.)
    resolved = binary.resolve()
    if resolved != binary:
        try:
            resolved.relative_to(home)
            resolved_dir = resolved.parent
            if resolved_dir.name == "bin":
                paths.append(resolved_dir.parent)
            else:
                paths.append(resolved_dir)
        except ValueError:
            pass

    return paths


def _make_probe_script(tmp_path, denied_dir, allowed_dir):
    """Create a Python script that probes sandbox restrictions.

    Uses caller-supplied directories so the test controls what exists
    and can verify sandbox enforcement independent of host state.
    """
    script = tmp_path / "probe.py"
    script.write_text(f"""\
import json
import os

results = {{}}

# Test 1: Can we read a specific file in the denied directory?
# We check for a known file rather than listdir because bwrap overlays
# the denied path with an empty tmpfs — listdir succeeds (empty dir)
# but the original contents are hidden.
credential_path = os.path.join({str(denied_dir)!r}, "credential.txt")
try:
    with open(credential_path) as f:
        f.read()
    results["read_denied"] = True
except Exception:
    results["read_denied"] = False

# Test 2: Can we write to the allowed directory?
try:
    test_file = os.path.join({str(allowed_dir)!r}, "probe_write_test")
    with open(test_file, "w") as f:
        f.write("test")
    os.unlink(test_file)
    results["write_allowed"] = True
except Exception:
    results["write_allowed"] = False

# Test 3: Can we write outside the allowed directories?
# Use PID in filename to avoid races under parallel test execution.
try:
    outside_file = f"/tmp/gatekit_probe_outside_{{os.getpid()}}"
    with open(outside_file, "w") as f:
        f.write("test")
    os.unlink(outside_file)
    results["write_outside"] = True
except Exception:
    results["write_outside"] = False

print(json.dumps(results))
""")
    return script


# ---------------------------------------------------------------------------
# macOS Seatbelt tests
# ---------------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.darwin_only
class TestSeatbeltSandboxProbe:
    """Test actual Seatbelt sandbox enforcement on macOS."""

    def test_seatbelt_blocks_denied_dir_and_allows_workspace(self, tmp_path):
        """Verify sandbox-exec blocks the denied dir and allows the workspace.

        The denied directory must be under the home directory because Seatbelt's
        allow-wins semantics mean system-allowed paths (like /private/var/folders)
        cannot be denied.  The home directory is denied by default, so an
        un-allowed subdirectory under ~ is effectively blocked.
        """
        from gatekit.sandbox.backends.seatbelt import SeatbeltBackend
        from gatekit.sandbox.backends.base import SandboxProfile

        backend = SeatbeltBackend()
        if not backend.is_available():
            pytest.skip("sandbox-exec not available")

        # Create the denied directory under home (which is denied by default).
        # We don't add it to any allowlist, so the home-deny blocks it.
        home = Path.home()
        denied_dir = home / ".gatekit_test_sandbox_secret"
        denied_dir.mkdir(exist_ok=True)
        credential_file = denied_dir / "credential.txt"
        credential_file.write_text("supersecret")

        # The allowed workspace is under /tmp (always allowed)
        allowed_dir = tmp_path / "workspace"
        allowed_dir.mkdir()

        try:
            script = _make_probe_script(tmp_path, denied_dir, allowed_dir)

            profile = SandboxProfile(
                read_write_paths=[allowed_dir],
                read_only_paths=_python_read_only_paths(),
                allow_network=True,
            )

            cmd = [sys.executable, str(script)]
            wrapped = backend.wrap_command(cmd, profile)

            result = subprocess.run(
                wrapped, capture_output=True, text=True, timeout=10
            )
            assert result.returncode == 0, f"Probe script failed: {result.stderr}"

            data = json.loads(result.stdout)
            assert data["read_denied"] is False, "Sandbox should block reading dir under ~"
            assert data["write_allowed"] is True, "Sandbox should allow writing to workspace"
            # /tmp is explicitly allowed in Seatbelt profiles
            assert data["write_outside"] is True, "/tmp should be writable"
        finally:
            # Clean up test directory under home
            if credential_file.exists():
                credential_file.unlink()
            if denied_dir.exists():
                denied_dir.rmdir()
            backend.cleanup()

    def test_seatbelt_preserves_stdio(self, tmp_path):
        """Verify a sandboxed process can communicate via stdio."""
        from gatekit.sandbox.backends.seatbelt import SeatbeltBackend
        from gatekit.sandbox.backends.base import SandboxProfile

        backend = SeatbeltBackend()
        if not backend.is_available():
            pytest.skip("sandbox-exec not available")

        script = tmp_path / "echo_server.py"
        script.write_text("""\
import sys
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
""")

        profile = SandboxProfile(read_only_paths=_python_read_only_paths())
        cmd = [sys.executable, str(script)]
        wrapped = backend.wrap_command(cmd, profile)

        try:
            proc = subprocess.Popen(
                wrapped,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            test_msg = '{"jsonrpc": "2.0", "method": "test", "id": 1}\n'
            proc.stdin.write(test_msg.encode())
            proc.stdin.flush()

            import select

            ready, _, _ = select.select([proc.stdout], [], [], 5)
            assert ready, "Should receive echo within 5 seconds"

            response = proc.stdout.readline().decode()
            assert '"jsonrpc"' in response

            proc.terminate()
            proc.wait(timeout=5)
        finally:
            backend.cleanup()


# ---------------------------------------------------------------------------
# Linux bubblewrap tests
# ---------------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.linux_only
class TestBubblewrapSandboxProbe:
    """Test actual bubblewrap sandbox enforcement on Linux."""

    def test_bwrap_blocks_denied_dir_and_allows_workspace(self, tmp_path):
        """Verify bwrap blocks the denied dir and allows the workspace."""
        from gatekit.sandbox.backends.bubblewrap import BubblewrapBackend
        from gatekit.sandbox.backends.base import SandboxProfile

        backend = BubblewrapBackend()
        if not backend.is_available():
            pytest.skip("bwrap not available or non-functional")

        # Create controlled directories
        denied_dir = tmp_path / "secret"
        denied_dir.mkdir()
        (denied_dir / "credential.txt").write_text("supersecret")

        allowed_dir = tmp_path / "workspace"
        allowed_dir.mkdir()

        script = _make_probe_script(tmp_path, denied_dir, allowed_dir)

        profile = SandboxProfile(
            read_write_paths=[allowed_dir],
            deny_paths=[denied_dir],
            allow_network=True,
        )

        cmd = [sys.executable, str(script)]
        wrapped = backend.wrap_command(cmd, profile)

        result = subprocess.run(
            wrapped, capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"Probe script failed: {result.stderr}"

        data = json.loads(result.stdout)
        assert data["read_denied"] is False, "Sandbox should block reading denied dir"
        assert data["write_allowed"] is True, "Sandbox should allow writing to workspace"
        # bwrap mounts a fresh /tmp, so writes there succeed
        assert data["write_outside"] is True, "/tmp should be writable (fresh tmpfs)"

    def test_bwrap_preserves_stdio(self, tmp_path):
        """Verify a sandboxed bwrap process can communicate via stdio."""
        from gatekit.sandbox.backends.bubblewrap import BubblewrapBackend
        from gatekit.sandbox.backends.base import SandboxProfile

        backend = BubblewrapBackend()
        if not backend.is_available():
            pytest.skip("bwrap not available or non-functional")

        script = tmp_path / "echo_server.py"
        script.write_text("""\
import sys
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
""")

        profile = SandboxProfile()
        cmd = [sys.executable, str(script)]
        wrapped = backend.wrap_command(cmd, profile)

        proc = subprocess.Popen(
            wrapped,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        test_msg = '{"jsonrpc": "2.0", "method": "test", "id": 1}\n'
        proc.stdin.write(test_msg.encode())
        proc.stdin.flush()

        import select

        ready, _, _ = select.select([proc.stdout], [], [], 5)
        assert ready, "Should receive echo within 5 seconds"

        response = proc.stdout.readline().decode()
        assert '"jsonrpc"' in response

        proc.terminate()
        proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Process lifecycle tests (both platforms)
# ---------------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.posix_only
class TestSandboxProcessLifecycle:
    """Test that sandboxed processes can be properly terminated."""

    def _get_backend_and_profile(self):
        """Get the appropriate backend for the current platform."""
        if sys.platform == "darwin":
            from gatekit.sandbox.backends.seatbelt import SeatbeltBackend
            backend = SeatbeltBackend()
        else:
            from gatekit.sandbox.backends.bubblewrap import BubblewrapBackend
            backend = BubblewrapBackend()

        if not backend.is_available():
            pytest.skip(f"{backend.name} not available")

        from gatekit.sandbox.backends.base import SandboxProfile
        return backend, SandboxProfile(read_only_paths=_python_read_only_paths())

    def test_killpg_terminates_sandboxed_process(self, tmp_path):
        """Verify os.killpg correctly terminates a sandboxed server."""
        backend, profile = self._get_backend_and_profile()

        script = tmp_path / "sleeper.py"
        script.write_text("""\
import time
import sys
sys.stdout.write("started\\n")
sys.stdout.flush()
time.sleep(300)
""")

        cmd = [sys.executable, str(script)]
        wrapped = backend.wrap_command(cmd, profile)

        try:
            proc = subprocess.Popen(
                wrapped,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )

            import select

            ready, _, _ = select.select([proc.stdout], [], [], 5)
            assert ready, "Process should start within 5 seconds"
            output = proc.stdout.readline().decode().strip()
            assert output == "started"

            os.killpg(proc.pid, signal.SIGTERM)

            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)

            assert proc.returncode is not None, "Process should have terminated"
        finally:
            backend.cleanup()
