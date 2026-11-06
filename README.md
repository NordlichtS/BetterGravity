# Better Control for Google Antigravity Multi(Sub)Agents

> ✦ **针对 Google Antigravity 多子代理与长任务的配额监控及安全管控插件** ✧

本工具目前已在 **Google Antigravity Windows 客户端** 完成测试，欢迎反馈其它平台的测试结果或功能建议。

主要用于解决多子代理长任务中常见的实际问题：**配额耗尽导致任务中途中断**、**多阶段子代理上下文膨胀**、**客户端配额界面刷新滞后**，以及**缺乏余量阶梯提醒与安全断点保存**（避免单轮长对话在无提示情况下耗尽 5h 限额或大量 Credit，留下未写完的文件与失控的子代理）。

---

## ✦ 核心特性

1. **调用客户端内部 RPC 获取实时配额 (`retrieveUserQuotaSummary`)**
   - 通过 Antigravity 客户端本地调试端口（读取 `DevToolsActivePort` 或动态探测进程端口）调用内部接口，无需手动点击界面刷新即可获取最新配额数据。
2. **定时轮询与空闲自动退出**
   - 默认每 5 秒执行一次会话活跃度检查与配额同步；
   - 通过监测会话数据库文件的写入时间判断 Agent 是否在工作，连续 2 次检测无活动（约 10 秒）后进程自动退出，不常驻后台，也不会占用聊天界面的 `1 task running` 状态槽。
3. **按当前活跃模型隔离告警**
   - 仅监控当前对话实际使用的模型组（`Gemini Models`、`Claude and GPT models` 或 `Gemini 4 Argon`）；
   - 其它模型组配额耗尽不会触发当前模型的告警或暂停。
4. **阶梯提醒与三级低余量预警**
   - 5 小时限额每消耗 10%、周限额每消耗 5%、Credit 每消耗 100 时，触发系统提示音与 Windows 托盘通知；
   - **最后 3 个阶梯（5h 剩余 ≤30%、≤20%、≤10%；周限额剩余 ≤15%、≤10%、≤5%）设为低余量预警线**，跨越时触发告警并通知 Agent 准备安全停车。
5. **安全停车与原生 Artifact 断点记录 (`checkpoint.md`)**
   - 触发预警或连续报错时，Agent 会在当前文件写入完整、语法闭合后暂停，避免留下损坏的半成品代码；
   - 进度保存至 Antigravity 原生 Artifact 目录下的 `<Artifact Directory>/checkpoint.md`，可直接在右侧 Artifacts 面板查看，不污染项目 Git 工作区。
6. **子代理并发审批与上下文压缩**
   - 当并发启动超过 2 个子代理（即 ≥3 个）时，先向用户展示任务拆分与按复杂度匹配的模型建议（复杂推理/重构使用主模型或 `pro`，简单检索使用 `flash`），确认后再启动；
   - 子代理完成阶段性任务后，先压缩或重置上下文再分配后续任务。
7. **首次工具调用前简短提示**
   - 每次收到用户 `<USER_REQUEST>` 后，在执行第一个工具调用前输出一句简短提示说明即将开展的操作（自动排除启动配额监控脚本等插件内部动作）；
   - 首个提示之后恢复 Antigravity 原生默认的汇报行为，不强制重复播报。
8. **纯英文规则描述，避免回答语言偏移**
   - 除本 `README.md` 外，`rules/AGENTS.md` 与监控脚本均采用英文编写，与 Antigravity 内部系统提示词语言保持一致，并严格跟随用户最新提问的语言作答。

---

## ✦ 运行机制

### 后台静默启动
在多步任务或子代理任务开始时，通过 PowerShell `Start-Process` 独立启动监控脚本，与会话主任务解耦：
```powershell
Start-Process -FilePath "python.exe" -ArgumentList "$env:USERPROFILE\.gemini\config\plugins\budget-orchestrator\scripts\client_quota_watcher.py", "--convo-id", "<CONVERSATION_ID>", "--model-group", "<CURRENT_MODEL>" -WindowStyle Hidden
```

### 空闲自动退出流程
- 当 Agent 处于工作状态时，`watcher` 每 5 秒轮询一次配额变化；
- 当会话数据库停止更新，连续 2 次检查均无活动（约 10 秒）时，输出 `Auto-terminating watcher` 并直接退出进程。

---

## ✦ 自定义配置

可在 `scripts/client_quota_watcher.py` 顶部调整以下常量：

```python
# ==============================================================================
# Global Configuration Constants
# Adjust polling cadence and auto-termination sensitivity here as needed
# ==============================================================================
CHECK_INTERVAL_SECONDS = 5.0     # Unified check interval (seconds): checks session activity + syncs live quota
MAX_INACTIVE_STRIKES = 2        # Max consecutive inactive checks before auto-terminating the watcher process
ACTIVE_WINDOW_SECONDS = 8.0     # Activity window (seconds): session is active if modified within this window
```

- **`CHECK_INTERVAL_SECONDS`**：轮询间隔秒数，默认 `5.0` 秒。
- **`MAX_INACTIVE_STRIKES`**：连续空闲多少次后自动退出，默认 `2` 次（5 秒 × 2 = 约 10 秒）。

---

## ✦ 项目结构

```text
BetterGravity/
├── plugin.json                 # Antigravity 全局插件清单配置
├── rules/
│   └── AGENTS.md               # 全局子代理调度与安全停车规则 (英文)
├── scripts/
│   ├── client_quota_watcher.py # 配额监控与告警脚本
│   ├── start_watcher.bat       # Windows 批处理启动脚本
│   └── start_watcher.vbs       # 无窗口启动脚本
├── install.ps1                 # 安装/同步至 Antigravity 全局插件目录的脚本
└── README.md                   # 说明文档
```

---

## ✦ 安装指引

**一键安装（推荐）：** 在 PowerShell 中运行项目目录下的 `install.ps1`：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install.ps1
```

**手动安装：** 将项目文件复制至 Antigravity 全局插件目录：
```text
%USERPROFILE%\.gemini\config\plugins\budget-orchestrator\
```
目录结构如下：
```text
C:\Users\<你的用户名>\.gemini\config\plugins\budget-orchestrator\
├── plugin.json
├── rules\AGENTS.md
└── scripts\client_quota_watcher.py
```

安装完成后，重启 Antigravity 客户端或新建会话即可生效。

---

## ✦ License
MIT License.
