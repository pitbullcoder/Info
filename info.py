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

# MeshCore transmission ceiling. Messages are built to fit under this.
MAX_MESSAGE_CHARS = 130

# Separator between channel entries packed into the same message.
ENTRY_SEPARATOR = " | "

# Pause between messages so a multi-message broadcast does not hammer the
# repeater. Channel sends are flood with no ACK, so this is pacing, not retry.
DEFAULT_INTER_MESSAGE_DELAY_SECONDS = 6.0


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
        if "name" not in entry:
            raise ValueError("every channel entry needs a 'name'")

    cfg.setdefault("header", "Marion mesh channels:")
    cfg.setdefault("inter_message_delay_seconds", DEFAULT_INTER_MESSAGE_DELAY_SECONDS)
    return cfg


def format_entry(entry):
    """Render one channel as 'name - description', or just 'name' if bare."""
    name = entry["name"].strip()
    desc = (entry.get("desc") or "").strip()
    if not desc:
        return name
    return "%s - %s" % (name, desc)


def _truncate_entry(text, limit):
    """Shorten an oversized entry to fit, marking it with an ellipsis."""
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1].rstrip() + "\u2026"


def build_messages(header, channels, limit=MAX_MESSAGE_CHARS):
    """Pack channel entries into self-contained messages of at most `limit` chars.

    The header opens the first message. Each message is independently readable,
    so a dropped packet costs one group of channels rather than garbling the
    whole list.
    """
    header = (header or "").strip()
    messages = []
    current = header

    for entry in channels:
        text = format_entry(entry)

        if len(text) > limit:
            LOG.warning("entry too long for one message, truncating: %s", text)
            text = _truncate_entry(text, limit)

        if not current:
            candidate = text
        else:
            candidate = current + ENTRY_SEPARATOR + text

        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            messages.append(current)
        current = text

    if current:
        messages.append(current)

    return messages


async def _default_sender(cfg, messages):
    """Connect to the companion over TCP and push each message to the channel.

    Isolated here so the transport can be swapped without touching the packer.
    """
    from meshcore import MeshCore

    mc = await MeshCore.create_tcp(cfg["host"], cfg["port"])
    try:
        for index, message in enumerate(messages):
            if index:
                await asyncio.sleep(cfg["inter_message_delay_seconds"])
            LOG.info("sending (%d chars): %s", len(message), message)
            await mc.commands.send_chan_msg(cfg["channel_index"], message)
    finally:
        await mc.disconnect()


async def broadcast(cfg, sender=None):
    """Build the channel list and hand it to the sender."""
    messages = build_messages(cfg["header"], cfg["channels"])
    if not messages:
        LOG.warning("nothing to broadcast")
        return []

    LOG.info("broadcasting %d message(s)", len(messages))
    send = sender or _default_sender
    await send(cfg, messages)
    return messages


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Broadcast the Marion mesh channel list.")
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG_PATH, help="path to config.json")
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="print the messages that would be sent, without transmitting",
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
        for message in build_messages(cfg["header"], cfg["channels"]):
            print("[%3d] %s" % (len(message), message))
        return 0

    try:
        asyncio.run(broadcast(cfg))
    except Exception as exc:  # noqa: BLE001 - timer unit should log and exit nonzero
        LOG.error("broadcast failed: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
