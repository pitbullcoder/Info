"""Tests for the Marion Info Bot message builder and broadcast loop."""

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

    async def __call__(self, cfg, message):
        self.calls.append((cfg, message))


class NormalizeChannelTest(unittest.TestCase):
    def test_hash_is_preserved(self):
        self.assertEqual(info.normalize_channel("#news"), "#news")

    def test_hash_is_added_when_missing(self):
        self.assertEqual(info.normalize_channel("news"), "#news")

    def test_whitespace_is_stripped(self):
        self.assertEqual(info.normalize_channel("  #news  "), "#news")

    def test_duplicate_hashes_are_collapsed(self):
        self.assertEqual(info.normalize_channel("##news"), "#news")


class BuildMessageTest(unittest.TestCase):
    def test_expected_shape(self):
        message = info.build_message(
            "Marion mesh channels:", ["#weather", "#news", "#gas"]
        )
        self.assertEqual(
            message,
            "Marion mesh channels:\n#weather\n#news\n#gas",
        )

    def test_lines_are_header_then_names(self):
        message = info.build_message("Chans:", ["#a", "#b"])
        self.assertEqual(message.splitlines(), ["Chans:", "#a", "#b"])

    def test_header_is_optional(self):
        message = info.build_message("", ["#a", "#b"])
        self.assertEqual(message.splitlines(), ["#a", "#b"])

    def test_none_header_is_treated_as_absent(self):
        self.assertEqual(info.build_message(None, ["#a"]), "#a")

    def test_empty_everything_yields_empty_string(self):
        self.assertEqual(info.build_message("", []), "")

    def test_names_are_normalized(self):
        message = info.build_message("Chans:", ["weather", " #news ", "##gas"])
        self.assertEqual(message.splitlines(), ["Chans:", "#weather", "#news", "#gas"])

    def test_result_stays_within_the_limit(self):
        channels = ["#channel%02d" % i for i in range(40)]
        message = info.build_message("Marion mesh channels:", channels)
        self.assertLessEqual(len(message), info.MAX_MESSAGE_CHARS)

    def test_overflow_drops_from_the_end_and_keeps_the_header(self):
        channels = ["#channel%02d" % i for i in range(40)]
        message = info.build_message("Chans:", channels)
        lines = message.splitlines()
        self.assertEqual(lines[0], "Chans:")
        self.assertEqual(lines[1], "#channel00")
        self.assertLess(len(lines) - 1, len(channels))

    def test_a_list_landing_exactly_on_the_limit_is_kept_whole(self):
        # Header plus one name plus the joining newline lands on the limit.
        header = "H"
        name_len = info.MAX_MESSAGE_CHARS - len(header) - 1
        channels = ["#" + "x" * (name_len - 1)]
        message = info.build_message(header, channels)
        self.assertEqual(len(message), info.MAX_MESSAGE_CHARS)
        self.assertEqual(len(message.splitlines()), 2)

    def test_one_char_over_the_limit_drops_the_name(self):
        header = "H"
        name_len = info.MAX_MESSAGE_CHARS - len(header)
        channels = ["#" + "x" * (name_len - 1)]
        message = info.build_message(header, channels)
        self.assertEqual(message, header)

    def test_oversized_header_alone_is_truncated(self):
        message = info.build_message("H" * 400, [], limit=20)
        self.assertEqual(len(message), 20)


class LoadConfigTest(unittest.TestCase):
    def _write(self, payload):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(payload, handle)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_header_default_is_applied(self):
        path = self._write(
            {"host": "127.0.0.1", "port": 5054, "channel_index": 0, "channels": ["#a"]}
        )
        self.assertEqual(info.load_config(path)["header"], "Marion mesh channels:")

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

    def test_non_string_channel_entry_is_rejected(self):
        path = self._write(
            {
                "host": "127.0.0.1",
                "port": 5054,
                "channel_index": 0,
                "channels": [{"name": "#a"}],
            }
        )
        with self.assertRaises(ValueError):
            info.load_config(path)

    def test_blank_channel_entry_is_rejected(self):
        path = self._write(
            {"host": "127.0.0.1", "port": 5054, "channel_index": 0, "channels": ["  "]}
        )
        with self.assertRaises(ValueError):
            info.load_config(path)


class BroadcastTest(unittest.TestCase):
    def _cfg(self, channels, header="Chans:"):
        return {
            "host": "127.0.0.1",
            "port": 5054,
            "channel_index": 0,
            "header": header,
            "channels": channels,
        }

    def test_sender_receives_one_message(self):
        sender = RecordingSender()
        message = asyncio.run(info.broadcast(self._cfg(["#a", "#b"]), sender=sender))
        self.assertEqual(len(sender.calls), 1)
        self.assertEqual(sender.calls[0][1], message)

    def test_sender_is_not_called_when_there_is_nothing_to_say(self):
        sender = RecordingSender()
        message = asyncio.run(info.broadcast(self._cfg([], header=""), sender=sender))
        self.assertEqual(message, "")
        self.assertEqual(sender.calls, [])


class MainTest(unittest.TestCase):
    def test_dry_run_does_not_need_a_radio(self):
        payload = {
            "host": "127.0.0.1",
            "port": 5054,
            "channel_index": 0,
            "channels": ["#a"],
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
