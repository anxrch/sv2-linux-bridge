#!/bin/bash
# SV2 Linux Bridge Installer
# Installs the authentication bridge for SV2 on Linux with Bottles

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/sv2-linux-bridge"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_status() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[OK]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check Python
check_python() {
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is required"
        exit 1
    fi
    print_success "Python 3 found"
}

# Check Bottles
check_bottles() {
    if flatpak list | grep -q "com.usebottles.bottles"; then
        print_success "Bottles found"
    else
        print_warning "Bottles not found. Install with: flatpak install flathub com.usebottles.bottles"
    fi
}

# Create virtual environment
setup_venv() {
    print_status "Setting up virtual environment..."

    if [[ ! -d "$SCRIPT_DIR/.venv" ]]; then
        python3 -m venv "$SCRIPT_DIR/.venv"
    fi

    source "$SCRIPT_DIR/.venv/bin/activate"
    pip install --upgrade pip -q
    pip install -r "$SCRIPT_DIR/requirements.txt" -q

    print_success "Virtual environment ready"
}

# Create executable wrapper
create_wrapper() {
    print_status "Creating executable wrapper..."

    mkdir -p "$BIN_DIR"

    cat > "$BIN_DIR/sv2-auth-bridge" << EOF
#!/bin/bash
INSTALL_DIR="$SCRIPT_DIR"
VENV_DIR="\$INSTALL_DIR/.venv"
export SV2_BOTTLE_NAME="\${SV2_BOTTLE_NAME:-svstudio64}"
export PYTHONPATH="\$INSTALL_DIR/src:\$PYTHONPATH"

# Activate venv and run
cd "\$INSTALL_DIR"
exec "\$VENV_DIR/bin/python" -m src.auth_bridge.server "\$@"
EOF

    chmod +x "$BIN_DIR/sv2-auth-bridge"
    print_success "Created $BIN_DIR/sv2-auth-bridge"
}

# Create desktop entry for protocol handler
create_desktop_entry() {
    print_status "Creating desktop entry..."

    mkdir -p "$DESKTOP_DIR"

    cat > "$DESKTOP_DIR/sv2-auth-bridge.desktop" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=SV2 Auth Bridge
Comment=OAuth handler for Synthesizer V Studio 2
Exec=$BIN_DIR/sv2-auth-bridge %u
NoDisplay=true
StartupNotify=false
MimeType=x-scheme-handler/dreamtonics-svstudio2;
EOF

    chmod +x "$DESKTOP_DIR/sv2-auth-bridge.desktop"

    # Update desktop database
    if command -v update-desktop-database &> /dev/null; then
        update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    fi

    # Register with xdg-mime
    if command -v xdg-mime &> /dev/null; then
        xdg-mime default sv2-auth-bridge.desktop x-scheme-handler/dreamtonics-svstudio2 2>/dev/null || true
    fi

    print_success "Desktop entry created"
}

# Setup PATH
setup_path() {
    if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
        print_warning "~/.local/bin is not in PATH"
        print_status "Add this to your ~/.bashrc or ~/.zshrc:"
        echo '  export PATH="$HOME/.local/bin:$PATH"'
    fi
}

# Print Firefox configuration instructions
print_firefox_config() {
    echo ""
    print_status "Firefox Configuration"
    echo ""
    echo "Edit your Firefox handlers.json file:"
    echo "  Location: ~/.mozilla/firefox/*.default-release/handlers.json"
    echo ""
    echo "Add this to the 'schemes' section:"
    echo ""
    cat << 'EOF'
  "dreamtonics-svstudio2": {
    "action": 2,
    "handlers": [
      {
        "name": "SV2 Auth Bridge",
        "path": "$HOME/.local/bin/sv2-auth-bridge"
      }
    ]
  }
EOF
    echo ""
    echo "(Replace \$HOME with your actual home directory path)"
}

# Print usage
print_usage() {
    echo ""
    print_success "Installation complete!"
    echo ""
    echo "Usage:"
    echo "  1. Start the auth bridge server:"
    echo "     sv2-auth-bridge --port 8888"
    echo ""
    echo "  2. Launch SV2 from Bottles"
    echo ""
    echo "  3. Click login in SV2, complete login in Firefox"
    echo ""
    echo "Environment variables:"
    echo "  SV2_BOTTLE_NAME  - Bottle name (default: svstudio64)"
    echo ""
    echo "Logs: /tmp/auth_bridge.log"
}

# Main
main() {
    echo "SV2 Linux Bridge Installer"
    echo "=========================="
    echo ""

    check_python
    check_bottles
    setup_venv
    create_wrapper
    create_desktop_entry
    setup_path
    print_firefox_config
    print_usage
}

main "$@"
