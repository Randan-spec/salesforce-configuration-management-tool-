#!/usr/bin/env bash
set -euo pipefail

# Purpose:
# - Install a usable Python runtime and tools (pip, python3-apt) so the
#   `cmtool.py` script and PyYAML can run on the target.


if [ "$EUID" -ne 0 ]; then
  echo "Please run as root: sudo ./bootstrap.sh"
  exit 1
fi

# Update package metadata and install Python 3 and pip. We include
# `python3-apt` and `python3-distutils` because some environments need them
# for packaging-related operations. 
apt-get update
apt-get -y install python3 python3-apt python3-distutils python3-pip 

# Installs PyYAML via pip so YAML manifests can be parsed by `cmtool.py`.

python3 -m pip install pyyaml

echo "Bootstrap complete. You can now run: sudo ./cmtool.py <manifest.json>"
