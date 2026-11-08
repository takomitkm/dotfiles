DSH #9271 修复套件
==================

这个补丁对应：
  deepseek-ai/deepseek-harness 讨论 #9271
  damokelis/deepseek-harness@fix/inspector-retained-state-budget
  commit 7a28f5392be77db2144c3c56271d75e03155dd15

修的是 @deepseek-ai/dsh-experimental-inspector 的 Cordis 树预算：
收集器裁剪时预留保留记录的 envelope（时间戳 + topic + payload 包装 + 数组定界符），
让 stateFits() 和收集器量同一批字节。Host(lib/index.js) 与 Client(lib/client.js) 两面都打。

安装
----
1. 双击 apply-9271.cmd
2. 重启 DeepSeek Harness 生效
   （脚本会先备份 app.asar 为 app.asar.prepatch-<时间>；已打过会直接提示）

撤回
----
1. 先彻底关闭 DeepSeek Harness
2. 双击 restore-asar.cmd
   （会从最新的 app.asar.prepatch-* / app.asar.bak-* 恢复）

DSH 更新后
----------
自动更新会覆盖 app.asar，补丁会丢。更新完再双击一次 apply-9271.cmd 即可。

注意
----
- 只修 #9271 的根因层（预算算术）。
- 不含"setState 永不 throw"的兜底层，所以 #10069（inspector: Host source is closed）仍在。
- 若想更稳，可再补兜底层，但那会改变崩溃行为（从崩溃变成丢帧 + 告警）。

文件
----
apply-9271.cmd     一键安装
apply-9271.py      实际打补丁的脚本（需 Python 3）
restore-asar.cmd   一键撤回
README.txt         本文件