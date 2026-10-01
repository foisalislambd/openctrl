import unittest

from openagent.agent import (
    RunStats,
    _as_bool,
    _budget_hit,
    _desktop_locked,
    _footer,
    _remember_cursor,
    _repair_tool_calls,
    _trim,
    _usage_cost,
    combine_notes,
)
from openagent.files import resolve_send_path, save_upload
from openagent.memory import Memory
from openagent.schedule import Schedule
from openagent.desktop import image_to_screen
from openagent.format_tg import markdown_to_html, one_line
from openagent.hotkeys import blocks_secure_attention, to_sendkeys
from openagent.safety import danger_reason


class FormatTests(unittest.TestCase):
    def test_bold_and_code_are_escaped(self):
        html = markdown_to_html("Use **notepad** and `<script>`")
        self.assertIn("<b>notepad</b>", html)
        self.assertIn("<code>&lt;script&gt;</code>", html)
        self.assertNotIn("<script>", html)

    def test_fence_becomes_pre(self):
        html = markdown_to_html("```\nline <1>\n```")
        self.assertIn("<pre>line &lt;1&gt;</pre>", html)

    def test_quote_and_link(self):
        html = markdown_to_html("> hello\nSee [docs](https://example.com/a?b=1)")
        self.assertIn("<blockquote>hello</blockquote>", html)
        self.assertIn('href="https://example.com/a?b=1"', html)

    def test_one_line_collapses(self):
        self.assertEqual(one_line("a\n\nb"), "a b")


class HotkeyTests(unittest.TestCase):
    def test_chord(self):
        self.assertEqual(to_sendkeys("ctrl+shift+p"), "{Ctrl}{Shift}p")
        self.assertEqual(to_sendkeys("alt+f4"), "{Alt}{F4}")
        self.assertEqual(to_sendkeys("enter"), "{Enter}")
        self.assertEqual(to_sendkeys("ctrl+a, delete"), "{Ctrl}a{Delete}")

    def test_words_are_rejected(self):
        with self.assertRaises(ValueError):
            to_sendkeys("hello there")

    def test_secure_attention_is_blocked(self):
        self.assertTrue(blocks_secure_attention(to_sendkeys("ctrl+alt+delete")))
        self.assertFalse(blocks_secure_attention(to_sendkeys("ctrl+s")))


class ScreenTests(unittest.TestCase):
    def test_image_pixels_map_onto_the_screen(self):
        capture = {"ox": 10, "oy": 20, "rw": 1920, "rh": 1080, "iw": 1600, "ih": 900}
        self.assertEqual(image_to_screen(0, 0, capture), (10, 20))
        self.assertEqual(image_to_screen(800, 450, capture), (970, 560))
        self.assertEqual(image_to_screen(9999, -5, capture), (1929, 20))
        self.assertEqual(image_to_screen(1599, 899, capture), (1929, 1099))


class HistoryTests(unittest.TestCase):
    def test_clear_flag_is_only_true_for_real_true(self):
        self.assertFalse(_as_bool("false"))
        self.assertTrue(_as_bool("true"))
        self.assertTrue(_as_bool(True))

    def test_missing_tool_result_is_repaired(self):
        messages = [
            {"role": "system", "content": "s"},
            {"role": "assistant", "tool_calls": [{"id": "a"}, {"id": "b"}]},
            {"role": "tool", "tool_call_id": "a", "content": "ok"},
            {"role": "user", "content": "next"},
        ]
        _repair_tool_calls(messages)
        self.assertEqual(messages[3]["tool_call_id"], "b")
        self.assertEqual(messages[4]["role"], "user")

    def test_trim_does_not_start_on_a_tool_result(self):
        messages = [{"role": "system", "content": "s"}]
        messages.append({"role": "user", "content": "u"})
        messages.append({"role": "assistant", "tool_calls": [{"id": "a"}]})
        messages.append({"role": "tool", "tool_call_id": "a", "content": "ok"})
        messages.extend({"role": "user", "content": str(i)} for i in range(10))
        _trim(messages, keep=6)
        self.assertEqual(messages[0]["role"], "system")
        self.assertNotEqual(messages[1]["role"], "tool")


