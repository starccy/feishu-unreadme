import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import main


class PatchDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_finds_both_real_anchors(self):
        js_file = self.temp_dir / "bundle.js"
        js_file.write_bytes(
            b'function read(){a.b.info("updateMessagesMeRead",t);}'
            b'class Service{send(){c.d.info('
            b'"MessageService::sendMessage:onSendMessageSuccess:",cid);}}'
        )

        patch_map = main.find_file(self.temp_dir)

        self.assertEqual(main.find_missing_patches(patch_map), [])
        self.assertEqual(
            {patch.name for _, patch in patch_map[js_file]},
            {"read-receipt-gate", "send-success-permit"},
        )

    def test_reports_a_missing_anchor(self):
        (self.temp_dir / "bundle.js").write_bytes(
            b'a.b.info("updateMessagesMeRead",t);'
        )

        patch_map = main.find_file(self.temp_dir)

        self.assertEqual(
            [patch.name for patch in main.find_missing_patches(patch_map)],
            ["send-success-permit"],
        )

    def test_modify_file_applies_multiple_anchors_without_offset_drift(self):
        js_file = self.temp_dir / "bundle.js"
        content = (
            b'a.b.info("updateMessagesMeRead",t);'
            b'c.d.info("MessageService::sendMessage:onSendMessageSuccess:",cid);'
        )
        js_file.write_bytes(content)
        patch_map = main.find_file(self.temp_dir)

        main.modify_file(js_file, list(reversed(patch_map[js_file])))

        modified = js_file.read_bytes()
        for _, patch in patch_map[js_file]:
            self.assertIn(patch.payload, modified)
        self.assertTrue(modified.endswith(content[content.index(b"c.d.info"):]))


@unittest.skipUnless(shutil.which("node"), "Node.js is required")
class JavaScriptPayloadTests(unittest.TestCase):
    def run_javascript(self, body):
        result = subprocess.run(
            ["node", "-e", body],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def test_send_success_creates_a_chat_scoped_permit(self):
        payload = main.PATCHES[1].payload.decode("ascii")
        result = self.run_javascript(
            "global.window={}; Date.now=()=>1000;"
            "const service={feedId:'chat-a',send(){return ("
            f"{payload}0);}}}}; service.send();"
            "console.log(JSON.stringify(window.__feishuUnreadmePermit));"
        )

        self.assertEqual(
            result,
            {
                "chatId": "chat-a",
                "expiresAt": 1000 + main.READ_RECEIPT_WINDOW_MS,
                "remaining": 1,
            },
        )

    def test_matching_chat_preserves_the_complete_report_and_consumes_permit(self):
        payload = main.PATCHES[0].payload.decode("ascii")
        result = self.run_javascript(
            "global.window={__feishuUnreadmePermit:"
            "{chatId:'chat-a',expiresAt:2000,remaining:1}};"
            "Date.now=()=>1000;let t={channel:{id:'chat-a'},messageIds:['m1'],"
            "foldIds:['f1'],maxPosition:9,maxPositionBadgeCount:2,"
            "threadId:'thread-a',threadMaxPosition:8,"
            "threadMaxPositionBadgeCount:1};"
            f"const ignored=({payload}0);"
            "console.log(JSON.stringify({t,permit:window.__feishuUnreadmePermit}));"
        )

        self.assertEqual(
            result["t"],
            {
                "channel": {"id": "chat-a"},
                "messageIds": ["m1"],
                "foldIds": ["f1"],
                "maxPosition": 9,
                "maxPositionBadgeCount": 2,
                "threadId": "thread-a",
                "threadMaxPosition": 8,
                "threadMaxPositionBadgeCount": 1,
            },
        )
        self.assertIsNone(result["permit"])

    def test_other_chat_has_every_read_cursor_blocked_without_consuming_permit(self):
        payload = main.PATCHES[0].payload.decode("ascii")
        result = self.run_javascript(
            "global.window={__feishuUnreadmePermit:"
            "{chatId:'chat-a',expiresAt:2000,remaining:1}};"
            "Date.now=()=>1000;let t={channel:{id:'chat-b'},messageIds:['m1'],"
            "foldIds:['f1'],maxPosition:9,maxPositionBadgeCount:2,"
            "threadId:'thread-b',threadMaxPosition:8,"
            "threadMaxPositionBadgeCount:1};"
            f"const ignored=({payload}0);"
            "console.log(JSON.stringify({t,permit:window.__feishuUnreadmePermit}));"
        )

        self.assertEqual(
            result["t"],
            {
                "channel": {"id": "chat-b"},
                "messageIds": [],
                "foldIds": [],
                "maxPosition": -1,
                "maxPositionBadgeCount": 0,
            },
        )
        self.assertEqual(result["permit"]["chatId"], "chat-a")
        self.assertEqual(result["permit"]["remaining"], 1)

    def test_expired_permit_is_blocked_and_removed(self):
        payload = main.PATCHES[0].payload.decode("ascii")
        result = self.run_javascript(
            "global.window={__feishuUnreadmePermit:"
            "{chatId:'chat-a',expiresAt:999,remaining:1}};"
            "Date.now=()=>1000;let t={channel:{id:'chat-a'},messageIds:['m1'],"
            "foldIds:['f1'],maxPosition:9,maxPositionBadgeCount:2,"
            "threadId:'thread-a',threadMaxPosition:8,"
            "threadMaxPositionBadgeCount:1};"
            f"const ignored=({payload}0);"
            "console.log(JSON.stringify({t,permit:window.__feishuUnreadmePermit}));"
        )

        self.assertEqual(
            result["t"],
            {
                "channel": {"id": "chat-a"},
                "messageIds": [],
                "foldIds": [],
                "maxPosition": -1,
                "maxPositionBadgeCount": 0,
            },
        )
        self.assertIsNone(result["permit"])
