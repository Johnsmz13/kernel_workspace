#!/usr/bin/env python3
"""Validate a Linux kernel .config against a policy rule set.

Self-contained: Python standard library only, no hardcoded paths. The config
file and profile come from the command line, so the script can be pointed at
any kernel .config on any machine.

Usage:
    ./kernel_config_check.py --config .config --profile desktop-wayland
    ./kernel_config_check.py --config config.baseline --profile desktop-wayland --emit-commands
    ./kernel_config_check.py --config .config --rules extra-rules.json --json

Exit codes:
    0  every applicable rule passed
    1  one or more rules failed
    2  the configuration file could not be read

Rule fields (built-in list and --rules JSON use the same schema):
    symbol    CONFIG_* name (CONFIG_ prefix optional). May be a fnmatch
              pattern such as CONFIG_NET_VENDOR_* which expands to every
              matching symbol present in the config.
    expect    "y" | "m" | "n" | "value=N" (also >=, <=, >, <) or a list of
              those. A rule passes if any token matches; for --emit-commands
              the first token is used as the preferred target.
    reason    human-readable justification
    group     report category (virtualization, graphics, network, ...)
    profiles  profiles the rule applies to (default: desktop-wayland; use
              "all" to apply everywhere)
    exclude   symbols/patterns removed from a wildcard expansion

Adding rules: append R(...) entries to the section comments in DEFAULT_RULES
below, or pass --rules with a JSON list of objects using the same fields.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import operator
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

DEFAULT_PROFILE = "desktop-wayland"
CONFIG_PREFIX = "CONFIG_"

_UNSET_RE = re.compile(r"^# (?P<name>CONFIG_[A-Za-z0-9_]+) is not set\s*$")
_SET_RE = re.compile(r"^(?P<name>CONFIG_[A-Za-z0-9_]+)=(?P<value>.*)$")
_VALUE_RE = re.compile(r"^value(?P<op>>=|<=|>|<|=)(?P<want>.+)$")
_OP_FUNCS = {"=": operator.eq, ">=": operator.ge, "<=": operator.le,
             ">": operator.gt, "<": operator.lt}


# --------------------------------------------------------------------------
# Rule model
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    """One policy rule targeting a symbol or a symbol pattern."""

    symbol: str
    expect: tuple[str, ...]
    group: str
    reason: str
    profiles: tuple[str, ...] = (DEFAULT_PROFILE,)
    exclude: tuple[str, ...] = ()

    @property
    def is_pattern(self) -> bool:
        return any(ch in self.symbol for ch in "*?[")


@dataclass
class Result:
    """Outcome of checking one rule (or one pattern expansion) against the config."""

    rule: Rule
    symbol: str
    actual: Optional[str]  # None = symbol not present in the config file
    passed: bool
    note: str = ""


def normalize(symbol: str) -> str:
    """Ensure a symbol or pattern carries the CONFIG_ prefix."""
    return symbol if symbol.startswith(CONFIG_PREFIX) else CONFIG_PREFIX + symbol


def R(symbol: str, expect, group: str, reason: str,
      exclude: Iterable[str] = (), profiles: Iterable[str] = (DEFAULT_PROFILE,)) -> Rule:
    """Compact constructor used by the rule tables below."""
    if isinstance(expect, str):
        expect = (expect,)
    return Rule(
        symbol=normalize(symbol),
        expect=tuple(expect),
        group=group,
        reason=reason,
        profiles=tuple(profiles),
        exclude=tuple(normalize(e) for e in exclude),
    )


# --------------------------------------------------------------------------
# Built-in policy rules (profile: desktop-wayland)
# --------------------------------------------------------------------------

DEFAULT_RULES: list[Rule] = [
    # -- virtualization ----------------------------------------------------
    R("VIRTUALIZATION", "n", "virtualization", "KVM host menu gate; no hypervisor use on this machine (lsmod: no kvm modules)"),
    R("KVM", "n", "virtualization", "KVM host core; explicitly disabled"),
    R("KVM_INTEL", "n", "virtualization", "Intel KVM host; explicitly disabled"),
    R("KVM_AMD", "n", "virtualization", "AMD KVM host; not applicable"),
    R("KVM_X86", "n", "virtualization", "hidden KVM x86 support; follows KVM=n"),
    R("KVM_GUEST", "n", "virtualization", "paravirt support for running *as* a KVM guest; default y, must be off"),
    R("HYPERVISOR_GUEST", "y", "virtualization", "kept: gate for PARAVIRT which x86_64 recommends on native hardware"),
    R("PARAVIRT", "y", "virtualization", "kept: pv-ops infrastructure recommended for x86_64 native kernels"),
    R("PARAVIRT_TIME_ACCOUNTING", "n", "virtualization", "guest steal-time accounting unused"),
    R("X86_VSMP", "n", "virtualization", "ScaleMP guest support; would force HYPERVISOR_GUEST/PARAVIRT"),
    R("XEN", "n", "virtualization", "Xen guest/dom0; collapses all drivers/xen"),
    R("XEN_PV", "n", "virtualization", "Xen PV guest"),
    R("XEN_PVH", "n", "virtualization", "Xen PVH guest"),
    R("XEN_DOM0", "n", "virtualization", "Xen privileged domain"),
    R("XEN_GNTDEV", "n", "virtualization", "Xen grant table device"),
    R("XEN_BACKEND", "n", "virtualization", "Xen backend drivers"),
    R("XEN_BLKDEV_FRONTEND", "n", "virtualization", "Xen block frontend"),
    R("XEN_NETDEV_FRONTEND", "n", "virtualization", "Xen net frontend"),
    R("ACRN_GUEST", "n", "virtualization", "ACRN guest support"),
    R("BHYVE_GUEST", "n", "virtualization", "bhyve guest support"),
    R("JAILHOUSE_GUEST", "n", "virtualization", "Jailhouse guest support"),
    R("INTEL_TDX_GUEST", "n", "virtualization", "Intel TDX guest support"),
    R("HYPERV", "n", "virtualization", "Microsoft Hyper-V guest support"),
    R("HYPERV_VMBUS", "n", "virtualization", "Hyper-V VMBus"),
    R("HYPERV_STORAGE", "n", "virtualization", "Hyper-V storage driver"),
    R("HYPERV_NET", "n", "virtualization", "Hyper-V network driver"),
    R("HYPERV_UTILS", "n", "virtualization", "Hyper-V utilities"),
    R("HYPERV_BALLOON", "n", "virtualization", "Hyper-V balloon driver"),
    R("PCI_HYPERV", "n", "virtualization", "Hyper-V PCI passthrough"),
    R("HYPERV_KEYBOARD", "n", "virtualization", "Hyper-V keyboard"),
    R("HID_HYPERV_MOUSE", "n", "virtualization", "Hyper-V mouse"),
    R("VMWARE_BALLOON", "n", "virtualization", "VMware balloon driver"),
    R("VMWARE_PVSCSI", "n", "virtualization", "VMware PVSCSI"),
    R("VMXNET3", "n", "virtualization", "VMware vmxnet3 NIC"),
    R("VMWARE_VMCI", "n", "virtualization", "VMware VMCI"),
    R("VMWARE_VMCI_VSOCKETS", "n", "virtualization", "VMware VMCI vsockets"),
    R("VBOXGUEST", "n", "virtualization", "VirtualBox guest driver"),
    R("VBOXSF_FS", "n", "virtualization", "VirtualBox shared folders"),
    R("VIRTIO", "n", "virtualization", "hidden VirtIO core; resolves to n once all virtio drivers are off"),
    R("VIRTIO_MENU", "n", "virtualization", "VirtIO drivers menu"),
    R("VIRTIO_PCI", "n", "virtualization", "VirtIO PCI transport"),
    R("VIRTIO_PCI_LEGACY", "n", "virtualization", "VirtIO legacy PCI"),
    R("VIRTIO_MMIO", "n", "virtualization", "VirtIO MMIO transport"),
    R("VIRTIO_MMIO_CMDLINE_DEVICES", "n", "virtualization", "VirtIO MMIO cmdline devices"),
    R("VIRTIO_NET", "n", "virtualization", "VirtIO network driver"),
    R("VIRTIO_BLK", "n", "virtualization", "VirtIO block driver"),
    R("VIRTIO_CONSOLE", "n", "virtualization", "VirtIO console"),
    R("VIRTIO_INPUT", "n", "virtualization", "VirtIO input"),
    R("VIRTIO_BALLOON", "n", "virtualization", "VirtIO balloon"),
    R("VIRTIO_PMEM", "n", "virtualization", "VirtIO pmem"),
    R("VIRTIO_MEM", "n", "virtualization", "VirtIO memory"),
    R("VIRTIO_RTC", "n", "virtualization", "VirtIO RTC"),
    R("VIRTIO_FS", "n", "virtualization", "VirtIO filesystem"),
    R("VIRTIO_VSOCKETS", "n", "virtualization", "VirtIO vsockets"),
    R("VHOST_MENU", "n", "virtualization", "vhost menu"),
    R("VHOST_NET", "n", "virtualization", "vhost-net backend"),
    R("VHOST_VSOCK", "n", "virtualization", "vhost-vsock backend"),
    R("VHOST_VDPA", "n", "virtualization", "vhost-vdpa backend"),
    R("VDPA", "n", "virtualization", "vDPA framework"),
    R("VSOCKETS", "n", "virtualization", "vsock address family"),
    R("VSOCKETS_DIAG", "n", "virtualization", "vsock diagnostics"),
    R("VSOCKETS_LOOPBACK", "n", "virtualization", "vsock loopback"),
    R("HYPERV_VSOCKETS", "n", "virtualization", "Hyper-V vsock transport"),
    R("VFIO", "n", "virtualization", "VFIO core (VM device passthrough)"),
    R("VFIO_PCI", "n", "virtualization", "VFIO PCI passthrough"),
    R("VFIO_PLATFORM", "n", "virtualization", "VFIO platform passthrough"),
    R("VFIO_MDEV", "n", "virtualization", "VFIO mediated devices"),
    R("DRM_I915_GVT_KVMGT", "n", "virtualization", "Intel GVT-g host GPU sharing"),
    R("REMOTEPROC", "n", "virtualization", "no remote-processor (DSP) hardware; REMOTEPROC selects VIRTIO (drivers/remoteproc/Kconfig:9) - root cause of VIRTIO=y"),
    R("RPMSG", "n", "virtualization", "rpmsg messaging stack unused without remote processors"),

    # -- graphics / console --------------------------------------------------
    R("DRM", ("m", "y"), "graphics", "keep: DRM core; required by i915"),
    R("DRM_I915", ("m", "y"), "graphics", "keep: bound driver for Iris Xe (lspci: kernel driver in use: i915)"),
    R("DRM_KMS_HELPER", ("m", "y"), "graphics", "keep: hidden helper selected by DRM drivers"),
    R("DRM_SIMPLEDRM", ("y", "m"), "graphics", "keep: early-boot framebuffer on UEFI systems"),
    R("DRM_FBDEV_EMULATION", ("y",), "graphics", "keep: fbdev emulation so fbcon works on the DRM output"),
    R("FRAMEBUFFER_CONSOLE", ("y",), "graphics", "keep: TTY console on framebuffer (useful without X11)"),
    R("FB_CORE", ("m", "y"), "graphics", "keep: hidden core selected by DRM fbdev emulation"),
    R("INTEL_GTT", ("m", "y"), "graphics", "keep: selected by DRM_I915 on x86 - cannot be n while i915 is on"),
    R("DRM_I915_PXP", ("y", "m"), "graphics", "keep: Intel PXP protected media path (pairs with MEI PXP)"),
    R("BACKLIGHT_CLASS_DEVICE", ("m", "y"), "graphics", "keep: selected by i915/ACPI for panel backlight"),
    R("ACPI_VIDEO", ("m", "y"), "graphics", "keep: selected by i915 on ACPI systems (display hotkeys)"),
    R("AGP", "n", "graphics", "no AGP-era GPU; i915 does not require AGP in this tree"),
    R("AGP_INTEL", "n", "graphics", "no Intel AGP graphics"),
    R("DRM_XE", "n", "graphics", "xe loaded but unbound; device is driven by i915"),
    R("DRM_AMDGPU", "n", "graphics", "no AMD GPU (lspci)"),
    R("DRM_RADEON", "n", "graphics", "no pre-GCN AMD GPU"),
    R("DRM_NOUVEAU", "n", "graphics", "no NVIDIA GPU"),
    R("DRM_VKMS", "n", "graphics", "virtual KMS test driver"),
    R("DRM_VGEM", "n", "graphics", "virtual GEM test driver"),
    R("DRM_GUD", "n", "graphics", "USB display driver, no such device"),
    R("DRM_VIRTIO_GPU", "n", "graphics", "virtio GPU (VM only)"),
    R("DRM_VMWGFX", "n", "graphics", "VMware SVGA (VM only)"),
    R("DRM_VBOXVIDEO", "n", "graphics", "VirtualBox video (VM only)"),
    R("DRM_QXL", "n", "graphics", "QXL (VM only)"),
    R("DRM_BOCHS", "n", "graphics", "Bochs VGA (VM only)"),
    R("DRM_CIRRUS_QEMU", "n", "graphics", "QEMU Cirrus (VM only)"),
    R("DRM_XEN_FRONTEND", "n", "graphics", "Xen DRM frontend (VM only)"),
    R("DRM_ACCEL", "n", "graphics", "accelerator subsystem; no such hardware"),
    R("DRM_ACCEL_IVPU", "n", "graphics", "Intel VPU accelerator not present (lspci)"),
    R("DRM_DEBUG_MM", "n", "graphics", "debug support only"),
    R("DRM_I915_DEBUG", "n", "graphics", "i915 debug options"),
    R("DRM_I915_SELFTEST", "n", "graphics", "i915 selftests"),
    R("DRM_DISPLAY_DP_AUX_CHARDEV", "n", "graphics", "DP AUX debug chardev"),
    R("FB", "n", "graphics", "legacy fbdev drivers menu; simpledrm handles UEFI boot"),
    R("FB_VESA", "n", "graphics", "legacy VESA framebuffer"),
    R("FB_EFI", "n", "graphics", "efifb not needed with simpledrm"),
    R("FB_SIMPLE", "n", "graphics", "legacy simple framebuffer"),

    # -- debug / tracing / kernel hacking ------------------------------------
    R("DEBUG_KERNEL", ("y",), "debug", "forced by EXPERT=y in 7.2.x (init/Kconfig:1709 'select DEBUG_KERNEL'); it only unhides options - the debug features themselves stay off"),
    R("DEBUG_INFO", "n", "debug", "no debug symbols; smaller build"),
    R("DEBUG_INFO_NONE", ("y",), "debug", "keep: debug information disabled (choice target)"),
    R("DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT", "n", "debug", "DWARF debug info not needed; the choice must resolve to DEBUG_INFO_NONE"),
    R("DEBUG_INFO_DWARF4", "n", "debug", "DWARF debug info not needed"),
    R("DEBUG_INFO_DWARF5", "n", "debug", "DWARF debug info not needed (this choice member is set in the baseline)"),
    R("DEBUG_INFO_BTF", "n", "debug", "no BTF needed (also drops the pahole build dependency)"),
    R("GDB_SCRIPTS", "n", "debug", "gdb helper scripts"),
    R("FTRACE", "n", "debug", "ftrace infrastructure unused"),
    R("KPROBES", "n", "debug", "kprobes unused"),
    R("UPROBES", "n", "debug", "uprobes unused"),
    R("DEBUG_FS", "n", "debug", "debugfs not required"),
    R("SLUB_DEBUG", "n", "debug", "SLUB debugging off"),
    R("ZSMALLOC_STAT", "n", "debug", "zsmalloc statistics debug feature; forces DEBUG_FS=y (mm/Kconfig:135)"),
    R("DYNAMIC_DEBUG", "n", "debug", "dynamic debug depends on DEBUG_FS; debug feature unused"),
    R("LIVEUPDATE", "n", "debug", "live-update orchestrator; its own Kconfig text says it primarily targets VM hosts"),
    R("KEXEC_HANDOVER", "n", "platform", "kexec handover for live update; unused on this desktop (its debugfs interface was the root cause of DEBUG_FS=y)"),
    R("KEXEC_HANDOVER_DEBUGFS", "n", "debug", "debugfs interface for kexec handover; selects DEBUG_FS (direct root cause of DEBUG_FS=y)"),
    R("SCHED_DEBUG", "n", "debug", "scheduler debugging info; defaults to y once DEBUG_KERNEL is visible"),
    R("PROVE_LOCKING", "n", "debug", "lock correctness proof"),
    R("LATENCYTOP", "n", "debug", "latency tracer"),
    R("GCOV_KERNEL", "n", "debug", "coverage instrumentation"),
    R("KASAN", "n", "debug", "sanitizer"),
    R("KCOV", "n", "debug", "coverage collection"),
    R("UBSAN", "n", "debug", "undefined-behaviour sanitizer"),
    R("DEBUG_LIST", "n", "debug", "list debugging"),
    R("KALLSYMS", ("y",), "debug", "keep: symbols needed by tooling"),
    R("MAGIC_SYSRQ", ("y",), "debug", "keep: SysRq for hang recovery (REISUB)"),
    R("IKCONFIG", ("y",), "debug", "keep: embedded kernel config"),
    R("IKCONFIG_PROC", ("y",), "debug", "keep: /proc/config.gz in use as the baseline seed"),
    R("EXPERT", ("y",), "debug", "keep: exposes per-codec and other hidden options needed by this policy"),
    R("BPF_SYSCALL", ("y",), "debug", "keep: used by systemd and common tooling"),
    R("BPF_JIT", "n", "debug", "BPF JIT not needed for a desktop"),

    # -- network core / tunnels ---------------------------------------------
    R("NET", ("y",), "network", "keep: networking core"),
    R("INET", ("y",), "network", "keep: IPv4"),
    R("UNIX", ("y",), "network", "keep: AF_UNIX (systemd, sshd)"),
    R("IPV6", ("y",), "network", "keep: IPv6"),
    R("PACKET", ("m", "y"), "network", "keep: AF_PACKET (DHCP clients, tcpdump)"),
    R("TUN", ("m", "y"), "network", "keep: TUN/TAP for OpenVPN/WireGuard userspace - explicit user requirement"),
    R("WIREGUARD", ("m", "y"), "network", "keep: WireGuard per user decision"),
    R("BRIDGE", ("m", "y"), "network", "keep: generic virtual networking per user decision"),
    R("VLAN_8021Q", ("m", "y"), "network", "keep: VLAN support, generic networking"),
    R("DUMMY", "n", "network", "dummy netdev test driver"),
    R("IFB", "n", "network", "intermediate functional block device unused"),
    R("MACVLAN", "n", "network", "no containers/VMs"),
    R("MACVTAP", "n", "network", "no containers/VMs"),
    R("VXLAN", "n", "network", "overlay networking unused"),
    R("GENEVE", "n", "network", "overlay networking unused"),
    R("BAREUDP", "n", "network", "UDP tunnel encapsulation unused"),
    R("GTP", "n", "network", "cellular user-plane tunneling unused"),
    R("L2TP", "n", "network", "L2TP VPN unused"),
    R("PPP", "n", "network", "PPP/modem unused"),
    R("SLIP", "n", "network", "legacy serial IP"),
    R("NET_IPIP", "n", "network", "IP-in-IP tunnel unused"),
    R("NET_IPGRE", "n", "network", "GRE tunnel unused"),
    R("NET_9P", "n", "network", "9p transport unused"),
    R("AF_RXRPC", "n", "network", "AFS RPC unused"),
    R("HSR", "n", "network", "high-availability seam protocol unused"),
    R("BATMAN_ADV", "n", "network", "mesh networking unused"),
    R("OPENVSWITCH", "n", "network", "OVS unused"),
    R("NET_TEAM", "n", "network", "team bonding unused"),
    R("BONDING", "n", "network", "bonding unused"),
    R("FDDI", "n", "network", "legacy FDDI"),
    R("NET_FC", "n", "network", "fibre channel unused"),
    R("X25", "n", "network", "legacy X.25"),
    R("LLC2", "n", "network", "legacy LLC2"),
    R("CAN", "n", "network", "no CAN bus hardware"),
    R("NFC", "n", "network", "no NFC hardware"),
    R("IEEE802154", "n", "network", "no 802.15.4 hardware"),
    R("WWAN", "n", "network", "no WWAN module present (lspci)"),
    R("WWAN_HWSIM", "n", "network", "WWAN test driver"),
    R("MHI_BUS", "n", "network", "MHI bus only serves WWAN/modem"),
    R("MHI_BUS_PCI_GENERIC", "n", "network", "MHI PCI transport unused"),
    R("IOSM", "n", "network", "Intel WWAN modem driver; no hardware"),
    R("MTK_T7XX", "n", "network", "MediaTek WWAN; no hardware"),
    R("NET_VENDOR_*", "n", "network", "no wired NIC (lspci); all ethernet vendor gates disabled"),
    R("PHYLIB", "n", "network", "phy framework only needed by wired NICs"),
    R("PHYLINK", "n", "network", "phylink unused without wired NICs"),
    R("FIXED_PHY", "n", "network", "fixed phy unused"),
    R("SFP", "n", "network", "SFP cages not present"),
    R("USB4", ("m", "y"), "network", "keep: Thunderbolt 4 / USB4 controllers present (lspci)"),
    R("USB4_NET", "n", "network", "Thunderbolt networking unused"),
    R("USB4_CONFIGFS", "n", "network", "USB4 configfs interface unused"),
    R("TYPEC", ("m", "y"), "network", "keep: USB Type-C class (UCSCI ports present)"),
    R("TYPEC_UCSI", ("m", "y"), "network", "keep: UCSI transport (ucsi_acpi bound)"),
    R("UCSI_ACPI", ("m", "y"), "network", "keep: ACPI UCSI interface"),
    R("USB_ROLE_SWITCH", ("m", "y"), "network", "keep: role switching for USB-C ports"),
    R("TYPEC_DP_ALTMODE", ("m", "y"), "network", "keep: DisplayPort alt-mode over USB-C"),
    R("TYPEC_TBT_ALTMODE", ("m", "y"), "network", "keep: Thunderbolt alt-mode"),
    R("TYPEC_MUX_INTEL_PMC", ("m", "y"), "network", "keep: Intel PMC USB-C mux"),

    # -- wireless ------------------------------------------------------------
    R("WLAN", ("y",), "wireless", "keep: wireless menu gate"),
    R("CFG80211", ("m", "y"), "wireless", "keep: cfg80211 for iwlwifi"),
    R("MAC80211", ("m", "y"), "wireless", "keep: mac80211 for iwlmvm"),
    R("WLAN_VENDOR_INTEL", ("y",), "wireless", "keep: Intel WiFi vendor gate (AX201)"),
    R("IWLWIFI", ("m", "y"), "wireless", "keep: AX201 WiFi driver"),
    R("IWLMVM", ("m", "y"), "wireless", "keep: AX201 uses the mvm opmode"),
    R("IWLDVM", "n", "wireless", "DVM opmode for old Intel WiFi"),
    R("IWLMLD", "n", "wireless", "MLD opmode for WiFi 7 devices; AX201 does not use it"),
    R("IWLMEI", "n", "wireless", "broken CSME WiFi sharing; not usable"),
    R("MAC80211_HWSIM", "n", "wireless", "mac80211 test driver"),
    R("CFG80211_WEXT", "n", "wireless", "legacy Wireless Extensions (niri/iwd use nl80211)"),
    R("WLAN_VENDOR_*", "n", "wireless", "all non-Intel WiFi vendors removed", exclude=("WLAN_VENDOR_INTEL",)),

    # -- bluetooth -----------------------------------------------------------
    R("BT", ("m", "y"), "bluetooth", "keep: Bluetooth core (btusb/hci0 present)"),
    R("BT_BREDR", ("y",), "bluetooth", "keep: classic Bluetooth"),
    R("BT_LE", ("y",), "bluetooth", "keep: Bluetooth Low Energy"),
    R("BT_LE_L2CAP_ECRED", ("y",), "bluetooth", "keep: LE credit-based connections"),
    R("BT_HIDP", ("m", "y"), "bluetooth", "keep: HID over Bluetooth (BT keyboards/mice)"),
    R("BT_MSFTEXT", ("y",), "bluetooth", "keep: Microsoft HCI extension used by BlueZ for some audio devices"),
    R("BT_HCIBTUSB", ("m", "y"), "bluetooth", "keep: USB Bluetooth transport (selects BT_INTEL)"),
    R("BT_HCIBTUSB_BCM", "n", "bluetooth", "Broadcom firmware support in btusb unused"),
    R("BT_HCIBTUSB_MTK", "n", "bluetooth", "MediaTek firmware support in btusb unused"),
    R("BT_HCIBTUSB_RTL", "n", "bluetooth", "Realtek firmware support in btusb unused"),
    R("BT_HCIUART", "n", "bluetooth", "serial BT transports unused"),
    R("BT_HCIBTSDIO", "n", "bluetooth", "SDIO BT transport unused"),
    R("BT_HCIVHCI", "n", "bluetooth", "virtual HCI driver unused"),
    R("BT_MRVL", "n", "bluetooth", "Marvell BT unused"),
    R("BT_ATH3K", "n", "bluetooth", "Atheros BT unused"),
    R("BT_MTKSDIO", "n", "bluetooth", "MediaTek SDIO BT unused"),
    R("BT_QCOMSMD", "n", "bluetooth", "Qualcomm BT unused"),
    R("BT_INTEL_PCIE", "n", "bluetooth", "PCIe Intel BT unused (AX201 uses USB)"),
    R("BT_DEBUGFS", "n", "bluetooth", "debugfs hooks unused"),
    R("BT_SELFTEST", "n", "bluetooth", "selftests unused"),
    R("BT_6LOWPAN", "n", "bluetooth", "6LoWPAN over BT unused"),
    R("BT_LEDS", "n", "bluetooth", "BT LED triggers unused"),
    R("BT_AOSPEXT", "n", "bluetooth", "Android HCI extension unused"),
    R("BT_BNEP", "n", "bluetooth", "BT network encapsulation (PAN) unused"),
    R("BT_RFCOMM", "n", "bluetooth", "RFCOMM serial unused"),
    R("BT_RFCOMM_TTY", "n", "bluetooth", "RFCOMM TTY unused"),

    # -- netfilter -----------------------------------------------------------
    R("NETFILTER", ("y",), "netfilter", "keep: netfilter core"),
    R("NF_TABLES", ("m", "y"), "netfilter", "keep: nftables core (user requirement)"),
    R("NF_TABLES_INET", ("y",), "netfilter", "keep: nft inet family"),
    R("NF_TABLES_IPV4", ("y",), "netfilter", "keep: nft ip family"),
    R("NF_TABLES_IPV6", ("y",), "netfilter", "keep: nft ip6 family"),
    R("NF_CONNTRACK", ("m", "y"), "netfilter", "keep: connection tracking"),
    R("NF_CT_NETLINK", ("m", "y"), "netfilter", "keep: conntrack netlink (conntrack tool)"),
    R("NF_NAT", ("m", "y"), "netfilter", "keep: NAT core"),
    R("NF_NAT_MASQUERADE", ("y",), "netfilter", "keep: masquerade support (selected)"),
    R("NF_NAT_REDIRECT", ("y",), "netfilter", "keep: redirect support (selected)"),
    R("NFT_CT", ("m", "y"), "netfilter", "keep: nft conntrack expression"),
    R("NFT_NAT", ("m", "y"), "netfilter", "keep: nft nat expression"),
    R("NFT_MASQ", ("m", "y"), "netfilter", "keep: nft masquerade"),
    R("NFT_REDIR", ("m", "y"), "netfilter", "keep: nft redirect"),
    R("NFT_REJECT", ("m", "y"), "netfilter", "keep: nft reject"),
    R("NFT_REJECT_INET", ("m", "y"), "netfilter", "keep: nft inet reject"),
    R("NFT_LOG", ("m", "y"), "netfilter", "keep: nft log"),
    R("NFT_LIMIT", ("m", "y"), "netfilter", "keep: nft limit"),
    R("NFT_CONNLIMIT", ("m", "y"), "netfilter", "keep: nft connlimit"),
    R("NF_LOG_SYSLOG", ("m", "y"), "netfilter", "keep: syslog backend for nft log"),
    R("NETFILTER_XTABLES", ("m", "y"), "netfilter", "keep: xtables core for iptables-nft"),
    R("NFT_COMPAT", ("m", "y"), "netfilter", "keep: iptables-nft compatibility layer"),
    R("NETFILTER_XT_MATCH_CONNTRACK", ("m", "y"), "netfilter", "keep: conntrack match"),
    R("NETFILTER_XT_MATCH_STATE", ("m", "y"), "netfilter", "keep: state match"),
    R("NETFILTER_XT_MATCH_COMMENT", ("m", "y"), "netfilter", "keep: comment match"),
    R("NETFILTER_XT_MATCH_LIMIT", ("m", "y"), "netfilter", "keep: limit match"),
    R("NETFILTER_XT_MATCH_MARK", ("m", "y"), "netfilter", "keep: mark match"),
    R("NETFILTER_XT_MATCH_MULTIPORT", ("m", "y"), "netfilter", "keep: multiport match"),
    R("NETFILTER_XT_MATCH_ADDRTYPE", ("m", "y"), "netfilter", "keep: addrtype match"),
    R("NETFILTER_XT_MATCH_MAC", ("m", "y"), "netfilter", "keep: mac match"),
    R("NETFILTER_XT_MATCH_TCPMSS", ("m", "y"), "netfilter", "keep: tcpmss match (VPN MTU fixups)"),
    R("NETFILTER_XT_MATCH_HL", ("m", "y"), "netfilter", "keep: TTL/HL match"),
    R("NETFILTER_XT_TARGET_LOG", ("m", "y"), "netfilter", "keep: iptables LOG target"),
    R("NETFILTER_XT_TARGET_MASQUERADE", ("m", "y"), "netfilter", "keep: iptables MASQUERADE target"),
    R("NETFILTER_XT_TARGET_REDIRECT", ("m", "y"), "netfilter", "keep: iptables REDIRECT target"),
    R("NETFILTER_XT_TARGET_TCPMSS", ("m", "y"), "netfilter", "keep: TCPMSS target"),
    R("NETFILTER_XT_NAT", ("m", "y"), "netfilter", "keep: SNAT/DNAT targets"),
    R("IP_NF_TARGET_REJECT", "n", "netfilter", "unreachable without legacy iptables: sits inside 'if IP_NF_IPTABLES' (net/ipv4/netfilter/Kconfig:142,195); nft REJECT is covered by the kept NFT_REJECT/NFT_REJECT_INET (re-enable IP_NF_IPTABLES_LEGACY if iptables-legacy is ever needed)"),
    R("NETFILTER_XTABLES_LEGACY", "n", "netfilter", "legacy iptables/arptables/ebtables core"),
    R("IP_NF_IPTABLES_LEGACY", "n", "netfilter", "legacy iptables backend"),
    R("IP_NF_IPTABLES", "n", "netfilter", "legacy iptables"),
    R("IP_NF_FILTER", "n", "netfilter", "legacy filter table"),
    R("IP_NF_MANGLE", "n", "netfilter", "legacy mangle table"),
    R("IP_NF_RAW", "n", "netfilter", "legacy raw table"),
    R("IP_NF_NAT", "n", "netfilter", "legacy nat table"),
    R("IP_NF_TARGET_MASQUERADE", "n", "netfilter", "legacy masquerade target"),
    R("IP_NF_ARPTABLES", "n", "netfilter", "arptables unused (iptables-nft)"),
    R("IP_NF_ARPFILTER", "n", "netfilter", "legacy arp filtering"),
    R("IP_NF_ARP_MANGLE", "n", "netfilter", "legacy arp mangling"),
    R("IP_NF_SECURITY", "n", "netfilter", "SECMARK over iptables unused"),
    R("IP_VS", "n", "netfilter", "IPVS load balancer unused"),
    R("BRIDGE_NF_EBTABLES", "n", "netfilter", "ebtables unused"),
    R("BRIDGE_NETFILTER", "n", "netfilter", "bridge netfilter hooks unused"),
    R("NF_TABLES_NETDEV", "n", "netfilter", "nft netdev family unused"),
    R("NF_TABLES_ARP", "n", "netfilter", "nft arp family unused"),
    R("NETFILTER_XT_TARGET_CT", "n", "netfilter", "CT target unused"),
    R("NETFILTER_XT_TARGET_TEE", "n", "netfilter", "TEE target unused"),
    R("NETFILTER_XT_TARGET_TPROXY", "n", "netfilter", "TPROXY target unused"),
    R("NETFILTER_XT_TARGET_AUDIT", "n", "netfilter", "AUDIT target unused"),
    R("NETFILTER_XT_TARGET_SECMARK", "n", "netfilter", "SECMARK target unused"),
    R("NETFILTER_XT_TARGET_TRACE", "n", "netfilter", "TRACE target unused"),
    R("NETFILTER_XT_TARGET_SYNPROXY", "n", "netfilter", "SYNPROXY target unused"),
    R("NETFILTER_XT_MATCH_RECENT", "n", "netfilter", "recent match unused"),
    R("NETFILTER_XT_MATCH_IPRANGE", "n", "netfilter", "iprange match unused"),
    R("NETFILTER_XT_MATCH_HASHLIMIT", "n", "netfilter", "hashlimit match unused"),
    R("NETFILTER_XT_MATCH_OSF", "n", "netfilter", "osf match unused"),
    R("NETFILTER_XT_MATCH_BPF", "n", "netfilter", "bpf match unused"),
    R("NETFILTER_XT_MATCH_OWNER", "n", "netfilter", "owner match unused"),
    R("NETFILTER_XT_MATCH_PKTTYPE", "n", "netfilter", "pkttype match unused"),
    R("NETFILTER_XT_MATCH_POLICY", "n", "netfilter", "policy match unused"),
    R("NETFILTER_XT_MATCH_HELPER", "n", "netfilter", "helper match unused"),
    R("NFT_OSF", "n", "netfilter", "nft osf unused"),
    R("NFT_TPROXY", "n", "netfilter", "nft tproxy unused"),
    R("NFT_SYNPROXY", "n", "netfilter", "nft synproxy unused"),
    R("NFT_XFRM", "n", "netfilter", "nft xfrm unused"),
    R("NFT_TUNNEL", "n", "netfilter", "nft tunnel unused"),
    R("NFT_QUEUE", "n", "netfilter", "nft queue unused"),
    R("NFT_QUOTA", "n", "netfilter", "nft quota unused"),
    R("NFT_NUMGEN", "n", "netfilter", "nft numgen unused"),
    R("NFT_HASH", "n", "netfilter", "nft hash unused"),
    R("NFT_SOCKET", "n", "netfilter", "nft socket unused"),
    R("NFT_FLOW_OFFLOAD", "n", "netfilter", "nft flow offload unused"),
    R("NFT_FIB", "n", "netfilter", "nft fib lookup unused"),
    R("NF_CONNTRACK_FTP", "n", "netfilter", "FTP ALG unused"),
    R("NF_CONNTRACK_SIP", "n", "netfilter", "SIP ALG unused"),
    R("NF_CONNTRACK_H323", "n", "netfilter", "H.323 ALG unused"),
    R("NF_CONNTRACK_IRC", "n", "netfilter", "IRC ALG unused"),
    R("NF_CONNTRACK_TFTP", "n", "netfilter", "TFTP ALG unused"),
    R("NF_CONNTRACK_AMANDA", "n", "netfilter", "Amanda ALG unused"),
    R("NF_CONNTRACK_NETBIOS_NS", "n", "netfilter", "NetBIOS NS ALG unused"),
    R("NF_CONNTRACK_SNMP", "n", "netfilter", "SNMP ALG unused"),
    R("NF_CONNTRACK_PPTP", "n", "netfilter", "PPTP ALG unused"),
    R("NF_CONNTRACK_SANE", "n", "netfilter", "SANE ALG unused"),
    R("NF_NAT_FTP", "n", "netfilter", "FTP NAT ALG unused"),
    R("NF_NAT_SIP", "n", "netfilter", "SIP NAT ALG unused"),
    R("NF_NAT_H323", "n", "netfilter", "H.323 NAT ALG unused"),
    R("NF_NAT_IRC", "n", "netfilter", "IRC NAT ALG unused"),
    R("NF_NAT_TFTP", "n", "netfilter", "TFTP NAT ALG unused"),
    R("NF_NAT_AMANDA", "n", "netfilter", "Amanda NAT ALG unused"),
    R("NF_NAT_PPTP", "n", "netfilter", "PPTP NAT ALG unused"),
    R("NF_CONNTRACK_MARK", "n", "netfilter", "conntrack mark unused"),
    R("NF_CONNTRACK_ZONES", "n", "netfilter", "conntrack zones unused"),
    R("NF_CONNTRACK_LABELS", "n", "netfilter", "conntrack labels unused"),
    R("NF_CONNTRACK_TIMESTAMP", "n", "netfilter", "conntrack timestamps unused"),
    R("NF_CONNTRACK_EVENTS", "n", "netfilter", "conntrack events (conntrackd) unused"),
    R("NF_CONNTRACK_PROCFS", "n", "netfilter", "conntrack procfs interface"),
    R("NF_CONNTRACK_TIMEOUT", "n", "netfilter", "per-ct timeouts unused"),
    R("NF_CONNTRACK_SECMARK", "n", "netfilter", "conntrack secmark unused"),
    R("NF_CT_NETLINK_TIMEOUT", "n", "netfilter", "conntrack netlink timeout interface unused"),
    R("NF_CT_NETLINK_HELPER", "n", "netfilter", "conntrack netlink helper interface unused"),
    R("NETFILTER_NETLINK_GLUE_CT", "n", "netfilter", "netlink conntrack glue unused"),

    # -- filesystem ----------------------------------------------------------
    R("EXT4_FS", ("y", "m"), "filesystem", "keep: root filesystem is ext4"),
    R("EXT4_USE_FOR_EXT2", ("y",), "filesystem", "keep: ext2/3 compatible mounting via ext4"),
    R("FAT_FS", ("m", "y"), "filesystem", "keep: FAT core (selected by VFAT_FS)"),
    R("VFAT_FS", ("m", "y"), "filesystem", "keep: /boot is FAT32"),
    R("EXFAT_FS", ("m", "y"), "filesystem", "keep: USB media filesystem per user decision (Ventoy stick is exFAT)"),
    R("NTFS3_FS", ("m", "y"), "filesystem", "keep: USB media filesystem per user decision"),
    R("ISO9660_FS", ("m", "y"), "filesystem", "keep: ISO images / optical media"),
    R("UDF_FS", ("m", "y"), "filesystem", "keep: DVD/Blu-ray media"),
    R("SQUASHFS", ("m", "y"), "filesystem", "keep: live-media and squashfs images"),
    R("FUSE_FS", ("m", "y"), "filesystem", "keep: FUSE in active use (gvfsd-fuse, portal)"),
    R("TMPFS", ("y",), "filesystem", "keep: tmpfs"),
    R("PROC_FS", ("y",), "filesystem", "keep: procfs"),
    R("SYSFS", ("y",), "filesystem", "keep: sysfs"),
    R("DEVTMPFS", ("y",), "filesystem", "keep: devtmpfs"),
    R("EFIVAR_FS", ("m", "y"), "filesystem", "keep: efivarfs (UEFI variables)"),
    R("PSTORE", ("m", "y"), "filesystem", "keep: pstore crash logs (mounted on this system)"),
    R("BINFMT_MISC", ("m", "y"), "filesystem", "keep: binfmt_misc (mounted on this system)"),
    R("XFS_FS", "n", "filesystem", "explicitly not wanted by user"),
    R("BTRFS_FS", "n", "filesystem", "explicitly not wanted by user"),
    R("F2FS_FS", "n", "filesystem", "unused filesystem"),
    R("JFS_FS", "n", "filesystem", "unused filesystem"),
    R("GFS2_FS", "n", "filesystem", "unused filesystem"),
    R("OCFS2_FS", "n", "filesystem", "unused filesystem"),
    R("NILFS2_FS", "n", "filesystem", "unused filesystem"),
    R("HFS_FS", "n", "filesystem", "unused filesystem"),
    R("HFSPLUS_FS", "n", "filesystem", "unused filesystem"),
    R("AFFS_FS", "n", "filesystem", "unused filesystem"),
    R("MINIX_FS", "n", "filesystem", "unused filesystem"),
    R("QNX4FS_FS", "n", "filesystem", "unused filesystem"),
    R("QNX6FS_FS", "n", "filesystem", "unused filesystem"),
    R("ROMFS_FS", "n", "filesystem", "unused filesystem"),
    R("UFS_FS", "n", "filesystem", "unused filesystem"),
    R("ADFS_FS", "n", "filesystem", "unused filesystem"),
    R("BEFS_FS", "n", "filesystem", "unused filesystem"),
    R("EROFS_FS", "n", "filesystem", "unused filesystem"),
    R("ORANGEFS_FS", "n", "filesystem", "unused filesystem"),
    R("ZONEFS_FS", "n", "filesystem", "unused filesystem"),
    R("AFS_FS", "n", "filesystem", "unused filesystem"),
    R("CEPH_FS", "n", "filesystem", "unused filesystem"),
    R("HPFS_FS", "n", "filesystem", "unused filesystem"),
    R("VXFS_FS", "n", "filesystem", "unused filesystem"),
    R("CRAMFS", "n", "filesystem", "unused filesystem"),
    R("CODA_FS", "n", "filesystem", "unused filesystem"),
    R("JFFS2_FS", "n", "filesystem", "no MTD flash filesystem usage"),
    R("UBIFS_FS", "n", "filesystem", "no UBI/MTD flash usage"),
    R("ECRYPTFS_FS", "n", "filesystem", "unused filesystem"),
    R("NFS_FS", "n", "filesystem", "no network filesystems in use"),
    R("NFSD", "n", "filesystem", "no NFS server"),
    R("CIFS", "n", "filesystem", "no SMB mounts in use"),
    R("9P_FS", "n", "filesystem", "no 9p mounts"),
    R("MSDOS_FS", "n", "filesystem", "VFAT coverage is sufficient; no plain FAT12/16-only media"),
    R("NTFS_FS", "n", "filesystem", "superseded by NTFS3"),
    R("OVERLAY_FS", "n", "filesystem", "no containers/overlay usage"),
    R("CONFIGFS_FS", "n", "filesystem", "nothing kept selects configfs"),
    R("CUSE", "n", "filesystem", "character-device fuse unused"),
    R("AUTOFS_FS", "n", "filesystem", "no systemd automount units in use"),

    # -- block / storage -----------------------------------------------------
    R("BLK_DEV_LOOP", ("m", "y"), "block", "keep: loop devices for ISO images"),
    R("ZRAM", ("m", "y"), "block", "keep: zram swap in active use"),
    R("ZRAM_BACKEND_LZ4HC", ("y",), "block", "keep: lz4hc backend corresponds to loaded lz4hc_compress"),
    R("ZRAM_BACKEND_842", ("y",), "block", "keep: 842 backend corresponds to loaded 842 modules"),
    R("SWAP", ("y",), "block", "keep: swap required for zram swap"),
    R("ZSWAP", "n", "block", "disabled at boot (zswap.enabled=0); zram used instead"),
    R("BLK_DEV_DM", ("m",), "block", "keep: device-mapper core for LUKS (user decision)"),
    R("DM_CRYPT", ("m",), "block", "keep: dm-crypt for LUKS (user decision)"),
    R("CRYPTO_XTS", ("m", "y"), "block", "keep: LUKS2 default cipher mode; must survive localmodconfig"),
    R("CRYPTO_AES_NI_INTEL", ("m", "y"), "block", "keep: AES-NI acceleration for LUKS"),
    R("BLK_DEV_MD", "n", "block", "no software RAID usage"),
    R("BLK_DEV_NBD", "n", "block", "network block device unused"),
    R("BLK_DEV_RAM", "n", "block", "ram block device unused"),
    R("BLK_DEV_NULL_BLK", "n", "block", "null_blk test driver unused"),
    R("LIBNVDIMM", "n", "block", "no NVDIMM hardware"),
    R("BLK_DEV_PMEM", "n", "block", "no persistent memory hardware"),
    R("MMC", "n", "block", "no SD/MMC reader on this machine"),
    R("ATA", "n", "block", "no SATA/ATA devices (NVMe only)"),
    R("SATA_AHCI", "n", "block", "no AHCI controller"),
    R("BLK_DEV_NVME", ("m", "y"), "block", "keep: NVMe SSD is the system disk"),
    R("SCSI", ("m", "y"), "block", "keep: needed by USB storage stack and SR_MOD"),
    R("BLK_DEV_SD", ("m", "y"), "block", "keep: SCSI disk (USB drives)"),
    R("BLK_DEV_SR", ("m", "y"), "block", "keep: SCSI CD-ROM (USB optical drives)"),
    R("USB_STORAGE", ("m", "y"), "block", "keep: USB mass storage in use (Ventoy stick)"),
    R("USB_UAS", ("m", "y"), "block", "keep: UAS in use by USB drives"),

    # -- audio ---------------------------------------------------------------
    R("SND_SOC", ("m", "y"), "audio", "keep: ASoC core required by the SOF stack"),
    R("SND_SOC_SOF_TOPLEVEL", ("y",), "audio", "keep: SOF menu gate"),
    R("SND_SOC_SOF_PCI", ("m", "y"), "audio", "keep: SOF PCI enumeration (SKL+ platforms)"),
    R("SND_SOC_SOF_TIGERLAKE", ("m", "y"), "audio", "keep: current working driver is sof-audio-pci-intel-tgl"),
    R("SND_SOC_SOF_HDA_LINK", ("y",), "audio", "keep: HDA link required for this machine's codec layout"),
    R("SND_SOC_SOF_HDA_AUDIO_CODEC", ("y",), "audio", "keep: enables the SOF HDA machine driver required for playback"),
    R("SND_SOC_SOF_INTEL_SOUNDWIRE", ("m", "y"), "audio", "keep: SoundWire link support for TGL"),
    R("SND_SOC_INTEL_SKL_HDA_DSP_GENERIC_MACH", ("m", "y"), "audio", "keep: machine driver bound by SOF HDA (snd_soc_skl_hda_dsp)"),
    R("SND_SOC_DMIC", ("m", "y"), "audio", "keep: digital microphone"),
    R("SOUNDWIRE", ("m", "y"), "audio", "keep: SoundWire bus"),
    R("SOUNDWIRE_INTEL", ("m", "y"), "audio", "keep: Intel SoundWire controller"),
    R("SND_SOC_SDCA", ("m", "y"), "audio", "keep: SDCA support used by the SOF/SDW stack"),
    R("SND_HDA_INTEL", ("m", "y"), "audio", "keep: HDA controller (active + fallback path)"),
    R("SND_HDA_CODEC_REALTEK", ("m", "y"), "audio", "keep: Realtek codec family (ALC269)"),
    R("SND_HDA_CODEC_ALC269", ("m", "y"), "audio", "keep: ALC269 codec present on this machine"),
    R("SND_HDA_CODEC_HDMI", ("m", "y"), "audio", "keep: HDMI codec family; hard dependency of the SOF machine driver"),
    R("SND_HDA_CODEC_HDMI_GENERIC", ("m", "y"), "audio", "keep: generic HDMI codec (loaded)"),
    R("SND_HDA_CODEC_HDMI_INTEL", ("m", "y"), "audio", "keep: Intel HDMI codec (loaded)"),
    R("SND_HDA_GENERIC", ("m", "y"), "audio", "keep: generic HDA codec fallback"),
    R("SND_USB_AUDIO", ("m", "y"), "audio", "keep: USB audio devices are a plausible plug-in"),
    R("SND_SEQUENCER", ("m", "y"), "audio", "keep: sequencer currently loaded/used by the audio stack"),
    R("SND_SEQ_DUMMY", ("m", "y"), "audio", "keep: currently loaded"),
    R("SND_SOC_INTEL_AVS", "n", "audio", "AVS driver loaded but unbound; SOF is the active path"),
    R("SND_SOC_SOF_ACPI", "n", "audio", "SOF ACPI enumeration only for Baytrail/Broadwell"),
    R("SND_SOC_SOF_BAYTRAIL", "n", "audio", "other Intel platform"),
    R("SND_SOC_SOF_BROADWELL", "n", "audio", "other Intel platform"),
    R("SND_SOC_SOF_MERRIFIELD", "n", "audio", "other Intel platform"),
    R("SND_SOC_SOF_SKYLAKE", "n", "audio", "other Intel platform"),
    R("SND_SOC_SOF_KABYLAKE", "n", "audio", "other Intel platform"),
    R("SND_SOC_SOF_APOLLOLAKE", "n", "audio", "other Intel platform"),
    R("SND_SOC_SOF_GEMINILAKE", "n", "audio", "other Intel platform"),
    R("SND_SOC_SOF_CANNONLAKE", "n", "audio", "other Intel platform (CNL module still built via TGL select)"),
    R("SND_SOC_SOF_COFFEELAKE", "n", "audio", "other Intel platform"),
    R("SND_SOC_SOF_COMETLAKE", "n", "audio", "other Intel platform"),
    R("SND_SOC_SOF_ICELAKE", "n", "audio", "other Intel platform"),
    R("SND_SOC_SOF_JASPERLAKE", "n", "audio", "other Intel platform"),
    R("SND_SOC_SOF_ELKHARTLAKE", "n", "audio", "other Intel platform"),
    R("SND_SOC_SOF_ALDERLAKE", "n", "audio", "other Intel platform"),
    R("SND_SOC_SOF_METEORLAKE", "n", "audio", "other Intel platform"),
    R("SND_SOC_SOF_LUNARLAKE", "n", "audio", "other Intel platform"),
    R("SND_SOC_SOF_PANTHERLAKE", "n", "audio", "other Intel platform"),
    R("SND_SOC_SOF_NOVALAKE", "n", "audio", "other Intel platform"),
    R("SND_SOC_SOF_NOCODEC_SUPPORT", "n", "audio", "no-codec debug mode; not for production"),
    R("SND_HDA_CODEC_ANALOG", "n", "audio", "codec family not present"),
    R("SND_HDA_CODEC_SIGMATEL", "n", "audio", "codec family not present"),
    R("SND_HDA_CODEC_VIA", "n", "audio", "codec family not present"),
    R("SND_HDA_CODEC_CONEXANT", "n", "audio", "codec family not present"),
    R("SND_HDA_CODEC_SENARYTECH", "n", "audio", "codec family not present"),
    R("SND_HDA_CODEC_CA0110", "n", "audio", "codec family not present"),
    R("SND_HDA_CODEC_CA0132", "n", "audio", "codec family not present"),
    R("SND_HDA_CODEC_CMEDIA", "n", "audio", "codec family not present"),
    R("SND_HDA_CODEC_CM9825", "n", "audio", "codec family not present"),
    R("SND_HDA_CODEC_SI3054", "n", "audio", "codec family not present"),
    R("SND_HDA_CODEC_CIRRUS", "n", "audio", "codec family not present"),
    R("SND_HDA_CODEC_CS8409", "n", "audio", "codec family not present"),
    R("SND_HDA_SCODEC_CS35L41_I2C", "n", "audio", "side codec not present"),
    R("SND_HDA_SCODEC_CS35L41_SPI", "n", "audio", "side codec not present"),
    R("SND_HDA_SCODEC_CS35L56_I2C", "n", "audio", "side codec not present"),
    R("SND_HDA_SCODEC_CS35L56_SPI", "n", "audio", "side codec not present"),
    R("SND_HDA_SCODEC_TAS2781_I2C", "n", "audio", "side codec not present"),
    R("SND_HDA_CODEC_ALC260", "n", "audio", "Realtek variant not present"),
    R("SND_HDA_CODEC_ALC262", "n", "audio", "Realtek variant not present"),
    R("SND_HDA_CODEC_ALC268", "n", "audio", "Realtek variant not present"),
    R("SND_HDA_CODEC_ALC662", "n", "audio", "Realtek variant not present"),
    R("SND_HDA_CODEC_ALC680", "n", "audio", "Realtek variant not present"),
    R("SND_HDA_CODEC_ALC861", "n", "audio", "Realtek variant not present"),
    R("SND_HDA_CODEC_ALC861VD", "n", "audio", "Realtek variant not present"),
    R("SND_HDA_CODEC_ALC880", "n", "audio", "Realtek variant not present"),
    R("SND_HDA_CODEC_ALC882", "n", "audio", "Realtek variant not present"),

    # -- input ---------------------------------------------------------------
    R("INPUT", ("y", "m"), "input", "keep: input core"),
    R("INPUT_EVDEV", ("m", "y"), "input", "keep: evdev is the only interface libinput/Wayland uses"),
    R("INPUT_UINPUT", ("m", "y"), "input", "keep: virtual input devices for Wayland tooling"),
    R("KEYBOARD_ATKBD", ("y", "m"), "input", "keep: internal AT keyboard"),
    R("SERIO", ("y", "m"), "input", "keep: serio bus for PS/2 devices"),
    R("SERIO_I8042", ("y", "m"), "input", "keep: i8042 controller (keyboard/touchpoint)"),
    R("MOUSE_PS2", ("m", "y"), "input", "keep: TrackPoint (PS/2)"),
    R("HID", ("y", "m"), "input", "keep: HID core"),
    R("HID_GENERIC", ("m", "y"), "input", "keep: generic HID driver"),
    R("USB_HID", ("m", "y"), "input", "keep: USB HID"),
    R("HID_MULTITOUCH", ("m", "y"), "input", "keep: touchpad multitouch"),
    R("I2C_HID", ("m", "y"), "input", "keep: I2C HID core for the touchpad"),
    R("I2C_HID_ACPI", ("m", "y"), "input", "keep: ACPI-enumerated I2C HID (SYNA8008 touchpad)"),
    R("INTEL_ISH_HID", ("m", "y"), "input", "keep: ISH sensor hub HID (loaded)"),
    R("HID_SENSOR_HUB", ("m", "y"), "input", "keep: HID sensor hub (accelerometer etc.)"),
    R("INPUT_JOYDEV", "n", "input", "legacy joydev; libinput uses evdev only"),
    R("INPUT_MOUSEDEV", "n", "input", "legacy /dev/input/mice; not used by libinput"),
    R("INPUT_PCSPKR", "n", "input", "PC speaker beeper unused"),

    # -- platform / power / boot --------------------------------------------
    R("THINKPAD_ACPI", ("m", "y"), "platform", "keep: ThinkPad hotkeys/fan/thermal (loaded)"),
    R("INTEL_HID_EVENT", ("m", "y"), "platform", "keep: Intel HID event driver (loaded)"),
    R("INTEL_VSEC", ("m", "y"), "platform", "keep: Intel VSEC (loaded; used by PMC telemetry)"),
    R("INTEL_MEI", ("m", "y"), "platform", "keep: Intel MEI core (loaded)"),
    R("INTEL_MEI_ME", ("m", "y"), "platform", "keep: MEI PCI controller (loaded)"),
    R("INTEL_MEI_HDCP", ("m", "y"), "platform", "keep: MEI HDCP (loaded)"),
    R("INTEL_MEI_PXP", ("m", "y"), "platform", "keep: MEI PXP (loaded; pairs with DRM_I915_PXP)"),
    R("INTEL_PMC_CORE", ("m", "y"), "platform", "keep: PMC core driver (loaded)"),
    R("SENSORS_CORETEMP", ("m", "y"), "platform", "keep: CPU temperature sensor (loaded)"),
    R("X86_PKG_TEMP_THERMAL", ("m", "y"), "platform", "keep: package thermal zone (loaded)"),
    R("INTEL_RAPL", ("m", "y"), "platform", "keep: RAPL power capping (loaded)"),
    R("MFD_INTEL_LPSS_PCI", ("m", "y"), "platform", "keep: LPSS (loaded; I2C/SPI/UART glue)"),
    R("I2C_I801", ("m", "y"), "platform", "keep: SMBus controller (loaded)"),
    R("SPI_INTEL_PCI", ("m", "y"), "platform", "keep: SPI controller for the BIOS flash (fwupd)"),
    R("INTEL_IOMMU", ("y",), "platform", "keep: IOMMU for Thunderbolt DMA protection"),
    R("MICROCODE", ("y",), "platform", "keep: microcode loading (initramfs early load)"),
    R("X86_INTEL_PSTATE", ("y",), "platform", "keep: active CPU scaling driver"),
    R("EFI", ("y",), "platform", "keep: UEFI boot"),
    R("EFI_STUB", ("y",), "platform", "keep: EFISTUB boot support"),
    R("EFI_PARTITION", ("y",), "platform", "keep: GPT partition support"),
    R("MSDOS_PARTITION", ("y",), "platform", "keep: MBR partition support (USB sticks)"),
    R("BLK_DEV_INITRD", ("y",), "platform", "keep: initramfs (Gentoo will boot via initramfs)"),
    R("MODULES", ("y",), "platform", "keep: loadable modules"),
    R("SUSPEND", ("y",), "platform", "keep: suspend-to-idle/RAM for a laptop"),
    R("HIBERNATION", "n", "platform", "no persistent swap device; hibernation impossible with zram only"),
]


# --------------------------------------------------------------------------
# Config parsing and checking
# --------------------------------------------------------------------------

def parse_config(path: Path) -> dict[str, str]:
    """Parse a kernel .config into {CONFIG_X: value}; unset -> "n"."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _SET_RE.match(line)
        if m:
            values[m.group("name")] = m.group("value")
            continue
        m = _UNSET_RE.match(line)
        if m:
            values[m.group("name")] = "n"
    return values


