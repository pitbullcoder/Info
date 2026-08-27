#!/usr/bin/env python3
"""Marion Info Bot.

Broadcasts the list of active Marion mesh channels to the public channel on a
weekly schedule. Driven by systemd timer; see info.timer.
"""

import argparse
import asyncio
import json
import logging
import os
import sys

LOG = logging.getLogger("info")

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# MeshCore transmission ceiling. The broadcast is built to fit inside one of these.
MAX_MESSAGE_CHARS = 130


def load_config(path):
    """Read and validate the JSON config file."""
    with open(path, "r", encoding="utf-8") as handle:
        cfg = json.load(handle)

    for key in ("host", "port", "channel_index", "channels"):
        if key not in cfg:
            raise ValueError("config missing required key: %s" % key)

    if not isinstance(cfg["channels"], list) or not cfg["channels"]:
        raise ValueError("config 'channels' must be a non-empty list")

    for entry in cfg["channels"]:
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError("every channel entry must be a non-empty string")

    cfg.setdefault("header", "Marion mesh channels:")
    return cfg


def normalize_channel(name):
    """Trim whitespace and ensure a single leading '#'."""
    return "#" + name.strip().lstrip("#")


def build_message(header, channels, limit=MAX_MESSAGE_CHARS):
    """Render the header and channel names as one newline-separated message.

    If the full list would exceed `limit`, trailing channels are dropped and a
    warning is logged — a short message that fits beats a long one the radio
    silently mangles.
    """
    header = (header or "").strip()
    names = [normalize_channel(name) for name in channels]

    lines = ([header] if header else []) + names
    dropped = []

    while lines and len("\n".join(lines)) > limit:
        if len(lines) == 1:
            # Nothing left but an oversized header; truncate it outright.
            lines[0] = lines[0][:limit]
            break
        dropped.append(lines.pop())

    if dropped:
        LOG.warning(
            "message exceeded %d chars; dropped %d channel(s): %s",
            limit,
            len(dropped),
            ", ".join(reversed(dropped)),
        )

    return "\n".join(lines)


async def _default_sender(cfg, message):
    """Connect to the companion over TCP and post the message to the channel.

    Isolated here so the transport can be swapped without touching the builder.
    """
    from meshcore import MeshCore

    mc = await MeshCore.create_tcp(cfg["host"], cfg["port"])
    try:
        LOG.info("sending (%d chars): %s", len(message), message.replace("\n", " / "))
        await mc.commands.send_chan_msg(cfg["channel_index"], message)
    finally:
        await mc.disconnect()


async def broadcast(cfg, sender=None):
    """Build the channel list and hand it to the sender."""
    message = build_message(cfg["header"], cfg["channels"])
    if not message:
        LOG.warning("nothing to broadcast")
        return ""

    send = sender or _default_sender
    await send(cfg, message)
    return message


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Broadcast the Marion mesh channel list.")
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG_PATH, help="path to config.json")
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="print the message that would be sent, without transmitting",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        cfg = load_config(args.config)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        LOG.error("could not load config from %s: %s", args.config, exc)
        return 1

    if args.dry_run:
        message = build_message(cfg["header"], cfg["channels"])
        print("--- %d of %d chars ---" % (len(message), MAX_MESSAGE_CHARS))
        print(message)
        return 0

    try:
        asyncio.run(broadcast(cfg))
    except Exception as exc:  # noqa: BLE001 - timer unit should log and exit nonzero
        LOG.error("broadcast failed: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
