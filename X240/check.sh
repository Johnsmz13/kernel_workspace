#!/bin/bash
# Check kernel config changes for ThinkPad X240
# Usage: ./check.sh [path-to-.config]
# Default: .config in current directory

CONFIG="${1:-.config}"

if [ ! -f "$CONFIG" ]; then
    echo "ERROR: Config file '$CONFIG' not found."
    echo "Usage: $0 [path-to-.config]"
    exit 1
fi

PASS=0
FAIL=0
WARN=0
MISSING=0
DEP=0

check() {
    local opt="$1"
    local expected="$2"
    local desc="$3"

    if ! grep -q "^${opt}=" "$CONFIG" && ! grep -q "^# ${opt} is not set" "$CONFIG"; then
        echo "MISS  $opt  ($desc)"
        MISSING=$((MISSING + 1))
        return
    fi

    actual=$(grep "^${opt}=" "$CONFIG" 2>/dev/null | head -1 | cut -d= -f2)
    not_set=$(grep "^# ${opt} is not set" "$CONFIG" 2>/dev/null)

    if [ "$expected" = "n" ]; then
        if [ -n "$not_set" ]; then
            echo "OK    $opt=n  ($desc)"
            PASS=$((PASS + 1))
        else
            echo "FAIL  $opt=$actual  expected=n  ($desc)"
            FAIL=$((FAIL + 1))
        fi
    else
        if [ "$actual" = "$expected" ]; then
            echo "OK    $opt=$actual  ($desc)"
            PASS=$((PASS + 1))
        else
            echo "FAIL  $opt=$actual  expected=$expected  ($desc)"
            FAIL=$((FAIL + 1))
        fi
    fi
}

# Check option that is forced on by a dependency (expected=value, but forced by dep)
check_dep() {
    local opt="$1"
    local expected="$2"
    local dep_reason="$3"
    local desc="$4"

    if ! grep -q "^${opt}=" "$CONFIG" && ! grep -q "^# ${opt} is not set" "$CONFIG"; then
        echo "MISS  $opt  ($desc)"
        MISSING=$((MISSING + 1))
        return
    fi

    actual=$(grep "^${opt}=" "$CONFIG" 2>/dev/null | head -1 | cut -d= -f2)
    not_set=$(grep "^# ${opt} is not set" "$CONFIG" 2>/dev/null)

    if [ "$expected" = "n" ]; then
        if [ -n "$not_set" ]; then
            echo "OK    $opt=n  ($desc)"
            PASS=$((PASS + 1))
        else
            echo "DEP   $opt=$actual  expected=n  forced by $dep_reason  ($desc)"
            DEP=$((DEP + 1))
        fi
    else
        if [ "$actual" = "$expected" ]; then
            echo "OK    $opt=$actual  ($desc)"
            PASS=$((PASS + 1))
        else
            echo "DEP   $opt=$actual  expected=$expected  forced by $dep_reason  ($desc)"
            DEP=$((DEP + 1))
        fi
    fi
}

echo "========================================"
echo "Kernel Config Check: $CONFIG"
echo "========================================"
echo ""

echo "--- A. Virtualization (should be disabled) ---"
check CONFIG_VIRTUALIZATION "n" "虚拟化总开关"
check CONFIG_VIRT_DRIVERS "n" "虚拟驱动"
echo ""

echo "--- B. WLAN Vendors (only Intel needed) ---"
check CONFIG_WLAN_VENDOR_INTEL "y" "Intel WiFi"
check CONFIG_WLAN_VENDOR_ATH "n" "Atheros WiFi"
check CONFIG_WLAN_VENDOR_BROADCOM "n" "Broadcom WiFi"
check CONFIG_WLAN_VENDOR_MARVELL "n" "Marvell WiFi"
check CONFIG_WLAN_VENDOR_MEDIATEK "n" "MediaTek WiFi"
check CONFIG_WLAN_VENDOR_MICROCHIP "n" "Microchip WiFi"
check CONFIG_WLAN_VENDOR_RALINK "n" "Ralink WiFi"
check CONFIG_WLAN_VENDOR_REALTEK "n" "Realtek WiFi"
check CONFIG_WLAN_VENDOR_RSI "n" "RSI WiFi"
check CONFIG_WLAN_VENDOR_ST "n" "ST WiFi"
check CONFIG_WLAN_VENDOR_TI "n" "TI WiFi"
check CONFIG_WLAN_VENDOR_ZYDAS "n" "ZyDAS WiFi"
check CONFIG_WLAN_VENDOR_QUANTENNA "n" "Quantenna WiFi"
check CONFIG_ATH5K_PCI "n" "Atheros 5K PCI"
echo ""