class SafetyTests(unittest.TestCase):
    def test_ordinary_commands_pass(self):
        self.assertIsNone(danger_reason("Get-ChildItem C:\\Users"))
        self.assertIsNone(danger_reason("Set-Content .\\note.txt 'hello'"))
        self.assertIsNone(danger_reason("Remove-Item .\\temp\\a.txt"))

    def test_destructive_commands_need_confirmation(self):
        self.assertIsNotNone(danger_reason("format C:"))
        self.assertIsNotNone(danger_reason("shutdown /s /t 0"))
        self.assertIsNotNone(danger_reason("Remove-Item C:\\Windows -Recurse"))
        self.assertIsNotNone(danger_reason("reg delete HKLM\\Software\\Foo /f"))


class CostTests(unittest.TestCase):
    def test_footer_shows_dollars(self):
        stats = RunStats(prompt_tokens=1500, completion_tokens=40, cost=0.012345, cost_known=True)
        self.assertIn("cost $0.012345", _footer(stats, 2))
        self.assertIn("1.5k in", _footer(stats, 2))

    def test_missing_cost_is_marked(self):
        self.assertIn("cost n/a", _footer(RunStats(), 1))
        self.assertIsNone(_usage_cost({}))
        self.assertEqual(_usage_cost({"cost": "0.5"}), 0.5)
        self.assertEqual(_usage_cost({"cost_details": {"upstream_inference_cost": 0.25}}), 0.25)


class PowerTests(unittest.TestCase):
    def test_budget_asks_again_after_each_block(self):
        stats = RunStats(cost=0.50, cost_known=True, budget_blocks=1)
        self.assertTrue(_budget_hit(stats, 0.50))
        stats.budget_blocks = 2
        self.assertFalse(_budget_hit(stats, 0.50))
        self.assertFalse(_budget_hit(RunStats(cost=1, cost_known=False), 0.50))

    def test_memory_round_trip(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            memory = Memory(Path(folder) / "memory.json")
            self.assertEqual(memory.write("last_cursor_folder", "C:\\work"), "Remembered last_cursor_folder.")
            again = Memory(Path(folder) / "memory.json")
            self.assertIn("last_cursor_folder", again.snapshot())
            self.assertEqual(memory.write("last_cursor_folder", ""), "Forgot last_cursor_folder.")

    def test_schedule_becomes_due(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            schedule = Schedule(Path(folder) / "schedules.json")
            schedule.add(1, 2, "open notepad", 15)
            self.assertEqual(schedule.due(now=0), [])
            ready = schedule.due(now=10**12)
            self.assertEqual(len(ready), 1)
            self.assertIn("Nothing", schedule.listing())

    def test_uploads_and_secret_files(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            inbox = Path(folder)
            path = save_upload(inbox, "my file.txt", b"hello")
            self.assertTrue(path.is_file())
            found, error = resolve_send_path(path.name, inbox)
            self.assertIsNone(error)
            self.assertEqual(found, str(path.resolve()))
            secret = inbox / ".env"
            secret.write_text("nope", encoding="utf-8")
            found, error = resolve_send_path(str(secret), inbox)
            self.assertIsNone(found)
            self.assertIn("secret", error)
            local = inbox / ".env.local"
            local.write_text("nope", encoding="utf-8")
            found, error = resolve_send_path(str(local), inbox)
            self.assertIsNone(found)

    def test_queued_notes_keep_the_picture_and_cost(self):
        text, image, cost = combine_notes(["open notepad", ("look at this", b"jpeg", 0.02)])
        self.assertIn("open notepad", text)
        self.assertIn("look at this", text)
        self.assertEqual(image, b"jpeg")
        self.assertAlmostEqual(cost, 0.02)
        self.assertTrue(_desktop_locked("Tool error: The Windows desktop is locked. Unlock the PC."))

    def test_cursor_folder_is_remembered(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            memory = Memory(Path(folder) / "memory.json")
            _remember_cursor(memory, r"Opened Cursor in C:\Work\demo. Opened the agent panel.")
            self.assertIn(r"C:\Work\demo", memory.read("last_cursor_folder"))


if __name__ == "__main__":
    unittest.main()
