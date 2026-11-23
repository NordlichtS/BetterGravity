# Better Control for Google Antigravity Multi(Sub)Agents

> ✦ **针对 Google Antigravity 多子代理与长任务的配额监控、安全管控及零膨胀 Skill 路由插件** ✧

本工具目前已在 **Google Antigravity Windows 客户端** 完成测试，欢迎反馈其它平台的测试结果或功能建议。

主要用于解决多子代理长任务与插件膨胀中的常见实际问题：**配额耗尽导致任务中途中断**、**多阶段子代理上下文膨胀**、**客户端配额界面刷新滞后**、**缺乏余量阶梯提醒与安全断点保存**，以及 **大量预装插件/Skill 每轮常驻 System Prompt 导致的上下文爆炸**（即使不涉及相关领域，也会持续占用数万字符并挤占子代理工具名额）。

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
7. **零上下文膨胀的本机 Skill 树状索引与 BM25 检索 (`Local Skill Router`)**
   - 配合禁用低频插件（`agy plugin disable <plugin>`）或卸载宽松用户技能，将每轮对话不再需要的数十个 Skill 描述从 System Prompt 中彻底移除，同时保留本机离线检索能力；
   - 当对话明确涉及专业领域（如学术论文检索、GCP/BigQuery、Web 性能、Android、本地 HLSL 等）时，由本机 Python CPU 运行 **2 层领域树 + BM25 检索**（支持中英文同义词扩展与自动指纹失效重建），仅向 LLM 返回 Top-K 最小摘要与 `SKILL.md` 路径；
   - 实时读取 `config.json` 感知插件启用状态并区分激活方式：`mode: direct` 插件即使禁用也可直接按 `SKILL.md` 执行（附带可选开启卡片链接）；`needs-mcp` / `needs-sidecar` / `needs-plugin` 插件在未启用时清晰提示用户开启后再调用。
8. **首次工具调用前简短提示**
   - 每次收到用户 `<USER_REQUEST>` 后，在执行第一个工具调用前输出一句简短提示说明即将开展的操作（自动排除启动配额监控脚本等插件内部动作）；
   - 首个提示之后恢复 Antigravity 原生默认的汇报行为，不强制重复播报。
9. **纯英文规则描述，避免回答语言偏移**
   - 除本 `README.md` 与 `skill_find.py` 内部中文查询同义词词表（不输出至 LLM 终端上下文）外，`rules/AGENTS.md`、索引输出与监控脚本均采用英文编写，与 Antigravity 内部系统提示词语言保持一致，并严格跟随用户最新提问的语言作答。

---

## ✦ 运行机制

### 1. 配额监控后台静默启动
在多步任务或子代理任务开始时，通过 PowerShell `Start-Process` 独立启动监控脚本，与会话主任务解耦：
```powershell
Start-Process -FilePath "python.exe" -ArgumentList "$env:USERPROFILE\.gemini\config\plugins\budget-orchestrator\scripts\client_quota_watcher.py", "--convo-id", "<CONVERSATION_ID>", "--model-group", "<CURRENT_MODEL>" -WindowStyle Hidden
```
- 当 Agent 处于工作状态时，`watcher` 每 5 秒轮询一次配额变化；
- 当会话数据库停止更新，连续 2 次检查均无活动（约 10 秒）时，输出 `Auto-terminating watcher` 并直接退出进程。

### 2. 本机 Skill 树状索引与按需检索
索引文件生成在插件目录内（`~/.gemini/config/plugins/budget-orchestrator/skill-index/`），**永不注入对话全局提示词**。日常普通聊天与常规编码零开销；仅在需要特定领域技能时由本机 Python CLI 检索：
```powershell
# 关键词检索（支持中/英文，返回 Top-3 及插件启用状态、激活模式、SKILL.md 路径）
python "$env:USERPROFILE\.gemini\config\plugins\budget-orchestrator\scripts\skill_find.py" search "学术论文 arxiv" -k 3

# 逐层浏览 2 层领域树（第 1 层领域概览 -> 第 2 层指定领域下的 Skill 列表）
python "$env:USERPROFILE\.gemini\config\plugins\budget-orchestrator\scripts\skill_find.py" tree
python "$env:USERPROFILE\.gemini\config\plugins\budget-orchestrator\scripts\skill_find.py" tree science/literature

# 显式重建索引（注：增删/更新插件后，首次 search 或 tree 也会按文件指纹自动重建）
python "$env:USERPROFILE\.gemini\config\plugins\budget-orchestrator\scripts\skill_find.py" rebuild
```

