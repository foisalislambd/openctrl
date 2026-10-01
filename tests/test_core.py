import unittest

from openagent.agent import RunStats, _as_bool, _footer, _repair_tool_calls, _trim, _usage_cost
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


if __name__ == "__main__":
    unittest.main()
