#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dsh-fix.py — DeepSeek Harness 本地补丁套件（单文件 / status·apply·rollback 子命令）

为什么存在:
  DSH 自动更新会整体覆盖 resources\\app.asar，本机补丁随之丢失。
  本脚本把"更新后重打补丁"做成一条命令；官方已修的部分自动跳过。

补丁清单（均为发行版未带的修复，上游讨论可见）:
  P1  inspector 保留态信封预算
      讨论: deepseek-ai/deepseek-harness #9271 / #10259
      参考: damokelis fork commit 7a28f53（master 已于 2026-11-04 以 57aae95 采纳同方案）
      文件: @deepseek-ai/dsh-experimental-inspector/lib/{index.js,client.js}
      效果: 消除 "inspector: source state exceeds the source-frame byte limit"
            → uncaught exception → Host exit 1 的崩溃类。
  P2  storage-json writeAtomic 瞬态重试
      讨论: #9575 / #10724 / #1628
      参考: @deepseek-ai/dsh-atomic-write commit 3e56eaa 的重试策略
            （EACCES/EBUSY/EPERM，有界退避；storage-json 至今未接入）
      文件: @deepseek-ai/dsh-storage-json/lib/index.js
      效果: Windows 上目标文件被杀软/索引器瞬时占用时 rename 报 EPERM，
            原实现一次失败即 fatal 退出宿主；补丁后最多重试 7 次（20→200ms）。

实现方式:
  原地改 asar，不重打包。每个目标文件补丁后按字节补回原长度（缩短块注释），
  再同步更新 asar 头部 JSON 里该文件的 SHA256 integrity（hash + blocks）。
  apply 完成后：读回校验哈希 + 自带 node --check 语法校验，任一失败自动回滚。

用法:
  python dsh-fix.py              # 只读状态（默认；双击即看状态）
  python dsh-fix.py status
  python dsh-fix.py apply [--yes]
  python dsh-fix.py rollback [--yes]   # 从最新备份恢复（撤销最近一次 apply）

注意:
  另有一个独立补丁"runner 换 node.exe"，由同目录 patch-runner-node.py 负责
  （自带 status/apply/rollback），更新后也要重打，见同目录 README.txt。
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time

APP_DIR = os.environ.get('DSH_APP_DIR') or os.path.join(
    os.environ.get('LOCALAPPDATA', r'C:\Users\takomi\AppData\Local'),
    'Programs', 'DeepSeek Harness')
ASAR = os.path.join(APP_DIR, 'resources', 'app.asar')
RES_DIR = os.path.join(APP_DIR, 'resources')
NODE_CANDIDATES = [
    os.path.join(APP_DIR, 'resources', 'runtime', 'primary-runtime', 'dependencies', 'node', 'bin', 'node.exe'),
    os.path.join(os.environ.get('USERPROFILE', ''), '.dsh', 'dsh-runtimes',
                 'dsh-primary-runtime', 'dependencies', 'node', 'bin', 'node.exe'),
]

INSPECTOR_LIB = 'dsh/node_modules/@deepseek-ai/dsh-experimental-inspector/lib/'
STORAGE_LIB = 'dsh/node_modules/@deepseek-ai/dsh-storage-json/lib/'

# ---------------- P1（与已验证的 apply-9271.py 完全同款） ----------------
P1_MARKER = 'const envelopeBytes = jsonByteLength('
P1_ENVELOPE_LINE = (
    'const envelopeBytes = jsonByteLength([{ monotonicMs: 0, topic: CORDIS_TREE_TOPIC, payload: null }]) '
    '- jsonByteLength(null) - 1 + 32;'
)

# ---------------- P2 ----------------
P2_ANCHOR = '\t\tawait rename(tmp, path);\n'
P2_BLOCK_READABLE = (
    '\t\tfor (let attempt = 0, delay = 20; ; attempt += 1) try {\n'
    '\t\t\tawait rename(tmp, path);\n'
    '\t\t\tbreak;\n'
    '\t\t} catch (error) {\n'
    '\t\t\tif (attempt > 6 || (error.code !== "EPERM" && error.code !== "EACCES" && error.code !== "EBUSY")) throw error;\n'
    '\t\t\tawait new Promise((resolve) => setTimeout(resolve, delay));\n'
    '\t\t\tdelay = Math.min(delay * 2, 200);\n'
    '\t\t}\n'
)
P2_BLOCK_COMPACT = (
    '\t\tfor (let a = 0, d = 20; ; a += 1) try { await rename(tmp, path); break; } catch (error) { '
    'if (a > 6 || (error.code !== "EPERM" && error.code !== "EACCES" && error.code !== "EBUSY")) throw error; '
    'await new Promise((r) => setTimeout(r, d)); d = Math.min(d * 2, 200); }\n'
)


