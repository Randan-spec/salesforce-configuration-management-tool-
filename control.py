#!/usr/bin/env python3
"""sends the repo to remote hosts and run cmtool.

Inventory can be JSON or YAML. Each host entry should include:
  name,host,user,ssh_port,manifest(path under repo)

This  streams a tarball over ssh into a temp dir on the remote(ubuntu servers),
 then runs `bootstrap.sh ( installs dependencies)` and `cmtool.py(installs the manifest)`, then cleans up.

"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Try to import PyYAML to support YAML inventories/manifests.
try:
    import yaml
except ImportError:
    yaml = None


def load_inventory(path):
    """Loads inventory file; JSON or YAML supported.
    """
    txt = Path(path).read_text()
    try:
        return json.loads(txt)
    except Exception:
        if yaml:
            return yaml.safe_load(txt)
        raise


def stream_and_run(host_entry, key=None):
    # `host_entry` expected keys: `host` (IP/name), optional `user`, `ssh_port`, `manifest`.
    # `key` is an optional path to a private key file passed to `ssh -i`.
    
    host = host_entry["host"]
    user = host_entry.get("user", "root")
    port = host_entry.get("ssh_port", 22)
    manifest = host_entry.get("manifest")

    # Remote command: mktemp, untar repo, 
    # runs bootstrap+cmtool (for manifest), cleanup; `{check}` forwards --check
    remote_cmd = (
        "set -euo pipefail; "
        "REMOTE_TMP=$(mktemp -d /tmp/cmtool.XXXXXX) && "
        "tar -xzf - --no-same-owner -C $REMOTE_TMP && "
        "chmod +x $REMOTE_TMP/bootstrap.sh $REMOTE_TMP/cmtool.py || true && "
        "sudo $REMOTE_TMP/bootstrap.sh && sudo $REMOTE_TMP/cmtool.py $REMOTE_TMP/" + manifest + "{check} && "
        "rm -rf $REMOTE_TMP"
    )

    # Build the ssh command. If `key` is provided it passes `-i <key>`.
    # Omitting `-i` lets the user's ssh config / agent choose a key.
    ssh_cmd = ["ssh", "-p", str(port)]
    if key:
        ssh_cmd += ["-i", key]
    # Attach the user@host and the formatted remote command.
    ssh_cmd += [f"{user}@{host}", remote_cmd.format(check=(" --check" if host_entry.get("check") else ""))]

    print("Streaming repo to", host)
    # Stream a gzipped tar of the repo root into the remote ssh command.
    # will create a `tar -czf -` subprocess and pipe its stdout into ssh stdin.
    # This avoids creating intermediate archives on the control host.
    tar_proc = subprocess.Popen(["tar", "-czf", "-", "-C", os.getcwd(), "."], stdout=subprocess.PIPE)
    p = subprocess.Popen(ssh_cmd, stdin=tar_proc.stdout)
    tar_proc.stdout.close()
    ret = p.wait()
    tar_proc.wait()
    if ret != 0:
        raise subprocess.CalledProcessError(ret, ssh_cmd)


def main():
    # Parse CLI arguments and prepare the list of hosts to deploy to.
    # - --inventory (required): path to JSON/YAML inventory containing `hosts` list
    # - --host (optional): restrict deployment to a single inventory entry by name
    # - --key (optional): SSH private key to pass to `ssh -i`
    # - --check (optional): forward dry-run to remote `cmtool.py`
    p = argparse.ArgumentParser()
    p.add_argument("--inventory", required=True)
    p.add_argument("--host", help="deploy only this inventory name")
    p.add_argument("--key", help="ssh private key")
    p.add_argument("--check", action="store_true", help="dry-run: forward --check to remote cmtool")
    args = p.parse_args()

    # Load inventory (JSON first, YAML fallback). Inventory is expected to be
    # a mapping with a `hosts` key containing a list of host entries.
    inv = load_inventory(args.inventory)
    hosts = inv.get("hosts", [])
    # If a single host name is requested, filter the inventory down to it.
    if args.host:
        hosts = [h for h in hosts if h.get("name") == args.host]
    if not hosts:
        print("No hosts to deploy")
        sys.exit(1)

    # Iterate the (possibly filtered) host list and perform the tar-over-SSH
    # deploy for each host. If `--check` is passed,it tag the host entry so
    # `stream_and_run` will include --check when invoking remote cmtool.py.
    for h in hosts:
        print("==>", h.get("name"), h.get("host"))
        if args.check:
            h["check"] = True
        stream_and_run(h, key=args.key)


if __name__ == "__main__":
    main()
