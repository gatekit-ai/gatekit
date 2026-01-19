"""Configuration persistence and management for Config Editor screen."""

import hashlib
import json
import logging
from typing import Dict, Any

from gatekit.config.models import ProxyConfig
from gatekit.config.loader import ConfigLoader
from gatekit.config.serialization import config_to_dict
from gatekit.config.persistence import save_config
from gatekit.config.errors import ConfigWriteError
from gatekit.plugins.manager import PluginManager


class ConfigPersistenceMixin:
    """Mixin providing configuration persistence functionality for ConfigEditorScreen."""

    async def _persist_config(self) -> bool:
        """Save configuration to disk using centralized save_config.

        Returns:
            True if save succeeded, False otherwise
        """
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        try:
            # Use centralized save_config with atomic writes and draft validation
            save_config(
                self.config_file_path,
                self.config,
                allow_incomplete=False,  # Config editor requires complete configs
                header=None,  # No header for config editor saves
                atomic=True,  # Always use atomic writes for safety
            )

            if logger:
                logger.log_state_change(
                    "config_saved",
                    {"path": str(self.config_file_path)},
                    {"status": "success"},
                    screen=self,
                )
            return True

        except ConfigWriteError as e:
            # Handle write errors from save_config
            if logger:
                import traceback

                logger.log_event(
                    "config_save_failed",
                    screen=self,
                    context={"error": str(e), "traceback": traceback.format_exc()},
                )

            # Show error modal
            self.app.notify(f"Failed to save configuration: {e}", severity="error")
            return False

        except ValueError as e:
            # Handle validation errors (incomplete configs)
            if logger:
                logger.log_event(
                    "config_serialization_failed",
                    screen=self,
                    context={"error": f"Failed to serialize config: {e}"},
                )

            self.app.notify(f"Failed to save configuration: {e}", severity="error")
            return False

        except Exception as e:
            # Handle unexpected errors
            if logger:
                import traceback

                logger.log_event(
                    "config_save_failed",
                    screen=self,
                    context={"error": str(e), "traceback": traceback.format_exc()},
                )

            self.app.notify(f"Failed to save configuration: {e}", severity="error")
            return False

    async def _save_and_rebuild(self) -> bool:
        """Save configuration and rebuild runtime state with concurrency safety.

        Returns:
            True if save succeeded, False if save failed (config reverted)
        """
        # Use lock to prevent concurrent save operations
        async with self._save_lock:
            if not await self._persist_config():
                # Only reload from disk if file exists (not for new documents)
                if self.config_file_path and self.config_file_path.exists():
                    # Reload from disk to discard in-memory drift
                    self.config = self._load_config_from_disk()

                    # Notify user that changes were reverted
                    self.app.notify(
                        "Configuration reverted to last saved state due to save failure",
                        severity="warning",
                    )

                    # Refresh runtime state from disk
                    await self._reset_runtime_from_disk()

                    # Clear dirty flag since we've reverted to the last saved state
                    self._mark_clean()
                else:
                    # New document or file doesn't exist - keep in-memory config
                    self.app.notify(
                        "Failed to save configuration. Your changes are still in memory.",
                        severity="error",
                    )
                    # Keep dirty flag - user needs to try saving again

                return False

            await self._rebuild_runtime_state()
            return True

    async def _rebuild_runtime_state(self) -> None:
        """Rebuild PluginManager and re-render UI."""
        from pathlib import Path

        # Use config file's directory or cwd for new documents
        config_dir = self.config_file_path.parent if self.config_file_path else Path.cwd()

        # Re-fetch plugins from manager (clears any caches)
        self.plugin_manager = PluginManager(
            self.config.plugins.to_dict() if self.config.plugins else {},
            config_directory=config_dir,
        )

        # CRITICAL: Must load plugins or get_plugins_for_upstream() returns empty!
        await self.plugin_manager.load_plugins()

        # Refresh available handlers and identity mapping to reflect latest config
        self._refresh_discovery_state()

        # Ensure handshake discovery runs for any new upstreams
        self._run_worker(self._discover_server_identities())

        # Reload the plugin display
        await self._populate_server_plugins()

        # Update any other UI elements that might be affected
        self.refresh()

    async def _reset_runtime_from_disk(self) -> None:
        """Reset runtime state from disk configuration (DRY helper)."""
        # Refresh available handlers in case they changed on disk
        await self._initialize_plugin_system()

        # Rebuild runtime state
        await self._rebuild_runtime_state()

    async def _refresh_plugin_display(self) -> None:
        """Rebuild plugin manager and re-render server plugin details.
        TODO: Mark for replacement in MSP-4 by grouped renderer in consolidated right panel.
        """
        # This is the deprecated version that will be replaced by _rebuild_runtime_state
        await self._rebuild_runtime_state()

    def _load_config_from_disk(self) -> ProxyConfig:
        """Thin wrapper around ConfigLoader().load_from_file() returning a fresh ProxyConfig."""
        loader = ConfigLoader()
        return loader.load_from_file(self.config_file_path)

    def _config_to_dict(self, config: ProxyConfig) -> Dict[str, Any]:
        """Convert ProxyConfig to dictionary suitable for YAML serialization.

        Wrapper around shared config_to_dict() function with draft validation enabled.

        Args:
            config: The ProxyConfig to convert

        Returns:
            Dictionary representation suitable for YAML
        """
        # Use shared serialization with draft validation
        return config_to_dict(config, validate_drafts=True)

    async def _save_configuration(self) -> bool:
        """Save the current configuration to disk.

        Returns:
            True if save succeeded, False otherwise
        """
        return await self._persist_config()

    def action_save_config(self) -> None:
        """Save current configuration to file."""
        self._run_worker(self._save_config_with_notification())

    def action_save_config_as(self) -> None:
        """Save current configuration to a new file (Save As)."""
        self._run_worker(self._save_config_as_with_modal())

    async def _save_config_as_with_modal(self) -> None:
        """Show Save As modal and save configuration to new path."""
        from pathlib import Path
        from textual_fspicker import FileSave
        from ..simple_modals import ConfirmModal

        # IMPORTANT: Validate here too - user can trigger Save As directly via Ctrl+Shift+S
        if not self._validate_can_save():
            return

        # Determine start location and default filename
        if self.config_file_path:
            start_dir = self.config_file_path.parent
            default_file = self.config_file_path.name
        else:
            # New document - use configs dir or cwd
            configs_dir = Path.cwd() / "configs"
            start_dir = configs_dir if configs_dir.exists() else Path.cwd()
            default_file = "gatekit.yaml"

        # Show Save As modal
        new_path = await self.app.push_screen_wait(
            FileSave(location=start_dir, default_file=default_file)
        )

        if new_path is None:
            # User cancelled
            return

        # Check if file already exists
        if new_path.exists():
            # Ask for confirmation to overwrite
            confirm = await self.app.push_screen_wait(
                ConfirmModal(
                    "Overwrite existing file?",
                    f"The file '{new_path.name}' already exists. Do you want to overwrite it?",
                    confirm_label="Overwrite",
                    cancel_label="Cancel",
                    confirm_variant="error",
                )
            )
            if not confirm:
                # User cancelled overwrite
                return

        # CRITICAL: Capture this BEFORE setting config_file_path
        was_new_document = self.is_new_document

        # Store old path in case we need to rollback
        old_path = self.config_file_path

        try:
            # Update config file path to new location
            self.config_file_path = new_path

            # Save to new path
            success = await self._save_and_rebuild()

            if success:
                self._mark_clean()
                self.app.notify(
                    f"✓ Saved to {new_path.name}. Restart MCP clients to apply.",
                    severity="success",
                )
                # Update header to show new filename
                self._update_header()
                # Add new file to recent files list
                from ...recent_files import RecentFiles
                recent_files = RecentFiles()
                recent_files.add(new_path)

                # Update app-level state for first save of new document
                if was_new_document:
                    self.app.config_path = self.config_file_path
                    self.app.config_exists = True
            else:
                # Save failed, rollback to old path
                self.config_file_path = old_path
                self._update_header()

        except Exception as e:
            # Rollback to old path on error
            self.config_file_path = old_path
            self._update_header()
            self.app.notify(
                f"Failed to save configuration: {e}",
                severity="error",
            )

    def _validate_can_save(self) -> bool:
        """Check if config is valid for saving. Returns False and shows warning if not.

        Validates that:
        1. At least one MCP server is configured
        2. At least one server is complete (not a draft)
        """
        # Check for empty upstreams
        if not self.config.upstreams:
            self.app.notify(
                "At least one MCP server must be configured before saving.",
                severity="warning",
            )
            return False

        # Check that at least one server is complete (not draft)
        has_complete_server = any(
            not getattr(u, "is_draft", False) for u in self.config.upstreams
        )
        if not has_complete_server:
            self.app.notify(
                "At least one MCP server must be fully configured before saving. "
                "Complete the server configuration (command or URL required).",
                severity="warning",
            )
            return False

        return True

    async def _save_config_with_notification(self) -> None:
        """Save config and show appropriate notification.

        Wraps _save_and_rebuild() with error handling to prevent silent failures
        if an unexpected exception occurs during save/rebuild.
        """
        # Validate before any save attempt
        if not self._validate_can_save():
            return

        # New document needs Save As flow
        if self.is_new_document:
            await self._save_config_as_with_modal()
            return

        try:
            success = await self._save_and_rebuild()
            if success:
                self._mark_clean()
                self.app.notify(
                    "✓ Saved. Restart MCP clients to apply.",
                    severity="success"
                )
            # Note: False case already handled by _save_and_rebuild (shows warning)
        except Exception as e:
            # Catch unexpected exceptions to prevent silent task death
            self.app.notify(
                f"Unexpected error saving configuration: {e}",
                severity="error"
            )
            # Optional: Log full traceback for debugging
            import traceback
            import logging
            logging.exception(f"Save error: {traceback.format_exc()}")

    # COMMENTED OUT: Reload functionality removed from UI
    # Keeping code for potential future restoration
    # def action_reload_config(self) -> None:
    #     """Reload configuration from file."""
    #     self._run_worker(self._reload_config_with_confirmation())
    #
    # async def _reload_config_with_confirmation(self) -> None:
    #     """Reload config, with confirmation if dirty state exists.
    #
    #     CRITICAL: Uses same _save_lock as save to prevent concurrent operations.
    #     CRITICAL: Assigns config before rebuild, but rolls back both config AND runtime on failure.
    #     """
    #     # Check dirty state and confirm before reload
    #     if self._config_dirty:
    #         from ..simple_modals import ConfirmModal
    #         result = await self.app.push_screen_wait(
    #             ConfirmModal("Discard unsaved changes?", "Reloading will discard all unsaved changes.")
    #         )
    #         if not result:
    #             return  # User cancelled
    #
    #     # CRITICAL: Use same lock as save to prevent race conditions
    #     async with self._save_lock:
    #         try:
    #             # Load into local variable first
    #             new_config = self._load_config_from_disk()
    #
    #             # Save old config for rollback if rebuild fails
    #             old_config = self.config
    #
    #             # Assign new config - if rebuild fails, we'll rollback to old_config
    #             self.config = new_config
    #
    #             try:
    #                 # Rebuild runtime state with new config
    #                 await self._reset_runtime_from_disk()
    #
    #                 # SUCCESS: Rebuild worked, keep new config
    #                 self._mark_clean()
    #
    #                 self.app.notify(
    #                     f"Configuration reloaded from {self.config_file_path.name}",
    #                     severity="information"
    #                 )
    #             except Exception as rebuild_error:
    #                 # CRITICAL ROLLBACK: Rebuild failed, must restore BOTH config AND runtime
    #                 self.config = old_config
    #
    #                 # CRITICAL: Rebuild runtime from self.config (old_config), NOT from disk
    #                 # Using _reset_runtime_from_disk() would reload from disk = wrong config
    #                 # Using _rebuild_runtime_state() rebuilds from self.config = correct
    #                 try:
    #                     await self._rebuild_runtime_state()
    #                     # Runtime now matches old config - consistent state restored
    #                 except Exception as rollback_error:
    #                     # Even rollback failed - system in unknown state
    #                     import logging
    #                     logging.error(
    #                         f"Runtime rollback failed after reload error. "
    #                         f"Original error: {rebuild_error}, "
    #                         f"Rollback error: {rollback_error}"
    #                     )
    #                     # At this point: config is old, runtime state is unknown
    #                     # User will need to restart app for guaranteed consistency
    #                     self.app.notify(
    #                         "Reload failed and rollback failed. Please restart the application.",
    #                         severity="error"
    #                     )
    #
    #                 raise rebuild_error
    #
    #         except Exception as e:
    #             # Either load failed (before any assignment) or rebuild failed (after rollback)
    #             # In both cases, config should be consistent
    #             self.app.notify(
    #                 f"Failed to reload configuration: {e}",
    #                 severity="error"
    #             )

    def _compute_config_hash(self) -> str:
        """Compute hash of current config for change detection.

        Returns empty string if config can't be serialized (e.g., has draft upstreams).
        This allows dirty tracking to work even with unsaveable intermediate states.
        """
        try:
            config_dict = self._config_to_dict(self.config)
            config_json = json.dumps(config_dict, sort_keys=True)
            return hashlib.sha256(config_json.encode()).hexdigest()
        except ValueError:
            # Config has unsaveable state (e.g., draft upstreams)
            # Return empty hash - dirty tracking still works, just can't detect if saved
            return ""
        except Exception as e:
            # Unexpected error during serialization
            logging.warning(f"Failed to compute config hash: {e}")
            return ""

    def _mark_dirty(self) -> None:
        """Mark config as having unsaved changes."""
        self._config_dirty = True
        self._update_header()

    def _mark_clean(self) -> None:
        """Mark config as saved.

        IMPORTANT: If config can't be serialized (e.g., has draft upstreams),
        we stay dirty to warn the user that the config is not actually saveable.
        This prevents showing a "clean" state for unsaveable configurations.
        """
        new_hash = self._compute_config_hash()
        if not new_hash:
            # Config can't be serialized - don't mark clean
            # Keep dirty state to warn user of unsaveable state
            logging.debug("Cannot mark clean: config is not serializable (may have draft upstreams)")
            return

        self._config_dirty = False
        self._last_saved_config_hash = new_hash
        self._update_header()

    def _update_header(self) -> None:
        """Update header to show dirty state (asterisk when unsaved changes exist)."""
        try:
            # Update the screen's subtitle to show filename and dirty indicator
            dirty_indicator = " *" if self._config_dirty else ""
            if self.config_file_path:
                self.sub_title = f"{self.config_file_path.name}{dirty_indicator}"
            else:
                self.sub_title = f"[New Configuration]{dirty_indicator}"
        except Exception:
            # Header not yet mounted or screen not ready - safe to ignore
            pass
