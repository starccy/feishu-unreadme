# 发送动作触发已读上报 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 改造 `main.py`,使其在飞书 `messenger.asar` 中注入两处 patch:一处把已有"无条件清空 messageIds"改为"放行计数器 > 0 时不清空",另一处在"用户发送消息"入口处把放行计数器置为 2。最终效果:打开会话/浏览仍然屏蔽已读;但用户主动发送消息后,对方能看到此前未读变已读。

**Architecture:** 把 `main.py` 中的单点 patch(`CODE_PATTERN` + `PAYLOAD`)重构为多组 `(pattern, payload)` 列表 `PATCHES`。`find_file` 对每个 pattern 在所有 js 文件中搜索锚点,产出 `{js_file: [(offset, payload), ...]}`;`modify_file` 对单个文件按 offset **倒序**注入,避免位移错乱。任意一组 pattern 未命中即视为版本不兼容,清理并退出。注入字面值采用**表达式 + 逗号**形式(而非 if/else statement),因为锚点位置在 `info("updateMessagesMeRead", ...)` 表达式参数列表中,必须是合法表达式。

**Tech Stack:** Python 3 标准库(`re`, `pathlib`, `shutil`, `struct`),stdlib `unittest`(不引入新依赖)。

---

## 文件结构

| 文件 | 角色 |
|------|------|
| `main.py`(修改) | 重构 PATCHES、`find_file`、`modify_file` 支持多锚点 + 倒序注入;加入锚点 2 |
| `tests/__init__.py`(新建) | 让 `tests` 成为可发现的 package |
| `tests/test_patch.py`(新建) | 单测:验证 `find_file` + `modify_file` 对人造 js 字节串的多锚点 / 倒序注入行为 |
| `asar.py` | **不动**,沿用 |
| `README.md`(修改) | 新增"已知问题"小节修订:说明回复消息后会触发已读 |

---

## Task 1: 引入测试目录 + baseline 测试现有单点 patch 行为

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_patch.py`

- [ ] **Step 1: 创建 `tests/__init__.py`**

```python
```

(空文件,只为让 `tests` 成为 package)

- [ ] **Step 2: 写 baseline 测试,覆盖现有 `find_file` + `modify_file` 行为**

创建 `tests/test_patch.py`,内容如下:

```python
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
```

- [ ] **Step 3: 运行测试验证全部通过**

Run: `python -m unittest discover -s tests -v`
Expected: 3 个 test 全部 PASS

- [ ] **Step 4: 提交**

```bash
git add tests/__init__.py tests/test_patch.py
git commit -m "test: 为现有 patch 行为加 baseline 单测"
```

---

## Task 2: 重构 `main.py` 为多锚点 PATCHES + 倒序注入

**Files:**
- Modify: `main.py:12-13`(`CODE_PATTERN` / `PAYLOAD` 定义)
- Modify: `main.py:34-51`(`find_file` 签名 / 返回类型)
- Modify: `main.py:63-69`(`modify_file` 签名)
- Modify: `main.py:90-97`(主流程调用处)
- Modify: `tests/test_patch.py`(适配新签名 + 新增同文件多锚点测试)

- [ ] **Step 1: 先写新测试,定义新的 API 行为(同文件多锚点 + 倒序注入)**

在 `tests/test_patch.py` 末尾(`if __name__` 之前)追加:

```python
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
```

同时,把 Task 1 中的 baseline 测试改为使用新 API:

`tests/test_patch.py` 中的 `FindFileTests.test_find_file_locates_existing_anchor`:

```python
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
```

`FindFileTests.test_find_file_skips_non_matching`:

```python
    def test_find_file_skips_non_matching(self):
        self._write("a.js", b'console.log("hello");')
        results = main.find_file(self.tmpdir, main.PATCHES)
        self.assertEqual(results, {})
