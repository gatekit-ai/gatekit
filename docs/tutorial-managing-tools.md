# Tutorial: Managing Tools with Gatekit

This tutorial shows how to filter, rename, and customize tool descriptions using the Tool Manager plugin.

## Why Manage Tools?

MCP servers often expose more tools than you need. Extra tools:
- Clutter the agent's context window
- Increase the chance of the agent picking the wrong tool
- May expose capabilities you'd rather hide

Tool Manager lets you curate exactly which tools are visible to your MCP client.

## Prerequisites

- Gatekit installed and configured (run `gatekit` to complete guided setup)
- At least one MCP server configured

## Step 1: Open the Server Panel

1. Run `gatekit`
2. Select your config file (or use the default)
3. In the main view, select the server you want to configure
4. Press `Enter` to open the server panel

Tool Manager is configured **per-server** because each server has different tools.

## Step 2: Enable Tool Manager

1. In the server panel, find **Tool Manager** under the Middleware section
2. Select it and press `Enter` to open the configuration modal
3. Toggle **Enabled** to on

## Step 3: Select Which Tools to Allow

The Tool Manager uses an **allowlist** - only checked tools are visible to your MCP client.

1. In the configuration modal, you'll see a list of all tools from this server
2. **Check** the tools you want to keep visible
3. **Uncheck** tools you want to hide

> **Tip**: Start by unchecking tools you never use. You can always re-enable them later.

## Step 4: Rename a Tool (Optional)

Tool names from MCP servers aren't always clear. You can rename them:

1. Select a tool in the list
2. Edit the **Display Name** field
3. The original tool still works - Gatekit translates the name automatically

**Example**: Rename `fs_read` to `read_file` for clarity.

## Step 5: Customize a Description (Optional)

Tool descriptions help the agent understand when to use each tool. Override unclear descriptions:

1. Select a tool in the list
2. Edit the **Display Description** field
3. Write a clear, specific description

**Example**: Change `puppeteer_screenshot`'s description from "Take a screenshot" to "Capture the current page for visual debugging. Use after navigation or interactions to verify the expected state rendered correctly."

## Step 6: Save and Restart

1. Press `Ctrl+S` or click **Save** to save your configuration
2. Restart your MCP client (Claude Desktop, Cursor, etc.)

Your client will now only see the tools you allowed, with your custom names and descriptions.

## Verifying It Works

Ask your MCP client to list available tools. You should see:
- Only the tools you enabled
- Your custom names (if you renamed any)
- Your custom descriptions (if you changed any)

## Next Steps

- Configure Tool Manager for your other servers
- Explore [audit logging](configuration-specification.md#plugin-configuration) to see what tools are being called
- Read the [plugin development guide](plugin-development-guide.md) to build custom filtering logic
