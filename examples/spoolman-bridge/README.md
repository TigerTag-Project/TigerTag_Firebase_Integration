# Spoolman bridge example

Self-contained Python script that syncs your TigerTag inventory into a
Spoolman instance.

```bash
pip install -r requirements.txt
export TIGERTAG_EMAIL=you@example.com
export TIGERTAG_PASSWORD=yourpassword
export SPOOLMAN_URL=http://192.168.1.10:7912
export DRY_RUN=1                    # dry-run mode
python3 sync.py
```

Source code: see [docs/clients/spoolman-bridge.md](../../docs/clients/spoolman-bridge.md)
for the full annotated implementation.

For production use, run via cron (`*/5 * * * *`) or as a systemd service.
A Docker compose example for running the bridge alongside Spoolman itself
is included in the doc.
