import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from asar import Asar, INTEGRITY_BLOCK_SIZE


class AsarIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_pack_writes_integrity_and_round_trips_files(self):
        source_dir = self.temp_dir / "source"
        source_dir.mkdir()
        small_content = b"console.log('hello');"
        large_content = b"a" * INTEGRITY_BLOCK_SIZE + b"tail"
        (source_dir / "small.js").write_bytes(small_content)
        (source_dir / "large.bin").write_bytes(large_content)
        archive_path = self.temp_dir / "test.asar"

        Asar.pack(source_dir, archive_path)

        with Asar.open(archive_path) as archive:
            small_info = archive.header["files"]["small.js"]
            large_info = archive.header["files"]["large.bin"]
            self.assertEqual(
                small_info["integrity"]["hash"],
                hashlib.sha256(small_content).hexdigest(),
            )
            self.assertEqual(len(large_info["integrity"]["blocks"]), 2)
            archive.extract(self.temp_dir / "extracted")

        self.assertEqual(
            (self.temp_dir / "extracted" / "small.js").read_bytes(), small_content
        )
        self.assertEqual(
            (self.temp_dir / "extracted" / "large.bin").read_bytes(), large_content
        )
