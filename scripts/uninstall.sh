#!/bin/bash

systemctl --user disable nova-chatmix --now
rm ~/.config/systemd/user/nova-chatmix.service
systemctl --user daemon-reload

rm ~/.local/bin/nova-chatmix 

sudo rm /etc/udev/rules.d/50-nova-pro.rules

sudo udevadm control --reload-rules
sudo udevadm trigger
