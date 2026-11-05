# Better Control for Google Antigravity Multi(Sub)Agents 

> ✦ **针对 Google Antigravity 多开子代理跑长任务时，更安全的自动操控** ✧

本工具目前经过 **Google Antigravity Windows 客户端** 的测试，如果你有其它平台的测试，或者需要加装的功能，也欢迎反馈。

目前实装的功能解决了多子代理长任务中，**额度意外耗尽被腰斩**、**长上下文膨胀越跑越慢**、**界面配额显示滞后**、**缺少临近余额多级预警**的痛点。（防止再出现那种，一轮对话直接瞬间烧穿5h额度和2500credit 然后留下一堆半成品文件和十几个死掉的sub agents）

---

##  核心特性

1. **直接调用客户端官方底层 RPC (`retrieveUserQuotaSummary`)**：
   - 不依赖网页或文本估算，直接与 Antigravity 客户端底层通信通道握手，解决客户端界面必须手动点击刷新按钮的滞后缺陷，获取实时最新配额数据。
2. **统一周期查询 + 连续 2 次无动作自动灭活（Zero Overhead）**：
   - 默认每 5 秒统一执行一次“会话活跃检测 + 最新配额同步”；
   - 实时监听对话底层活动，只要 Agent 停止工作连续 2 次检查（~10 秒），Watcher 会自动关闭退出，绝不常驻系统后台，也不占用聊天界面的 “1 task running” 槽。
   - 支持在代码文件头部自由修改轮询间隔的时间常数。
3. **多模型隔离（Active-Model Scope Isolation）**：
   - 动态识别当前对话正在使用的模型（Claude 或 Gemini）；
   - 某一个模型耗尽不会误杀或误报正在使用其它模型的正常任务（比如Claude模型的任务触发停车时，不会影响还在跑的Gemini模型的任务）
4. **多级连续危险防线（Triple Danger Safety Net）**：
   - 5 小时限额每消耗 10%、周度限额每消耗 5%、Credit 每消耗 100 发出原生系统提示音与 Windows 气泡通知；
   - **最后 3 次告警（如 5h 剩余 ≤30%、≤20%、≤10%）全部定义为危险线**，触发有声音的警告通知，并在工作区生成 `.danger_parking_alert`。
5. **安全闭合点收敛与原生 Artifact 断点持久化 (Safe Parking Protocol)**：
   - Agent 绝对不在修改文件半途中断，确保语法闭合、磁盘完整落盘（Flush）；
   - 直接采用 Antigravity 原生 **Artifact Markdown (`checkpoint.md`)** 格式记录断点（右侧 Artifacts 面板可直接交互预览，对新接手的 LLM 最省 Token，且不污染项目 Git 工作区）。
6. **多子代理启动门禁 (Subagent Concurrency Gate)**：
   - 派发超过 2 个 Subagent（≥3 并行）时，Agent 暂停并向上级汇报分工结构和模型分级（比如要不要降级到 flash 还是升级到 pro），经人工同意后再启动；
   - 这一步可以指示agent具体怎么配置子代理，可以描述的很具体，也可以给出模糊指示，让指挥级agent自己考虑。
   - 子代理阶段性汇报后，触发一次上下文压缩。
7. **首步工具调用前简短告知 (First Tool-Call Notice)**：
   - 每次收到用户主动发出的 Prompt 并完成初始思考后，在发起第一个 Tool Call 之前先用一句话简短告知马上要做什么（无需等待用户回复直接继续），避免工具调用期间界面无文字提示导致用户误判工作尚未开始。

---

## 🎯 运行机制与测试

### 独立静默拉起（不占用聊天窗口任务槽）
在 Agent 长任务开始时，可通过 PowerShell 后台隐式启动：
```powershell
Start-Process -FilePath "python.exe" -ArgumentList "C:\path\to\client_quota_watcher.py", "--convo-id", "<CONVERSATION_ID>", "--model-group", "gemini" -WindowStyle Hidden
```
防止出现一直有 1 task running 的标识

### 自灭机制实测
- 当 Agent 处于工作状态时，`watcher` 每 5 秒轮询一次，并更新配额阶梯；
- 当 Agent 工作完成（数据库无新写入），Watcher 在第 1 次检测发现无活动（1/2），第 2 次检测依然无活动（2/2）时，**立即在终端输出 `Auto-terminating watcher` 并自我销毁进程**，实现真正的按需启动与零后台残留。

---

## ⚙️ 自定义配置 (Configuration)

在 `scripts/client_quota_watcher.py` 文件开头，可直接按需调整以下全局常量：

```python
# ==============================================================================
# 全局可调配置常量 (Global Configuration Constants)
# ==============================================================================
CHECK_INTERVAL_SECONDS = 5.0     # 统一轮询间隔（秒）：每隔多少秒执行一次“活跃检测 + 余额配额同步”
MAX_INACTIVE_STRIKES = 2        # 连续无活动次数上限：连续多少次检测到对话未在运行后自动退出进程
ACTIVE_WINDOW_SECONDS = 8.0     # 判定活跃的时间窗口（秒）：最后一次写入距离当前小于该值视为活跃
```

- **调整查询频率**：如果你希望更频繁或更节省系统性能，可将 `CHECK_INTERVAL_SECONDS` 改为 `3.0` 或 `10.0`。
- **调整自灭灵敏度**：`MAX_INACTIVE_STRIKES` 默认为 2 次（5秒 × 2次 = 10秒无动作即自动终止）。



---

## 📂 项目结构

```text
BetterGravity/
├── plugin.json                 # Antigravity 全局插件清单配置
├── rules/
│   └── AGENTS.md               # 全局生效的多子代理与安全停车行为准则 (Behavioral Guard)
├── scripts/
│   ├── client_quota_watcher.py # 直连 Antigravity 客户端的 Python 监控守护程序
│   ├── start_watcher.bat       # Windows 批处理启动脚本
│   └── start_watcher.vbs       # 静默无窗口启动脚本
├── install.ps1                 # 一键安装/部署到 Antigravity 全局目录脚本
└── README.md                   # 本文档
```

---

## 🛠️ 安装指引 (Quick Installation)

**一键自动安装（推荐）：** 打开 PowerShell，直接运行目录内的 `install.ps1`：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install.ps1
```

**或者手动复制安装：** 将本项目整体复制或软链接至 Antigravity 的全局插件目录：
```text
%USERPROFILE%\.gemini\config\plugins\budget-orchestrator\
```
目录结构对应如下：
```text
C:\Users\<你的用户名>\.gemini\config\plugins\budget-orchestrator\
├── plugin.json
├── rules\AGENTS.md
└── scripts\client_quota_watcher.py
```

安装完成后，重启一次 Antigravity 客户端（或新开会话），全局规则即可自动生效。



---

## 📄 License
MIT License.
