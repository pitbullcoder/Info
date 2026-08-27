"""Tests for the Marion Info Bot message packer and broadcast loop."""

import asyncio
import json
import os
import tempfile
import unittest

import info


class RecordingSender:
    """Stand-in for the radio transport; records what it was asked to send."""

    def __init__(self):
        self.calls = []

    async def __call__(self, cfg, messages):
        self.calls.append((cfg, list(messages)))


def ch(name, desc=None):
    entry = {"name": name}
    if desc is not None:
        entry["desc"] = desc
    return entry


class FormatEntryTest(unittest.TestCase):
    def test_name_and_description(self):
        self.assertEqual(info.format_entry(ch("#news", "headlines")), "#news - headlines")

    def test_bare_name_when_description_missing(self):
        self.assertEqual(info.format_entry(ch("#news")), "#news")

    def test_bare_name_when_description_empty(self):
        self.assertEqual(info.format_entry(ch("#news", "   ")), "#news")

    def test_whitespace_is_stripped(self):
        self.assertEqual(info.format_entry(ch("  #news  ", "  headlines  ")), "#news - headlines")


class BuildMessagesTest(unittest.TestCase):
    def test_empty_channel_list_yields_header_only(self):
        self.assertEqual(info.build_messages("Header:", []), ["Header:"])

    def test_empty_header_and_channels_yields_nothing(self):
        self.assertEqual(info.build_messages("", []), [])

    def test_short_list_fits_in_one_message(self):
        messages = info.build_messages("Chans:", [ch("#a", "one"), ch("#b", "two")])
        self.assertEqual(messages, ["Chans: | #a - one | #b - two"])

    def test_every_message_respects_the_limit(self):
        channels = [ch("#chan%02d" % i, "description number %d" % i) for i in range(12)]
        messages = info.build_messages("Marion mesh channels:", channels)
        self.assertGreater(len(messages), 1)
        for message in messages:
            self.assertLessEqual(len(message), info.MAX_MESSAGE_CHARS)

    def test_no_entry_is_lost_across_messages(self):
        channels = [ch("#chan%02d" % i, "description number %d" % i) for i in range(12)]
        messages = info.build_messages("Marion mesh channels:", channels)
        joined = " ".join(messages)
        for entry in channels:
            self.assertIn(entry["name"], joined)

    def test_entry_landing_exactly_on_the_limit_is_kept_whole(self):
        # Header plus separator plus entry lands on exactly the limit.
        header = "H"
        pad = info.MAX_MESSAGE_CHARS - len(header) - len(info.ENTRY_SEPARATOR)
        entry = ch("#" + "x" * (pad - 1))
        messages = info.build_messages(header, [entry], limit=info.MAX_MESSAGE_CHARS)
        self.assertEqual(len(messages), 1)
        self.assertEqual(len(messages[0]), info.MAX_MESSAGE_CHARS)

    def test_one_char_over_the_limit_splits(self):
        header = "H"
        pad = info.MAX_MESSAGE_CHARS - len(header) - len(info.ENTRY_SEPARATOR)
        entry = ch("#" + "x" * pad)
        messages = info.build_messages(header, [entry], limit=info.MAX_MESSAGE_CHARS)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0], header)

    def test_oversized_entry_is_truncated_not_dropped(self):
        entry = ch("#long", "d" * 400)
        messages = info.build_messages("", [entry], limit=50)
        self.assertEqual(len(messages), 1)
        self.assertEqual(len(messages[0]), 50)
        self.assertTrue(messages[0].endswith("\u2026"))

    def test_oversized_entry_does_not_disturb_its_neighbours(self):
        channels = [ch("#a", "one"), ch("#long", "d" * 400), ch("#b", "two")]
        messages = info.build_messages("", channels, limit=50)
        joined = " ".join(messages)
        self.assertIn("#a - one", joined)
        self.assertIn("#b - two", joined)
        for message in messages:
            self.assertLessEqual(len(message), 50)

    def test_header_is_optional(self):
        messages = info.build_messages(None, [ch("#a", "one")])
        self.assertEqual(messages, ["#a - one"])


class LoadConfigTest(unittest.TestCase):
    def _write(self, payload):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(payload, handle)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_defaults_are_applied(self):
        path = self._write(
            {"host": "127.0.0.1", "port": 5054, "channel_index": 0, "channels": [ch("#a", "one")]}
        )
        cfg = info.load_config(path)
        self.assertEqual(cfg["header"], "Marion mesh channels:")
        self.assertEqual(
            cfg["inter_message_delay_seconds"], info.DEFAULT_INTER_MESSAGE_DELAY_SECONDS
        )

    def test_missing_required_key_is_rejected(self):
        path = self._write({"host": "127.0.0.1", "port": 5054, "channel_index": 0})
        with self.assertRaises(ValueError):
            info.load_config(path)

    def test_empty_channel_list_is_rejected(self):
        path = self._write(
            {"host": "127.0.0.1", "port": 5054, "channel_index": 0, "channels": []}
        )
        with self.assertRaises(ValueError):
            info.load_config(path)

    def test_channel_without_name_is_rejected(self):
        path = self._write(
            {
                "host": "127.0.0.1",
                "port": 5054,
                "channel_index": 0,
                "channels": [{"desc": "nameless"}],
            }
        )
        with self.assertRaises(ValueError):
            info.load_config(path)


class BroadcastTest(unittest.TestCase):
    def _cfg(self, channels):
        return {
            "host": "127.0.0.1",
            "port": 5054,
            "channel_index": 0,
            "header": "Chans:",
            "inter_message_delay_seconds": 0,
            "channels": channels,
        }

    def test_sender_receives_the_packed_messages(self):
        sender = RecordingSender()
        cfg = self._cfg([ch("#a", "one"), ch("#b", "two")])
        messages = asyncio.run(info.broadcast(cfg, sender=sender))
        self.assertEqual(len(sender.calls), 1)
        self.assertEqual(sender.calls[0][1], messages)

    def test_sender_is_not_called_when_there_is_nothing_to_say(self):
        sender = RecordingSender()
        cfg = self._cfg([])
        cfg["header"] = ""
        messages = asyncio.run(info.broadcast(cfg, sender=sender))
        self.assertEqual(messages, [])
        self.assertEqual(sender.calls, [])


class MainTest(unittest.TestCase):
    def test_dry_run_does_not_need_a_radio(self):
        payload = {
            "host": "127.0.0.1",
            "port": 5054,
            "channel_index": 0,
            "channels": [ch("#a", "one")],
        }
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(payload, handle)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        self.assertEqual(info.main(["--config", handle.name, "--dry-run"]), 0)

    def test_missing_config_exits_nonzero(self):
        self.assertEqual(info.main(["--config", "/nonexistent/config.json", "--dry-run"]), 1)


if __name__ == "__main__":
    unittest.main()
