import unittest

from openctrl_windows.hotkeys import blocks_secure_attention, to_sendkeys


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
