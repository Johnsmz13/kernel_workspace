#!/bin/bash
set -euo pipefail

# Terminal Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

TOTAL_STEPS=10

print_header() {
    echo ""
    echo "========================================================"
    echo "  ${BOLD}$1${NC}"
    echo "========================================================"
}

print_step() {
    local step_num=$1
    local total=$2
    local desc=$3
    echo ""
    echo "--------------------------------------------------------"
    echo "  Step ${step_num}/${total}: ${desc}"
    echo "--------------------------------------------------------"
}

confirm() {
    local desc="$1"
    local critical="${2:-false}"

    echo -e "\n${CYAN}>> ${desc}${NC}"

    if [ "$critical" = "true" ]; then
        read -r -p "   [y]es / [q]uit: " choice
    else
        read -r -p "   [y]es / [s]kip / [q]uit: " choice
    fi

    case "$choice" in
        [Yy]*) return 0 ;;
        [Ss]*)
            if [ "$critical" = "true" ]; then
                echo -e "   ${RED}Cannot skip a critical step. Exiting.${NC}"
                exit 1
            fi
            echo -e "   ${YELLOW}Skipped.${NC}"
            return 1
            ;;
        [Qq]*)
            echo -e "   ${RED}Exiting script.${NC}"
            exit 0
            ;;
        *)
            if [ "$critical" = "true" ]; then
                echo -e "   ${RED}Invalid input for critical step. Exiting.${NC}"
                exit 1
            fi
            echo -e "   ${YELLOW}Skipped (default).${NC}"
            return 1
            ;;
    esac
}

die() {
    echo -e "${RED}Error: $*${NC}" >&2
    exit 1
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

# --- Main Execution ---
SUDO="sudo"
if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
fi

ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ]; then
    ARCHIVE=$(ls -1t kernel_pkg_*.tar.gz 2>/dev/null | head -n1 || true)
fi

[ -n "$ARCHIVE" ] || die "No 'kernel_pkg_*.tar.gz' found. Pass archive as argument."
[ -f "$ARCHIVE" ] || die "Archive not found: $ARCHIVE"

need_cmd tar
need_cmd sha256sum
need_cmd depmod
need_cmd install
need_cmd ukify
need_cmd sbctl
need_cmd sed
need_cmd cut
need_cmd head
need_cmd tr

UKIFY=$(command -v ukify)
SBCTL=$(command -v sbctl)
DEPMOD=$(command -v depmod)

[ -d /efi ] || die "/efi does not exist. Mount your ESP at /efi first."
[ -d /efi/EFI/Linux ] || $SUDO mkdir -p /efi/EFI/Linux
[ -f /etc/os-release ] || die "/etc/os-release not found; ukify needs it for --os-release."

if [ -f "${ARCHIVE}.sha256" ]; then
    if confirm "Verify SHA256 checksum for ${ARCHIVE}?"; then
        (cd "$(dirname "$ARCHIVE")" && sha256sum -c "$(basename "${ARCHIVE}.sha256")")
    fi
fi

KERNEL_VER=$(tar -tzf "$ARCHIVE" | sed -n 's#^[^/]*/boot/vmlinuz-\(.*\)$#\1#p' | head -n1 || true)
[ -n "$KERNEL_VER" ] || die "Could not determine kernel version from archive."

STAGING_DIR=$(tar -tzf "$ARCHIVE" | head -n1 | cut -d/ -f1 || true)
[ -n "$STAGING_DIR" ] || die "Could not determine staging directory."

print_header "Kernel Installation Script (Gentoo UKI / EFISTUB Target)"
echo "  Archive   : ${ARCHIVE}"
echo "  Kernel    : ${KERNEL_VER}"
echo "  Staging   : ${STAGING_DIR}"
echo "  Final UKI : /efi/EFI/Linux/gentoo.efi"

# Step 1: Extract
print_step 1 $TOTAL_STEPS "Extract archive"
if confirm "Extract '${ARCHIVE}' to current directory?" "true"; then
    tar -xzf "$ARCHIVE"
    echo -e "   ${GREEN}[OK] Extracted successfully.${NC}"
fi

# Step 2: Copy to /boot
print_step 2 $TOTAL_STEPS "Install kernel files to /boot"
BACKUP_DIR="/boot/backup-${KERNEL_VER}-$(date +%Y%m%d-%H%M%S)"

for f in vmlinuz-${KERNEL_VER} System.map-${KERNEL_VER} config-${KERNEL_VER}; do
    if [ -f "/boot/$f" ]; then
        echo -e "   ${YELLOW}Warning: /boot/$f already exists and will be overwritten!${NC}"
        if confirm "Back up /boot/$f to ${BACKUP_DIR}?"; then
            $SUDO mkdir -p "$BACKUP_DIR"
            $SUDO cp -a "/boot/$f" "$BACKUP_DIR/"
        fi
    fi
done

if confirm "Copy vmlinuz, System.map, and config to /boot?" "true"; then
    $SUDO install -m 0644 "${STAGING_DIR}/boot/vmlinuz-${KERNEL_VER}" "/boot/vmlinuz-${KERNEL_VER}"
    $SUDO install -m 0644 "${STAGING_DIR}/boot/System.map-${KERNEL_VER}" "/boot/System.map-${KERNEL_VER}"
    $SUDO install -m 0644 "${STAGING_DIR}/boot/config-${KERNEL_VER}" "/boot/config-${KERNEL_VER}"
    echo -e "   ${GREEN}[OK] Files copied to /boot.${NC}"
fi

