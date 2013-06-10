#!/bin/sh

# Arguments are:
#   1. kernel version
#   2. path to the bzImage file
#   3. path to the System.map file
#   4. default install path
#   5. location of kernel source
#   6. path to the config file

function mount_boot() {
    # Shamelessly copied from Gentoos /usr/portage/eclass/mount-boot.eclass
    if [[ -n ${DONT_MOUNT_BOOT} ]] ; then
        return
    fi

    # note that /dev/BOOT is in the Gentoo default /etc/fstab file
    local fstabstate=$(awk '!/^#|^[[:blank:]]+#|^\/dev\/BOOT/ {print $2}' /etc/fstab | egrep "^/boot$" )
    local procstate=$(awk '$2 ~ /^\/boot$/ {print $2}' /proc/mounts)
    local proc_ro=$(awk '{ print $2 " ," $4 "," }' /proc/mounts | sed -n '/\/boot .*,ro,/p')

    if [ -n "${fstabstate}" ] && [ -n "${procstate}" ]; then
        if [ -n "${proc_ro}" ]; then
            mount -o remount,rw /boot
            if [ "$?" -ne 0 ]; then
                echo "Unable to remount /boot in rw mode. Please do it manually!"
                exit 1
            fi
            touch /boot/.e.remount
        fi
    elif [ -n "${fstabstate}" ] && [ -z "${procstate}" ]; then
        mount /boot -o rw
        if [ ! "$?" -eq 0 ]; then
            echo "Please mount your /boot partition manually!"
            exit 1
        fi
        touch /boot/.e.mount
    fi
}

set -e

kver="$1"
source_bzimage="$2"
install_directory="$4"
source_config="$6"
grub_config="${install_directory}/grub/grub.conf"

target_bzimage="${install_directory}/bzImage-$kver"
target_config="${install_directory}/config-$kver"

mount_boot

if [[ -e "${target_bzimage}" ]] || [[ -e "${target_config}" ]]; then
  buildno=1
  while [[ -e "${target_bzimage}-build${buildno}" ]] || [[ -e "${target_config}-build${buildno}" ]]; do
    buildno=$((${buildno}+1))
  done
  target_bzimage="${target_bzimage}-build${buildno}"
  target_config="${target_config}-build${buildno}"
fi

cp "$source_config" "$target_config"
cp "$source_bzimage" "$target_bzimage"
# use '0,\#regex#' to replace only the first occurance
sed -i "0,\#^kernel [^ ]*#s##kernel ${target_bzimage}#" "${grub_config}"

# Rebuild third-party kernel modules on Gentoo
if [[ -e "/etc/gentoo-release" ]]; then
  packages_with_kmodules="$(find /var/db/pkg -name CONTENTS -exec grep -H "/lib/modules/" "{}" \; | cut -d "/" -f 5-6 | sort -u | sed s_^_=_)"
  if [[ -n "${packages_with_kmodules}" ]]; then
    emerge --keep-going -1v --nodeps ${packages_with_kmodules}
  fi
fi
