#!/bin/bash
# Gather hardware information for Linux kernel configuration
# Target: ThinkPad X240 (20ALCTO1WW)

set -e

OUTPUT="hardware_info.txt"
echo "Gathering hardware information for kernel configuration..."
echo "Output will be saved to $OUTPUT"

# Basic system info
{
echo "=== System Information ==="
echo "Host: $(cat /sys/devices/virtual/dmi/id/product_name 2>/dev/null || echo 'Unknown')"
echo "BIOS: $(cat /sys/devices/virtual/dmi/id/bios_version 2>/dev/null || echo 'Unknown')"
echo "CPU: $(grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2 | xargs)"
echo "Kernel: $(uname -r)"
echo "Architecture: $(uname -m)"
echo ""

echo "=== CPU Flags ==="
grep -oP 'flags\s*: \K.*' /proc/cpuinfo | head -1 | tr ' ' '\n' | sort
echo ""

echo "=== PCI Devices ==="
lspci -nn 2>/dev/null || echo "lspci not available"
echo ""

echo "=== USB Devices ==="
lsusb 2>/dev/null || echo "lsusb not available"
echo ""

echo "=== Block Devices ==="
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,MODEL 2>/dev/null || echo "lsblk not available"
echo ""

echo "=== Network Interfaces ==="
ip link show 2>/dev/null || echo "ip not available"
echo ""

echo "=== Wireless Info ==="
iwconfig 2>/dev/null || echo "iwconfig not available"
echo ""

echo "=== Battery Info ==="
for bat in /sys/class/power_supply/BAT*; do
    if [ -d "$bat" ]; then
        echo "Battery: $(basename $bat)"
        cat "$bat/manufacturer" 2>/dev/null && echo ""
        cat "$bat/model_name" 2>/dev/null && echo ""
        cat "$bat/status" 2>/dev/null && echo ""
        cat "$bat/capacity" 2>/dev/null && echo "%"
    fi
done
echo ""

echo "=== Input Devices ==="
cat /proc/bus/input/devices 2>/dev/null || echo "Input info not available"
echo ""

echo "=== Audio Devices ==="
aplay -l 2>/dev/null || echo "aplay not available"
echo ""

echo "=== Bluetooth ==="
hciconfig -a 2>/dev/null || echo "hciconfig not available"
echo ""

echo "=== DMI/SMBIOS Info ==="
dmidecode -t system 2>/dev/null || echo "dmidecode not available (requires root)"
echo ""

echo "=== Kernel Modules Currently Loaded ==="
lsmod 2>/dev/null || echo "lsmod not available"
echo ""

echo "=== Existing Kernel Config ==="
if [ -f /proc/config.gz ]; then
    echo "Current kernel config available at /proc/config.gz"
    zcat /proc/config.gz | grep -E '^CONFIG_' | head -50
    echo "... (truncated)"
elif [ -f "/boot/config-$(uname -r)" ]; then
    echo "Current kernel config at /boot/config-$(uname -r)"
    grep -E '^CONFIG_' "/boot/config-$(uname -r)" | head -50
    echo "... (truncated)"
else
    echo "No current kernel config found"
fi
echo ""

echo "=== Storage Controllers ==="
lspci -nn | grep -iE '(sata|ahci|scsi|nvme|ide)' 2>/dev/null || echo "None found"
echo ""

echo "=== Graphics ==="
lspci -nn | grep -iE '(vga|3d|display)' 2>/dev/null || echo "None found"
echo ""

echo "=== Network Controllers ==="
lspci -nn | grep -iE '(network|ethernet|wireless|wifi)' 2>/dev/null || echo "None found"
echo ""

echo "=== Sensors ==="
sensors 2>/dev/null || echo "sensors not available"
echo ""

echo "=== Webcam ==="
ls /dev/video* 2>/dev/null && echo "Video devices found" || echo "No video devices"
echo ""

echo "=== SD Card Reader ==="
lspci -nn | grep -i sd 2>/dev/null || echo "No SD controller found in lspci"
echo ""

echo "=== Fingerprint Reader ==="
lsusb 2>/dev/null | grep -i fingerprint || echo "No fingerprint reader found"
echo ""

echo "=== TPM ==="
ls /dev/tpm* 2>/dev/null && echo "TPM devices found" || echo "No TPM devices"
echo ""

echo "=== EFI Variables ==="
if [ -d /sys/firmware/efi ]; then
    echo "EFI boot detected"
    efibootmgr 2>/dev/null || echo "efibootmgr not available"
else
    echo "Legacy BIOS boot"
fi

} > "$OUTPUT" 2>&1

echo "Hardware information saved to $OUTPUT"
echo "Please review the file and use it to configure your kernel."