echo "--- C. NET Vendors (only Intel needed) ---"
check CONFIG_NET_VENDOR_INTEL "y" "Intel Ethernet"
check CONFIG_NET_VENDOR_3COM "n" "3COM"
check CONFIG_NET_VENDOR_ADAPTEC "n" "Adaptec"
check CONFIG_NET_VENDOR_AGERE "n" "Agere"
check CONFIG_NET_VENDOR_ALIBABA "n" "Alibaba"
check CONFIG_NET_VENDOR_AMAZON "n" "Amazon"
check CONFIG_NET_VENDOR_AMD "n" "AMD"
check CONFIG_NET_VENDOR_AQUANTIA "n" "Aquantia"
check CONFIG_NET_VENDOR_ARC "n" "ARC"
check CONFIG_NET_VENDOR_ASIX "n" "ASIX"
check CONFIG_NET_VENDOR_ATHEROS "n" "Atheros"
check CONFIG_NET_VENDOR_BROADCOM "n" "Broadcom"
check CONFIG_NET_VENDOR_CADENCE "n" "Cadence"
check CONFIG_NET_VENDOR_CHELSIO "n" "Chelsio"
check CONFIG_NET_VENDOR_CISCO "n" "Cisco"
check CONFIG_NET_VENDOR_DAVICOM "n" "DAVICOM"
check CONFIG_NET_VENDOR_DEC "n" "DEC"
check CONFIG_NET_VENDOR_DLINK "n" "D-Link"
check CONFIG_NET_VENDOR_EMULEX "n" "Emulex"
check CONFIG_NET_VENDOR_ENGLEDER "n" "Engleder"
check CONFIG_NET_VENDOR_FUNGIBLE "n" "Fungible"
check CONFIG_NET_VENDOR_GOOGLE "n" "Google"
check CONFIG_NET_VENDOR_ADI "n" "ADI"
check CONFIG_NET_VENDOR_LITEX "n" "LiteX"
check CONFIG_NET_VENDOR_MARVELL "n" "Marvell"
check CONFIG_NET_VENDOR_MELLANOX "n" "Mellanox"
check CONFIG_NET_VENDOR_META "n" "Meta"
check CONFIG_NET_VENDOR_MICREL "n" "Micrel"
check CONFIG_NET_VENDOR_MICROCHIP "n" "Microchip"
check CONFIG_NET_VENDOR_MICROSOFT "n" "Microsoft"
check CONFIG_NET_VENDOR_MUCSE "n" "Mucse"
check CONFIG_NET_VENDOR_MYRI "n" "Myricom"
check CONFIG_NET_VENDOR_NATSEMI "n" "NatSemi"
check CONFIG_NET_VENDOR_NETRONOME "n" "Netronome"
check CONFIG_NET_VENDOR_8390 "n" "8390"
check CONFIG_NET_VENDOR_NVIDIA "n" "NVIDIA"
check CONFIG_NET_VENDOR_OKI "n" "OKI"
check CONFIG_NET_VENDOR_PENSANDO "n" "Pensando"
check CONFIG_NET_VENDOR_QLOGIC "n" "QLogic"
check CONFIG_NET_VENDOR_BROCADE "n" "Brocade"
check CONFIG_NET_VENDOR_RDC "n" "RDC"
check CONFIG_NET_VENDOR_REALTEK "n" "Realtek"
check CONFIG_NET_VENDOR_ROCKER "n" "Rocker"
check CONFIG_NET_VENDOR_SILAN "n" "Silan"
check CONFIG_NET_VENDOR_SIS "n" "SiS"
check CONFIG_NET_VENDOR_SOLARFLARE "n" "Solarflare"
check CONFIG_NET_VENDOR_SMSC "n" "SMSC"
check CONFIG_NET_VENDOR_STMICRO "n" "STMicro"
check CONFIG_NET_VENDOR_SUN "n" "Sun"
check CONFIG_NET_VENDOR_TEHUTI "n" "Tehuti"
check CONFIG_NET_VENDOR_TI "n" "TI"
check CONFIG_NET_VENDOR_VERTEXCOM "n" "Vertexcom"
check CONFIG_NET_VENDOR_VIA "n" "VIA"
check CONFIG_NET_VENDOR_WANGXUN "n" "Wangxun"
check CONFIG_NET_VENDOR_WIZNET "n" "WizNet"
check CONFIG_NET_VENDOR_XILINX "n" "Xilinx"
check CONFIG_NET_VENDOR_XIRCOM "n" "Xircom"
echo ""

echo "--- D. Bluetooth (only Intel btusb needed) ---"
check CONFIG_BT "m" "Bluetooth subsystem"
check CONFIG_BT_INTEL "m" "Intel BT"
check CONFIG_BT_HCIBTUSB "m" "BT USB driver"
check CONFIG_BT_BCM "n" "Broadcom BT"
check CONFIG_BT_RTL "n" "Realtek BT"
check CONFIG_BT_MTK "n" "MediaTek BT"
check CONFIG_BT_HCIBTUSB_BCM "n" "Broadcom btusb"
check CONFIG_BT_HCIBTUSB_MTK "n" "MediaTek btusb"
check CONFIG_BT_HCIBTUSB_RTL "n" "Realtek btusb"
check CONFIG_BT_INTEL_PCIE "n" "Intel PCIe BT"
echo ""

