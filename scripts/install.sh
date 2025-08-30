#!/bin/bash

## Copy `50-nova-pro.rules` to `/etc/udev/rules.d` and reload udev rules:
# To be able to run the script as a non-root user, some udev rules need to be applied.
# This will allow regular users to access the base station USB device.
# It also starts the script when it gets plugged in (only when the systemd service is also set up).
sudo cp 50-nova-pro.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger

## The systemd service expects the script in .local/bin
# Create the folder if it doesn't exist
mkdir -p ~/.local/bin
# Copy the script to the expected location
cp -i nova-chatmix.py ~/.local/bin/nova-chatmix
chmod +x ~/.local/bin/nova-chatmix

# Create systemd user unit folder if it doesn't exist
mkdir -p ~/.config/systemd/user
# Install the service file
cp nova-chatmix.service ~/.config/systemd/user/
# Reload systemd configuration
systemctl --user daemon-reload
# Enable and start the service
systemctl --user enable nova-chatmix --now
