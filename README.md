cmtool — minimal configuration tool

Overview:
- `cmtool.py`: apply JSON/YAML manifests on Ubuntu targets (requires root).
- `control.py`: stream repo to a remote host and run `bootstrap.sh` + `cmtool.py` there.
- `bootstrap.sh`: installs Python and PyYAML on Ubuntu targets.


Quick commands

From project root, with the virtualenv active:
```bash
python3 -m pip install pyyaml
```

Deploy from the control host (dry-run first):
```bash
./control.py --inventory inventory/hosts.yaml --key /path/to/sshkey --check
./control.py --inventory inventory/hosts.yaml --key /path/to/sshkey
```

On a target (manual example):
```bash
sudo ./bootstrap.sh
sudo ./cmtool.py manifests/site.yaml
```

Inventory
- Use `inventory/hosts.yaml`; each host needs `name`, `host`, `user`, and `manifest`.

Notes
- `file` resources support `content` or `source` (repo file), owner/group/mode, and optional `backup`.
- `package` resources use apt(Only); `service` resources use systemctl. `notify` triggers service restarts.
- `--check` for (DRY-RUN).

Files
- [cmtool.py](cmtool.py)
- [control.py](control.py)
- [bootstrap.sh](bootstrap.sh)
- [manifests/site.yaml](manifests/site.yaml)
- [inventory/hosts.yaml](inventory/hosts.yaml)

