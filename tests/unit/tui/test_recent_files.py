"""Unit tests for RecentFiles management."""

import json
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from gatekit.tui.recent_files import RecentFiles, humanize_timestamp


class TestRecentFiles:
    """Test RecentFiles class functionality."""

    def test_init_creates_state_directory(self, tmp_path, monkeypatch):
        """Test initialization creates state directory if it doesn't exist."""
        # Mock get_user_state_dir to return our temp path
        state_dir = tmp_path / 'state'
        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()

            assert recent.recent_file.parent == state_dir
            assert recent.recent_file.name == 'recent.json'

    def test_add_new_file(self, tmp_path):
        """Test adding a new file to recent files list."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            test_file = tmp_path / 'test.yaml'
            test_file.touch()

            recent.add(test_file)

            all_recent = recent.get_all()
            assert len(all_recent) == 1
            assert all_recent[0]['path'] == str(test_file)
            assert all_recent[0]['display_name'] == 'test.yaml'
            assert 'last_opened' in all_recent[0]

    def test_add_updates_existing_file(self, tmp_path):
        """Test adding an existing file updates its timestamp."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            test_file = tmp_path / 'test.yaml'
            test_file.touch()

            # Add file first time
            recent.add(test_file)
            first_timestamp = recent.get_all()[0]['last_opened']

            # Add same file again after a short delay
            import time
            time.sleep(0.01)
            recent.add(test_file)

            all_recent = recent.get_all()
            assert len(all_recent) == 1  # Still only one entry
            second_timestamp = all_recent[0]['last_opened']
            assert second_timestamp != first_timestamp  # Timestamp updated

    def test_respects_max_items_limit(self, tmp_path):
        """Test that only max_items most recent files are kept."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles(max_items=3)

            # Add 5 files
            for i in range(5):
                test_file = tmp_path / f'test{i}.yaml'
                test_file.touch()
                recent.add(test_file)
                import time
                time.sleep(0.01)  # Ensure different timestamps

            all_recent = recent.get_all()
            assert len(all_recent) == 3  # Only 3 most recent kept
            # Most recent should be first
            assert 'test4.yaml' in all_recent[0]['path']

    def test_get_all_filters_nonexistent_files(self, tmp_path):
        """Test get_all() filters out files that no longer exist."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()

            # Add two files
            file1 = tmp_path / 'exists.yaml'
            file1.touch()
            file2 = tmp_path / 'deleted.yaml'
            file2.touch()

            recent.add(file1)
            recent.add(file2)

            # Delete one file
            file2.unlink()

            all_recent = recent.get_all()
            assert len(all_recent) == 1
            assert 'exists.yaml' in all_recent[0]['path']

    def test_remove_file(self, tmp_path):
        """Test removing a file from recent files list."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()

            file1 = tmp_path / 'file1.yaml'
            file1.touch()
            file2 = tmp_path / 'file2.yaml'
            file2.touch()

            recent.add(file1)
            recent.add(file2)

            recent.remove(file1)

            all_recent = recent.get_all()
            assert len(all_recent) == 1
            assert 'file2.yaml' in all_recent[0]['path']

    def test_clear_all_files(self, tmp_path):
        """Test clearing all recent files."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()

            # Add some files
            for i in range(3):
                test_file = tmp_path / f'test{i}.yaml'
                test_file.touch()
                recent.add(test_file)

            recent.clear()

            all_recent = recent.get_all()
            assert len(all_recent) == 0

    def test_persistence_across_instances(self, tmp_path):
        """Test that recent files persist across RecentFiles instances."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)

        test_file = tmp_path / 'test.yaml'
        test_file.touch()

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            # Create first instance and add file
            recent1 = RecentFiles()
            recent1.add(test_file)

            # Create second instance and verify file is there
            recent2 = RecentFiles()
            all_recent = recent2.get_all()
            assert len(all_recent) == 1
            assert 'test.yaml' in all_recent[0]['path']

    def test_handles_corrupted_json_gracefully(self, tmp_path):
        """Test that corrupted JSON file is handled gracefully."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)
        recent_file = state_dir / 'recent.json'

        # Write corrupted JSON
        recent_file.write_text('{ corrupted json }}')

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            all_recent = recent.get_all()

            # Should return empty list and not crash
            assert all_recent == []

    def test_handles_missing_json_file(self, tmp_path):
        """Test that missing JSON file is handled gracefully."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            all_recent = recent.get_all()

            # Should return empty list
            assert all_recent == []

    def test_handles_invalid_utf8_gracefully(self, tmp_path):
        """Test that invalid UTF-8 in state file is handled gracefully."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)
        recent_file = state_dir / 'recent.json'

        # Write invalid UTF-8 bytes
        recent_file.write_bytes(b'\xff\xfe invalid utf-8 \x80\x81')

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            all_recent = recent.get_all()

            # Should return empty list and not crash
            assert all_recent == []

    def test_handles_json_array_instead_of_object(self, tmp_path):
        """Test that JSON array instead of object is handled gracefully."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)
        recent_file = state_dir / 'recent.json'

        # Write valid JSON but wrong type (array instead of object)
        recent_file.write_text('["not", "an", "object"]')

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            all_recent = recent.get_all()

            # Should return empty list and not crash
            assert all_recent == []

    def test_handles_json_primitive_gracefully(self, tmp_path):
        """Test that JSON primitive values are handled gracefully."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)
        recent_file = state_dir / 'recent.json'

        # Write valid JSON but primitive type
        recent_file.write_text('42')

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            all_recent = recent.get_all()

            # Should return empty list and not crash
            assert all_recent == []

    def test_handles_recent_files_as_string(self, tmp_path):
        """Test that recent_files as a string is handled gracefully."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)
        recent_file = state_dir / 'recent.json'

        # Write valid JSON structure but recent_files is a string
        recent_file.write_text('{"version": 1, "recent_files": "not a list"}')

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            all_recent = recent.get_all()

            # Should return empty list and not crash
            assert all_recent == []

    def test_handles_recent_files_list_of_strings(self, tmp_path):
        """Test that recent_files as list of strings is handled gracefully."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)
        recent_file = state_dir / 'recent.json'

        # Write list of strings instead of list of dicts
        recent_file.write_text('{"version": 1, "recent_files": ["string1", "string2"]}')

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            all_recent = recent.get_all()

            # Should return empty list and not crash
            assert all_recent == []

    def test_handles_recent_files_dict_missing_path_key(self, tmp_path):
        """Test that entries missing 'path' key are filtered out gracefully."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)
        recent_file = state_dir / 'recent.json'

        # Write dict missing 'path' key
        recent_file.write_text('{"version": 1, "recent_files": [{"display_name": "test.yaml"}]}')

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            all_recent = recent.get_all()

            # Should return empty list and not crash
            assert all_recent == []

    def test_handles_recent_files_path_as_number(self, tmp_path):
        """Test that 'path' as a number is handled gracefully."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)
        recent_file = state_dir / 'recent.json'

        # Write entry with 'path' as a number
        recent_file.write_text('{"version": 1, "recent_files": [{"path": 123, "display_name": "test"}]}')

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            all_recent = recent.get_all()

            # Should return empty list and not crash
            assert all_recent == []

    def test_handles_mixed_valid_invalid_entries(self, tmp_path):
        """Test that valid entries are kept while invalid ones are filtered out."""
        import json

        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)
        recent_file = state_dir / 'recent.json'

        # Create a valid test file
        valid_file = tmp_path / 'valid.yaml'
        valid_file.touch()

        # Write mix of valid and invalid entries using json.dumps for proper escaping
        data = {
            "version": 1,
            "recent_files": [
                {"path": str(valid_file), "last_opened": "2025-01-01T00:00:00Z", "display_name": "valid.yaml"},
                "invalid string entry",
                {"display_name": "missing path"},
                {"path": 123},
                {"path": "/nonexistent/file.yaml", "last_opened": "2025-01-01T00:00:00Z", "display_name": "nonexistent.yaml"}
            ]
        }
        recent_file.write_text(json.dumps(data))

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            all_recent = recent.get_all()

            # Should return only the one valid entry (nonexistent file filtered by get_all)
            assert len(all_recent) == 1
            assert 'valid.yaml' in all_recent[0]['path']

    def test_repairs_missing_display_name(self, tmp_path):
        """Test that missing display_name is derived from path."""
        import json

        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)
        recent_file = state_dir / 'recent.json'

        # Create test file
        test_file = tmp_path / 'test.yaml'
        test_file.touch()

        # Write entry without display_name using json.dumps for proper escaping
        data = {
            "version": 1,
            "recent_files": [
                {"path": str(test_file), "last_opened": "2025-01-01T00:00:00Z"}
            ]
        }
        recent_file.write_text(json.dumps(data))

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            all_recent = recent.get_all()

            # Should derive display_name from path
            assert len(all_recent) == 1
            assert all_recent[0]['display_name'] == 'test.yaml'

    def test_repairs_invalid_display_name_type(self, tmp_path):
        """Test that non-string display_name is replaced with derived value."""
        import json

        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)
        recent_file = state_dir / 'recent.json'

        # Create test file
        test_file = tmp_path / 'test.yaml'
        test_file.touch()

        # Write entry with display_name as number using json.dumps for proper escaping
        data = {
            "version": 1,
            "recent_files": [
                {"path": str(test_file), "last_opened": "2025-01-01T00:00:00Z", "display_name": 123}
            ]
        }
        recent_file.write_text(json.dumps(data))

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            all_recent = recent.get_all()

            # Should replace invalid display_name with derived value
            assert len(all_recent) == 1
            assert all_recent[0]['display_name'] == 'test.yaml'

    def test_repairs_missing_last_opened(self, tmp_path):
        """Test that missing last_opened gets empty string default."""
        import json

        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)
        recent_file = state_dir / 'recent.json'

        # Create test file
        test_file = tmp_path / 'test.yaml'
        test_file.touch()

        # Write entry without last_opened using json.dumps for proper escaping
        data = {
            "version": 1,
            "recent_files": [
                {"path": str(test_file), "display_name": "test.yaml"}
            ]
        }
        recent_file.write_text(json.dumps(data))

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            all_recent = recent.get_all()

            # Should add empty last_opened (humanize_timestamp will show "unknown")
            assert len(all_recent) == 1
            assert 'last_opened' in all_recent[0]
            assert isinstance(all_recent[0]['last_opened'], str)

    def test_repairs_invalid_last_opened_type(self, tmp_path):
        """Test that non-string last_opened gets empty string default."""
        import json

        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)
        recent_file = state_dir / 'recent.json'

        # Create test file
        test_file = tmp_path / 'test.yaml'
        test_file.touch()

        # Write entry with last_opened as number using json.dumps for proper escaping
        data = {
            "version": 1,
            "recent_files": [
                {"path": str(test_file), "display_name": "test.yaml", "last_opened": 12345}
            ]
        }
        recent_file.write_text(json.dumps(data))

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            all_recent = recent.get_all()

            # Should replace invalid last_opened with empty string
            assert len(all_recent) == 1
            assert 'last_opened' in all_recent[0]
            assert isinstance(all_recent[0]['last_opened'], str)

    def test_atomic_write(self, tmp_path):
        """Test that file writes are atomic (temp + replace)."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            test_file = tmp_path / 'test.yaml'
            test_file.touch()

            recent.add(test_file)

            # Verify recent.json exists
            recent_json = state_dir / 'recent.json'
            assert recent_json.exists()

            # Verify no temp files left behind
            temp_files = list(state_dir.glob('*.tmp'))
            assert len(temp_files) == 0

    @pytest.mark.posix_only
    def test_file_descriptor_closed_on_write_failure(self, tmp_path, monkeypatch):
        """Test that file descriptor is closed even if write fails."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)

        # Track open/close calls
        open_fds = []
        original_open = os.open
        original_close = os.close

        def tracking_open(*args, **kwargs):
            fd = original_open(*args, **kwargs)
            open_fds.append(fd)
            return fd

        def tracking_close(fd):
            if fd in open_fds:
                open_fds.remove(fd)
            return original_close(fd)

        # Patch os.write to fail after first byte
        write_call_count = [0]
        original_write = os.write

        def failing_write(fd, data):
            write_call_count[0] += 1
            if write_call_count[0] == 1:
                # Fail on first write to simulate disk full
                raise OSError("No space left on device")
            return original_write(fd, data)

        monkeypatch.setattr('os.open', tracking_open)
        monkeypatch.setattr('os.close', tracking_close)
        monkeypatch.setattr('os.write', failing_write)

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            test_file = tmp_path / 'test.yaml'
            test_file.touch()

            # This should fail but not leak file descriptors
            try:
                recent.add(test_file)
            except OSError:
                pass  # Expected

            # Verify all file descriptors were closed
            assert len(open_fds) == 0, f"File descriptors leaked: {open_fds}"

    @pytest.mark.posix_only
    def test_file_permissions_on_unix(self, tmp_path):
        """Test that recent.json has secure permissions (0600) on Unix."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles()
            test_file = tmp_path / 'test.yaml'
            test_file.touch()

            recent.add(test_file)

            # Check file permissions
            recent_json = state_dir / 'recent.json'
            stat_info = recent_json.stat()
            mode = stat_info.st_mode & 0o777
            assert mode == 0o600, f"Expected 0600, got {oct(mode)}"

    def test_json_format_structure(self, tmp_path):
        """Test that saved JSON has correct structure."""
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)

        with patch('gatekit.tui.recent_files.get_user_state_dir', return_value=state_dir):
            recent = RecentFiles(max_items=5)
            test_file = tmp_path / 'test.yaml'
            test_file.touch()

            recent.add(test_file)

            # Read and parse JSON directly
            recent_json = state_dir / 'recent.json'
            data = json.loads(recent_json.read_text())

            # Verify structure
            assert data['version'] == 1
            assert data['max_items'] == 5
            assert 'recent_files' in data
            assert len(data['recent_files']) == 1
            assert 'path' in data['recent_files'][0]
            assert 'last_opened' in data['recent_files'][0]
            assert 'display_name' in data['recent_files'][0]


class TestHumanizeTimestamp:
    """Test humanize_timestamp() function."""

    def test_just_now(self):
        """Test timestamp within last minute."""
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat().replace('+00:00', 'Z')

        result = humanize_timestamp(timestamp)
        assert result == "just now"

    def test_minutes_ago(self):
        """Test timestamp within last hour."""
        then = datetime.now(timezone.utc) - timedelta(minutes=5)
        timestamp = then.isoformat().replace('+00:00', 'Z')

        result = humanize_timestamp(timestamp)
        assert result == "5 minutes ago"

    def test_one_minute_ago(self):
        """Test singular 'minute' for 1 minute."""
        then = datetime.now(timezone.utc) - timedelta(minutes=1)
        timestamp = then.isoformat().replace('+00:00', 'Z')

        result = humanize_timestamp(timestamp)
        assert result == "1 minute ago"

    def test_hours_ago(self):
        """Test timestamp within last day."""
        then = datetime.now(timezone.utc) - timedelta(hours=3)
        timestamp = then.isoformat().replace('+00:00', 'Z')

        result = humanize_timestamp(timestamp)
        assert result == "3 hours ago"

    def test_one_hour_ago(self):
        """Test singular 'hour' for 1 hour."""
        then = datetime.now(timezone.utc) - timedelta(hours=1)
        timestamp = then.isoformat().replace('+00:00', 'Z')

        result = humanize_timestamp(timestamp)
        assert result == "1 hour ago"

    def test_yesterday(self):
        """Test timestamp between 1-2 days ago."""
        then = datetime.now(timezone.utc) - timedelta(days=1, hours=5)
        timestamp = then.isoformat().replace('+00:00', 'Z')

        result = humanize_timestamp(timestamp)
        assert result == "yesterday"

    def test_days_ago(self):
        """Test timestamp within last week."""
        then = datetime.now(timezone.utc) - timedelta(days=4)
        timestamp = then.isoformat().replace('+00:00', 'Z')

        result = humanize_timestamp(timestamp)
        assert result == "4 days ago"

    def test_weeks_ago(self):
        """Test timestamp within last month."""
        then = datetime.now(timezone.utc) - timedelta(weeks=2)
        timestamp = then.isoformat().replace('+00:00', 'Z')

        result = humanize_timestamp(timestamp)
        assert result == "2 weeks ago"

    def test_one_week_ago(self):
        """Test singular 'week' for 1 week."""
        then = datetime.now(timezone.utc) - timedelta(weeks=1)
        timestamp = then.isoformat().replace('+00:00', 'Z')

        result = humanize_timestamp(timestamp)
        assert result == "1 week ago"

    def test_old_date(self):
        """Test timestamp older than 28 days shows formatted date."""
        then = datetime.now(timezone.utc) - timedelta(days=60)
        timestamp = then.isoformat().replace('+00:00', 'Z')

        result = humanize_timestamp(timestamp)
        # Should return formatted date like "Nov 12, 2024"
        assert len(result) > 5  # Should be a date string
        assert ',' in result  # Date format includes comma

    def test_invalid_timestamp(self):
        """Test that invalid timestamp returns 'unknown'."""
        result = humanize_timestamp("not-a-timestamp")
        assert result == "unknown"

    def test_corrupted_timestamp(self):
        """Test that corrupted timestamp returns 'unknown'."""
        result = humanize_timestamp("2024-99-99T99:99:99Z")
        assert result == "unknown"
