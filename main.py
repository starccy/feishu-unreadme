"""
使用方法: python main.py <飞书安装根目录>
"""
import sys
import re
import shutil
from typing import Optional, List, Tuple, Pattern, Dict
from pathlib import Path
from asar import Asar


PATCHES = [
    # (pattern, payload) 列表;每组 pattern 必须在解包目录中恰好命中至少一处,
    # 否则视为版本不兼容并退出。payload 是一段 JS 字节串,会被插入到 pattern
    # 匹配位置的开头(变量名起始处)。因为锚点都位于表达式参数列表中,所以
    # payload 必须是表达式(末尾用 `,`),不能是 statement。
    (
        re.compile(rb'\w+\.\w+\.info\("updateMessagesMeRead"'),
        b"(window.__feishuAllowMeReadCount>0?window.__feishuAllowMeReadCount--:t.messageIds=[]),",
    ),
    (
        re.compile(rb'\w+\.\w+\.info\("MessageService::sendMessage:onSendMessageSuccess:"'),
        b"window.__feishuAllowMeReadCount=1,",
    ),
]

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


def find_file(search_dir: Path, patches: List[Tuple[Pattern[bytes], bytes]]) -> Dict[Path, List[Tuple[int, bytes]]]:
    """
    对每个 (pattern, payload),在 search_dir 下所有 .js 文件中搜索锚点。
    返回 {js_file: [(offset, payload), ...]}。同一文件可能有多个锚点。
    """
    result: dict = {}
    all_js_files = list(search_dir.rglob("*.js"))
    for js_file in all_js_files:
        try:
            content = js_file.read_bytes()
        except OSError:
            continue
        for pattern, payload in patches:
            for match in pattern.finditer(content):
                result.setdefault(js_file, []).append((match.start(), payload))
    return result


def make_backup(asar_file: Path):
    bak_file = asar_file.with_suffix(".asar.bak")
    if bak_file.exists():
        print(f"备份文件已存在：{bak_file}")
        return
    print(f"备份原始 asar 文件：{asar_file} -> {bak_file}")
    shutil.copy2(asar_file, bak_file)


def modify_file(js_file: Path, anchors: List[Tuple[int, bytes]]) -> None:
    """
    在 js_file 中按 offset 倒序插入多个 payload,避免后续 offset 失效。
    anchors: List[Tuple[int, bytes]],元素为 (offset, payload)。
    """
    print(f"正在修改文件：{js_file}({len(anchors)} 处锚点)")
    with open(js_file, "rb+") as f:
        content = f.read()
        # 倒序:先在大 offset 处插入,小 offset 不受影响
        for offset, payload in sorted(anchors, key=lambda x: -x[0]):
            content = content[:offset] + payload + content[offset:]
        f.seek(0)
        f.truncate()
        f.write(content)


def main():
    if len(sys.argv) < 2:
        print("请指定飞书安装目录", file=sys.stderr)
        exit(1)

    install_dir = sys.argv[1]
    asar_file = find_asar_file(install_dir)
    if not asar_file:
        print("未找到 messenger.asar，可能是飞书安装目录指定的不正确，或版本不兼容", file=sys.stderr)
        exit(1)
    bak_file = asar_file.with_suffix(".asar.bak")
    if bak_file.exists():
        print(f"检测到备份文件 {bak_file}，似乎已经修改过了。若要重新执行，请先将 `messenger.asar.bak` 重命名回 `messenger.asar`", file=sys.stderr)
        exit(1)

    make_backup(asar_file)
    unpack_asar(asar_file)

    files_map = find_file(UNPACKED_DIR, PATCHES)

    # 每个 pattern 都至少命中一次,才认为版本兼容
    covered_payloads = {payload for anchors in files_map.values() for _, payload in anchors}
    expected_payloads = {payload for _, payload in PATCHES}
    missing = expected_payloads - covered_payloads
    if missing:
        print(f"未找到 {len(missing)} 组锚点,可能是版本不兼容", file=sys.stderr)
        shutil.rmtree(UNPACKED_DIR)
        exit(1)

    for js_file, anchors in files_map.items():
        modify_file(js_file, anchors)

    # 打包回 asar 文件
    print(f"正在打包：{UNPACKED_DIR} -> {asar_file}")
    Asar.pack(UNPACKED_DIR, asar_file)

    # 清理临时目录
    shutil.rmtree(UNPACKED_DIR)

    print("修改完成。请重启飞书。若飞书功能异常，请将 `messenger.asar.bak` 重命名回 `messenger.asar`")



if __name__ == '__main__':
    main()
