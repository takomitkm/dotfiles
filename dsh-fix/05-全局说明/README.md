# DeepSeek Harness — 桌面版补丁与配置工具

本目录是更新后可用的"必用脚本 + 配置维护"工具集合。**App 自动更新会覆盖 `app.asar`**，补丁随之失效；更新后需重新运行对应脚本。

---

## 📁 快速导航

| 目录 | 用途 | 何时使用 |
|---|---|---|
| **01-更新后必用** | DSH 核心补丁（一次应用、每次更新重打） | App 更新后第一时间运行 |
| **02-配置与维护** | 完整性标签清理等维护脚本 | 日常性能调优、权限调整 |
| **03-快捷方式** | 停止进程等常用 .lnk | 手动操作 |
| **04-参考存档** | 旧版本 dsh-9271 套件 | 查阅历史、手工对比 |
| **05-全局说明** | 本文档等通用说明 | 阅读 |
| **06-已证伪勿用** | runner 换 node.exe 的作废方案（存档） | **不要运行**，仅备查 |

---

## 🔧 核心补丁（01-更新后必用）

### `dsh-fix.py` — 两个本地补丁的总装脚本

**为什么需要它**：DSH 官方发行版在 0.2.2-rc.1 及之前仍未包含以下修复，导致两类崩溃：

| 补丁 | 上游讨论 | 效果 |
|---|---|---|
| **P1: inspector 信封预算** | #9271 / #10259 | 消除 Cordis 树快照超过字节限时 Host 退出 1 |
| **P2: storage-json 重试** | #9575 / #10724 | 消除 Windows 上瞬时文件锁导致的 EPERM fatal load failure |

**用法**:

```powershell
# 只看状态（不改动任何东西）
python "01-更新后必用\dsh-fix.py"

# 打印状态
python "01-更新后必用\dsh-fix.py" status

# 打补丁（先备份；DSH 运行中会询问，--yes 跳过询问）
python "01-更新后必用\dsh-fix.py" apply --yes

# 回滚到最新备份（撤销最近一次 apply）
python "01-更新后必用\dsh-fix.py" rollback --yes
```

**注意**：
- 脚本只做等长字节替换 + 头部 SHA256 同步；失败自动回滚。
- 更新 DSH App 后会丢失，需重复 `apply --yes`。
- `dsh-fix.py` 只含 P1/P2，不含 runner 补丁（后者已证伪，见 `06-已证伪勿用\`）。

---

### ⛔ `patch-runner-node.py` — 已证伪，不要用

**结论（2026-11-03 实测）**：把 runner 从 Electron 换成随包 `node.exe` **不可行**。`runner.js` 在 `app.asar` 内部，只有 Electron 的 node 能读 asar；官方 node.exe 会 `Cannot find module ...app.asar\...\runner.js`，导致**所有子进程工具全挂**。A1/A2 已回滚，`NPTH` 已删。工具仅存档在 `06-已证伪勿用\`，**不要 apply**。

详见 `06-已证伪勿用\为什么不能用.md` 与 `S:\apps\llm\agentwork\LOCAL-DIVERGENCE.md`。正确方向是持久 PTY（`dsh-tool-pwsh-persistent`）。

---

## ⚙️ 配置与维护（02-配置与维护）

### `清理 DSH 完整性标签.py`

删除 DSH 沙盒在工作区根上种下的完整性标签和 ACE（仅当 DSH 不再打开该工作区时）。

---

## 📄 旧版参考（04-参考存档）

早期 `dsh-9271-fix` 套件（单补丁只含 P1），保留作为历史参考。

---

## 💡 常见问题

### Q: App 更新后我的补丁还在吗？

A: 不在。自动更新会整体替换 `resources/app.asar`，本地补丁随之消失。**每次更新后必须重新跑 `apply --yes`**。

### Q: 如何检查当前是否已打上补丁？

A: 运行 `status` 命令即可看到结果，类似：

```text
P1 inspector (#9271):
  index.js   ✓ 已打
  client.js  ✓ 已打

P2 storage-json (#9575):
  index.js   ✓ 已打
```

### Q: 回滚会影响我的配置吗？

A: `rollback` 只从最新的 `app.asar.prepatch-*` 备份恢复原始二进制，**不会删除任何 profile、插件、存储数据**。但重启 DSH 后会丢失补丁（相当于回到出厂状态）。

---

## 📎 补充说明

- **Inspection 相关**：你在 `cordis.patch.yml` 里已有 `experimental-inspector disabled: true`，这已是最优解（关闭比抬上限更安全，避免崩溃 + "新建对话慢"）。
- **Memory 蒸馏**：你的记忆预算（memsearch）还有 19k+ 额度，建议定期手动切块补跑，或精简候选。
- **OVHcloud AI Endpoints**：免费匿名兜底通道（oai.endpoints.kepler.ai.cloud.ovh.net），限额 2 次/min/IP，按模型分桶；敏感图像请关闭"Local-only vision"开关。

---

## ✅ 下次更新后的操作流程

1. App 完成更新并重启 → 发现 DSH 图标变了或版本号更新（例如到 0.2.3-rc.x）。
2. 运行 `dsh-fix.py` **status** 确认补丁缺失。
3. 运行 `dsh-fix.py` **apply --yes** 重新打上 P1/P2。
4. 再次 status 确认全部显示 "✓ 已打"。
   （runner 补丁已证伪，不重打；如需省资源请用持久 PTY，见 `dsh初始化.py`。）

如有问题，截图或输出 `status` 内容发我即可快速定位。

---

*最后更新日期：2026-11-08*
