#!/usr/bin/env python3
"""cmtool.py - idempotent config applier.

Supported resource types: package, file, service.
Accepts JSON or YAML manifests. File, `source` paths are resolved against
the manifest's dir.

Where useful, comments note alternative approaches (e.g., using a library
like python-apt, systemd DBus APIs, or an existing CM tool such as Ansible).
"""

import json  #parse manifest JSON
import os  #OS utilities (check euid, path operations)
import stat  #file mode constants for permission checks
import subprocess  # run system commands (apt, systemctl)
import sys  # CLI args and exit handling
from pathlib import Path  # path and file helpers

# optional PyYAML: enable reading YAML manifests when available and fallback to JSON
try:
    import yaml  
except Exception:
    yaml = None


# Toggle for dry-run mode; set by CLI `--check`.
DRY_RUN = False


def _run(cmd, capture=False, check=False):
    """
    - If `DRY_RUN` is enabled it only print the command (unless `capture` is True)
    - Using subprocess.run keeps the script small; 
    """
    if DRY_RUN and not capture:
        print("DRY-RUN: ", " ".join(cmd))
        class R: returncode = 0; stdout = b""; stderr = b""
        return R()
    return subprocess.run(cmd, stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None,
                          check=check)


def load_manifest(path):
    """Load manifest JSON or YAML from `path`.

    The code first attempts JSON, then falls back to YAML (if PyYAML is
    available).
    """
    txt = Path(path).read_text()
    try:
        return json.loads(txt)
    except Exception:
        if yaml:
            return yaml.safe_load(txt)
        raise


def pkg_installed(name):
    """Return True if package `name` is installed (Debian/Ubuntu).

    This uses `dpkg-query` for simplicity. 
    """
    p = _run(["dpkg-query", "-W", "-f=${Status}", name], capture=True)
    return p.returncode == 0 and b"install ok installed" in p.stdout


def ensure_package(r):
    """Expected keys: `name`, optional `state` (present/absent).
    Returns True if a change was made (or would be made in dry-run).
    """
    name = r["name"]
    state = r.get("state", "present")
    if state == "present":
        if not pkg_installed(name):
            print("Installing", name) if not DRY_RUN else print("DRY-RUN: would install", name)
            if not DRY_RUN:
                _run(["apt-get", "-y", "install", name], check=True)
            return True
    else:
        if pkg_installed(name):
            print("Removing", name) if not DRY_RUN else print("DRY-RUN: would remove", name)
            if not DRY_RUN:
                _run(["apt-get", "-y", "remove", name], check=True)
            return True
    return False


def read_source(src, repo_root, manifest_dir):
    """Resolve a `source` path to a real file and return its contents.
    - This allows manifests to refer to files bundled in the directory.
    """
    p = Path(src)
    if not p.is_absolute():
        if repo_root:
            p = Path(repo_root) / p
        else:
            p = Path(manifest_dir).parent / p
    return p.read_text()


def ensure_file(r, repo_root, manifest_dir):
    """
    Returns True if a change was made (or would be made in dry-run).
    """
    path = Path(r["path"])
    content = r.get("content", "")
    if r.get("source"):
        try:
            content = read_source(r["source"], repo_root, manifest_dir)
        except Exception as e:
            print("Warning: source read failed:", e)

    changed = False
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    # Compare current contents to desired; write/backup only on difference.
    if not path.exists() or path.read_bytes() != content.encode():
        if r.get("backup") and path.exists():
            # Simple backup naming; add timestamp if needed to avoid clobber.
            bak = path.with_suffix(path.suffix + ".old") if path.suffix else Path(str(path)+".old")
            if bak.exists():
                import time
                bak = Path(str(bak) + "." + str(int(time.time())))
            if DRY_RUN:
                print("DRY-RUN: would backup", path, "->", bak)
            else:
                path.replace(bak)
                print("Backed up to", bak)
            changed = True
        if DRY_RUN:
            print("DRY-RUN: would write file", path)
        else:
            path.write_bytes(content.encode())
        changed = True

    # Owner/group change:, skip if account/group doesn't exist.
    if r.get("owner") or r.get("group"):
        try:
            import pwd, grp, os as _os
            st = path.stat()
            uid = st.st_uid
            gid = st.st_gid
            if r.get("owner"):
                try:
                    uid = pwd.getpwnam(r["owner"]).pw_uid
                except KeyError:
                    print("Owner not found, skipping chown")
            if r.get("group"):
                try:
                    gid = grp.getgrnam(r["group"]).gr_gid
                except KeyError:
                    print("Group not found, skipping chown")
            if st.st_uid != uid or st.st_gid != gid:
                if DRY_RUN:
                    print("DRY-RUN: would chown", path, f"{uid}:{gid}")
                else:
                    _os.chown(path, uid, gid)
                changed = True
        except PermissionError:
            print("Permission denied changing owner/group; run as root")

    # Mode (permission) changes.
    if r.get("mode"):
        desired = int(r["mode"], 8) if isinstance(r["mode"], str) else int(r["mode"]) 
        cur = stat.S_IMODE(path.stat().st_mode)
        if cur != desired:
            if DRY_RUN:
                print("DRY-RUN: would chmod", path, oct(desired))
            else:
                path.chmod(desired)
            changed = True

    return changed


