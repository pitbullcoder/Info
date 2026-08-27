# Info

MeshCore Station G3 Information Broadcast to Share Active Channels and General Info.

Posts the list of active Marion mesh channels to the **public** channel every
Friday at 8pm Eastern. Runs on the Station G3 Pi against the Marion Info Bot
companion (hash `0x63`, TCP 5054).

## How it works

The channel list lives in `config.json`. On each run the bot posts a single
message: the header line, then one channel name per line.

The whole thing is built to fit inside MeshCore's 130-character limit. If the
list ever grows past that, trailing channels are dropped and a warning is logged
rather than sending something the radio will mangle.

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

The character count is printed above the message so you can see the headroom.

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
| `header` | First line of the message. Set to `""` to omit. |
| `channels` | List of channel names. A leading `#` is added if missing. |

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
