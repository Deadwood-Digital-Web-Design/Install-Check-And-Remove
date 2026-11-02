import os
import tempfile
import time
import unittest
from pathlib import Path

import installer_check_remover as m


def make(path, hours_old=48, size=100):
    path.write_bytes(b"x" * size)
    ts = time.time() - hours_old * 3600
    os.utime(path, (ts, ts))


class ScanTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.folders = {"Test": self.root}

    def tearDown(self):
        self._tmp.cleanup()

    def test_finds_installers_only(self):
        make(self.root / "Setup_App_1.2.exe")
        make(self.root / "thing.msi")
        make(self.root / "portable_tool.exe")   # not installer-ish
        make(self.root / "notes.txt")
        names = sorted(i.name for i in m.scan(self.folders, 1))
        self.assertEqual(names, ["Setup_App_1.2.exe", "thing.msi"])

    def test_finds_hyphenated_setup_name(self):
        make(self.root / "Insights Capture-3.8.0-setup.exe")
        self.assertEqual(len(m.scan(self.folders, 1)), 1)

    def test_skips_brand_new_files(self):
        make(self.root / "fresh_setup.exe", hours_old=0)
        self.assertEqual(m.scan(self.folders, 1), [])

    def test_does_not_dig_into_subfolders(self):
        (self.root / "sub").mkdir()
        make(self.root / "sub" / "setup.exe")
        self.assertEqual(m.scan(self.folders, 1), [])

    def test_status_unknown_off_windows(self):
        if os.name != "nt":
            make(self.root / "setup.msi")
            self.assertEqual(m.scan(self.folders, 1)[0].status, "Unknown")

    def test_guess_status_matching(self):
        installed = {"google chrome", "7-zip 23.01"}
        self.assertEqual(m.guess_status("ChromeSetup.exe", installed), "Installed")
        self.assertEqual(m.guess_status("ObscureThing_setup_v2.exe", installed), "Not found")


class RemoveTests(unittest.TestCase):
    def test_remove_moves_file_out(self):
        if os.name == "nt":
            self.skipTest("uses the real Recycle Bin on Windows")
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as trash:
            f = Path(d) / "setup.msi"
            make(f)
            items = m.scan({"T": Path(d)}, 1)
            removed, freed, failed = m.remove_items(items, Path(trash))
            self.assertEqual((removed, freed, failed), (1, 100, []))
            self.assertFalse(f.exists())
            self.assertTrue((Path(trash) / "setup.msi").exists())  # recoverable

    def test_failure_reports_reason_and_path(self):
        item = m.Item(0, "ghost_setup.exe", "/nope/ghost_setup.exe", 10, 0, "T", "Unknown")
        removed, freed, failed = m.remove_items([item], Path(tempfile.gettempdir()) / "unused")
        self.assertEqual(removed, 0)
        self.assertEqual(failed[0][0], "ghost_setup.exe")
        self.assertEqual(failed[0][2], "/nope/ghost_setup.exe")

    def test_permanent_delete_clears_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "setup.msi"
            make(f)
            os.chmod(f, 0o444)
            items = m.scan({"T": Path(d)}, 1)
            removed, _, failed = m.remove_items(items, permanent=True)
            self.assertEqual((removed, failed), (1, []))
            self.assertFalse(f.exists())


if __name__ == "__main__":
    unittest.main()