def out_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def find_node():
    for p in NODE_CANDIDATES:
        if p and os.path.isfile(p):
            return p
    return None


def parse_asar(path):
    """返回 (entries, data_start, data, header_bytes)。
    asar 布局: u32=4 | u32=header_size | u32=? | u32=json_len | json... | 数据区
    数据区起点 = 8 + header_size（与 patch-runner-node.py 一致）。"""
    with open(path, 'rb') as f:
        head = f.read(16)
        if len(head) < 16:
            raise SystemExit('asar 文件太小: ' + path)
        header_size = struct.unpack('<I', head[4:8])[0]
        str_len = struct.unpack('<I', head[12:16])[0]
        raw = f.read(str_len).decode('utf-8', 'replace')
    depth = 0
    end = None
    for i, ch in enumerate(raw):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise SystemExit('无法解析 asar 头部 JSON')
    header = json.loads(raw[:end])
    data_start = 8 + header_size

    def walk(node, prefix=''):
        files = node.get('files')
        if files:
            for name, child in files.items():
                p = prefix + '/' + name if prefix else name
                if child.get('files') is not None:
                    yield from walk(child, p)
                else:
                    yield p, child

    entries = {p: e for p, e in walk(header)}
    data = open(path, 'rb').read()
    return entries, data_start, data, data[:data_start]


def entry_bytes(entries, ds, data, rel):
    e = entries.get(rel)
    if e is None:
        return None
    off = ds + int(e['offset'])
    return data[off:off + e['size']]


def pad_to(b, target):
    """字节级补回原长度：删块注释中段 / 不足则补换行（与 apply-9271.py 同款）。"""
    delta = len(b) - target
    if delta == 0:
        return b
    if delta < 0:
        return b + b'\n' * (-delta)
    idx = 0
    while True:
        i = b.find(b'/**', idx)
        if i < 0:
            break
        j = b.find(b'*/', i + 3)
        if j < 0:
            break
        if (j - (i + 3)) >= delta + 8:
            return b[:j - delta] + b[j:]
        idx = j + 2
    raise ValueError('没有足够长的块注释可删 %d 字节' % delta)


def p1_patch(content):
    """inspector: publishCordisTree 预留信封（返回新文本或 None=已打/找不到锚点）。"""
    if P1_MARKER in content:
        return None
    i = content.find('function publishCordisTree(ctx, publisher, limits) {')
    if i < 0:
        raise ValueError('P1 锚点 function publishCordisTree 未找到')
    j = content.find('}, limits);', i)
    if j < 0:
        raise ValueError('P1 结束锚点 }, limits); 未找到')
    k = content.find('\n', j)
    m = re.match(r'\n([ \t]*)\}', content[k:])
    if not m:
        raise ValueError('P1 收尾大括号未匹配')
    ls = content.rfind('\n', 0, i) + 1
    findent = content[ls:i]
    inner = findent + '\t'
    newblock = (
        findent + 'function publishCordisTree(ctx, publisher, limits) {\n'
        + inner + P1_ENVELOPE_LINE + '\n'
        + inner + 'return observeCordisTree(ctx, (snapshot) => {\n'
        + inner + '\tpublisher.setState(CORDIS_TREE_TOPIC, snapshot);\n'
        + inner + '}, { ...limits, maxBytes: limits.maxBytes - envelopeBytes });\n'
        + findent + '}'
    )
    end = k + m.end()
    return content[:i] + newblock + content[end:]


def p2_patch(content):
    """storage-json: writeAtomic 的 rename 加退避重试。返回 (新文本, 变体名) 或 (None, 原因)。"""
    func_start = content.find('async function writeAtomic')
    if func_start < 0:
        return None, 'writeAtomic 未找到'
    total = content.count(P2_ANCHOR)
    if total != 1:
        return None, 'P2 锚点出现 %d 次（应为 1），拒绝盲替换' % total
    if 'setTimeout(resolve, delay)' in content[func_start:func_start + 1500]:
        return None, 'already'
    for name, block in (('readable', P2_BLOCK_READABLE), ('compact', P2_BLOCK_COMPACT)):
        new = content.replace(P2_ANCHOR, block, 1)
        if P2_ANCHOR not in new:
            return new, name
    return None, '替换失败'


def p1_done(content):
    return P1_MARKER in content


def p2_done(content):
    i = content.find('async function writeAtomic')
    if i < 0:
        return False
    body = content[i:i + 1500]
    return 'setTimeout' in body and 'await rename(tmp, path);' in body


def dsh_running():
    try:
        r = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq DeepSeek Harness.exe'],
            capture_output=True, text=True, timeout=15)
        return 'DeepSeek Harness.exe' in (r.stdout or '')
    except Exception:
        return False