def ensure_service(r):
    """Ensure a service resource 
    Expected keys: `name`, `ensure` (started/stopped), `enable` (bool).
    Returns True if a change was made (or would be made in dry-run).
    """
    name = r["name"]
    want = r.get("ensure", "started")
    p = _run(["systemctl", "is-active", name], capture=True)
    active = p.returncode == 0 and b"active" in p.stdout
    changed = False
    if want == "started" and not active:
        print("Starting", name) if not DRY_RUN else print("DRY-RUN: would start", name)
        if not DRY_RUN:
            _run(["systemctl", "start", name], check=True)
        changed = True
    if want == "stopped" and active:
        print("Stopping", name) if not DRY_RUN else print("DRY-RUN: would stop", name)
        if not DRY_RUN:
            _run(["systemctl", "stop", name], check=True)
        changed = True
    if r.get("enable"):
        p2 = _run(["systemctl", "is-enabled", name], capture=True)
        if not (p2.returncode == 0 and b"enabled" in p2.stdout):
            print("Enabling", name) if not DRY_RUN else print("DRY-RUN: would enable", name)
            if not DRY_RUN:
                _run(["systemctl", "enable", name], check=True)
            changed = True
    return changed


def main():
    # Basic runtime and CLI handling:
    # - require root because it perform package/service/file operations
    # - accept a single manifest path and an optional `--check` flag for dry-run mode
    if os.geteuid() != 0:
        print("Run as root (sudo) on target")
        sys.exit(1)
    if len(sys.argv) < 2:
        print("Usage: cmtool.py <manifest.{json|yaml}>")
        sys.exit(1)
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("--check", action="store_true", help="dry-run (no changes)")
    args = parser.parse_args()
    manifest = args.manifest
    global DRY_RUN
    DRY_RUN = bool(args.check)

    # Resolves manifest paths. `manifest_dir` is the directory containing the
    # manifest; `repo_root` is to be its parent (used to resolve
    # `source:` entries that reference files inside the repository tree).
    manifest_dir = str(Path(manifest).parent)
    repo_root = str(Path(manifest).parent.parent)

    # Load manifest (JSON first, YAML fallback) and extract resources list.
    data = load_manifest(manifest)
    resources = data.get("resources", [])

    # `notify` will collects services that should be restarted after all changes.
    notify = set()

    # If any package resource will install software, run `apt-get update`
    # first (unless in dry-run). This mirrors common CM behavior.
    if any(r.get("type") == "package" and r.get("state","present") == "present" for r in resources):
        print("apt-get update...") if not DRY_RUN else print("DRY-RUN: would apt-get update")
        if not DRY_RUN:
            _run(["apt-get", "update"], check=True)

    # Iterate resources and apply supported types. Each ensure_* function
    # returns True when it made (or would make) a change.
    for r in resources:
        t = r.get("type")
        changed = False
        if t == "package":
            changed = ensure_package(r)
        elif t == "file":
            changed = ensure_file(r, repo_root, manifest_dir)
        elif t == "service":
            changed = ensure_service(r)
        else:
            print("Unknown resource", t)

        # If the resource changed, add any `notify: ["service:name"]` items
        # to the `notify` set so services are restarted once at the end.
        if changed:
            for n in r.get("notify", []):
                if n.startswith("service:"):
                    notify.add(n.split(":",1)[1])

    # Restart all notified services a single time after applying changes.
    for s in notify:
        print("Restarting", s)
        _run(["systemctl", "restart", s], check=True)

    print("Done")


if __name__ == "__main__":
    main()
