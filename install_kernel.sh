#!/bin/bash
set -euo pipefail

# Terminal Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

TOTAL_STEPS=7

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

if [ -f "${ARCHIVE}.sha256" ]; then
    if confirm "Verify SHA256 checksum for ${ARCHIVE}?"; then
        (cd "$(dirname "$ARCHIVE")" && sha256sum -c "$(basename "${ARCHIVE}.sha256")")
    fi
fi

KERNEL_VER=$(tar -tzf "$ARCHIVE" | sed -n 's#^[^/]*/boot/vmlinuz-\(.*\)$#\1#p' | head -n1 || true)
[ -n "$KERNEL_VER" ] || die "Could not determine kernel version from archive."

STAGING_DIR=$(tar -tzf "$ARCHIVE" | head -n1 | cut -d/ -f1 || true)
[ -n "$STAGING_DIR" ] || die "Could not determine staging directory."

print_header "Kernel Installation Script (Void Linux Target)"
echo "  Archive : ${ARCHIVE}"
echo "  Kernel  : ${KERNEL_VER}"
echo "  Staging : ${STAGING_DIR}"

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
    $SUDO cp "${STAGING_DIR}/boot/vmlinuz-${KERNEL_VER}" /boot/
    $SUDO cp "${STAGING_DIR}/boot/System.map-${KERNEL_VER}" /boot/
    $SUDO cp "${STAGING_DIR}/boot/config-${KERNEL_VER}" /boot/
    echo -e "   ${GREEN}[OK] Files copied to /boot.${NC}"
fi

# Step 3: Copy modules
print_step 3 $TOTAL_STEPS "Install kernel modules"
if [ -d "/lib/modules/${KERNEL_VER}" ]; then
    echo -e "   ${YELLOW}Warning: /lib/modules/${KERNEL_VER} already exists and will be overwritten!${NC}"
    if confirm "Move existing /lib/modules/${KERNEL_VER} to .bak?"; then
        $SUDO mv "/lib/modules/${KERNEL_VER}" "/lib/modules/${KERNEL_VER}.bak.$(date +%Y%m%d-%H%M%S)"
    fi
fi

if confirm "Copy modules to /lib/modules/${KERNEL_VER}?" "true"; then
    $SUDO mkdir -p /lib/modules
    $SUDO cp -r "${STAGING_DIR}/lib/modules/${KERNEL_VER}" /lib/modules/
    need_cmd depmod
    $SUDO depmod -a "${KERNEL_VER}"
    echo -e "   ${GREEN}[OK] Modules installed and depmod run.${NC}"
fi

# Step 4: Initramfs
print_step 4 $TOTAL_STEPS "Generate initramfs"
if command -v dracut >/dev/null 2>&1; then
    if confirm "Generate initramfs using dracut? (Command: dracut --force --kver ${KERNEL_VER} /boot/initramfs-${KERNEL_VER}.img)"; then
        $SUDO dracut --force --kver "${KERNEL_VER}" "/boot/initramfs-${KERNEL_VER}.img"
        echo -e "   ${GREEN}[OK] Initramfs generated.${NC}"
    fi
else
    echo -e "   ${YELLOW}dracut not found. Skipping initramfs generation.${NC}"
fi

# Step 5: GRUB
print_step 5 $TOTAL_STEPS "Update GRUB bootloader"
if command -v update-grub >/dev/null 2>&1; then
    GRUB_CMD="update-grub"
elif command -v grub-mkconfig >/dev/null 2>&1; then
    GRUB_CMD="grub-mkconfig -o /boot/grub/grub.cfg"
else
    GRUB_CMD=""
fi

if [ -n "$GRUB_CMD" ]; then
    if confirm "Update GRUB configuration? (Command: $GRUB_CMD)"; then
        $SUDO $GRUB_CMD
        echo -e "   ${GREEN}[OK] GRUB updated.${NC}"
    fi
else
    echo -e "   ${YELLOW}No GRUB update command found. Update bootloader manually.${NC}"
fi

# Step 6: Cleanup
print_step 6 $TOTAL_STEPS "Clean up temporary files"
if confirm "Remove staging directory and original archive?"; then
    rm -rf "${STAGING_DIR}"
    rm -f "${ARCHIVE}" "${ARCHIVE}.sha256"
    echo -e "   ${GREEN}[OK] Cleaned up.${NC}"
fi

# Step 7: Reboot
print_step 7 $TOTAL_STEPS "Reboot system"
if confirm "Reboot the system now to boot into the new kernel?"; then
    sync
    echo -e "   ${GREEN}[OK] Rebooting...${NC}"
    $SUDO reboot
else
    echo ""
    echo -e "   ${GREEN}[OK] Installation complete!${NC}"
    echo -e "   Run ${CYAN}${SUDO:+sudo }reboot${NC} when you are ready."
    echo ""
fi