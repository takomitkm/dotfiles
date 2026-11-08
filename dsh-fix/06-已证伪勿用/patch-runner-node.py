#!/usr/bin/env python3
"""DSH runner 补丁：把私有 subprocess runner 从 Electron 二进制换成随包 node.exe。

    python patch-runner-node.py status     # 只看状态（默认，不改任何东西）
    python patch-runner-node.py apply      # 打补丁（会备份）
    python patch-runner-node.py rollback   # 还原

原理
----
`dsh-subprocess-local/lib/runner-launch-*.js` 里 `spawnRunnerInvocation()` 用
`process.execPath` 当 runner 可执行文件；桌面版里那是 Electron（235 MB / RSS 152 MB）。
本脚本做两处**等长字节替换**，因此 app.asar 大小不变、头部偏移不变，只需同步改
`desktop-runtime.json` 里那条 sha256：

1. `…spawnRunnerInvocation` 里的 `process.execPath` → `process.env.NPTH`
   （两者都是 16 字节），并把 `NPTH = 随包 node.exe` 写进用户环境变量。
2. `desktop-runtime.json` 中该文件的 sha256 换成改后的实际哈希。

风险
----
* 依赖用户环境变量 `NPTH`。变量丢了 = 所有子进程类工具报错（会报得很响，不会静默）。
* App 升级会覆盖 app.asar，届时补丁消失，需要重新 apply。
* 只在 **Node 版本一致** 时安全：本机实测 Electron-as-node 与随包 node.exe 都是 24.21.0，
  且 koffi 走 Node-API（napi 10），同一个 koffi.node 在 node.exe 下加载成功。
"""
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time

ASAR = r"C:\Users\takomi\AppData\Local\Programs\DeepSeek Harness\resources\app.asar"
NODE_EXE = r"C:\Users\takomi\AppData\Local\Programs\DeepSeek Harness\resources\runtime\primary-runtime\dependencies\node\bin\node.exe"
RUNNER_REL = "node_modules/@deepseek-ai/dsh-subprocess-local/lib/runner-launch-B2zsQ1Dz.js"
MANIFEST_REL = "desktop-runtime.json"
# asar 内路径带 dsh/ 前缀，清单里的 path 不带
ASAR_RUNNER = "dsh/" + RUNNER_REL
ASAR_MANIFEST = "dsh/" + MANIFEST_REL
ENV_NAME = "NPTH"

ANCHOR = b'return [process.execPath, fileURLToPath(import.meta.resolve('
OLD = b"process.execPath"           # 16 bytes
NEW = b"process.env.NPTH"           # 16 bytes


def read_header(path):
    """asar: u32=4 | u32=header_size | u32=? | u32=json_len | json... | data
    JSON 从第 16 字节开始，数据区起点 = 8 + header_size。"""
    with open(path, "rb") as f:
        head = f.read(16)
        h_size = struct.unpack("<I", head[4:8])[0]
        str_len = struct.unpack("<I", head[12:16])[0]
        hdr = json.loads(f.read(str_len).decode("utf-8"))
    return hdr, 8 + h_size


def walk(node, prefix=""):
    out = []
    for name, meta in (node.get("files") or {}).items():
        p = f"{prefix}/{name}"
        if "files" in meta:
            out += walk(meta, p)
        else:
            out.append((p.lstrip("/"), int(meta.get("offset", -1)), int(meta.get("size", 0))))
    return out


def entries():
    hdr, base = read_header(ASAR)
    return {p: (o, s) for p, o, s in walk(hdr)}, base


def read_entry(path):
    ents, base = entries()
    if path not in ents:
        raise SystemExit(f"找不到 asar 条目: {path}")
    off, size = ents[path]
    with open(ASAR, "rb") as f:
        f.seek(base + off)
        return bytearray(f.read(size)), base + off


def write_back(offset_abs, data):
    with open(ASAR, "r+b") as f:
        f.seek(offset_abs)
        f.write(bytes(data))


def env_value():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as k:
            return winreg.QueryValueEx(k, ENV_NAME)[0]
    except OSError:
        return None
    except Exception:
        return None


def broadcast_env_change():
    """告诉 Explorer 环境变量变了，否则新启动的应用继承的是旧环境（会拿不到 NPTH）。"""
    try:
        import ctypes
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        res = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, ctypes.c_wchar_p("Environment"),
            SMTO_ABORTIFHUNG, 3000, ctypes.byref(res))
        print("  已广播 WM_SETTINGCHANGE(Environment)")
    except Exception as e:  # noqa: BLE001
        print(f"  广播失败（不影响已设变量，重启即可）: {e}")


