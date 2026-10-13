#!/usr/bin/env bash

set -u

errors=0
warnings=0

CONFIG=""
EFI_IMAGE=""

RED=$'\033[31m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
BLUE=$'\033[34m'
RESET=$'\033[0m'

usage() {
    cat <<EOF
Usage:
  $0 --config <kernel-config> [--efi <efi-image>]

Required:
  --config PATH    Path to the Linux kernel configuration file.

Optional:
  --efi PATH       Path to the final EFI executable to inspect for
                   a Secure Boot PE/Authenticode signature.

Examples:
  $0 --config /usr/src/linux/.config

  $0 --config /usr/src/linux/.config \\
     --efi /boot/EFI/Gentoo/gentoo.efi

Purpose:
  Check whether a Linux kernel configuration is suitable for:

    - x86_64 UEFI
    - EFI Stub boot
    - NVMe root device
    - ext4 root filesystem
    - no initramfs
    - Secure Boot

EOF
}

while (( $# > 0 )); do
    case "$1" in
        --config)
            if (( $# < 2 )); then
                echo "Error: --config requires a path." >&2
                usage >&2
                exit 2
            fi
            CONFIG="$2"
            shift 2
            ;;

        --efi)
            if (( $# < 2 )); then
                echo "Error: --efi requires a path." >&2
                usage >&2
                exit 2
            fi
            EFI_IMAGE="$2"
            shift 2
            ;;

        -h|--help)
            usage
            exit 0
            ;;

        *)
            echo "Error: Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ -z "$CONFIG" ]]; then
    echo "Error: --config is required." >&2
    echo >&2
    usage >&2
    exit 2
fi

if [[ ! -r "$CONFIG" ]]; then
    echo "Error: Cannot read kernel config: $CONFIG" >&2
    exit 2
fi

ok() {
    printf '%s[ OK ]%s %s\n' "$GREEN" "$RESET" "$*"
}

warn() {
    printf '%s[WARN]%s %s\n' "$YELLOW" "$RESET" "$*"
    warnings=$((warnings + 1))
}

fail() {
    printf '%s[FAIL]%s %s\n' "$RED" "$RESET" "$*"
    errors=$((errors + 1))
}

info() {
    printf '%s[INFO]%s %s\n' "$BLUE" "$RESET" "$*"
}

get_config() {
    local key="$1"
    local line

    line="$(
        grep -E "^${key}=|^# ${key} is not set$" \
            "$CONFIG" 2>/dev/null | tail -n1 || true
    )"

    case "$line" in
        "${key}=y")
            echo "y"
            ;;
        "${key}=m")
            echo "m"
            ;;
        "${key}="*)
            printf '%s\n' "${line#*=}"
            ;;
        "# ${key} is not set")
            echo "n"
            ;;
        *)
            echo "missing"
            ;;
    esac
}

require_y() {
    local key="$1"
    local description="$2"
    local value

    value="$(get_config "$key")"

    case "$value" in
        y)
            ok "$key=y -- $description"
            ;;
        m)
            fail "$key=m -- $description; this must be built-in (=y) for no-initramfs boot"
            ;;
        n)
            fail "$key is disabled -- $description"
            ;;
        missing)
            fail "$key is missing from the config -- $description"
            ;;
        *)
            fail "$key=$value -- expected y; $description"
            ;;
    esac
}

echo
echo "================================================================"
echo " EFI Stub + NVMe + ext4 + no-initramfs + Secure Boot checker"
echo "================================================================"
echo
echo "Kernel config : $CONFIG"

if [[ -n "$EFI_IMAGE" ]]; then
    echo "EFI image     : $EFI_IMAGE"
else
    echo "EFI image     : not specified"
fi

echo

#
# 1. EFI / EFI Stub
#

echo "== 1. EFI / EFI Stub =="

require_y CONFIG_EFI \
    "EFI support"

require_y CONFIG_EFI_STUB \
    "allow the Linux kernel to execute as an EFI application"

echo

#
# 2. Block layer / PCI / NVMe / GPT
#

echo "== 2. Storage path =="

require_y CONFIG_BLOCK \
    "block device support"

require_y CONFIG_PCI \
    "PCI support required by typical NVMe controllers"

require_y CONFIG_BLK_DEV_NVME \
    "NVMe host driver required to access the root device"

efi_partition="$(get_config CONFIG_EFI_PARTITION)"