def expand_rule(rule: Rule, config: dict[str, str]) -> list[str]:
    """Return the config symbols a rule applies to (wildcard expansion included)."""
    if not rule.is_pattern:
        return [rule.symbol]
    names = [name for name in config if fnmatch.fnmatchcase(name, rule.symbol)]
    for pattern in rule.exclude:
        names = [n for n in names if not fnmatch.fnmatchcase(n, pattern)]
    return sorted(names)


def expect_matches(actual: Optional[str], token: str) -> bool:
    """True if the actual value satisfies one expect token."""
    if token in ("y", "m", "n"):
        if token == "n":
            return actual in (None, "n")
        return actual == token
    if token.startswith("value"):
        return _value_matches(actual, token)
    raise ValueError(f"bad expect token: {token!r}")


def _value_matches(actual: Optional[str], token: str) -> bool:
    m = _VALUE_RE.match(token)
    if not m:
        raise ValueError(f"bad value token: {token!r}")
    if actual is None:
        return False
    op, want = m.group("op"), m.group("want")
    try:
        return _OP_FUNCS[op](int(actual), int(want))
    except ValueError:
        return op == "=" and actual.strip('"') == want.strip('"')


def check(config: dict[str, str], rules: Sequence[Rule], profile: str) -> list[Result]:
    """Evaluate every applicable rule; one Result per symbol (patterns expand)."""
    results: list[Result] = []
    for rule in rules:
        if profile not in rule.profiles and "all" not in rule.profiles:
            continue
        symbols = expand_rule(rule, config)
        if rule.is_pattern and not symbols:
            results.append(Result(rule, rule.symbol, None, True, note="no matching symbols"))
            continue
        for symbol in symbols:
            actual = config.get(symbol)
            passed = any(expect_matches(actual, t) for t in rule.expect)
            note = ""
            if actual is None and passed:
                note = "absent from config (treated as 'n')"
            results.append(Result(rule, symbol, actual, passed, note))
    return results


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def fmt_value(actual: Optional[str]) -> str:
    return "(absent)" if actual is None else actual


