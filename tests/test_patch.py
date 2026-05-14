import re
import unittest
from pathlib import Path
import tempfile
import shutil

import main


class FindFileTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _write(self, relpath: str, content: bytes) -> Path:
        p = self.tmpdir / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return p

    def test_find_file_locates_existing_anchor(self):
        js = b'function f(){a.b.info("updateMessagesMeRead",t.messageIds);}'
        self._write("a.js", js)
        results = main.find_file(self.tmpdir)
        self.assertEqual(len(results), 1)
        path, offset = results[0]
        self.assertEqual(path.name, "a.js")
        self.assertEqual(js[offset:offset + 1], b"a")  # 命中的是变量名起始

    def test_find_file_skips_non_matching(self):
        self._write("a.js", b'console.log("hello");')
        results = main.find_file(self.tmpdir)
        self.assertEqual(results, [])


class ModifyFileTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_modify_file_inserts_payload_at_offset(self):
        js = b'function f(){a.b.info("updateMessagesMeRead",t.messageIds);}'
        p = self.tmpdir / "a.js"
        p.write_bytes(js)
        offset = js.index(b"a.b.info")
        main.modify_file(p, offset)
        modified = p.read_bytes()
        self.assertIn(main.PAYLOAD, modified)
        # PAYLOAD 应该紧贴在原 'a' 字符之前
        idx = modified.index(main.PAYLOAD)
        self.assertEqual(modified[idx + len(main.PAYLOAD):idx + len(main.PAYLOAD) + 1], b"a")


if __name__ == "__main__":
    unittest.main()