case "$efi_partition" in
    y)
        ok "CONFIG_EFI_PARTITION=y -- GPT/EFI partition support"
        ;;
    m)
        fail "CONFIG_EFI_PARTITION=m -- partition support required before mounting root should be built-in"
        ;;
    *)
        warn "CONFIG_EFI_PARTITION=$efi_partition -- verify GPT partition support if the NVMe disk uses GPT"
        ;;
esac

echo

#
# 3. ext4 root
#

echo "== 3. Root filesystem =="

require_y CONFIG_EXT4_FS \
    "ext4 root filesystem support"

echo

#
# 4. Device filesystem
#

echo "== 4. Device filesystem =="

require_y CONFIG_DEVTMPFS \
    "devtmpfs support"

devtmpfs_mount="$(get_config CONFIG_DEVTMPFS_MOUNT)"

case "$devtmpfs_mount" in
    y)
        ok "CONFIG_DEVTMPFS_MOUNT=y -- kernel can automatically mount devtmpfs"
        ;;
    *)
        warn "CONFIG_DEVTMPFS_MOUNT=$devtmpfs_mount -- normally recommended for a simple no-initramfs system"
        ;;
esac

echo

#
# 5. Kernel command line
#

echo "== 5. Kernel command line =="

cmdline="$(get_config CONFIG_CMDLINE)"

case "$cmdline" in
    missing|n|'""')
        info "No built-in CONFIG_CMDLINE was found."
        info "This is valid, but the kernel must receive a root device externally."
        info "For example:"
        echo
        echo "    root=UUID=<root-filesystem-uuid> rw"
        echo
        ;;
    *)
        echo "CONFIG_CMDLINE=$cmdline"

        if [[ "$cmdline" == *"root="* ]]; then
            ok "CONFIG_CMDLINE contains a root= parameter"
        else
            warn "CONFIG_CMDLINE does not contain root=; ensure the EFI boot entry or UKI supplies it"
        fi
        ;;
esac

echo

#
# 6. Built-in initramfs
#

echo "== 6. Built-in initramfs =="

initrd_source="$(get_config CONFIG_INITRAMFS_SOURCE)"

case "$initrd_source" in
    '""'|missing|n)
        ok "No built-in CONFIG_INITRAMFS_SOURCE detected"
        ;;
    *)
        warn "CONFIG_INITRAMFS_SOURCE=$initrd_source"
        warn "The kernel appears to contain a built-in initramfs."
        ;;
esac

echo

#
# 7. Secure Boot related kernel options
#

echo "== 7. Secure Boot / kernel security =="

module_sig="$(get_config CONFIG_MODULE_SIG)"

case "$module_sig" in
    y)
        ok "CONFIG_MODULE_SIG=y -- kernel module signature verification is supported"
        ;;
    *)
        warn "CONFIG_MODULE_SIG=$module_sig -- recommended when using Secure Boot with loadable modules"
        ;;
esac

module_sig_force="$(get_config CONFIG_MODULE_SIG_FORCE)"

case "$module_sig_force" in
    y)
        ok "CONFIG_MODULE_SIG_FORCE=y -- unsigned/untrusted loadable modules are rejected"
        ;;
    *)
        warn "CONFIG_MODULE_SIG_FORCE=$module_sig_force -- kernel does not enforce signed modules through this option"
        ;;
esac

module_sig_all="$(get_config CONFIG_MODULE_SIG_ALL)"

case "$module_sig_all" in
    y)
        ok "CONFIG_MODULE_SIG_ALL=y -- modules are automatically signed during the kernel build"
        ;;
    *)
        info "CONFIG_MODULE_SIG_ALL=$module_sig_all -- verify separately how loadable modules are signed"
        ;;
esac

lockdown="$(get_config CONFIG_SECURITY_LOCKDOWN_LSM)"

case "$lockdown" in
    y)
        ok "CONFIG_SECURITY_LOCKDOWN_LSM=y -- kernel lockdown LSM is available"
        ;;
    *)
        warn "CONFIG_SECURITY_LOCKDOWN_LSM=$lockdown -- review your Secure Boot/lockdown policy"
        ;;
esac

integrity="$(get_config CONFIG_INTEGRITY)"

case "$integrity" in
    y)
        ok "CONFIG_INTEGRITY=y -- integrity subsystem is enabled"
        ;;
    *)
        info "CONFIG_INTEGRITY=$integrity"
        ;;
esac

echo

