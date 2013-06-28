#!/usr/bin/env python3

import os, sys
import os.path
import shutil
import urllib.request 
import subprocess
import re
import http.client as httplib

if "DEVNULL" not in subprocess.__dict__:
    subprocess.DEVNULL = open(os.devnull, "w")

install_directory = "/usr/src"
current_kernel_symlink = "linux"
kernel_org_mirror = "https://www.kernel.org/pub/linux/kernel"
alternate_kconfig = ".ketchup-config" # must not be ".config"
makeopts = ["-j4"]
# Specify the command that should be executed to install the kernel.
# If install_directory is None, "make install" will be executed
# The command will be executed with the following options:
#   1. kernel version
#   2. path to the bzImage file
#   3. path to the System.map file
#   4. default install path
#   5. location of kernel source
#   6. path to the config file
#install_command = ["echo", "--"]
install_command = [os.path.abspath(os.path.dirname(sys.argv[0])+"/installkernel.sh")]


class KernelInfo:
    def __init__(self, major, minor, template, previous=None):
        self.major = major
        self.minor = minor
        self.template = template
        self.previous = previous
    
    @property
    def directoryname(self):
        return self.template.format(str(self))
    
class Kernel3xInfo(KernelInfo):
    def __init__(self, *args, **kwargs):
        KernelInfo.__init__(self, *args, **kwargs)
        self.is_3x = True
    
    @classmethod
    def from_directory_name(cls, directoryname):
        matches = re.match(r"^(.*?)3\.(\d+)(?:\.(\d+))?(.*)/?$", directoryname).groups()
        #matches = re.match(r"^(.*?)3\.(\d+)-rc(\d+)(.*)/?$", directoryname).groups()
        #matches = re.match(r"^(.*?)2\.6\.(\d+)(?:\.(\d+))?(.*)/?$", directoryname).groups()
        
        major = int(matches[1])
        if matches[2] is not None:
            minor = int(matches[2])
        else:
            minor = 0
        template = "{}{{}}{}".format(matches[0], matches[-1])
        self = cls(major, minor, template)
        if directoryname != self.directoryname:
            raise Exception("Unknown parse error")
        return self
        
    def __str__(self):
        if self.minor == 0:
            return "3.{}".format(self.major)
        else:
            return "3.{}.{}".format(self.major, self.minor)
        
    @property
    def next_minor(self):
        return Kernel3xInfo(self.major, self.minor+1, self.template, previous=self)
    
    @property
    def incr_url(self):
        if self.previous is None:
            return None
        
        if self.previous.major == self.major and self.previous.minor+1 == self.minor and self.previous.minor != 0:
            patch = "/v3.x/incr/patch-3.{}.{}-{}.xz".format(self.major, self.previous.minor, self.minor)
        elif self.previous.major == self.major and self.previous.minor == 0:
            patch = "/v3.x/patch-3.{}.{}.xz".format(self.major, self.minor)
        elif self.previous.major+1 == self.major and self.previous.minor == 0 and self.minor == 0:
            patch = "/v3.x/patch-3.{}.xz".format(self.major)
        else:
            return None
        
        return kernel_org_mirror + patch
    
    @property
    def abs_url(self):
        if self.minor == 0:
            tarfile = "/v3.x/linux-3.{}.tar.xz".format(self.major)
        else:
            tarfile = "/v3.x/linux-3.{}.{}.tar.xz".format(self.major, self.minor)
        return kernel_org_mirror + tarfile
        
    
    @property
    def is_available(self):
        if self.incr_url != None:
            return (head_request(self.incr_url) < 300)
        else:
            return (head_request(self.abs_url) < 300)

def head_request(url):
    groups = re.match("^(.*?)://(.*?)(/.*)?$", url).groups()
    if groups[0] == "http":
        conn = httplib.HTTPConnection(groups[1])
    elif groups[0] == "https":
        conn = httplib.HTTPSConnection(groups[1])
    else:
        raise Exception("Protocol '{}' is not supported for kernel_org_mirror".format(groups[0]))
    conn.request("HEAD", groups[2] if groups[2] != None else "/")
    res = conn.getresponse()
    return res.status

