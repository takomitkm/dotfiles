# coding: utf-8
"""
清理 DSH（DeepSeek Harness）沙盒留在工作区根上的完整性标签与两条 ACE。

双击运行：检查默认目录（S:\\apps\\llm\\agentwork、S:\\work\\WCIS），
列出要删的东西，确认后执行。也可以在命令行传入别的目录，或用鼠标把目录
拖到脚本上。

只做两件事：
  1. 删除该目录根上的 Mandatory Label（Low/High 等），恢复到"没有标签"
     （有效完整性级别 = Medium）；
  2. 删除两类 ACE：
       - DENY Everyone（掩码含 FILE_DELETE_CHILD）
       - SID 以 S-1-4- 开头的 allow（DSH 的 workspace capability）
其余 ACE 一律保留。

标签与 ACE 的删除会由 Windows 自动传播到整棵子树；目录很大时要跑几分钟
到十几分钟。DSH 下次以 workspace-write 打开同一目录会重新种回来，重跑本
脚本即可。
"""

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

SE_FILE_OBJECT = 1
DACL_SECURITY_INFORMATION = 0x00000004
LABEL_SECURITY_INFORMATION = 0x00000010
FILE_DELETE_CHILD = 0x40
ACCESS_DENIED_ACE_TYPE = 1
EVERYONE_SID = "S-1-1-0"

DEFAULT_TARGETS = [
    r"S:\apps\llm\agentwork",
    r"S:\work\WCIS",
]


class ACE_HEADER(ctypes.Structure):
    _fields_ = [
        ("AceType", ctypes.c_ubyte),
        ("AceFlags", ctypes.c_ubyte),
        ("AceSize", wintypes.WORD),
    ]


class ACL_SIZE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("AceCount", wintypes.DWORD),
        ("AclBytesInUse", wintypes.DWORD),
        ("AclBytesFree", wintypes.DWORD),
    ]


class SECURITY_DESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("Revision", ctypes.c_ubyte),
        ("Sbz1", ctypes.c_ubyte),
        ("Control", wintypes.WORD),
        ("Owner", ctypes.c_void_p),
        ("Group", ctypes.c_void_p),
        ("Sacl", ctypes.c_void_p),
        ("Dacl", ctypes.c_void_p),
    ]


class ACL(ctypes.Structure):
    _fields_ = [
        ("AclRevision", ctypes.c_ubyte),
        ("Sbz1", ctypes.c_ubyte),
        ("AclSize", wintypes.WORD),
        ("AceCount", wintypes.WORD),
        ("Sbz2", wintypes.WORD),
    ]


advapi32.GetNamedSecurityInfoW.argtypes = [
    wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_void_p),
]
advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
advapi32.GetAclInformation.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_int]
advapi32.GetAclInformation.restype = wintypes.BOOL
advapi32.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
advapi32.GetAce.restype = wintypes.BOOL
advapi32.InitializeAcl.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
advapi32.InitializeAcl.restype = wintypes.BOOL
advapi32.AddAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
advapi32.AddAce.restype = wintypes.BOOL
advapi32.SetNamedSecurityInfoW.argtypes = [
    wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
]
advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
advapi32.InitializeSecurityDescriptor.argtypes = [ctypes.c_void_p, wintypes.DWORD]
advapi32.InitializeSecurityDescriptor.restype = wintypes.BOOL
advapi32.SetSecurityDescriptorSacl.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                               ctypes.c_void_p, wintypes.BOOL]
advapi32.SetSecurityDescriptorSacl.restype = wintypes.BOOL
kernel32.LocalFree.argtypes = [ctypes.c_void_p]
kernel32.LocalFree.restype = ctypes.c_void_p
kernel32.GetVolumeInformationW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD,
]
kernel32.GetVolumeInformationW.restype = wintypes.BOOL