#### 实用示例（纯中文按需发现已禁用的英文插件）
在实测环境中关闭非必需插件后，每轮注入上下文的插件 Skill 从 **118 个降至 6 个（减少约 95%）**、插件 MCP Server 从 **17 个降至 1 个**（同时避免 `browser` 等内置子代理因配额/预算溢出被挤出）。即便在对话中完全不提及英文插件名，Agent 仍可通过纯中文触发本机检索按需发现目标：
- 当对话仅涉及日常问答或普通代码时，**不加载任何外部插件目录（0 开销）**；
- 当提到「做网页前端」时，运行 `skill_find.py search "做网页前端" -k 3` 可直接定位到已禁用的英文插件 `modern-web-guidance-plugin` 与 `chrome-devtools-plugin`（`mode: direct`，可直接读取 `SKILL.md` 执行或附带一键启用链接）：
  ```text
  Query: 做网页前端 (matched 14 skills, showing top 3)
  [1] modern-web-guidance | web/modern-web | plugin: modern-web-guidance-plugin (disabled) | mode: direct | score: 40.89
      Search tool for modern web development best practices.
      SKILL: C:\Users\<USER>\.gemini\config\plugins\modern-web-guidance-plugin\skills\modern-web-guidance\SKILL.md
      Plugin (disabled, optional): [modern-web-guidance-plugin](customization://modern-web-guidance-plugin)  OR  agy plugin enable modern-web-guidance-plugin
  [2] chrome-extensions | web/modern-web | plugin: modern-web-guidance-plugin (disabled) | mode: direct | score: 33.32
      Build and publish Chrome Extensions using Manifest V3 best practices.
      SKILL: C:\Users\<USER>\.gemini\config\plugins\modern-web-guidance-plugin\skills\chrome-extensions\SKILL.md
      Plugin (disabled, optional): [modern-web-guidance-plugin](customization://modern-web-guidance-plugin)  OR  agy plugin enable modern-web-guidance-plugin
  [3] debug-optimize-lcp | web/devtools | plugin: chrome-devtools-plugin (disabled) | mode: direct | score: 23.91
      Guides debugging and optimizing Largest Contentful Paint (LCP) using Chrome DevTools MCP tools.
      SKILL: C:\Users\<USER>\.gemini\config\plugins\chrome-devtools-plugin\skills\debug-optimize-lcp\SKILL.md
      Plugin (disabled, optional): [chrome-devtools-plugin](customization://chrome-devtools-plugin)  OR  agy plugin enable chrome-devtools-plugin
  ```
- 同理，当提到「阅读论文」时，也会精准命中已禁用的 `scientific-literature` 插件（`literature-search-arxiv`、`literature-search-biorxiv`、`literature-search-europepmc` 等），兼顾零日常上下文膨胀与按需可用性。

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

如需微调本机 Skill 路由的领域映射、双语同义词表（`CN_EN_SYNONYMS`）或激活模式判定逻辑，可编辑 `scripts/build_skill_index.py` 后重新安装或执行 `skill_find.py rebuild`。

---

## ✦ 项目结构

```text
BetterGravity/
├── plugin.json                     # Antigravity 全局插件清单配置 (v1.1.0)
├── rules/
│   └── AGENTS.md                   # 统一精简的全局规则：配额护栏、子代理调度与按需 Skill 路由 (纯英文)
├── scripts/
│   ├── client_quota_watcher.py     # 配额监控与告警脚本
│   ├── start_watcher.bat           # Windows 批处理启动脚本
│   ├── start_watcher.vbs           # 无窗口启动脚本
│   ├── build_skill_index.py        # 扫描本机插件与 ~/.agents/skills 生成 2 层树与 BM25 索引
│   └── skill_find.py               # 本机离线检索 CLI（含指纹校验自动重建与实时启用状态检查）
├── install.ps1                     # 安装/同步至 Antigravity 全局插件目录并初始化索引的脚本
└── README.md                       # 说明文档
```

---

## ✦ 安装指引

**一键安装（推荐）：** 在 PowerShell 中运行项目目录下的 `install.ps1`（将自动同步规则与脚本至全局插件目录，并在检测到 Python 时生成初始 `skill-index/`）：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install.ps1
```

**手动安装：** 将项目文件复制至 Antigravity 全局插件目录，并执行一次索引构建：
```text
%USERPROFILE%\.gemini\config\plugins\budget-orchestrator\
```
目录结构如下（运行一次 `install.ps1` 或 `skill_find.py rebuild` 后会生成 `skill-index\`）：
```text
C:\Users\<你的用户名>\.gemini\config\plugins\budget-orchestrator\
├── plugin.json
├── rules\AGENTS.md
├── scripts\
│   ├── client_quota_watcher.py
│   ├── start_watcher.bat
│   ├── start_watcher.vbs
│   ├── build_skill_index.py
│   └── skill_find.py
└── skill-index\                    # 运行后自动生成的离线索引与 TREE.md（不入 Git）
```

> **提示**：若希望最大化节省 Token，可用 `agy plugin disable <插件名>` 关闭低频领域插件，将其交由 BetterGravity 的本机 `skill_find.py` 按需发现，仅常开日常高频使用的插件（如 `budget-orchestrator`、`gdrive` 等）。安装或变更后，重启 Antigravity 客户端或新建会话即可生效。

---

## ✦ License
MIT License.
