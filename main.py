"""
使用方法: python main.py <飞书安装根目录>
"""
import sys
import shutil
from typing import Optional, List, Tuple
from pathlib import Path


CODE_PIECE = 'info("updateMessagesMeRead",'
PAYLOAD = "t.messageIds = [];"


def find_search_dir(install_dir: str) -> Optional[Path]:
    """
    要修改的文件位于 <install_dir>/app?/webcontent/messenger 目录下
    非 Windows 平台可能没有 app 这个中间目录
    """
    return next(Path(install_dir).rglob("webcontent/messenger"), None)


def find_file(search_dir: Path) -> List[Tuple[Path, int]]:
    """
    搜索要修改的 js 文件
    """
    all_js_files = list(search_dir.rglob("*.js"))
    result = []
    for js_file in all_js_files:
        with open(js_file) as f:
            content = f.read()
            try:
                offset = content.index(CODE_PIECE)
                lst_return_offset = content.rindex("return ", 0, offset)
                result.append((js_file, lst_return_offset))
            except ValueError:
                continue

    return result


def create_backup(js_file: Path):
    bak_file = js_file.with_suffix(".bak")
    if bak_file.exists():
        return
    print(f"创建备份文件：{bak_file}...")
    shutil.copyfile(js_file, bak_file)


def modify_file(js_file: Path, offset: int):
    print(f"正在修改文件：{js_file}")
    with open(js_file, "r+") as f:
        content = f.read()
        f.seek(offset)
        f.write(PAYLOAD)
        f.write(content[offset:])


def main():
    if len(sys.argv) < 2:
        print("请指定飞书安装目录", file=sys.stderr)
        exit(1)

    install_dir = sys.argv[1]
    search_dir = find_search_dir(install_dir)

    if not search_dir:
        print("未找到 messenger 目录，可能是飞书安装目录指定的不正确", file=sys.stderr)
        exit(1)
    
    js_files = find_file(search_dir)
    for js_file, offset in js_files:
        create_backup(js_file)
        modify_file(js_file, offset)

    print("修改完成。请重启飞书。若飞书功能异常，请将 .bak 备份文件恢复为 .js 文件")



if __name__ == '__main__':
    main()