def set_env(value):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_SET_VALUE) as k:
        if value is None:
            try:
                winreg.DeleteValue(k, ENV_NAME)
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(k, ENV_NAME, 0, winreg.REG_SZ, value)
    broadcast_env_change()


def status():
    js, _ = read_entry(ASAR_RUNNER)
    patched = NEW in js
    n_anchor = js.count(ANCHOR)
    old_left = js.count(OLD)
    node_ok = os.path.isfile(NODE_EXE)
    ev = env_value()
    man, _ = read_entry(ASAR_MANIFEST)
    rec = json.loads(man.decode("utf-8"))
    expect = None
    for e in rec.get("files", []):
        if e.get("path") == RUNNER_REL:
            expect = e.get("sha256")
            break
    actual = hashlib.sha256(bytes(js)).hexdigest()
    print(f"asar           : {ASAR}")
    print(f"runner 文件    : {RUNNER_REL}")
    print(f"  已打补丁     : {patched}")
    print(f"  锚点出现次数 : {n_anchor}  (生产分支应为 1)")
    print(f"  剩余 execPath: {old_left}")
    print(f"  清单 sha256  : {expect}")
    print(f"  实际 sha256  : {actual}   {'OK' if expect == actual else '不一致'}")
    print(f"node.exe       : {'存在' if node_ok else '缺失'}  {NODE_EXE}")
    print(f"用户环境 {ENV_NAME}   : {ev!r}")
    if patched and not node_ok:
        print("\n!! 已打补丁但 node.exe 不存在 —— 先 rollback")
    if patched and not ev:
        print(f"\n!! 已打补丁但 {ENV_NAME} 未设置 —— 所有子进程类工具会报错，先 rollback 或补设变量")


def apply():
    ts = time.strftime("%Y%m%d-%H%M%S")
    js, js_off = read_entry(ASAR_RUNNER)
    if NEW in js:
        print("已经是打过补丁的状态，什么都不做。")
        return status()
    if js.count(ANCHOR) != 1:
        raise SystemExit(f"锚点出现 {js.count(ANCHOR)} 次（期望 1），放弃以防误改")
    i = js.find(ANCHOR)
    j = js.find(OLD, i, i + len(ANCHOR) + 64)
    if j < 0:
        raise SystemExit("在锚点后面找不到 process.execPath，放弃")
    if len(OLD) != len(NEW):
        raise SystemExit("替换长度不等，放弃（会破坏 asar 头部偏移）")

    backup = ASAR + f".bak-runner-node-{ts}"
    print(f"备份 -> {backup}")
    shutil.copy2(ASAR, backup)

    js[j:j + len(OLD)] = NEW
    write_back(js_off, js)
    new_hash = hashlib.sha256(bytes(js)).hexdigest()
    print(f"runner 已改写，新 sha256 = {new_hash}")

    man, man_off = read_entry(ASAR_MANIFEST)
    rec = json.loads(man.decode("utf-8"))
    hit = None
    for e in rec.get("files", []):
        if e.get("path") == RUNNER_REL:
            hit = e
            break
    if hit is None:
        raise SystemExit("清单里找不到该文件条目，放弃（请先 rollback 备份）")
    old_hash = hit["sha256"]
    pos = man.decode("utf-8").find(f'"{old_hash}"')
    if pos < 0 or len(old_hash) != 64:
        raise SystemExit("清单里的哈希串定位失败，放弃（请先 rollback 备份）")
    man[pos + 1:pos + 65] = new_hash.encode("ascii")
    write_back(man_off, man)
    print(f"清单 sha256 已更新 {old_hash[:12]}… -> {new_hash[:12]}…")

    set_env(NODE_EXE)
    print(f"用户环境变量 {ENV_NAME} = {NODE_EXE}")
    print("\n完成。**重启 DSH 后生效**。")
    status()


def rollback():
    cands = sorted(
        [os.path.join(os.path.dirname(ASAR), f) for f in os.listdir(os.path.dirname(ASAR))
         if f.startswith("app.asar.bak-runner-node-")],
        key=os.path.getmtime, reverse=True)
    if not cands:
        raise SystemExit("没有找到本脚本的备份（app.asar.bak-runner-node-*），无法自动回滚")
    src = cands[0]
    print(f"从备份恢复: {src}")
    shutil.copy2(src, ASAR)
    set_env(None)
    print(f"已删除用户环境变量 {ENV_NAME}")
    status()


if __name__ == "__main__":
    action = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    {"status": status, "apply": apply, "rollback": rollback}.get(
        action, lambda: print("用法: status | apply | rollback"))()