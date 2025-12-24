#!/bin/bash
# Setup script for LibreOffice (used for PDF export)
#
# LibreOffice is optional but enables PDF export from Excel models.
# This script installs LibreOffice on macOS or Ubuntu.

set -e

echo "Setting up LibreOffice for PDF export..."

# Detect OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "Detected macOS"

    # Check if Homebrew is installed
    if ! command -v brew &> /dev/null; then
        echo "Homebrew not found. Please install Homebrew first:"
        echo "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        exit 1
    fi

    # Install LibreOffice via Homebrew
    echo "Installing LibreOffice via Homebrew..."
    brew install --cask libreoffice

    echo "LibreOffice installed successfully!"
    echo "Location: /Applications/LibreOffice.app"

elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo "Detected Linux"

    # Check for apt (Debian/Ubuntu)
    if command -v apt-get &> /dev/null; then
        echo "Installing LibreOffice via apt..."
        sudo apt-get update
        sudo apt-get install -y libreoffice

        echo "LibreOffice installed successfully!"

    # Check for dnf (Fedora)
    elif command -v dnf &> /dev/null; then
        echo "Installing LibreOffice via dnf..."
        sudo dnf install -y libreoffice

        echo "LibreOffice installed successfully!"

    else
        echo "Unsupported Linux distribution. Please install LibreOffice manually."
        exit 1
    fi

else
    echo "Unsupported operating system: $OSTYPE"
    echo "Please install LibreOffice manually from: https://www.libreoffice.org/"
    exit 1
fi

# Verify installation
echo ""
echo "Verifying installation..."
if command -v soffice &> /dev/null; then
    soffice --version
    echo ""
    echo "LibreOffice is ready for PDF export!"
else
    echo "LibreOffice installed but 'soffice' command not found in PATH."
    echo "You may need to add it to your PATH or restart your terminal."
fi
