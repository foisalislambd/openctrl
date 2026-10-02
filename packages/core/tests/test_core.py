import unittest

from openctrl.config import SettingsError, load_settings, read_settings, save_settings, values_from_settings
from openctrl.paths import data_directory, launch_command
from openctrl.version import VersionError, changelog_notes, current_version, is_newer
from openctrl.agent import (
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
from openctrl.files import resolve_send_path, save_upload
from openctrl.memory import Memory
from openctrl.schedule import Schedule
from openctrl.screen import image_to_screen
from openctrl.format_tg import markdown_to_html, one_line
from openctrl.safety import danger_reason


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
        self.assertIsNone(danger_reason("Get-ChildItem C:\\Users", "win32"))
        self.assertIsNone(danger_reason("Set-Content .\\note.txt 'hello'", "win32"))
        self.assertIsNone(danger_reason("Remove-Item .\\temp\\a.txt", "win32"))

    def test_destructive_commands_need_confirmation(self):
        self.assertIsNotNone(danger_reason("format C:", "win32"))
        self.assertIsNotNone(danger_reason("shutdown /s /t 0", "win32"))
        self.assertIsNotNone(danger_reason("Remove-Item C:\\Windows -Recurse", "win32"))
        self.assertIsNotNone(danger_reason("reg delete HKLM\\Software\\Foo /f", "win32"))

    def test_unix_destructive_commands_need_confirmation(self):
        self.assertIsNone(danger_reason("ls /home", "linux"))
        self.assertIsNotNone(danger_reason("rm -rf /", "linux"))
        self.assertIsNotNone(danger_reason("shutdown -h now", "darwin"))
        self.assertIsNotNone(danger_reason("mkfs.ext4 /dev/sdb", "linux"))
        self.assertIsNotNone(danger_reason("rm -rf /usr/bin", "linux"))
        self.assertIsNone(danger_reason("rm -rf /tmp/build", "linux"))


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
            database = inbox / "openctrl.db"
            database.write_text("nope", encoding="utf-8")
            found, error = resolve_send_path(str(database), inbox)
            self.assertIsNone(found)
            wal = inbox / "openctrl.db-wal"
            wal.write_text("nope", encoding="utf-8")
            found, error = resolve_send_path(str(wal), inbox)
            self.assertIsNone(found)
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


class StoreTests(unittest.TestCase):
    def test_env_is_copied_once_and_then_ignored(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".env").write_text(
                "TELEGRAM_BOT_TOKEN=token-1\nOPENROUTER_API_KEY=key-1\n"
                "TELEGRAM_ALLOWED_USER_IDS=12, 34\nSTART_WITH_WINDOWS=0\n",
                encoding="utf-8",
            )
            settings = read_settings(root)
            self.assertEqual(settings.telegram_token, "token-1")
            self.assertEqual(settings.openrouter_api_key, "key-1")
            self.assertEqual(settings.allowed_user_ids, frozenset({12, 34}))
            self.assertFalse(settings.start_with_windows)
            self.assertTrue(settings.agent_autostart)
            self.assertTrue((root / "data" / "openctrl.db").is_file())
            save_settings(root, {**values_from_settings(settings), "telegram_bot_token": "token-2"})
            (root / ".env").write_text(
                "TELEGRAM_BOT_TOKEN=token-9\nOPENROUTER_API_KEY=key-9\n",
                encoding="utf-8",
            )
            again = read_settings(root)
            self.assertEqual(again.telegram_token, "token-2")
            self.assertEqual(again.openrouter_api_key, "key-1")

    def test_bad_id_and_limits(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(SettingsError):
                save_settings(
                    root,
                    {
                        "telegram_bot_token": "token",
                        "openrouter_api_key": "key",
                        "telegram_allowed_user_ids": "abc",
                    },
                )
            with self.assertRaises(SystemExit):
                load_settings(root)
            saved = save_settings(
                root,
                {
                    "telegram_bot_token": "token",
                    "openrouter_api_key": "key",
                    "max_steps": "999",
                    "max_task_cost": "nope",
                    "agent_autostart": "no",
                },
            )
            self.assertEqual(saved.max_steps, 80)
            self.assertEqual(saved.max_task_cost, 0.50)
            self.assertFalse(saved.agent_autostart)
            self.assertTrue(load_settings(root).configured)

    def test_setup_window_builds(self):
        import tempfile
        import tkinter as tk
        from pathlib import Path

        from openctrl.deskapp import DeskApp

        try:
            window = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        window.withdraw()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = DeskApp(window, root, lambda: None, lambda _path, enabled: f"login {enabled}")
            app.build()
            window.update()
            self.assertIn("telegram_bot_token", app._entries)
            self.assertEqual(app._entries["openrouter_model"].get(), "openai/gpt-6-luna-pro")
            app._entries["telegram_bot_token"].delete(0, "end")
            app._entries["telegram_bot_token"].insert(0, "token")
            app._entries["openrouter_api_key"].delete(0, "end")
            app._entries["openrouter_api_key"].insert(0, "key")
            app._autostart.set(False)
            app._login.set(False)
            app.save_clicked()
            window.update()
            stored = read_settings(root)
            self.assertEqual(stored.telegram_token, "token")
            self.assertFalse(stored.start_with_windows)
            self.assertIn("login False", app._note_label.cget("text"))
        window.destroy()


class ReleaseTests(unittest.TestCase):
    def test_version_file_is_the_app_version(self):
        self.assertEqual(current_version(), "1.1.0")

    def test_only_a_greater_version_is_released(self):
        self.assertTrue(is_newer("1.1.0", []))
        self.assertTrue(is_newer("1.2.0", ["v1.1.0", "v1.0.0"]))
        self.assertTrue(is_newer("1.10.0", ["v1.9.0"]))
        self.assertFalse(is_newer("1.1.0", ["v1.1.0"]))
        self.assertFalse(is_newer("1.0.0", ["1.1.0"]))
        self.assertFalse(is_newer("1.2.0", ["v1.10.0"]))
        with self.assertRaises(VersionError):
            is_newer("1.1", [])

    def test_changelog_section_stops_at_the_next_version(self):
        notes = changelog_notes("# Changelog\n\n## 1.1.0\n\n- Window\n\n## 1.0.0\n\n- First\n", "v1.1.0")
        self.assertIn("Window", notes)
        self.assertNotIn("First", notes)
        self.assertEqual(changelog_notes("# Changelog\n", "2.0.0"), "OpenCtrl 2.0.0")

    def test_source_checkout_keeps_data_beside_the_app(self):
        import sys
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(data_directory(root), root)
            if sys.platform == "win32":
                (root / "run.bat").write_text("@echo off\n", encoding="utf-8")
                command, work = launch_command(root)
                self.assertEqual(command, [str((root / "run.bat").resolve())])
            else:
                script = root / "run.sh"
                script.write_text("#!/bin/sh\n", encoding="utf-8")
                command, work = launch_command(root)
                self.assertEqual(command[0], "/bin/sh")
                self.assertEqual(command[1], str(script.resolve()))
            self.assertEqual(work, root.resolve())


if __name__ == "__main__":
    unittest.main()
