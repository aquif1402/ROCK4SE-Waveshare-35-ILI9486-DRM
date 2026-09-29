# Security notes

## `driver_gui.py`

`driver_gui.py` is an administrative utility. It can modify kernel-driver source, compile modules, modify Device Tree files, restart services, and reboot the system.

The public repository version does not contain the password from the original live-system backup. It binds to `127.0.0.1` by default.

For remote access, prefer an SSH tunnel, for example:

```bash
ssh -L 5000:127.0.0.1:5000 radxa@<ROCK4SE_IP>
```

Then open `http://127.0.0.1:5000` locally.

If you intentionally expose the GUI on a LAN, add authentication and firewall restrictions appropriate to your environment. Do not grant `NOPASSWD: ALL` to the web-service account merely to make the GUI work.
