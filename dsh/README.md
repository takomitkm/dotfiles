# DSH 桌面工具库（总入口）

本文件夹集中管理 DeepSeek Harness 桌面版的**本地补丁、维护脚本与踩坑记录**。
App 自动更新会覆盖 `resources\app.asar`，补丁随之失效 → 更新后重跑 `01-更新后必用\dsh-fix.py apply --yes`。

## 目录

| 目录 | 内容 | 何时用 |
|---|---|---|
| `01-更新后必用` | `dsh-fix.py`（P1 inspector + P2 storage-json 补丁，status/apply/rollback 子命令） | App 更新后 |
| `02-配置与维护` | `清理 DSH 完整性标签.py` 等 | 权限/沙盒维护 |
| `03-快捷方式` | `STOP-DSH-全部.lnk` | 手动 |
| `04-参考存档` | 旧 dsh-9271 套件 | 备查 |
| `05-全局说明` | 详细 README | 阅读 |
| `06-已证伪勿用` | 作废方案（**不要运行**） | 仅供了解为什么不行 |
| `99-旧版存档` | 历史遗留 | 备查 |

---

## ⚠️ 已踩过的坑（不要再犯）

### 坑 1：DSH 的 runner 不能换成随包 `node.exe`（2026-11-03 实测证伪）

- **想做**：每次 `ops_bash` 都起一份 Electron 当 runner（磁盘 235MB / RSS ~152MB / 启动 190ms），想换成轻量 node.exe 省内存。
- **为什么不行**：`runner.js` 及其依赖在 **`app.asar` 内部**，**只有 Electron 的 node 能读 asar**（Electron 给 `fs`/模块加载器打了补丁）。官方 `node.exe` 启动直接报：

  ```
  Error: Cannot find module
    'C:\…\resources\app.asar\dsh\node_modules\@deepseek-ai\dsh-subprocess-local\lib\runner.js'
  ```

  宿主随后报 `runner exited with exit code 1 before proving its managed range empty`，**所有子进程类工具全挂**（`pwsh` 直接失败）。
- **结论**：`process.execPath` 是"唯一能读到自己 asar 内 runner 的运行时"，不是疏忽。换 node.exe 这条路**作废**（A1/A2 已回滚、环境变量 `NPTH` 已删）。
- **存档**：作废脚本在 `06-已证伪勿用\patch-runner-node.py`，**永远不要 apply**。
- **真正能省那份内存的路**：绕开一次性 spawn，改用**持久 PTY**（`dsh-tool-pwsh-persistent`，见桌面 `dsh初始化.py`）—— 已采纳。
- **详证**：`06-已证伪勿用\为什么不能用.md`、`S:\apps\llm\agentwork\LOCAL-DIVERGENCE.md`（A1/A2 条目）、上游 discussion #6884。

### 坑 2：asar 原地补丁的完整性（写文件时别丢掉头部哈希）

- 原地改 asar 必须**同一步**里既写内容、又把头部 JSON 里该文件的 SHA256（`hash` + `blocks`）一起更新；中间任何异常都要能从备份回滚。
- `dsh-fix.py` 已按此实现：先备份 → 写内容+更新哈希 → 读回校验哈希 → `node --check` 语法校验 → 任一失败自动回滚。

---

*最后更新：2026-11-08*
