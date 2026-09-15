#!/bin/bash
set -euo pipefail

# Terminal Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

TOTAL_STEPS=5

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
[ -f Makefile ] || die "Run this from the kernel source root."

need_cmd make
need_cmd tar
need_cmd sha256sum

KERNEL_VER=$(make -s kernelrelease) || die "Failed to get kernelrelease."
[ -n "$KERNEL_VER" ] || die "Empty kernelrelease."

KERNEL_IMAGE=$(make -s image_name) || die "Failed to get image_name."
[ -f "$KERNEL_IMAGE" ] || die "Kernel image not found: $KERNEL_IMAGE. Build it first."

STAGING_DIR="kernel_staging_${KERNEL_VER}"
ARCHIVE_NAME="${ARCHIVE_NAME:-kernel_pkg_${KERNEL_VER}.tar.gz}"

print_header "Kernel Packing Script (Debian Builder)"
echo "  Kernel Version : ${KERNEL_VER}"
echo "  Kernel Image   : ${KERNEL_IMAGE}"
echo "  Staging Dir    : ${STAGING_DIR}"
echo "  Final Archive  : ${ARCHIVE_NAME}"

# Step 1: Modules
print_step 1 $TOTAL_STEPS "Install modules to staging directory"
if confirm "Run 'make modules_install INSTALL_MOD_PATH=${STAGING_DIR}'?" "true"; then
    make modules_install INSTALL_MOD_PATH="${STAGING_DIR}"

    # Remove build/source symlinks that point to build-host paths.
    rm -f "${STAGING_DIR}/lib/modules/${KERNEL_VER}/build" \
          "${STAGING_DIR}/lib/modules/${KERNEL_VER}/source"

    echo -e "   ${GREEN}[OK] Modules installed to staging.${NC}"
fi

# Step 2: Boot files
print_step 2 $TOTAL_STEPS "Collect kernel image and configs"
if confirm "Copy kernel image, System.map, and .config to ${STAGING_DIR}/boot?" "true"; then
    mkdir -p "${STAGING_DIR}/boot"
    cp "${KERNEL_IMAGE}" "${STAGING_DIR}/boot/vmlinuz-${KERNEL_VER}"
    cp System.map "${STAGING_DIR}/boot/System.map-${KERNEL_VER}"
    cp .config "${STAGING_DIR}/boot/config-${KERNEL_VER}"
    echo -e "   ${GREEN}[OK] Files collected.${NC}"
fi

# Step 3: Archive
print_step 3 $TOTAL_STEPS "Create compressed archive"
if confirm "Create tar.gz archive '${ARCHIVE_NAME}'?" "true"; then
    tar -czf "${ARCHIVE_NAME}" "${STAGING_DIR}"
    sha256sum "${ARCHIVE_NAME}" > "${ARCHIVE_NAME}.sha256"
    ARCHIVE_SIZE=$(du -h "${ARCHIVE_NAME}" | cut -f1)
    echo -e "   ${GREEN}[OK] Archive created (Size: ${ARCHIVE_SIZE}).${NC}"
    echo -e "   ${GREEN}[OK] Checksum written to ${ARCHIVE_NAME}.sha256.${NC}"
fi

# Step 4: Cleanup
print_step 4 $TOTAL_STEPS "Clean up staging directory"
if confirm "Remove staging directory '${STAGING_DIR}' to free space?"; then
    rm -rf "${STAGING_DIR}"
    echo -e "   ${GREEN}[OK] Staging directory removed.${NC}"
fi

# Step 5: Summary
print_step 5 $TOTAL_STEPS "Summary and Next Steps"
echo -e "   ${GREEN}[OK] Packing complete!${NC}"
echo ""
echo "   To transfer to your Void Linux target machine, run:"
echo -e "   ${CYAN}scp ${ARCHIVE_NAME} ${ARCHIVE_NAME}.sha256 user@<TARGET_IP>:~/${NC}"
echo ""
echo "   Then, on the Void Linux machine, run the install_kernel.sh script."
echo ""