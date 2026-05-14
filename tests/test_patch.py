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
        results = main.find_file(self.tmpdir, main.PATCHES)
        # 单一 pattern,单一文件
        self.assertEqual(len(results), 1)
        (path, anchors), = results.items()
        self.assertEqual(path.name, "a.js")
        self.assertEqual(len(anchors), 1)
        offset, payload = anchors[0]
        self.assertEqual(js[offset:offset + 1], b"a")
        self.assertEqual(payload, main.PATCHES[0][1])

    def test_find_file_skips_non_matching(self):
        self._write("a.js", b'console.log("hello");')
        results = main.find_file(self.tmpdir, main.PATCHES)
        self.assertEqual(results, {})


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
        payload = main.PATCHES[0][1]
        main.modify_file(p, [(offset, payload)])
        modified = p.read_bytes()
        self.assertIn(payload, modified)
        idx = modified.index(payload)
        self.assertEqual(modified[idx + len(payload):idx + len(payload) + 1], b"a")


class MultiAnchorTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_find_file_returns_per_patch_results(self):
        """find_file 返回 dict: {js_file: [(offset, payload), ...]}"""
        js = b'PRE x.y.info("A",t) MID p.q.info("B",t) END'
        p = self.tmpdir / "a.js"
        p.write_bytes(js)

        patches = [
            (re.compile(rb'\w+\.\w+\.info\("A"'), b"AA,"),
            (re.compile(rb'\w+\.\w+\.info\("B"'), b"BB,"),
        ]
        results = main.find_file(self.tmpdir, patches)

        self.assertIn(p, results)
        offsets_payloads = sorted(results[p])  # 按 offset 升序
        self.assertEqual(len(offsets_payloads), 2)
        self.assertEqual(offsets_payloads[0][1], b"AA,")
        self.assertEqual(offsets_payloads[1][1], b"BB,")
        # 锚点必须落在变量名起始位置
        self.assertEqual(js[offsets_payloads[0][0]:offsets_payloads[0][0] + 1], b"x")
        self.assertEqual(js[offsets_payloads[1][0]:offsets_payloads[1][0] + 1], b"p")

    def test_modify_file_inserts_multiple_payloads_in_reverse(self):
        """同文件多个 offset,倒序注入,字节级正确"""
        js = b'PRE x.y.info("A",t) MID p.q.info("B",t) END'
        p = self.tmpdir / "a.js"
        p.write_bytes(js)

        off_a = js.index(b"x.y.info")
        off_b = js.index(b"p.q.info")
        main.modify_file(p, [(off_a, b"AA,"), (off_b, b"BB,")])

        modified = p.read_bytes()
        self.assertEqual(
            modified,
            b'PRE AA,x.y.info("A",t) MID BB,p.q.info("B",t) END',
        )

    def test_modify_file_handles_unsorted_offset_list(self):
        """即使传入未排序的 (offset, payload) 列表,modify_file 也能正确处理"""
        js = b'PRE x.y.info("A",t) MID p.q.info("B",t) END'
        p = self.tmpdir / "a.js"
        p.write_bytes(js)

        off_a = js.index(b"x.y.info")
        off_b = js.index(b"p.q.info")
        # 顺序故意打乱:小 offset 在后
        main.modify_file(p, [(off_b, b"BB,"), (off_a, b"AA,")])

        modified = p.read_bytes()
        self.assertEqual(
            modified,
            b'PRE AA,x.y.info("A",t) MID BB,p.q.info("B",t) END',
        )


if __name__ == "__main__":
    unittest.main()