def download_decompress_patch(url):
    data = urllib.request.urlopen(url).read()
    xzcat = subprocess.Popen(["xzcat"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    patch = subprocess.Popen(["patch", "-p1", "--dry-run"], stdin=xzcat.stdout, stdout=subprocess.DEVNULL)
    xzcat.stdin.write(data)
    xzcat.stdin.close()

    if xzcat.wait() + patch.wait() != 0:
        raise Exception("dry-run decompression or patching failed.")
    
    print("  [1/2] Dry run complete, patching ...")
    xzcat = subprocess.Popen(["xzcat"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    patch = subprocess.Popen(["patch", "-p1"], stdin=xzcat.stdout, stdout=subprocess.DEVNULL)
    xzcat.stdin.write(data)
    xzcat.stdin.close()

    if xzcat.wait() + patch.wait() != 0:
        raise Exception("Decompressing or patching failed, even though dry-run succeeded.")
    print("  [2/2] done.")


def main():
    os.chdir(install_directory)
    hasbeenupdated = False
    
    while True:
        directoryname = os.readlink(current_kernel_symlink)
        if len(sys.argv) > 1:
            directoryname = sys.argv[1]
        current_kernel = Kernel3xInfo.from_directory_name(directoryname)
        next_kernel = current_kernel.next_minor
        if not next_kernel.is_available:
            break
        print("Updating from {} to {}.".format(current_kernel, next_kernel))
        os.chdir(directoryname)
        download_decompress_patch(next_kernel.incr_url)
        os.chdir('..')
        os.rename(current_kernel.directoryname, next_kernel.directoryname)
        os.remove(current_kernel_symlink)
        os.symlink(next_kernel.directoryname, current_kernel_symlink)
        hasbeenupdated = True
    
    if hasbeenupdated:
        os.chdir(current_kernel.directoryname)
        shutil.copy2(".config", alternate_kconfig)
        print("Compiling linux-{}".format(current_kernel))
        print("  [1/4] Configuration")
        
        # make olddefconfig was introduced in linux 3.7
        if current_kernel.is_3x and current_kernel.major >= 7:
            oldconfig_command = "olddefconfig"
        else:
            oldconfig_command = "oldnoconfig"
        olddefconfig = subprocess.Popen(["make", "KCONFIG_CONFIG="+alternate_kconfig, oldconfig_command] + makeopts, stdout=subprocess.DEVNULL)
        if olddefconfig.wait() != 0:
            raise Exception("make {} failed".format(oldconfig_command))
        
        print("  [2/4] Compiling")
        make = subprocess.Popen(["make", "KCONFIG_CONFIG="+alternate_kconfig, "all"] + makeopts)
        if make.wait() != 0:
            raise Exception("make failed")

        print("  [3/4] Install modules")
        makemodulesinstall = subprocess.Popen(["make", "KCONFIG_CONFIG="+alternate_kconfig, "modules_install"] + makeopts)
        if makemodulesinstall.wait() != 0:
            raise Exception("make modules_install failed")
        
        print("  [4/4] Install kernel")
        if install_command is None:
            makeinstall = subprocess.Popen(["make", "KCONFIG_CONFIG="+alternate_kconfig, "install"] + makeopts)
            if makeinstall.wait() != 0:
                raise Exception("make install failed")
        else:
            makeinstall = subprocess.Popen(install_command + [str(current_kernel), "arch/x86/boot/bzImage", "arch/x86/boot/System.map", "/boot", install_directory+"/"+current_kernel.directoryname, alternate_kconfig])
            if makeinstall.wait() != 0:
                raise Exception("installation with command '{}' failed".format(" ".join(install_command)))
        
        has_config_differences = False
        for command in [["python2", "./scripts/diffconfig", ".config", alternate_kconfig],
                         ["python2.7", "./scripts/diffconfig", ".config", alternate_kconfig],
                         ["./scripts/diffconfig", ".config", alternate_kconfig]]:
            diffconfig = subprocess.Popen(command, stdout=subprocess.PIPE)
            for line in diffconfig.stdout:
                line = line.decode("utf-8")
                if has_config_differences is False:
                    print("\nThe following config options were applied automatically, use 'make oldconfig' to fix that:")
                    has_config_differences = True
                print("  " + line)
            if diffconfig.wait() == 0:
                break
        else:
            print("You might have to run 'make oldconfig', I can't check for that. sry")
    else:
        print("No operation")

if __name__ == '__main__':
    sys.exit(main())