# Step 3: Copy modules
print_step 3 $TOTAL_STEPS "Install kernel modules"
if [ -d "/lib/modules/${KERNEL_VER}" ]; then
    echo -e "   ${YELLOW}Warning: /lib/modules/${KERNEL_VER} already exists and will be moved to .bak.${NC}"
    if confirm "Move existing /lib/modules/${KERNEL_VER} to .bak?" "true"; then
        $SUDO mv "/lib/modules/${KERNEL_VER}" "/lib/modules/${KERNEL_VER}.bak.$(date +%Y%m%d-%H%M%S)"
    else
        die "Refusing to overwrite existing modules without a backup."
    fi
fi

if confirm "Copy modules to /lib/modules/${KERNEL_VER}?" "true"; then
    $SUDO mkdir -p /lib/modules
    $SUDO cp -a "${STAGING_DIR}/lib/modules/${KERNEL_VER}" /lib/modules/
    $SUDO "$DEPMOD" -a "${KERNEL_VER}"
    echo -e "   ${GREEN}[OK] Modules installed and depmod run.${NC}"
fi

# Step 4: Read cmdline
print_step 4 $TOTAL_STEPS "Read kernel command line from /proc/cmdline"
CMDLINE=$(cat /proc/cmdline 2>/dev/null || true)
CMDLINE=$(printf '%s' "$CMDLINE" | tr -d '\n')
if [ -z "$CMDLINE" ]; then
    die "ERROR: /proc/cmdline is empty or unreadable. Refusing to build a UKI without a kernel command line."
fi
echo -e "   ${GREEN}[OK] Using current cmdline:${NC}"
echo "       $CMDLINE"

# Step 5: Build unsigned UKI
print_step 5 $TOTAL_STEPS "Build unsigned UKI with ukify (no initramfs)"
UNSIGNED_UKI="/boot/gentoo-unsigned-${KERNEL_VER}.efi"
if confirm "Build ${UNSIGNED_UKI} using /boot/vmlinuz-${KERNEL_VER}?" "true"; then
    $SUDO "$UKIFY" build \
        --linux="/boot/vmlinuz-${KERNEL_VER}" \
        --cmdline="$CMDLINE" \
        --uname="$KERNEL_VER" \
        --os-release=@/etc/os-release \
        --output="$UNSIGNED_UKI"
    echo -e "   ${GREEN}[OK] Unsigned UKI built: ${UNSIGNED_UKI}${NC}"
fi

# Step 6: Deploy UKI
print_step 6 $TOTAL_STEPS "Back up old UKI and deploy new UKI"
FINAL_UKI="/efi/EFI/Linux/gentoo.efi"
if [ -f "$FINAL_UKI" ]; then
    UKI_BACKUP="${FINAL_UKI}.bak-$(date +%Y%m%d-%H%M%S)"
    echo -e "   ${YELLOW}Backing up existing ${FINAL_UKI} to ${UKI_BACKUP}${NC}"
    $SUDO cp -a "$FINAL_UKI" "$UKI_BACKUP"
fi
if confirm "Install ${UNSIGNED_UKI} as ${FINAL_UKI}?" "true"; then
    $SUDO cp "$UNSIGNED_UKI" "$FINAL_UKI"
    echo -e "   ${GREEN}[OK] UKI copied to ${FINAL_UKI}.${NC}"
fi

# Step 7: Sign UKI
print_step 7 $TOTAL_STEPS "Sign UKI with sbctl"
if confirm "Sign ${FINAL_UKI} with sbctl and save to sbctl database?" "true"; then
    $SUDO "$SBCTL" sign -s "$FINAL_UKI"
    $SUDO "$SBCTL" verify "$FINAL_UKI"
    echo -e "   ${GREEN}[OK] UKI signed and verified.${NC}"
fi

# Step 8: Verify UKI contents
print_step 8 $TOTAL_STEPS "Verify UKI contents"
echo -e "   ${CYAN}UKI inspect output (if available):${NC}"
$SUDO "$UKIFY" inspect "$FINAL_UKI" 2>/dev/null || true
echo ""
echo -e "   ${YELLOW}Expected: no .initrd section.${NC}"

# Step 9: Cleanup
print_step 9 $TOTAL_STEPS "Clean up temporary files"
if confirm "Remove staging directory and original archive?"; then
    rm -rf "${STAGING_DIR}"
    rm -f "${ARCHIVE}" "${ARCHIVE}.sha256"
    echo -e "   ${GREEN}[OK] Cleaned up.${NC}"
fi

# Step 10: Reboot / hints
print_step 10 $TOTAL_STEPS "Next steps and reboot"
echo -e "   ${GREEN}[OK] Installation complete!${NC}"
echo ""
echo -e "   ${YELLOW}This script did NOT modify UEFI boot entries.${NC}"
echo "   Check that your firmware boot entry Boot0000 points to:"
echo "       \\EFI\\Linux\\gentoo.efi"
echo ""
echo "   Suggested checks:"
echo -e "       ${CYAN}sudo efibootmgr -v${NC}"
echo -e "       ${CYAN}sudo sbctl status${NC}"
echo -e "       ${CYAN}sudo sbctl verify /efi/EFI/Linux/gentoo.efi${NC}"
echo ""
if confirm "Reboot the system now to boot into the new kernel?"; then
    sync
    echo -e "   ${GREEN}[OK] Rebooting...${NC}"
    $SUDO reboot
else
    echo ""
    echo -e "   ${GREEN}Run ${CYAN}${SUDO:+sudo }reboot${NC} when you are ready."
    echo ""
fi