def fmt_expect(rule: Rule) -> str:
    return " | ".join(rule.expect)


def group_results(results: Sequence[Result]) -> dict[str, list[Result]]:
    """Group results by rule group, preserving first-seen order."""
    groups: dict[str, list[Result]] = {}
    for res in results:
        groups.setdefault(res.rule.group, []).append(res)
    return groups


def render_text(results: Sequence[Result], quiet: bool) -> str:
    out: list[str] = []
    for group, items in group_results(results).items():
        fails = [r for r in items if not r.passed]
        passes = [r for r in items if r.passed]
        if quiet and not fails:
            continue
        out.append(f"[{group}]")
        by_rule: dict[int, list[Result]] = {}
        for res in fails:
            by_rule.setdefault(id(res.rule), []).append(res)
        for rid, bad in by_rule.items():
            rule = bad[0].rule
            if len(bad) == 1:
                res = bad[0]
                out.append(f"  FAIL  {res.symbol} = {fmt_value(res.actual)}"
                           f"  (expected: {fmt_expect(rule)})")
                out.append(f"        reason: {rule.reason}")
                if res.note:
                    out.append(f"        note: {res.note}")
            else:
                out.append(f"  FAIL  {rule.symbol} — {len(bad)} mismatches"
                           f" (expected: {fmt_expect(rule)})")
                for res in bad:
                    out.append(f"        - {res.symbol} = {fmt_value(res.actual)}")
                out.append(f"        reason: {rule.reason}")
        if not quiet:
            seen: set[int] = set()
            for res in passes:
                rid = id(res.rule)
                rule = res.rule
                if rule.is_pattern:
                    if rid in seen:
                        continue
                    seen.add(rid)
                    count = sum(1 for r in passes if r.rule is rule)
                    out.append(f"  pass  {rule.symbol} — {count} symbols satisfy"
                               f" '{fmt_expect(rule)}'")
                else:
                    extra = f"  [{res.note}]" if res.note else ""
                    out.append(f"  pass  {res.symbol} = {fmt_value(res.actual)}{extra}")
        out.append("")
    return "\n".join(out)


