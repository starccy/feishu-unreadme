"""
使用方法: python main.py <飞书安装根目录>
"""
import sys
import re
import shutil
from typing import Optional, List, Tuple
from pathlib import Path
from asar import Asar


CODE_PATTERN = re.compile(rb'\w+\.\w+\.info\("updateMessagesMeRead"')
PAYLOAD = b"t.messageIds=[],"

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
    搜索要修改的 js 文件，返回 (文件路径, 插入位置) 列表
    插入位置是 x.Y.info("updateMessagesMeRead" 中变量名的起始位置
    """
    all_js_files = list(search_dir.rglob("*.js"))
    result = []
    for js_file in all_js_files:
        with open(js_file, 'rb') as f:
            try:
                content = f.read()
            except UnicodeDecodeError:
                continue
            match = CODE_PATTERN.search(content)
            if match:
                result.append((js_file, match.start()))

    return result


def make_backup(asar_file: Path):
    bak_file = asar_file.with_suffix(".asar.bak")
    if bak_file.exists():
        print(f"备份文件已存在：{bak_file}")
        return
    print(f"备份原始 asar 文件：{asar_file} -> {bak_file}")
    shutil.copy2(asar_file, bak_file)


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
    bak_file = asar_file.with_suffix(".asar.bak")
    if bak_file.exists():
        print(f"检测到备份文件 {bak_file}，似乎已经修改过了。若要重新执行，请先将 `messenger.asar.bak` 重命名回 `messenger.asar`", file=sys.stderr)
        exit(1)

    make_backup(asar_file)
    unpack_asar(asar_file)

    js_files = find_file(UNPACKED_DIR)
    if not js_files:
        print("未找到需要修改的代码，可能是版本不兼容", file=sys.stderr)
        shutil.rmtree(UNPACKED_DIR)
        exit(1)

    for js_file, offset in js_files:
        modify_file(js_file, offset)

    # 打包回 asar 文件
    print(f"正在打包：{UNPACKED_DIR} -> {asar_file}")
    Asar.pack(UNPACKED_DIR, asar_file)

    # 清理临时目录
    shutil.rmtree(UNPACKED_DIR)

    print("修改完成。请重启飞书。若飞书功能异常，请将 `messenger.asar.bak` 重命名回 `messenger.asar`")



if __name__ == '__main__':
    main()