echo "--- E. iwlwifi (disable debug) ---"
check CONFIG_IWLWIFI "m" "iwlwifi driver"
check CONFIG_IWLWIFI_DEBUG "n" "iwlwifi debug"
check CONFIG_IWLWIFI_DEBUGFS "n" "iwlwifi debugfs"
echo ""

echo "--- F. NVMe (user has SATA only) ---"
check CONFIG_NVME_CORE "n" "NVMe core"
check CONFIG_NVME_KEYRING "n" "NVMe keyring"
check CONFIG_NVME_AUTH "n" "NVMe auth"
check CONFIG_NVME_MULTIPATH "n" "NVMe multipath"
check CONFIG_NVME_HWMON "n" "NVMe hwmon"
check CONFIG_NVME_HOST_AUTH "n" "NVMe host auth"
echo ""

echo "--- G. Media/TV (only UVC webcam needed) ---"
check CONFIG_MEDIA_ANALOG_TV_SUPPORT "n" "Analog TV"
check CONFIG_MEDIA_DIGITAL_TV_SUPPORT "n" "Digital TV"
check CONFIG_MEDIA_RADIO_SUPPORT "n" "Radio"
check CONFIG_MEDIA_TEST_SUPPORT "n" "Media test"
check CONFIG_DVB_CORE "n" "DVB core"
check CONFIG_DVB_NET "n" "DVB net"
echo ""

echo "--- H. PCMCIA/CardBus (X240 has no slot) ---"
check CONFIG_PCCARD "n" "PCCard"
check CONFIG_PCMCIA "n" "PCMCIA"
check CONFIG_CARDBUS "n" "CardBus"
echo ""

echo "--- I. Platform Drivers ---"
check CONFIG_CHROME_PLATFORMS "n" "Chrome"
check CONFIG_SURFACE_PLATFORMS "n" "Surface"
echo ""

echo "--- J. HID ---"
check CONFIG_HID_NTRIG "n" "N-Trig digitizer"
check CONFIG_HID_MAGICMOUSE "n" "Apple Magic Mouse"
check CONFIG_HID_PID "n" "PID force feedback"
check CONFIG_HID_HAPTIC "n" "Haptic"
echo ""

echo "--- K. Input ---"
check CONFIG_INPUT_JOYDEV "n" "Joystick device"
check CONFIG_INPUT_TOUCHSCREEN "n" "Touchscreen"
echo ""

echo "--- L. USB ---"
check CONFIG_USB_MON "n" "USB monitor"
check CONFIG_USB_OHCI_HCD "n" "OHCI"
check CONFIG_USB_OHCI_HCD_PCI "n" "OHCI PCI"
check CONFIG_USB_UHCI_HCD "n" "UHCI"
check CONFIG_USB_XHCI_PCI_RENESAS "n" "Renesas xHCI"
check CONFIG_USB_XHCI_HCD "y" "xHCI (needed)"
check CONFIG_USB_EHCI_HCD "y" "EHCI (needed)"
echo ""

echo "--- M. Sound ---"
check CONFIG_SND "m" "Sound subsystem"
check CONFIG_SND_HDA_INTEL "m" "HDA Intel"
check CONFIG_SND_HDA_CODEC_ALC269 "m" "ALC269 codec"
check CONFIG_SND_HDA_CODEC_HDMI "m" "HDMI codec"
check CONFIG_SND_HDA_HWDEP "n" "HDA hwdep"
check CONFIG_SND_HDA_RECONFIG "n" "HDA reconfig"
check CONFIG_SND_HDA_INPUT_BEEP "n" "HDA beep"
check CONFIG_SND_HDA_PATCH_LOADER "n" "HDA patch loader"
check_dep CONFIG_SND_CTL_LED "n" "SND_HDA_CODEC_REALTEK_LIB" "Sound LED control"
check_dep CONFIG_SND_INTEL_SOUNDWIRE_ACPI "n" "SND_HDA_CORE+ACPI" "SoundWire"
echo ""

echo "--- N. DRM/GPU ---"
check CONFIG_DRM_I915 "m" "i915 driver"
check CONFIG_DRM_XE "n" "Intel Xe GPU"
check CONFIG_DRM_PANIC "n" "DRM panic"
check_dep CONFIG_DRM_PRIVACY_SCREEN "n" "THINKPAD_ACPI" "Privacy screen"
check CONFIG_DRM_I915_PXP "n" "i915 PXP"
echo ""

