#!/bin/bash

# Agent Crucible Plugin Installer for Claude Code

set -e

echo "Installing Agent Crucible plugin..."

# Check if running from the correct directory
if [ ! -d "plugin/agent-crucible" ]; then
    echo "Error: Please run this script from the agent-crucible repository root"
    exit 1
fi

# Create plugin directory
PLUGIN_DIR="$HOME/.claude/plugins/cache/agent-crucible/agent-crucible/0.1.0"
mkdir -p "$PLUGIN_DIR"

# Copy plugin files
echo "Copying plugin files..."
cp -r plugin/agent-crucible/* "$PLUGIN_DIR/"

# Update installed_plugins.json
INSTALLED_PLUGINS="$HOME/.claude/plugins/installed_plugins.json"

if [ ! -f "$INSTALLED_PLUGINS" ]; then
    echo "Creating installed_plugins.json..."
    cat > "$INSTALLED_PLUGINS" << 'EOF'
{
  "version": 2,
  "plugins": {}
}
EOF
fi

# Check if already registered
if grep -q "agent-crucible@agent-crucible" "$INSTALLED_PLUGINS"; then
    echo "Plugin already registered."
else
    echo "Registering plugin..."
    # Use Python to safely update JSON
    python3 << 'PYEOF'
import json
import os

plugins_file = os.path.expanduser("~/.claude/plugins/installed_plugins.json")
with open(plugins_file, 'r') as f:
    data = json.load(f)

data["plugins"]["agent-crucible@agent-crucible"] = [{
    "scope": "user",
    "installPath": os.path.expanduser("~/.claude/plugins/cache/agent-crucible/agent-crucible/0.1.0"),
    "version": "0.1.0",
    "installedAt": "2026-05-12T14:20:00.000Z",
    "lastUpdated": "2026-05-12T14:20:00.000Z",
    "gitCommitSha": "local"
}]

with open(plugins_file, 'w') as f:
    json.dump(data, f, indent=2)

print("Plugin registered successfully.")
PYEOF
fi

echo ""
echo "✓ Agent Crucible plugin installed successfully!"
echo ""
echo "Next steps:"
echo "1. Restart Claude Code"
echo "2. Use /agent-crucible skill or call crew_run() MCP tool"
echo ""
