import json
import os
from pathlib import Path
import tempfile
import unittest
from rea_team.safety import read_private_json, ReaError

class PrivateArtifactTests(unittest.TestCase):
    def test_private_json(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'report.json'; p.write_text('{"ok":true}'); p.chmod(0o600)
            self.assertEqual(read_private_json(p), {'ok':True})
    def test_rejects_public_file(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'report.json'; p.write_text('{}'); p.chmod(0o644)
            with self.assertRaises(ReaError): read_private_json(p)
    def test_rejects_hardlinks(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'report.json'; p.write_text('{}'); p.chmod(0o600)
            os.link(p,Path(d)/'other')
            with self.assertRaises(ReaError): read_private_json(p)
    def test_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'report.json'; p.write_text('{}'); p.chmod(0o600)
            q=Path(d)/'other'; q.symlink_to(p)
            with self.assertRaises(OSError): read_private_json(q)
    def test_rejects_over_budget(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'report.json'; p.write_text(' '*100); p.chmod(0o600)
            with self.assertRaises(ReaError): read_private_json(p, 10)
