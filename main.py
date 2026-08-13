"""
使用方法: python main.py <飞书安装根目录> [--repatch]
"""
import argparse
import sys
import re
import shutil
from typing import Dict, List, NamedTuple, Optional, Pattern, Sequence, Tuple
from pathlib import Path
from asar import Asar


READ_RECEIPT_WINDOW_MS = 1500
READ_STATE_PLACEHOLDER = b"__FEISHU_UNREADME_STATE__"


class Patch(NamedTuple):
    name: str
    pattern: Pattern[bytes]
    payload: bytes

    def render(self, match: re.Match[bytes]) -> "Patch":
        """根据锚点捕获内容生成当前命中的补丁。"""
        if READ_STATE_PLACEHOLDER not in self.payload:
            return self

        read_state = match.group("read_state")
        return self._replace(
            payload=self.payload.replace(READ_STATE_PLACEHOLDER, read_state)
        )


PATCHES = (
    Patch(
        name="read-receipt-gate",
        pattern=re.compile(
            rb'[\w$]+\.[\w$]+\.info\("updateMessagesMeRead"'
            rb'(?=,\(0,[\w$]+\.[\w$]+\)\(\{\.\.\.'
            rb'(?P<read_state>[\w$]+)\},)'
        ),
        payload=(
            b"((r,p=window.__feishuUnreadmePermit,n=Date.now())=>{"
            b"if(p&&p.chatId===r.channel?.id&&p.expiresAt>=n&&p.remaining>0){"
            b"--p.remaining<=0&&(window.__feishuUnreadmePermit=null)"
            b"}else{r.messageIds=[],r.foldIds=[],r.maxPosition=-1,"
            b"r.maxPositionBadgeCount=0,r.threadId=r.threadMaxPosition="
            b"r.threadMaxPositionBadgeCount=void 0,p&&p.expiresAt<n&&"
            b"(window.__feishuUnreadmePermit=null)}})("
            + READ_STATE_PLACEHOLDER
            + b"),"
        ),
    ),
    Patch(
        name="send-success-permit",
        pattern=re.compile(
            rb'\w+\.\w+\.info\("MessageService::sendMessage:onSendMessageSuccess:"'
        ),
        payload=(
            "window.__feishuUnreadmePermit=this.feedId?{chatId:this.feedId,"
            "expiresAt:Date.now()+%d,remaining:1}:null,"
            % READ_RECEIPT_WINDOW_MS
        ).encode("ascii"),
    ),
)

Anchor = Tuple[int, Patch]
PatchMap = Dict[Path, List[Anchor]]

UNPACKED_DIR = Path(__file__).parent / "unpacked"


def find_asar_file(install_dir: str) -> Optional[Path]:
    """
    要修改的 js 文件位于 <install_dir>/app?/webcontent/messenger.asar 包内
    非 Windows 平台可能没有 app 这个中间目录
    """
    return next(Path(install_dir).rglob("webcontent/messenger.asar"), None)


def unpack_asar(asar_file: Path):
    if UNPACKED_DIR.exists():
        shutil.rmtree(UNPACKED_DIR)

    with Asar.open(asar_file) as archive:
        archive.extract(UNPACKED_DIR)


def find_file(search_dir: Path, patches: Sequence[Patch] = PATCHES) -> PatchMap:
    """
    搜索所有补丁锚点，返回 {文件路径: [(插入位置, 补丁), ...]}。
    """
    all_js_files = list(search_dir.rglob("*.js"))
    result: PatchMap = {}
    for js_file in all_js_files:
        try:
            content = js_file.read_bytes()
        except OSError:
            continue
        for patch in patches:
            for match in patch.pattern.finditer(content):
                result.setdefault(js_file, []).append(
                    (match.start(), patch.render(match))
                )

    return result


def find_missing_patches(
    patch_map: PatchMap, patches: Sequence[Patch] = PATCHES
) -> List[Patch]:
    matched_names = {
        patch.name for anchors in patch_map.values() for _, patch in anchors
    }
    return [patch for patch in patches if patch.name not in matched_names]


def make_backup(asar_file: Path):
    bak_file = asar_file.with_suffix(".asar.bak")
    if bak_file.exists():
        print(f"备份文件已存在：{bak_file}")
        return
    print(f"备份原始 asar 文件：{asar_file} -> {bak_file}")
    shutil.copy2(asar_file, bak_file)


def modify_file(js_file: Path, anchors: Sequence[Anchor]):
    patch_names = ", ".join(patch.name for _, patch in anchors)
    print(f"正在修改文件：{js_file}（{patch_names}）")
    with open(js_file, "rb+") as f:
        content = f.read()
        for offset, patch in sorted(anchors, key=lambda anchor: anchor[0], reverse=True):
            content = content[:offset] + patch.payload + content[offset:]
        f.seek(0)
        f.truncate()
        f.write(content)


def parse_args():
    parser = argparse.ArgumentParser(description="修改飞书客户端的已读回执逻辑")
    parser.add_argument("install_dir", help="飞书安装根目录")
    parser.add_argument(
        "--repatch",
        action="store_true",
        help="使用已有的原始备份重新生成补丁",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    install_dir = args.install_dir
    asar_file = find_asar_file(install_dir)
    if not asar_file:
        print("未找到 messenger.asar，可能是飞书安装目录指定的不正确，或版本不兼容", file=sys.stderr)
        exit(1)
    bak_file = asar_file.with_suffix(".asar.bak")
    if bak_file.exists() and not args.repatch:
        print(f"检测到备份文件 {bak_file}，似乎已经修改过了。若要重新执行，请先将 `messenger.asar.bak` 重命名回 `messenger.asar`", file=sys.stderr)
        exit(1)
    if args.repatch and not bak_file.exists():
        print("未找到原始备份，无法使用 --repatch", file=sys.stderr)
        exit(1)

    source_asar_file = bak_file if args.repatch else asar_file
    if args.repatch:
        print(f"使用原始备份重新生成补丁：{source_asar_file}")

    temp_asar_file = asar_file.with_name(f"{asar_file.name}.tmp")
    try:
        unpack_asar(source_asar_file)

        patch_map = find_file(UNPACKED_DIR)
        missing_patches = find_missing_patches(patch_map)
        if missing_patches:
            missing_names = ", ".join(patch.name for patch in missing_patches)
            print(f"未找到补丁锚点：{missing_names}，可能是版本不兼容", file=sys.stderr)
            exit(1)

        for js_file, anchors in patch_map.items():
            modify_file(js_file, anchors)

        print(f"正在打包：{UNPACKED_DIR} -> {temp_asar_file}")
        Asar.pack(UNPACKED_DIR, temp_asar_file)
        with Asar.open(temp_asar_file):
            pass

        make_backup(asar_file)
        temp_asar_file.replace(asar_file)
    finally:
        if UNPACKED_DIR.exists():
            shutil.rmtree(UNPACKED_DIR)
        if temp_asar_file.exists():
            temp_asar_file.unlink()

    print("修改完成。请重启飞书。若飞书功能异常，请将 `messenger.asar.bak` 重命名回 `messenger.asar`")



if __name__ == '__main__':
    main()