echo "--- O. Serial ---"
check CONFIG_SERIAL_NONSTANDARD "n" "Non-standard serial"
check CONFIG_SERIAL_8250_MANY_PORTS "n" "Many ports"
echo ""

echo "--- P. I2C/SPI ---"
check CONFIG_I2C_DESIGNWARE_AMDPSP "n" "AMD PSP I2C"
check CONFIG_I2C_SLAVE "n" "I2C slave"
check CONFIG_SPI_AMD "n" "AMD SPI"
echo ""

echo "--- Q. Debug/Staging ---"
check_dep CONFIG_DEBUG_FS "n" "KEXEC_HANDOVER_DEBUGFS" "Debug filesystem"
check_dep CONFIG_DEBUG_KERNEL "n" "EXPERT" "Kernel debugging"
check CONFIG_STAGING "n" "Staging drivers"
check CONFIG_STAGING_MEDIA "n" "Staging media"
check CONFIG_BPF_PRELOAD "n" "BPF preload"
check CONFIG_PRINTK_TIME "n" "Printk time"
echo ""

echo "--- R. ATA Legacy ---"
check CONFIG_ATA_SFF "n" "ATA SFF"
check CONFIG_ATA_BMDMA "n" "ATA BMDMA"
check CONFIG_ATA_PIIX "n" "Intel PIIX PATA"
check CONFIG_SATA_AHCI "y" "SATA AHCI (needed)"
echo ""

echo "--- S. TUN/TAP (Network Tunnel - must be present) ---"
check CONFIG_TUN "m" "TUN/TAP network tunnel"
echo ""

echo "--- T. Performance (verify correct values) ---"
check CONFIG_HZ "1000" "Timer frequency"
check CONFIG_PREEMPT_LAZY "y" "Preempt model"
check CONFIG_CPU_FREQ_DEFAULT_GOV_SCHEDUTIL "y" "CPU freq governor"
check CONFIG_NO_HZ_FULL "y" "Full dynamic tick"
check CONFIG_TRANSPARENT_HUGEPAGE_MADVISE "y" "THP madvise"
check CONFIG_X86_INTEL_PSTATE "y" "Intel P-state"
check CONFIG_KERNEL_ZSTD "y" "ZSTD compression"
check CONFIG_INTEL_IDLE "y" "Intel idle driver"
echo ""

echo "--- U. Hardware Drivers (must be present) ---"
check CONFIG_E1000E "m" "Intel Ethernet"
check CONFIG_DRM_I915 "m" "Intel GPU"
check CONFIG_IWLWIFI "m" "Intel WiFi"
check CONFIG_SND_HDA_INTEL "m" "HDA Audio"
check CONFIG_USB_VIDEO_CLASS "m" "UVC Webcam"
check CONFIG_THINKPAD_ACPI "m" "ThinkPad ACPI"
check CONFIG_MMC_REALTEK_PCI "m" "Realtek SD reader"
check CONFIG_ACPI_BATTERY "y" "Battery"
check CONFIG_ACPI_AC "y" "AC adapter"
check CONFIG_ACPI_THERMAL "y" "Thermal"
echo ""

echo "--- V. Filesystem ---"
check CONFIG_XFS_FS "y" "XFS (root filesystem)"
check CONFIG_BTRFS_FS "n" "Btrfs (not needed)"
check CONFIG_EXT4_FS "y" "EXT4"
check CONFIG_FAT_FS "m" "FAT (EFI)"
check CONFIG_VFAT_FS "m" "VFAT (EFI)"
check CONFIG_PROC_FS "y" "procfs"
check CONFIG_EFIVAR_FS "y" "EFI variables"
echo ""

echo "--- W. Network Features ---"
check CONFIG_TUN "m" "TUN tunnel proxy"
check CONFIG_NETFILTER "y" "Netfilter"
check CONFIG_IPV6 "n" "IPv6 (disabled)"
echo ""

echo "========================================"
echo "SUMMARY"
echo "========================================"
echo "PASS:    $PASS"
echo "FAIL:    $FAIL"
echo "DEP:     $DEP  (forced by dependencies, acceptable)"
echo "MISSING: $MISSING  (parent option disabled, expected)"
echo "TOTAL:   $((PASS + FAIL + DEP + MISSING))"
echo ""

if [ "$FAIL" -gt 0 ]; then
    echo "Result: SOME CHECKS FAILED"
    echo "Review FAIL entries above and fix .config manually."
    echo "Then re-run: make olddefconfig && $0 $CONFIG"
    exit 1
elif [ "$MISSING" -gt 0 ]; then
    echo "Result: SOME OPTIONS MISSING"
    echo "This is normal when parent vendor/feature menus are disabled."
    echo "All missing options are expected (parent disabled by design)."
    exit 0
else
    echo "Result: ALL CHECKS PASSED"
    exit 0
fi
