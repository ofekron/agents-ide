#!/bin/bash
# Agents IDE Installation Wizard for macOS and Linux

set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${BOLD}${CYAN}"
echo "╔════════════════════════════════════════╗"
echo "║     Agents IDE Installation Wizard     ║"
echo "╚════════════════════════════════════════╝"
echo -e "${NC}"

# Function to prompt user
ask() {
    local prompt="$1"
    local default="$2"
    read -p "$prompt [$default]: " response
    echo "${response:-$default}"
}

confirm() {
    local prompt="$1"
    read -p "$prompt (y/n): " -n 1 -r
    echo
    [[ $REPLY =~ ^[Yy]$ ]]
}

# Step 1: Check Python
echo -e "${BOLD}Step 1: Checking Python...${NC}"
if command -v python3 &> /dev/null; then
    python_version=$(python3 --version 2>&1 | cut -d' ' -f2)
    major=$(echo $python_version | cut -d'.' -f1)
    minor=$(echo $python_version | cut -d'.' -f2)

    if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
        echo -e "${GREEN}✓ Python $python_version found${NC}"
    else
        echo -e "${RED}✗ Python 3.11+ required (found $python_version)${NC}"
        echo ""
        echo "Please install Python 3.11 or newer:"
        echo "  macOS: brew install python@3.11"
        echo "  Linux: sudo apt install python3.11"
        exit 1
    fi
else
    echo -e "${RED}✗ Python not found${NC}"
    echo ""
    echo "Please install Python 3.11+:"
    echo "  macOS: brew install python@3.11"
    echo "  Linux: sudo apt install python3.11"
    exit 1
fi

# Step 2: Check Node.js
echo ""
echo -e "${BOLD}Step 2: Checking Node.js...${NC}"
if command -v node &> /dev/null; then
    node_version=$(node --version)
    echo -e "${GREEN}✓ Node.js $node_version found${NC}"
else
    echo -e "${YELLOW}⚠ Node.js not found${NC}"
    echo ""
    if confirm "Would you like instructions to install Node.js?"; then
        echo ""
        echo "Install Node.js:"
        echo "  macOS: brew install node"
        echo "  Linux (Debian/Ubuntu): sudo apt install nodejs npm"
        echo "  Linux (Fedora): sudo dnf install nodejs npm"
        echo "  Or download from: https://nodejs.org/"
        echo ""
        read -p "Press Enter after installing Node.js to continue..."

        if ! command -v node &> /dev/null; then
            echo -e "${RED}Node.js still not found. Please install and try again.${NC}"
            exit 1
        fi
    else
        echo -e "${RED}Node.js is required. Exiting.${NC}"
        exit 1
    fi
fi

# Step 3: Install pyright
echo ""
echo -e "${BOLD}Step 3: Installing pyright LSP server...${NC}"
if command -v pyright-langserver &> /dev/null; then
    echo -e "${GREEN}✓ pyright-langserver already installed${NC}"
    if confirm "Reinstall/update pyright?"; then
        npm install -g pyright
    fi
else
    if confirm "Install pyright globally via npm?"; then
        echo "Running: npm install -g pyright"
        npm install -g pyright
        echo -e "${GREEN}✓ pyright installed${NC}"
    else
        echo -e "${YELLOW}⚠ Skipping pyright installation${NC}"
        echo "  You'll need to install it manually: npm install -g pyright"
    fi
fi

# Step 4: Install agents-ide
echo ""
echo -e "${BOLD}Step 4: Installing agents-ide...${NC}"
echo ""
echo "Installation options:"
echo "  1) Development mode (editable install, recommended for contributors)"
echo "  2) Regular install"
echo ""
install_mode=$(ask "Choose installation mode" "1")

if [ "$install_mode" = "1" ]; then
    echo "Running: pip install -e ."
    pip install -e .
else
    echo "Running: pip install ."
    pip install .
fi
echo -e "${GREEN}✓ agents-ide installed${NC}"

# Step 5: Configure Claude Code
echo ""
echo -e "${BOLD}Step 5: Configure Claude Code${NC}"
echo ""

claude_settings="$HOME/.claude/settings.json"
if [ -f "$claude_settings" ]; then
    echo "Found existing Claude Code settings at: $claude_settings"
    if confirm "Would you like to see the MCP configuration to add?"; then
        echo ""
        echo -e "${CYAN}Add this to your mcpServers in $claude_settings:${NC}"
        echo ""
        echo '  "agents-ide": {'
        echo '    "command": "agents-ide"'
        echo '  }'
        echo ""
    fi
else
    echo "Claude Code settings not found."
    if confirm "Create settings file with agents-ide configured?"; then
        mkdir -p "$HOME/.claude"
        cat > "$claude_settings" << 'EOF'
{
  "mcpServers": {
    "agents-ide": {
      "command": "agents-ide"
    }
  }
}
EOF
        echo -e "${GREEN}✓ Created $claude_settings${NC}"
    fi
fi

# Done
echo ""
echo -e "${BOLD}${GREEN}════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  Installation Complete!${NC}"
echo -e "${BOLD}${GREEN}════════════════════════════════════════${NC}"
echo ""
echo "Commands available:"
echo "  agents-ide        - Run MCP server"
echo "  agents-ide-daemon - Manage LSP daemon"
echo ""
echo "Test the daemon:"
echo "  agents-ide-daemon start"
echo "  agents-ide-daemon status"
echo ""