#
# 8. Running system root device
#

echo "== 8. Running system root =="

if command -v findmnt >/dev/null 2>&1; then

    root_source="$(findmnt -n -o SOURCE / 2>/dev/null || true)"
    root_fstype="$(findmnt -n -o FSTYPE / 2>/dev/null || true)"
    root_uuid="$(findmnt -n -o UUID / 2>/dev/null || true)"

    if [[ -n "$root_source" ]]; then
        info "Current root device: $root_source"
    fi

    case "$root_fstype" in
        ext4)
            ok "Current root filesystem is ext4"
            ;;
        "")
            warn "Could not determine the current root filesystem type"
            ;;
        *)
            warn "Current root filesystem is $root_fstype, not ext4"
            ;;
    esac

    if [[ -n "$root_uuid" ]]; then
        info "Root filesystem UUID: $root_uuid"
        info "Suggested kernel command line:"
        echo
        echo "    root=UUID=$root_uuid rw"
        echo
    fi

else
    info "findmnt is not available; skipping runtime root filesystem checks"
fi

#
# 9. Firmware boot mode
#

echo "== 9. Firmware boot mode =="

if [[ -d /sys/firmware/efi ]]; then
    ok "The running system was booted via UEFI"
else
    warn "/sys/firmware/efi does not exist; the running system does not appear to have booted via UEFI"
fi

if [[ -d /sys/firmware/efi/efivars ]]; then
    ok "EFI variables are accessible"
else
    warn "EFI variables are not currently accessible"
fi

echo

#
# 10. Current Secure Boot state
#

echo "== 10. Current Secure Boot state =="

if command -v mokutil >/dev/null 2>&1; then

    mok_output="$(mokutil --sb-state 2>&1 || true)"
    echo "$mok_output"

    if echo "$mok_output" | grep -qi "SecureBoot enabled"; then
        ok "UEFI Secure Boot is currently enabled"
    else
        warn "Secure Boot does not appear to be enabled"
    fi

else
    info "mokutil is not installed; current Secure Boot state cannot be checked automatically"
fi

echo

#
# 11. EFI executable signature
#

echo "== 11. EFI executable signature =="

if [[ -n "$EFI_IMAGE" ]]; then

    if [[ ! -r "$EFI_IMAGE" ]]; then

        fail "Cannot read EFI image: $EFI_IMAGE"

    elif command -v sbverify >/dev/null 2>&1; then

        sb_output="$(sbverify --list "$EFI_IMAGE" 2>&1 || true)"

        if echo "$sb_output" |
            grep -qiE 'signature|certificate|issuer|subject'; then

            ok "$EFI_IMAGE contains PE/Authenticode signature information"
            echo
            echo "$sb_output"
            echo

        else
            fail "No PE/Authenticode signature was detected in $EFI_IMAGE"
        fi

    else

        warn "sbverify is not installed; cannot inspect the EFI image signature"
        info "Install the Gentoo package that provides sbsigntools/sbverify."

    fi

else

    info "No EFI executable was supplied."
    info "After building and signing the EFI kernel, run:"
    echo
    echo "    $0 --config $CONFIG --efi /boot/EFI/Gentoo/gentoo.efi"
    echo

fi

#
# Summary
#

echo "================================================================"
echo " Summary"
echo "================================================================"

if (( errors == 0 )); then
    printf '%sNo fatal kernel configuration problems were detected.%s\n' \
        "$GREEN" "$RESET"
else
    printf '%s%d fatal problem(s) detected.%s\n' \
        "$RED" "$errors" "$RESET"
fi

if (( warnings > 0 )); then
    printf '%s%d warning(s) require manual review.%s\n' \
        "$YELLOW" "$warnings" "$RESET"
fi

echo
echo "IMPORTANT:"
echo
echo "A successful result does NOT prove that Secure Boot will accept"
echo "the final EFI executable."
echo
echo "For a successful Secure Boot chain:"
echo
echo "  1. The final EFI executable must be signed."
echo "  2. The signing certificate must be trusted by the firmware,"
echo "     shim/MOK, or another valid Secure Boot trust path."
echo "  3. The UEFI boot entry must point to the correct EFI executable."
echo "  4. The kernel must receive the correct root= parameter."
echo "  5. NVMe and ext4 support must be built into the kernel (=y),"
echo "     because there is no initramfs available to load them."
echo

if (( errors > 0 )); then
    exit 1
fi

exit 0