def render_json(results: Sequence[Result], config_path: str, profile: str) -> str:
    payload = {
        "config": config_path,
        "profile": profile,
        "results": [
            {
                "symbol": r.symbol,
                "group": r.rule.group,
                "expected": list(r.rule.expect),
                "actual": r.actual,
                "passed": r.passed,
                "reason": r.rule.reason,
                "note": r.note,
            }
            for r in results
        ],
        "summary": summary(results),
    }
    return json.dumps(payload, indent=2)


def summary(results: Sequence[Result]) -> dict:
    groups: dict[str, dict[str, int]] = {}
    for res in results:
        g = groups.setdefault(res.rule.group, {"passed": 0, "failed": 0})
        g["passed" if res.passed else "failed"] += 1
    total = {"passed": sum(g["passed"] for g in groups.values()),
             "failed": sum(g["failed"] for g in groups.values())}
    return {"groups": groups, "total": total}


def render_summary(results: Sequence[Result]) -> str:
    s = summary(results)
    out = ["=== SUMMARY ===", f"{'group':<16}{'pass':>6}{'fail':>6}"]
    for group, counts in s["groups"].items():
        out.append(f"{group:<16}{counts['passed']:>6}{counts['failed']:>6}")
    t = s["total"]
    out.append(f"{'TOTAL':<16}{t['passed']:>6}{t['failed']:>6}")
    out.append(f"RESULT: {'PASS' if t['failed'] == 0 else 'FAIL'}")
    return "\n".join(out)