```

`ModifyFileTests.test_modify_file_inserts_payload_at_offset`:

```python
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
```

(注意:`main.PAYLOAD` 这个常量在重构后不存在,改为引用 `main.PATCHES[0][1]`。)

- [ ] **Step 2: 运行测试验证全部 FAIL(因为 main.py 还没改)**

Run: `python -m unittest discover -s tests -v`
Expected: 几条 test 报 `AttributeError: module 'main' has no attribute 'PATCHES'`,或 `TypeError: find_file() takes 1 positional argument but 2 were given`

- [ ] **Step 3: 重构 `main.py`**

替换 `main.py` 第 12-13 行:

```python
PATCHES = [
    # (pattern, payload) 列表;每组 pattern 必须在解包目录中恰好命中至少一处,
    # 否则视为版本不兼容并退出。payload 是一段 JS 字节串,会被插入到 pattern
    # 匹配位置的开头(变量名起始处)。因为锚点都位于表达式参数列表中,所以
    # payload 必须是表达式(末尾用 `,`),不能是 statement。
    (
        re.compile(rb'\w+\.\w+\.info\("updateMessagesMeRead"'),
        b"(window.__feishuAllowMeReadCount>0?window.__feishuAllowMeReadCount--:t.messageIds=[]),",
    ),
]
```

替换 `main.py:34-51` 的 `find_file`:

```python
def find_file(search_dir: Path, patches) -> dict:
    """
    对每个 (pattern, payload),在 search_dir 下所有 .js 文件中搜索锚点。
    返回 {js_file: [(offset, payload), ...]}。同一文件可能有多个锚点。
    """
    result: dict = {}
    all_js_files = list(search_dir.rglob("*.js"))
    for js_file in all_js_files:
        try:
            content = js_file.read_bytes()
        except (OSError, UnicodeDecodeError):
            continue
        for pattern, payload in patches:
            for match in pattern.finditer(content):
                result.setdefault(js_file, []).append((match.start(), payload))
    return result
```

替换 `main.py:63-69` 的 `modify_file`:

```python
def modify_file(js_file: Path, anchors):
    """
    在 js_file 中按 offset 倒序插入多个 payload,避免后续 offset 失效。
    anchors: List[Tuple[int, bytes]],元素为 (offset, payload)。
    """
    print(f"正在修改文件:{js_file}({len(anchors)} 处锚点)")
    with open(js_file, "rb+") as f:
        content = f.read()
        # 倒序:先在大 offset 处插入,小 offset 不受影响
        for offset, payload in sorted(anchors, key=lambda x: -x[0]):
            content = content[:offset] + payload + content[offset:]
        f.seek(0)
        f.truncate()
        f.write(content)
```

替换 `main.py:90-97` 的主流程片段:

```python
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
```

- [ ] **Step 4: 运行测试验证全部 PASS**

Run: `python -m unittest discover -s tests -v`
Expected: 全部 PASS(baseline + 多锚点 + 倒序)

- [ ] **Step 5: 提交**

```bash
git add main.py tests/test_patch.py
git commit -m "refactor: main.py 改为多锚点 PATCHES + 倒序注入"
```

---

## Task 3: 逆向定位锚点 2 — 发送消息入口

**Files:**
- 不修改任何源文件;产出一个**字符串字面**记录在 Task 4 的代码中。
- 涉及的临时操作目录:`unpacked/`(由 `main.py` 解包产生,本任务结束后保留供 Task 4 / Task 5 复用)。

> 本任务是"发现性"任务,无单元测试,产物是一个稳定可匹配的字节串 pattern。

- [ ] **Step 1: 准备一份解包目录**

需要任意一份近期飞书的 `messenger.asar`。在终端运行:

```bash
python -c "
from pathlib import Path
from asar import Asar
import shutil

# 把下面这一行的 ASAR_PATH 改成本机 messenger.asar 的真实路径
ASAR_PATH = Path('/path/to/feishu/install/.../webcontent/messenger.asar')

out = Path('unpacked')
if out.exists(): shutil.rmtree(out)
with Asar.open(ASAR_PATH) as a:
    a.extract(out)
