#!/usr/bin/env python3
"""Apply the #9271 fix to the installed DeepSeek Harness app.

Fix: deepseek-ai/deepseek-harness, discussion #9271
  damokelis/deepseek-harness@fix/inspector-retained-state-budget
  commit 7a28f5392be77db2144c3c56271d75e03155dd15
  "fix(inspector): reserve retained-record envelope in Cordis tree budget"

It patches publishCordisTree() in @deepseek-ai/dsh-experimental-inspector
(lib/index.js for the Host, lib/client.js for the Client) so the collector
budget reserves the retained-record envelope. The archive is edited in place:
file byte lengths are preserved and the header SHA256 integrity is updated,
so no asar repack and no offset relocation is needed.

Usage:
  python apply-9271.py            # patch the default install
  set DSH_APP_DIR=C:\\path\\to\\app && python apply-9271.py

The script is idempotent: if the patch is already present it reports that and
exits 0. It backs up app.asar to app.asar.prepatch-<timestamp> first and
restores it automatically if anything fails.
"""

import hashlib
import json
import os
import re
import shutil
import struct
import sys
import time

APP = os.environ.get('DSH_APP_DIR') or r'C:\Users\takomi\AppData\Local\Programs\DeepSeek Harness'
ASAR = os.path.join(APP, 'resources', 'app.asar')
LIB_SUFFIX = 'dsh/node_modules/@deepseek-ai/dsh-experimental-inspector/lib/'
FILES = ('index.js', 'client.js')
ENVELOPE_LINE = (
    'const envelopeBytes = jsonByteLength([{ monotonicMs: 0, topic: CORDIS_TREE_TOPIC, payload: null }]) '
    '- jsonByteLength(null) - 1 + 32;'
)


def fail(msg):
    print('[ERROR] ' + msg)
    sys.exit(1)


def parse_header(data):
    if len(data) < 16:
        fail('asar is too small')
    json_size = struct.unpack_from('<I', data, 8)[0]
    raw = data[16:16 + json_size].decode('utf-8', 'replace')
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
        fail('cannot parse the asar header JSON')
    header = json.loads(raw[:end])
    data_start = (16 + end + 3) & ~3
    return header, data_start


def walk(node, path=''):
    files = node.get('files')
    if files:
        for name, child in files.items():
            p = path + '/' + name if path else name
            if child.get('files') is not None:
                yield from walk(child, p)
            else:
                yield p, child


def patch_function(b):
    """Return patched bytes, or None when the function is already patched."""
    s = b.decode('utf-8')
    if 'const envelopeBytes = jsonByteLength(' in s:
        return None
    i = s.find('function publishCordisTree(ctx, publisher, limits) {')
    if i < 0:
        fail('publishCordisTree not found (app layout changed?)')
    j = s.find('}, limits);', i)
    if j < 0:
        fail('publishCordisTree end not found (app layout changed?)')
    k = s.find('\n', j)
    m = re.match(r'\n([ \t]*)\}', s[k:])
    if not m:
        fail('publishCordisTree closing brace not found')
    ls = s.rfind('\n', 0, i) + 1
    findent = s[ls:i]
    inner = findent + '\t'
    newblock = (
        findent + 'function publishCordisTree(ctx, publisher, limits) {\n'
        + inner + ENVELOPE_LINE + '\n'
        + inner + 'return observeCordisTree(ctx, (snapshot) => {\n'
        + inner + '\tpublisher.setState(CORDIS_TREE_TOPIC, snapshot);\n'
        + inner + '}, { ...limits, maxBytes: limits.maxBytes - envelopeBytes });\n'
        + findent + '}'
    )
    end = k + m.end()
    return (s[:i] + newblock + s[end:]).encode('utf-8')


def pad_to(b, target):
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
    fail('no comment block large enough to pad the file back to its original length')


def main():
    if not os.path.exists(ASAR):
        fail('app.asar not found: ' + ASAR)
    data = open(ASAR, 'rb').read()
    header, data_start = parse_header(data)
    entries = {p: e for p, e in walk(header)}
    print('app.asar :', ASAR)
    print('data_start:', data_start)

    probe = entries.get(LIB_SUFFIX + 'index.js')
    if probe is None:
        fail('inspector index.js entry not found in header')
    cur = data[data_start + int(probe['offset']): data_start + int(probe['offset']) + probe['size']]
    if b'const envelopeBytes = jsonByteLength(' in cur:
        print('[OK] already patched; nothing to do')
        return 0

    bak = ASAR + '.prepatch-' + time.strftime('%Y%m%d-%H%M%S')
    shutil.copy2(ASAR, bak)
    print('backup   :', bak)

    f = None
    try:
        f = open(ASAR, 'r+b')
        header_bytes = f.read(data_start)
        for name in FILES:
            path = LIB_SUFFIX + name
            ent = entries.get(path)
            if ent is None:
                fail('entry not found: ' + path)
            off, size = int(ent['offset']), ent['size']
            old_hash = ent['integrity']['hash']
            cur = data[data_start + off: data_start + off + size]
            if hashlib.sha256(cur).hexdigest() != old_hash:
                fail('content/hash mismatch for ' + name + '; archive is not in the expected state')
            patched = patch_function(cur)
            if patched is None:
                print('[OK]', name, 'already patched')
                continue
            patched = pad_to(patched, size)
            if len(patched) != size:
                fail('padding did not restore the original length for ' + name)
            new_hash = hashlib.sha256(patched).hexdigest()
            f.seek(data_start + off)
            f.write(patched)
            oldb, newb = old_hash.encode(), new_hash.encode()
            pos = 0
            count = 0
            while True:
                i = header_bytes.find(oldb, pos)
                if i < 0:
                    break
                f.seek(i)
                f.write(newb)
                count += 1
                pos = i + len(oldb)
            if count == 0:
                fail('old integrity hash not found in header for ' + name)
            print('[OK]', name, 'patched; header hashes updated:', count)
        f.flush()
        os.fsync(f.fileno())
        f.close()
        f = None
        print('[DONE] patch applied. Restart DeepSeek Harness to activate it.')
        return 0
    except SystemExit:
        if f is not None:
            try:
                f.close()
            except Exception:
                pass
        shutil.copy2(bak, ASAR)
        raise
    except Exception as ex:
        if f is not None:
            try:
                f.close()
            except Exception:
                pass
        shutil.copy2(bak, ASAR)
        fail('write failed (%s: %s); restored the backup' % (type(ex).__name__, ex))
    return 1


if __name__ == '__main__':
    sys.exit(main())