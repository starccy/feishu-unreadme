"""
使用方法: python main.py <飞书安装根目录>
"""
import sys
import shutil
from typing import Optional, List, Tuple
from pathlib import Path
from asar import Asar


CODE_PIECE = b'info("updateMessagesMeRead",'
PAYLOAD = b"t.messageIds = [];"

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


def find_file(search_dir: Path) -> List[Tuple[Path, int]]:
    """
    搜索要修改的 js 文件
    """
    all_js_files = list(search_dir.rglob("*.js"))
    result = []
    for js_file in all_js_files:
        with open(js_file, 'rb') as f:
            try:
                content = f.read()
            except UnicodeDecodeError:
                continue
            try:
                offset = content.index(CODE_PIECE)
                lst_return_offset = content.rindex(b"return ", 0, offset)
                result.append((js_file, lst_return_offset))
            except ValueError:
                continue

    return result


def make_backup(asar_file: Path):
    bak_file = asar_file.with_suffix(".asar.bak")
    if bak_file.exists():
        return
    print(f"重命名/备份原始 asar 文件：{asar_file} -> {bak_file}")
    shutil.move(asar_file, bak_file)


def modify_file(js_file: Path, offset: int):
    print(f"正在修改文件：{js_file}")
    with open(js_file, "rb+") as f:
        content = f.read()
        f.seek(offset)
        f.write(PAYLOAD)
        f.write(content[offset:])


def main():
    if len(sys.argv) < 2:
        print("请指定飞书安装目录", file=sys.stderr)
        exit(1)

    install_dir = sys.argv[1]
    asar_file = find_asar_file(install_dir)
    if not asar_file:
        print("未找到 messenger.asar，可能是飞书安装目录指定的不正确，或版本不兼容", file=sys.stderr)
        exit(1)
    if asar_file.is_dir():
        print("似乎文件已经修改过了。若要重新执行，请先将 `messenger.asar` 目录删除，并将 `messenger.asar.bak` 重命名回 `messenger.asar`", file=sys.stderr)
        exit(1)

    unpack_asar(asar_file)
    make_backup(asar_file)

    js_files = find_file(UNPACKED_DIR)
    for js_file, offset in js_files:
        modify_file(js_file, offset)

    # 不需要重新打包，只需保证目录名与原 asar 文件名一致即可
    shutil.move(UNPACKED_DIR, asar_file)

    print("修改完成。请重启飞书。若飞书功能异常，请将删除 `messenger.asar` 目录，并将 `messenger.asar.bak` 重命名回 `messenger.asar`")



if __name__ == '__main__':
    main()
