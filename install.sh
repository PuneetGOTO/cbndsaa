#!/bin/bash

# ==============================================================================
#            Discord Lottery Bot One-Click Installer for Ubuntu
# ==============================================================================
#
# This script automates the installation and configuration of the lottery bot.
# It will:
#   1. Check for root privileges.
#   2. Update system packages.
#   3. Install Python3, pip, and venv.
#   4. Clone the bot's source code from a Git repository.
#   5. Set up a Python virtual environment and install dependencies.
#   6. Interactively configure the bot (.env file).
#   7. Set up a systemd service for auto-starting and process management.
#   8. Start the bot service.
#
# Usage:
#   bash <(curl -fsSL YOUR_RAW_SCRIPT_URL)
#
# ==============================================================================

# --- Script Configuration ---
# !!! IMPORTANT !!!
# CHANGE THIS TO YOUR BOT'S GIT REPOSITORY URL
GIT_REPO_URL="https://github.com/PuneetGOTO/DISCORDCJBT.git"

# Directory where the bot will be installed
INSTALL_DIR="/opt/discord_lottery_bot"

# Name for the systemd service
SERVICE_NAME="lottery-bot"

# --- Helper Functions ---

# Function to print colored messages
print_msg() {
    COLOR=$1
    MSG=$2
    NC='\033[0m' # No Color
    case $COLOR in
        "green") echo -e "\033[0;32m${MSG}${NC}" ;;
        "yellow") echo -e "\033[0;33m${MSG}${NC}" ;;
        "red") echo -e "\033[0;31m${MSG}${NC}" ;;
        "blue") echo -e "\033[0;34m${MSG}${NC}" ;;
        *)
    esac
}

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# --- Main Installation Logic ---

main() {
    print_msg blue "Starting Discord Lottery Bot Installation..."

    # 1. Check for root privileges
    if [ "$(id -u)" -ne 0 ]; then
        print_msg red "Error: This script must be run as root. Please use sudo."
        exit 1
    fi

    # 2. Update system packages
    print_msg blue "Updating package lists..."
    apt-get update -y

    # 3. Install dependencies
    print_msg blue "Installing required packages (git, python3, python3-pip, python3-venv)..."
    apt-get install -y git python3 python3-pip python3-venv

    # 4. Clone the repository
    if [ -d "$INSTALL_DIR" ]; then
        print_msg yellow "Installation directory $INSTALL_DIR already exists. Pulling latest changes."
        cd "$INSTALL_DIR"
        git pull
    else
        print_msg blue "Cloning repository from $GIT_REPO_URL..."
        git clone "$GIT_REPO_URL" "$INSTALL_DIR"
    fi
    cd "$INSTALL_DIR"

    # 5. Set up Python virtual environment
    print_msg blue "Setting up Python virtual environment..."
    python3 -m venv venv
    source venv/bin/activate

    print_msg blue "Installing Python dependencies from requirements.txt..."
    pip install -r requirements.txt

    # 6. Interactive Configuration
    print_msg blue "Configuring the bot..."
    if [ -f ".env" ]; then
        print_msg yellow ".env file already exists. Skipping creation."
    else
        cp .env.example .env
        read -p "Please enter your Discord Bot Token: " BOT_TOKEN
        read -p "Please enter your Bot Owner ID: " BOT_OWNER_ID
        sed -i "s/^BOT_TOKEN=.*/BOT_TOKEN=${BOT_TOKEN}/" .env
        sed -i "s/^BOT_OWNER_ID=.*/BOT_OWNER_ID=${BOT_OWNER_ID}/" .env
    fi

    # 7. Set up systemd service
    print_msg blue "Setting up systemd service..."
    cat > /etc/systemd/system/${SERVICE_NAME}.service <<EOL
[Unit]
Description=Discord Lottery Bot
After=network.target

[Service]
User=root
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python3 ${INSTALL_DIR}/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

    # 8. Start the service
    print_msg blue "Reloading systemd, enabling and starting the bot service..."
    systemctl daemon-reload
    systemctl enable ${SERVICE_NAME}
    systemctl restart ${SERVICE_NAME}

    print_msg green "-----------------------------------------------------"
    print_msg green "  Installation Complete!"
    print_msg green "-----------------------------------------------------"
    print_msg yellow "The bot is now running as a background service."
    print_msg yellow "To check its status, run: systemctl status ${SERVICE_NAME}"
    print_msg yellow "To view its logs, run: journalctl -u ${SERVICE_NAME} -f"
}

# --- Execute Main Function ---
main