def render_commands(results: Sequence[Result], scripts_config: str, config_path: str) -> str:
    """Emit shell commands fixing every failed rule via scripts/config."""
    out = [
        "#!/bin/sh",
        "# Generated by kernel_config_check.py --emit-commands.",
        "# Review before running. Requires the kernel tree's scripts/config.",
        "set -u",
        f"SCRIPTS_CONFIG={shlex.quote(scripts_config)}",
        f"CONFIG_FILE={shlex.quote(config_path)}",
    ]
    emitted: set[str] = set()
    for res in results:
        if res.passed or not res.symbol.startswith(CONFIG_PREFIX):
            continue
        target = res.rule.expect[0]
        if res.symbol in emitted:
            continue
        emitted.add(res.symbol)
        prefix = '"$SCRIPTS_CONFIG" --file "$CONFIG_FILE"'
        note = f"# [{res.rule.group}] {res.rule.reason}"
        if target == "n":
            cmd = f"{prefix} --disable {res.symbol}"
        elif target == "y":
            cmd = f"{prefix} --enable {res.symbol}"
        elif target == "m":
            cmd = f"{prefix} --module {res.symbol}"
        elif target.startswith("value"):
            m = _VALUE_RE.match(target)
            want = m.group("want") if m else ""
            if want.startswith('"') or want.startswith("'"):
                cmd = f"{prefix} --set-str {res.symbol} {want.strip(chr(34) + chr(39))}"
            else:
                cmd = f"{prefix} --set-val {res.symbol} {want}"
        else:
            continue
        out.append(note)
        out.append(cmd)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def load_external_rules(path: Path) -> list[Rule]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rules: list[Rule] = []
    for item in data:
        rules.append(R(
            item["symbol"], item["expect"], item["group"], item["reason"],
            exclude=item.get("exclude", ()),
            profiles=item.get("profiles", (DEFAULT_PROFILE,)),
        ))
    return rules


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check a Linux kernel .config against policy rules.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", required=True, help="path to the kernel .config")
    parser.add_argument("--profile", default=DEFAULT_PROFILE,
                        help="rule profile to apply")
    parser.add_argument("--rules", help="optional JSON file with extra rules")
    parser.add_argument("--emit-commands", action="store_true",
                        help="print scripts/config fix commands for failed rules")
    parser.add_argument("--scripts-config", default="scripts/config",
                        help="path to the kernel tree's scripts/config")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--quiet", action="store_true",
                        help="only failures and the summary")
    parser.add_argument("--list-groups", action="store_true",
                        help="list rule groups and how many rules each has")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_groups:
        counts: dict[str, int] = {}
        rules = list(DEFAULT_RULES)
        if args.rules:
            rules += load_external_rules(Path(args.rules))
        for rule in rules:
            if args.profile in rule.profiles or "all" in rule.profiles:
                counts[rule.group] = counts.get(rule.group, 0) + 1
        for group, count in counts.items():
            print(f"{group:<16}{count:>4} rules")
        return 0

    config_path = Path(args.config)
    if not config_path.is_file():
        print(f"error: cannot read config file: {config_path}", file=sys.stderr)
        return 2
    try:
        config = parse_config(config_path)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rules = list(DEFAULT_RULES)
    if args.rules:
        rules += load_external_rules(Path(args.rules))

    results = check(config, rules, args.profile)

    if args.emit_commands:
        sys.stdout.write(render_commands(results, args.scripts_config, str(config_path)))
        return 0 if all(r.passed for r in results) else 1
    if args.json:
        print(render_json(results, str(config_path), args.profile))
    else:
        print(render_text(results, args.quiet))
        print(render_summary(results))
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
