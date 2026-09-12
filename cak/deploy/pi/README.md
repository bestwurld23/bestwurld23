# Raspberry Pi deployment

A Pi runs the node as a plain systemd service. No container, no orchestrator — the fewer
moving parts between a steward and a working device, the better.

Hardware, power and solar sizing are in `docs/hardware.md`.

## Install

```bash
git clone <this repo> cak && cd cak
sudo ./deploy/pi/install.sh
```

The script installs into `/opt/cak`, `/etc/cak` and `/var/lib/cak`, creates an
unprivileged `cak` user, copies the fixture pack, generates a steward password, and starts
the service.

**Write the steward password down when it prints.** It is stored only as a PBKDF2 hash and
cannot be recovered — only replaced with `cak-node hash-password`.

To install with your own pack instead of the fixture:

```bash
sudo ./deploy/pi/install.sh --pack /path/to/packs/us-il-chicago
```

## After install

```bash
systemctl status cak-node
journalctl -u cak-node -f

/opt/cak/venv/bin/cak-node health --config /etc/cak/node.toml
/opt/cak/venv/bin/cak-node verify --config /etc/cak/node.toml
/opt/cak/venv/bin/cak-node ask --config /etc/cak/node.toml "when is early voting?"
```

## Opening it to the room

By default the node listens on localhost, which is right for a device a steward operates
on a touchscreen. To let residents reach it from their own phones on the local network,
edit `/etc/cak/node.toml`:

```toml
bind = "0.0.0.0"
```

The node **refuses to start** bound off-localhost without `steward_password_hash` set. The
installer sets one, so this works — but change it from the generated value if more than
one person will have it.

Then `sudo systemctl restart cak-node`.

### A memorable name

```bash
sudo apt-get install -y avahi-daemon
sudo hostnamectl set-hostname civic
```

The node is then at `http://civic.local:8080` for anyone on the same network.

### Wi-Fi access point mode

So phones can join `CAK-<place>` with no upstream internet at all (PRD §6.2, "Could").
Full AP configuration is Phase 2; the short version on Raspberry Pi OS Bookworm is
NetworkManager in AP mode:

```bash
sudo nmcli device wifi hotspot ifname wlan0 ssid CAK-Englewood password <8+ chars>
sudo nmcli connection modify Hotspot connection.autoconnect yes
```

Residents join the network and open `http://civic.local:8080`. Nothing is forwarded to the
internet, and nothing needs to be.

## Updating official files

The steward flow is in `docs/steward-runbook.md`. From a terminal:

```bash
sudo -u cak /opt/cak/venv/bin/cak-node load-folder \
  --config /etc/cak/node.toml /media/cak-usb \
  --source "Board website, 2026-09-12"
```

`cak-usb-load.service` does the same thing as a one-shot unit, for a steward who cannot
use a terminal. It is installed but **not enabled**, on purpose: with it enabled, anyone
who can plug in a USB stick can change what the node says. Enable it only where the device
is not physically reachable by the public, and read `docs/threat-model.md` T1 first.

```bash
sudo systemctl start cak-usb-load        # run it once, by hand
```

## Adding a local model (Phase 1)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
```

Then in `/etc/cak/node.toml`:

```toml
generator = "ollama"
model = "llama3.2:3b"
```

Restart, and check `cak-node health` shows `"model_loaded": true`. If Ollama is not
running, the node keeps answering — the citation lock and the extractive path are what
make the answers safe, not the model.

Note the licence constraint in `docs/hardware.md` before baking weights into an SD image.

## Backups

Three things matter, and they are all small:

```bash
sudo tar czf cak-backup-$(date +%F).tar.gz \
  /var/lib/cak/pack \
  /var/lib/cak/state/changelog.jsonl \
  /etc/cak/steward.ed25519
```

- The **pack** is the content.
- The **change log** is the history, and it is the thing you cannot reconstruct.
- The **signing key** is what lets this node keep appending to that history.

`cak.db` holds counters and the report queue; back it up if you have unsynced field
reports, but nothing in it is irreplaceable. Keep a copy of the log off the device — an
auditor's earlier export is the ground truth if the device is ever tampered with.

## Uninstall

```bash
sudo systemctl disable --now cak-node.service
sudo rm -f /etc/systemd/system/cak-node.service /etc/systemd/system/cak-usb-load.service
sudo systemctl daemon-reload
sudo rm -rf /opt/cak /usr/share/cak
# Keep /var/lib/cak and /etc/cak if you want the log and key. Removing them
# destroys the audit history for this node.
```
