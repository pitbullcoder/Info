# Info

MeshCore Station G3 Information Broadcast to Share Active Channels and General Info.

Posts the list of active Marion mesh channels to the **public** channel every
Friday at 8pm Eastern. Runs on the Station G3 Pi against the Marion Info Bot
companion (hash `0x63`, TCP 5054).

## How it works

The channel list lives in `config.json`. On each run the bot renders every entry
as `#name - description`, greedily packs those entries into messages of at most
130 characters, and sends them to the configured channel.

Each message is self-contained rather than being one long string split at
arbitrary points, so a dropped packet costs one group of channels instead of
garbling the list. Channel sends are flood with no ACK, so there is no retry
logic — just a fixed delay between messages to pace the repeater.

## Install

```bash
sudo git clone https://github.com/pitbullcoder/Info.git /opt/info
cd /opt/info
sudo pip3 install -r requirements.txt --break-system-packages
sudo cp config.example.json config.json
sudo nano config.json
```

Check what it will say before putting it on the air:

```bash
python3 /opt/info/info.py --config /opt/info/config.json --dry-run
```

Each line is printed with its character count so you can see the packing.

Then install the timer:

```bash
sudo cp info.service info.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now info.timer
systemctl list-timers info.timer
```

To send one immediately without waiting for Friday:

```bash
sudo systemctl start info.service
journalctl -u info.service -n 50
```

## Configuration

| Key | Meaning |
| --- | --- |
| `host` / `port` | Companion TCP endpoint — `127.0.0.1:5054` |
| `channel_index` | Channel to post to. `0` is public. |
| `header` | Opens the first message. Set to `""` to omit. |
| `inter_message_delay_seconds` | Pause between messages |
| `channels` | List of `{"name": ..., "desc": ...}`. `desc` is optional. |

Adding a channel is a `config.json` edit — no code change, no restart needed,
since the timer reads the file fresh on each run.

## Tests

```bash
python3 -m unittest info_test -v
python3 -m pyflakes info.py info_test.py
```

## Notes

- The `OnCalendar` line pins the schedule to `America/New_York`, so DST is
  handled without depending on the Pi's system timezone. That syntax needs
  systemd 252 or newer; on older systemd, drop the timezone suffix and set the
  system timezone with `sudo timedatectl set-timezone America/New_York`.
- `Persistent=true` means a Friday the Pi was powered down gets picked up on the
  next boot rather than silently skipped.
- The companion needs a `path_hash_mode` row in the repeater's `companion_prefs`
  table to use 2-byte path hashes:

  ```bash
  sudo sqlite3 /var/lib/openhop_repeater/repeater.db \
    "INSERT INTO companion_prefs (companion_hash, prefs_json)
     VALUES ('0x63', '{\"path_hash_mode\":1}');"
  ```

## License

GPL-3.0