def list_backups():
    """按文件名内嵌时间戳排序（copy2 保留原 mtime，mtime 不可靠）。"""
    pat = re.compile(r'^(?:app\.asar\.bak|app\.asar\.prepatch|app\.asar\.bak-runner-node)-(\d{8}-\d{6})')
    out = []
    try:
        names = os.listdir(RES_DIR)
    except OSError:
        return out
    for n in names:
        m = pat.match(n)
        if m:
            full = os.path.join(RES_DIR, n)
            if os.path.isfile(full):
                out.append((m.group(1), full))
    out.sort(reverse=True)
    return out


def node_check(node_exe, text, tag):
    if not node_exe:
        print('  [WARN] 未找到 node.exe，跳过语法校验:', tag)
        return True
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix='.mjs', prefix='dsh-check-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        r = subprocess.run([node_exe, '--check', tmp], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            print('  [FAIL] 语法校验失败:', tag)
            print((r.stderr or '')[:800])
            return False
        print('  [OK] 语法校验通过:', tag)
        return True
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def get_version(entries, ds, data):
    b = entry_bytes(entries, ds, data, 'package.json')
    if not b:
        return '?'
    try:
        return json.loads(b.decode('utf-8')).get('version', '?')
    except Exception:
        return '?'


def read_entry_text(entries, ds, data, rel):
    b = entry_bytes(entries, ds, data, rel)
    if b is None:
        return None
    return b.decode('utf-8')  # strict：出现非 UTF-8 说明布局变了，宁可拒绝


def cmd_status():
    print('app.asar:', ASAR)
    if not os.path.isfile(ASAR):
        print('  [ERROR] 文件不存在')
        return 1
    st = os.stat(ASAR)
    print('  size=%d  mtime=%s' % (st.st_size, time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))))
    entries, ds, data, _ = parse_asar(ASAR)
    print('  DSH version:', get_version(entries, ds, data))
    print('  DSH running:', dsh_running())

    print('\nP1 inspector (#9271):')
    for fn in ('index.js', 'client.js'):
        rel = INSPECTOR_LIB + fn
        try:
            text = read_entry_text(entries, ds, data, rel)
        except Exception as ex:
            print('  %-10s 读取失败: %s' % (fn, ex))
            continue
        if text is None:
            print('  %-10s 不存在' % fn)
        elif p1_done(text):
            print('  %-10s ✓ 已打' % fn)
        else:
            print('  %-10s ✗ 未打' % fn)

    print('\nP2 storage-json (#9575):')
    rel = STORAGE_LIB + 'index.js'
    try:
        text = read_entry_text(entries, ds, data, rel)
    except Exception as ex:
        print('  读取失败:', ex)
        text = None
    if text is None:
        print('  index.js 不存在')
    elif p2_done(text):
        print('  index.js   ✓ 已打')
    else:
        print('  index.js   ✗ 未打')

    print('\n备份（按名称时间戳，新→旧，最多 5 条）:')
    for ts, path in list_backups()[:5]:
        print('  %s  %s' % (ts, os.path.basename(path)))
    print('\n提示: 本脚本只含 P1/P2。runner 换 node.exe 的方案已证伪（见 06-已证伪勿用），此处不涉及。')
    return 0