print('解包完成 ->', out.resolve())
"
```

Expected: 终端输出 `解包完成 -> .../unpacked`,目录下出现一堆 js 文件。

- [ ] **Step 2: grep 候选关键词**

依次执行下列命令,记录命中数:

```bash
grep -rEo '\w+\.\w+\.info\("send[A-Za-z_]*"' unpacked --include='*.js' | sort -u
grep -rEo '\w+\.\w+\.info\("[A-Za-z_]*[Ss]end[Mm]essage[A-Za-z_]*"' unpacked --include='*.js' | sort -u
grep -rEo '\w+\.\w+\.info\("[A-Za-z_]*[Mm]essage[Ss]end[A-Za-z_]*"' unpacked --include='*.js' | sort -u
```

Expected: 至少有几个候选,例如 `e.t.info("sendMessage"`、`a.b.info("messageSend"`、`x.y.info("sendTextMessage"` 等。

- [ ] **Step 3: 在候选中筛选锚点 2**

选取标准(必须全部满足):

1. **触发条件单一**:用关键词所在文件中前后 ~200 字节的代码上下文判断,该 info 日志应当**仅在用户主动发送消息时**触发(而非"草稿保存"、"消息已读上报本身"、"消息撤回"等附带事件)。可用 `grep -B 5 -A 5 -n` 看上下文。
2. **每次回车都会进**:看上下文中是否包在某个 if 条件下;若条件复杂(比如 "仅文本消息" 之类的限定),换一个更靠近发送通用入口的候选。
3. **位于表达式参数列表中**:确认该 info 调用在 `xx.xx.info("...", arg1, arg2, ...)` 这种形式中。Payload 就可以用表达式 + 逗号形式安全前置。

选定后,把命中的字面字符串(完整的 `\w+\.\w+\.info\("..."` 形式)记下来,记为 **ANCHOR2_LITERAL**。例如假定选定的字符串是 `t.r.info("sendMessage"`,则 ANCHOR2_LITERAL = `t.r.info("sendMessage"`,对应的正则 pattern = `\w+\.\w+\.info\("sendMessage"`。

- [ ] **Step 4: 在所有候选 js 文件里验证 pattern 的唯一性**

```bash
grep -rEo '\w+\.\w+\.info\("sendMessage"' unpacked --include='*.js' | wc -l
```

(把 `sendMessage` 换成上一步选定的具体字符串)

Expected: 命中 1 处或少数几处;若命中数 >10,该锚点过于泛滥,回到 Step 3 换更具体的字符串(例如改用 `"sendMessage_v2"` 或 `"send_message_done"` 等)。

- [ ] **Step 5: 记录决策**

把选定的 `ANCHOR2_PATTERN`(正则字符串)和 `ANCHOR2_PAYLOAD` 写入下一个 task。本任务不 commit(没有改任何项目文件)。

---

## Task 4: 把锚点 2 加入 PATCHES + 测试

**Files:**
- Modify: `main.py`(`PATCHES` 列表)
- Modify: `tests/test_patch.py`(新增锚点 2 端到端测试)

- [ ] **Step 1: 把锚点 2 加进 `main.py` 的 `PATCHES`**

修改 `main.py` 中 `PATCHES` 列表为:

```python
PATCHES = [
    (
        re.compile(rb'\w+\.\w+\.info\("updateMessagesMeRead"'),
        b"(window.__feishuAllowMeReadCount>0?window.__feishuAllowMeReadCount--:t.messageIds=[]),",
    ),
    (
        # Task 3 选定的字面值,把下面这行的字符串替换成实际选中的 pattern
        re.compile(rb'\w+\.\w+\.info\("sendMessage"'),
        b"window.__feishuAllowMeReadCount=2,",
    ),
]
```

注意:`b'\w+\.\w+\.info\("sendMessage"'` 中的 `sendMessage` 必须替换为 Task 3 Step 3 选定的实际字面值。Payload 末尾必须以 `,` 结尾(表达式逗号形式),除非 Task 3 Step 3 中发现锚点上下文不是参数列表(此时改用末尾 `;` 的 statement 形式)。

- [ ] **Step 2: 在 `tests/test_patch.py` 加测试,覆盖两条 PATCHES 都生效**

在 `tests/test_patch.py` 末尾(`if __name__` 之前)追加:

```python
class TwoAnchorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_both_real_patches_apply(self):
        # 取 PATCHES 中两条 pattern 的字面"代表样例",拼成同一份 fake js
        # 第一条:updateMessagesMeRead
        # 第二条:Task 3 选定的字符串(此处用 fake 的 "sendMessage" 占位,
        #   如果 Task 3 选定的字符串不同,请同步替换下方 sample 字面值)
        js = (
            b'function reader(){a.b.info("updateMessagesMeRead",t.messageIds);}\n'
            b'function sender(){c.d.info("sendMessage",msg);}\n'
        )
        p = self.tmpdir / "a.js"
        p.write_bytes(js)

        files_map = main.find_file(self.tmpdir, main.PATCHES)
        self.assertIn(p, files_map)
        anchors = files_map[p]
        self.assertEqual(len(anchors), 2)

        main.modify_file(p, anchors)
        modified = p.read_bytes()

        # 两个 payload 都应当出现且位置正确
        for _, payload in main.PATCHES:
            self.assertIn(payload, modified)

        # 锚点 1 的 payload 应在 'a.b.info("updateMessagesMeRead"' 之前
        idx1 = modified.index(b'a.b.info("updateMessagesMeRead"')
        self.assertEqual(
            modified[idx1 - len(main.PATCHES[0][1]):idx1],
            main.PATCHES[0][1],
        )
        # 锚点 2 的 payload 应在 'c.d.info("sendMessage"' 之前
        idx2 = modified.index(b'c.d.info("sendMessage"')
        self.assertEqual(
            modified[idx2 - len(main.PATCHES[1][1]):idx2],
            main.PATCHES[1][1],
        )
```

如果 Task 3 选定的字面不是 `"sendMessage"`,请把上面 fake js 中 `"sendMessage"` 替换为实际字符串。

- [ ] **Step 3: 运行测试**

Run: `python -m unittest discover -s tests -v`
Expected: 全部 PASS。

- [ ] **Step 4: 提交**

```bash
git add main.py tests/test_patch.py
git commit -m "feat: 新增 sendMessage 锚点,主动发送消息时放行已读上报"
```

(commit message 中的 `sendMessage` 视实际锚点字面调整。)

---

## Task 5: 真实 messenger.asar 端到端集成验证

**Files:**
- 无源文件修改;以双账号手工验证脚本是否在真实飞书中按预期工作。

> 自动化测试无法覆盖飞书 native 行为;此 task 是 spec 中"测试方案"的执行。

- [ ] **Step 1: 备份当前飞书状态**

确保飞书进程已关闭。如有 `messenger.asar.bak`,先把它重命名回 `messenger.asar`(以脚本退出条件为准):

```bash
# 仅在已有 bak 时执行;路径替换为本机实际路径
mv /path/to/feishu/.../webcontent/messenger.asar.bak /path/to/feishu/.../webcontent/messenger.asar
```

- [ ] **Step 2: 执行新版脚本**

```bash
python main.py /path/to/feishu/install
```

Expected: 输出 "修改完成。请重启飞书"。两个锚点都注入成功,无 "未找到 N 组锚点" 报错。

- [ ] **Step 3: 重启飞书,准备测试账号**

用主账号 + 测试账号(或同事配合)登录两端飞书客户端。

- [ ] **Step 4: 用例 1(回归 / 屏蔽看消息)**

操作:测试号给主账号发一条消息;主账号打开会话,**不回复**,停留 10 秒。
Expected: 测试号那一侧消息状态**仍显示"未读"**。

- [ ] **Step 5: 用例 2(新功能 / 发消息触发已读)**

操作:测试号再发一条新消息;主账号打开会话,**回复一条任意普通文本消息**。
Expected: 测试号那一侧此前的未读消息状态**变成"已读"**。

- [ ] **Step 6: 用例 3(放行严格性)**

操作:用例 2 完成后,测试号再发一条新消息;主账号**不打开会话,也不回复**,等待 30 秒。
Expected: 测试号那一侧此条新消息**仍显示"未读"**(放行计数器已消费完,不再放行)。

- [ ] **Step 7: 用例 4(群聊场景)**

操作:在一个测试群聊里,按用例 1–3 的顺序复测一遍。
Expected: 同上。

- [ ] **Step 8: 失败处理**

如果用例 2 失败(发送消息后对方仍显示未读):说明方案 A 不可行(飞书未在发送后自动触发 `updateMessagesMeRead`)。回退到 spec 中提到的方案 B(在发送回调里主动调用上报)。本计划停在此处,新开一个 plan。

如果用例 1 / 3 / 4 失败:可能是放行计数器初值过大、或锚点 2 选错(在浏览类入口而非发送入口)。回 Task 3 重选锚点 2。

- [ ] **Step 9: 通过全部用例 → 收尾**

```bash
git status   # 确认无未提交改动
```

无需 commit。

---

## Task 6: 更新 README

**Files:**
- Modify: `README.md`(原"已知问题 / TODO"小节)

- [ ] **Step 1: 修改 README "已知问题 / TODO" 小节**

原内容(`README.md:31-41`):

```markdown
## 已知问题 / TODO

毕竟只是在 js 层修改的逻辑,而非拦截网络请求等更加靠谱的方式。前端可能有多个入口
来进行消息已读回执的请求,导致在以下情况下对方会看到自己已读:

* 对一个消息进行引用并回复
* 对一个消息贴表情
* 接收对方发送的文件

此外要注意,飞书更新后会覆盖修改的文件,所以需要重新执行脚本来修改。
```

替换为:

```markdown
## 行为说明

普通看消息(打开会话/滚动浏览)不会让对方看到已读。**但主动回复对方消息后,
对方会看到该会话此前未读变为已读** —— 这是有意为之,因为只回不读对方会困惑。

## 已知问题 / TODO

前端可能有多个入口会进行消息已读回执的请求,以下情况仍可能让对方看到已读:

* 对一个消息进行引用并回复
* 对一个消息贴表情
* 接收对方发送的文件

此外,飞书更新后会覆盖修改的文件,所以需要重新执行脚本。
```

- [ ] **Step 2: 提交**

```bash
git add README.md
git commit -m "docs: README 增加发送消息触发已读的行为说明"
```

---

## 完成定义

- `python -m unittest discover -s tests -v` 全部 PASS。
- `python main.py <飞书安装目录>` 在真机上成功注入两处锚点。
- Task 5 的 4 个用例全部按预期通过。
- README 已更新行为说明。
- 所有改动已提交。
