"""Tests for path truncation in welcome screen."""


from gatekit.tui.screens.welcome import truncate_long_path


class TestTruncateLongPath:
    """Test suite for intelligent path truncation."""

    def test_short_path_unchanged(self):
        """Test that short paths are not truncated."""
        path = "config.yaml"
        assert truncate_long_path(path, max_length=50) == path

    def test_path_at_max_length_unchanged(self):
        """Test that paths exactly at max_length are not truncated."""
        path = "a" * 50
        assert truncate_long_path(path, max_length=50) == path

    def test_path_just_over_max_length_unchanged_if_few_parts(self):
        """Test that paths with fewer than 3 parts are not truncated even if long."""
        path = "very-long-filename-here.yaml"
        result = truncate_long_path(path, max_length=10)
        assert result == path  # Can't truncate meaningfully

    def test_truncates_middle_of_long_path(self):
        """Test that long paths get middle segments replaced with ellipsis."""
        path = "~/very/long/path/to/configs/file.yaml"
        result = truncate_long_path(path, max_length=30)

        # Should keep first and last 2 parts
        assert result.startswith("~")
        assert result.endswith("configs/file.yaml")
        assert "..." in result
        assert len(result) <= 30

    def test_keeps_as_many_start_parts_as_possible(self):
        """Test that truncation keeps as many leading parts as fit."""
        path = "~/alpha/beta/gamma/delta/epsilon/zeta/file.yaml"
        result = truncate_long_path(path, max_length=40)

        # Should have ~, at least one middle part, ..., and last 2 parts
        assert result.startswith("~")
        assert "..." in result
        assert result.endswith("zeta/file.yaml")

        # Count parts - should have more than just ~ and last 2
        parts = result.split("/")
        assert len(parts) >= 4  # ~, some parts, ..., zeta, file.yaml

    def test_handles_relative_paths(self):
        """Test truncation of relative paths."""
        path = "some/deeply/nested/directory/structure/here/file.yaml"
        result = truncate_long_path(path, max_length=35)

        assert result.startswith("some")
        assert "..." in result
        assert result.endswith("here/file.yaml")
        assert len(result) <= 35

    def test_handles_absolute_paths(self):
        """Test truncation of absolute Unix paths."""
        path = "/usr/local/lib/python3.10/site-packages/gatekit/config.yaml"
        result = truncate_long_path(path, max_length=45)

        assert result.startswith("/usr")
        assert "..." in result
        assert result.endswith("gatekit/config.yaml")
        assert len(result) <= 45

    def test_preserves_home_shortening(self):
        """Test that ~ prefix is preserved in truncation."""
        path = "~/projects/gatekit/configs/production/servers/main.yaml"
        result = truncate_long_path(path, max_length=40)

        assert result.startswith("~")
        assert "..." in result
        assert result.endswith("servers/main.yaml")

    def test_very_aggressive_truncation(self):
        """Test truncation with very small max_length."""
        path = "~/a/b/c/d/e/f/g/h/i/j/k/l/m/file.yaml"
        result = truncate_long_path(path, max_length=25)

        # Should still produce valid format: start/.../end
        assert result.startswith("~")
        assert "..." in result
        assert result.endswith("m/file.yaml")
        assert len(result) <= 25

    def test_handles_single_part_path(self):
        """Test that single-part paths are not truncated."""
        path = "verylongfilenamehere.yaml"
        result = truncate_long_path(path, max_length=10)
        assert result == path  # Can't truncate single part

    def test_handles_two_part_path(self):
        """Test that two-part paths are not truncated."""
        path = "configs/verylongfilename.yaml"
        result = truncate_long_path(path, max_length=15)
        assert result == path  # Need 3+ parts to truncate

    def test_exact_fit_after_truncation(self):
        """Test behavior when truncated result exactly fits."""
        # Craft a path where keeping first + ... + last 2 exactly fits
        path = "~/abc/def/ghi/jkl/mno/pqr/stu/vwx/yz.yaml"
        result = truncate_long_path(path, max_length=50)

        assert "..." in result or len(result) <= 50
        assert result.endswith("vwx/yz.yaml")

    def test_windows_absolute_path(self):
        """Test truncation of Windows absolute paths."""
        path = "C:\\Users\\username\\AppData\\Local\\Gatekit\\configs\\production.yaml"
        result = truncate_long_path(path, max_length=45)

        # Should preserve backslash separator
        assert "\\" in result
        assert "/" not in result
        assert result.startswith("C:\\")
        assert result.endswith("configs\\production.yaml")
        assert "..." in result
        assert len(result) <= 45

    def test_windows_unc_path(self):
        """Test truncation of Windows UNC paths."""
        path = "\\\\server\\share\\very\\long\\path\\to\\configs\\file.yaml"
        result = truncate_long_path(path, max_length=40)

        # Should preserve backslash separator
        assert "\\" in result
        assert "/" not in result
        assert "..." in result
        assert result.endswith("configs\\file.yaml")
        assert len(result) <= 40

    def test_windows_relative_path(self):
        """Test truncation of Windows relative paths."""
        path = "configs\\production\\servers\\alpha\\beta\\gamma\\main.yaml"
        result = truncate_long_path(path, max_length=40)

        # Should preserve backslash separator
        assert "\\" in result
        assert "/" not in result
        assert "..." in result
        assert result.endswith("gamma\\main.yaml")
        assert len(result) <= 40

    def test_windows_short_path_unchanged(self):
        """Test that short Windows paths are not truncated."""
        path = "C:\\configs\\file.yaml"
        result = truncate_long_path(path, max_length=50)
        assert result == path
        assert "\\" in result

    def test_mixed_separators_preserves_original(self):
        """Test that mixed separators preserve the detected style."""
        # If path has backslashes anywhere, use backslash
        path = "C:\\Users\\username/configs/file.yaml"  # Mixed (weird but possible)
        result = truncate_long_path(path, max_length=30)

        # Should detect backslash and use it
        assert "\\" in result
        assert "..." in result

    def test_windows_drive_letter_preserved(self):
        """Test that Windows drive letters are preserved in truncation."""
        path = "D:\\projects\\gatekit\\very\\long\\directory\\structure\\file.yaml"
        result = truncate_long_path(path, max_length=40)

        assert result.startswith("D:\\")
        assert "..." in result
        assert "structure\\file.yaml" in result
        assert len(result) <= 40