def cmd_apply(yes):
    if dsh_running() and not yes:
        ans = input('[!] DeepSeek Harness 正在运行。继续打补丁？（生效需重启）[y/N]: ')
        if ans.strip().lower() != 'y':
            print('已取消。')
            return 0
    entries, ds, data, header_bytes = parse_asar(ASAR)

    # --- 计划 ---
    jobs = []  # (rel, old_text, new_bytes)
    for fn in ('index.js', 'client.js'):
        rel = INSPECTOR_LIB + fn
        try:
            text = read_entry_text(entries, ds, data, rel)
        except Exception as ex:
            print('[ABORT] %s 读取失败: %s' % (rel, ex))
            return 1
        if text is None:
            print('[ABORT] asar 内不存在:', rel)
            return 1
        if p1_done(text):
            print('[SKIP] P1 %s 已打' % fn)
            continue
        try:
            new_text = p1_patch(text)
        except ValueError as ex:
            print('[ABORT] P1 %s: %s' % (fn, ex))
            return 1
        jobs.append((rel, fn, text, new_text))

    rel2 = STORAGE_LIB + 'index.js'
    try:
        text2 = read_entry_text(entries, ds, data, rel2)
    except Exception as ex:
        print('[ABORT] %s 读取失败: %s' % (rel2, ex))
        return 1
    if text2 is None:
        print('[ABORT] asar 内不存在:', rel2)
        return 1
    if p2_done(text2):
        print('[SKIP] P2 storage-json 已打')
    else:
        new2, variant = p2_patch(text2)
        if new2 is None:
            print('[ABORT] P2: %s' % variant)
            return 1
        print('[INFO] P2 使用 %s 变体' % variant)
        jobs.append((rel2, 'storage-json', text2, new2))

    if not jobs:
        print('所有补丁均已生效，无需操作。')
        return 0

    # --- 备份 ---
    ts = time.strftime('%Y%m%d-%H%M%S')
    bak = os.path.join(RES_DIR, 'app.asar.prepatch-' + ts)
    shutil.copy2(ASAR, bak)
    print('[OK] 备份: %s' % os.path.basename(bak))

    # --- 写入 ---
    node_exe = find_node()
    ok_all = True
    checked = []  # (rel, new_text)
    try:
        with open(ASAR, 'r+b') as f:
            hdr = header_bytes
            for rel, tag, old_text, new_text in jobs:
                e = entries[rel]
                off = ds + int(e['offset'])
                size = e['size']
                new_b = new_text.encode('utf-8')
                try:
                    new_b = pad_to(new_b, size)
                except ValueError as ex:
                    print('[ABORT] %s 补长失败: %s' % (tag, ex))
                    ok_all = False
                    break
                if len(new_b) != size:
                    print('[ABORT] %s 长度不等于原长' % tag)
                    ok_all = False
                    break
                old_hash = hashlib.sha256(old_text.encode('utf-8')).hexdigest()
                new_hash = hashlib.sha256(new_b).hexdigest()
                f.seek(off)
                f.write(new_b)
                ob, nb = old_hash.encode(), new_hash.encode()
                pos, count = 0, 0
                while True:
                    i = hdr.find(ob, pos)
                    if i < 0:
                        break
                    hdr = hdr[:i] + nb + hdr[i + len(ob):]
                    count += 1
                    pos = i + len(nb)
                if count == 0:
                    print('[ABORT] %s 头部未找到旧哈希' % tag)
                    ok_all = False
                    break
                print('[OK] %s 已写入（头部哈希更新 %d 处）' % (tag, count))
                checked.append((rel, tag, new_text if isinstance(new_text, str) else new_text.decode('utf-8')))
            if ok_all:
                f.seek(0)
                f.write(hdr)
                f.flush()
                os.fsync(f.fileno())
    except Exception as ex:
        print('[ERROR] 写入阶段异常: %r' % ex)
        ok_all = False

    if not ok_all:
        shutil.copy2(bak, ASAR)
        print('[ROLLBACK] 已从备份恢复。')
        return 1

    # --- 读回校验 + 语法 ---
    entries2, ds2, data2, _ = parse_asar(ASAR)
    for rel, tag, new_text in checked:
        e = entries2[rel]
        b = data2[ds2 + int(e['offset']): ds2 + int(e['offset']) + e['size']]
        if hashlib.sha256(b).hexdigest() != e['integrity']['hash']:
            print('[FAIL] %s 读回哈希与头部不一致' % tag)
            ok_all = False
            continue
        actual = b.decode('utf-8')
        if 'rename(tmp, path)' not in actual and 'publishCordisTree' not in actual:
            print('[FAIL] %s 读回内容异常' % tag)
            ok_all = False
            continue
        if not node_check(node_exe, actual, tag):
            ok_all = False

    if not ok_all:
        shutil.copy2(bak, ASAR)
        print('[ROLLBACK] 校验失败，已从备份恢复。')
        return 1

    print('\n[DONE] 补丁完成，重启 DeepSeek Harness 生效。')
    print('[INFO] 撤销本次: python dsh-fix.py rollback')
    return 0


def cmd_rollback(yes):
    backups = list_backups()
    if not backups:
        print('[ERROR] 找不到任何备份。')
        return 1
    if dsh_running() and not yes:
        ans = input('[!] DSH 正在运行，回滚前建议先关闭。继续？[y/N]: ')
        if ans.strip().lower() != 'y':
            print('已取消。')
            return 0
    ts, newest = backups[0]
    print('[INFO] 从最新备份恢复: %s (%s)' % (os.path.basename(newest), ts))
    shutil.copy2(newest, ASAR)
    print('[DONE] 已恢复，重启 DSH 生效。')
    print('[INFO] 若要回到出厂原始版，请手动使用更早的备份文件。')
    return 0


def main():
    out_utf8()
    ap = argparse.ArgumentParser(description='DSH 本地补丁套件')
    ap.add_argument('command', nargs='?', default='status', choices=['status', 'apply', 'rollback'])
    ap.add_argument('--yes', action='store_true', help='跳过交互确认')
    args = ap.parse_args()
    if args.command == 'status':
        sys.exit(cmd_status())
    if args.command == 'apply':
        sys.exit(cmd_apply(args.yes))
    if args.command == 'rollback':
        sys.exit(cmd_rollback(args.yes))


if __name__ == '__main__':
    main()