def sid_to_str(p):
    out = wintypes.LPWSTR()
    if not advapi32.ConvertSidToStringSidW(p, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return out.value
    finally:
        kernel32.LocalFree(out)


def is_ntfs(path):
    root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
    fs = ctypes.create_unicode_buffer(64)
    ok = kernel32.GetVolumeInformationW(root, None, 0, None, None, None, fs, 64)
    return bool(ok) and fs.value.upper() == "NTFS"


def read_dacl(path):
    sd = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    rc = advapi32.GetNamedSecurityInfoW(
        path, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
        None, None, ctypes.byref(dacl), None, ctypes.byref(sd),
    )
    if rc != 0:
        raise OSError(rc, "GetNamedSecurityInfoW: " + ctypes.FormatError(rc))
    return sd, dacl


def acl_revision(dacl):
    return ctypes.cast(dacl, ctypes.POINTER(ctypes.c_ubyte))[0]


def list_aces(dacl):
    info = ACL_SIZE_INFORMATION()
    if not advapi32.GetAclInformation(dacl, ctypes.byref(info), ctypes.sizeof(info), 2):
        raise ctypes.WinError(ctypes.get_last_error())
    out = []
    for i in range(info.AceCount):
        acep = ctypes.c_void_p()
        if not advapi32.GetAce(dacl, i, ctypes.byref(acep)):
            raise ctypes.WinError(ctypes.get_last_error())
        hdr = ctypes.cast(acep, ctypes.POINTER(ACE_HEADER)).contents
        mask = ctypes.cast(acep.value + 4, ctypes.POINTER(wintypes.DWORD)).contents.value
        out.append({
            "index": i, "ptr": acep.value, "type": hdr.AceType,
            "flags": hdr.AceFlags, "size": hdr.AceSize, "mask": mask,
            "sid": sid_to_str(acep.value + 8),
        })
    return info, out


def is_dsh_ace(ace):
    if ace["sid"].startswith("S-1-4-"):
        return True
    if ace["type"] == ACCESS_DENIED_ACE_TYPE and ace["sid"] == EVERYONE_SID and ace["mask"] & FILE_DELETE_CHILD:
        return True
    return False


def has_label(path):
    try:
        out = subprocess.run(["icacls", path], capture_output=True, text=True, errors="replace")
    except OSError:
        return False
    return "Mandatory Label" in (out.stdout or "")


def clear_label(path):
    sd = SECURITY_DESCRIPTOR()
    if not advapi32.InitializeSecurityDescriptor(ctypes.cast(ctypes.byref(sd), ctypes.c_void_p), 1):
        raise ctypes.WinError(ctypes.get_last_error())
    acl = ACL()
    if not advapi32.InitializeAcl(ctypes.cast(ctypes.byref(acl), ctypes.c_void_p), ctypes.sizeof(acl), 2):
        raise ctypes.WinError(ctypes.get_last_error())
    if not advapi32.SetSecurityDescriptorSacl(ctypes.cast(ctypes.byref(sd), ctypes.c_void_p), True,
                                              ctypes.cast(ctypes.byref(acl), ctypes.c_void_p), False):
        raise ctypes.WinError(ctypes.get_last_error())
    rc = advapi32.SetNamedSecurityInfoW(path, SE_FILE_OBJECT, LABEL_SECURITY_INFORMATION,
                                        None, None, None, ctypes.byref(sd))
    if rc != 0:
        raise OSError(rc, "SetNamedSecurityInfoW(label): " + ctypes.FormatError(rc))


def drop_aces(path):
    sd, dacl = read_dacl(path)
    try:
        info, aces = list_aces(dacl)
        drop = [a for a in aces if is_dsh_ace(a)]
        if not drop:
            return 0
        cap = info.AclBytesInUse + 64
        buf = ctypes.create_string_buffer(cap)
        rev = acl_revision(dacl)
        if not advapi32.InitializeAcl(buf, cap, rev):
            raise ctypes.WinError(ctypes.get_last_error())
        kept = 0
        for ace in aces:
            if is_dsh_ace(ace):
                continue
            if not advapi32.AddAce(buf, rev, 0xFFFFFFFF, ace["ptr"], ace["size"]):
                raise ctypes.WinError(ctypes.get_last_error())
            kept += 1
        rc = advapi32.SetNamedSecurityInfoW(path, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
                                            None, None, ctypes.cast(buf, ctypes.c_void_p), None)
        if rc != 0:
            raise OSError(rc, "SetNamedSecurityInfoW(dacl): " + ctypes.FormatError(rc))
        print("  已删除 ACE %d 条，保留 %d 条" % (len(drop), kept))
        for ace in drop:
            print("    - type=%d mask=0x%08x sid=%s" % (ace["type"], ace["mask"], ace["sid"]))
        return len(drop)
    finally:
        if sd:
            kernel32.LocalFree(sd)


def inspect(path, quiet=False):
    if not os.path.exists(path):
        print("[跳过] 不存在: %s" % path)
        return None
    if not os.path.isdir(path):
        print("[跳过] 不是目录: %s" % path)
        return None
    if not is_ntfs(path):
        print("[跳过] 不是 NTFS，无法存 ACL: %s" % path)
        return None
    label = has_label(path)
    sd, dacl = read_dacl(path)
    try:
        info, aces = list_aces(dacl)
        dsh = [a for a in aces if is_dsh_ace(a)]
    finally:
        if sd:
            kernel32.LocalFree(sd)
    if quiet:
        return label, len(dsh)
    print("[目标] %s" % path)
    print("  完整性标签: %s" % ("有（将删除，恢复为无标签/Medium）" if label else "无"))
    print("  DSH ACE   : %s" % ("%d 条（将删除）" % len(dsh) if dsh else "无"))
    for ace in dsh:
        print("    - type=%d mask=0x%08x sid=%s" % (ace["type"], ace["mask"], ace["sid"]))
    return label, len(dsh)


def clean(path):
    t0 = time.monotonic()
    label, n_ace = inspect(path, quiet=True)
    if label is None:
        return False, False
    if not label and n_ace == 0:
        print("  已干净，无需改动。")
        return True, False
    print("  开始清理（大目录的传播可能要几分钟到十几分钟）...")
    if label:
        clear_label(path)
        print("  标签已删除")
    if n_ace:
        drop_aces(path)
    if has_label(path):
        print("  [失败] 标签仍然存在")
        return False, True
    side_sd, side_dacl = read_dacl(path)
    try:
        _, aces = list_aces(side_dacl)
        left = [a for a in aces if is_dsh_ace(a)]
    finally:
        if side_sd:
            kernel32.LocalFree(side_sd)
    if left:
        print("  [失败] 仍有 %d 条 DSH ACE" % len(left))
        return False, True
    print("  校验通过，用时 %.1f 秒" % (time.monotonic() - t0))
    return True, True


def main():
    args = [a.strip('"') for a in sys.argv[1:] if not a.startswith("--")]
    yes = "--yes" in sys.argv
    targets = args if args else DEFAULT_TARGETS

    print("清理 DSH 沙盒完整性标签与 ACE")
    print("=" * 46)
    print("将处理的目录：")
    for t in targets:
        print("  %s" % t)
    print("")

    reports = []
    for t in targets:
        reports.append(inspect(t))

    todo = [t for t, r in zip(targets, reports) if r and (r[0] or r[1])]
    if not todo:
        print("")
        print("全部已干净，没有要改的东西。")
        return 0

    if not yes:
        print("")
        ans = input("确认清理以上目录？输入 y 回车执行，其它键取消: ").strip().lower()
        if ans != "y":
            print("已取消，没有改动。")
            return 0

    ok_all = True
    for t in todo:
        print("")
        ok, changed = clean(t)
        ok_all = ok_all and ok

    print("")
    print("完成。" if ok_all else "有失败项，见上面的输出。")
    return 0 if ok_all else 2


if __name__ == "__main__":
    code = 0
    try:
        code = main()
    except Exception as exc:
        print("")
        print("出错: %s: %s" % (type(exc).__name__, exc))
        code = 2
    if "--no-pause" not in sys.argv:
        try:
            input("按回车关闭窗口...")
        except EOFError:
            pass
    raise SystemExit(code)
