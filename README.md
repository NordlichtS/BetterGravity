# BetterGravity — Google Antigravity 客户端性能、可靠性与额度优化插件

BetterGravity 是用于安装在 Google Antigravity 客户端的扩展组件，目标是在客户端侧提升运行性能与任务可靠性，并减少上下文的无效消耗（不限于当前已实现的模块，后续可持续扩展其他客户端优化能力）。可以热加载，不会替换任何原生的配置文件，附带安装与卸载脚本。

目前版本已在 **Google Antigravity Windows 客户端 v2.34.0** 完成测试，欢迎反馈其他平台的测试结果喵！如果有改进建议或者需要的新功能，也欢迎提出喵！

当前已实现三类核心能力：
1. **本机技能树自动查找与系统提示词底噪削减（Local Skill Router）**：减少常驻上下文占用，按需检索本地 Skill。
2. **子代理集群调度与实时配额管控**：通过并发审批、模型分级、阶段上下文重置与后台配额监测节约额度。
3. **执行可靠性与交互反馈增强**：低余量/报错时安全停车并保存断点、首条工具调用简短提示、纯英文规则防止语种漂移。

---

## 1. 本机技能树自动查找与提示词底噪削减（核心）

### 背景与设计思路
系统提示词膨胀是许多 Agent 客户端普遍存在的问题：大量预装插件与 Skill 描述每轮都会注入对话上下文，即使当前任务完全用不到，也会持续消耗 token 并挤占内置工具或子代理名额，有时把官方自带的插件全部装完就直接占满了customization budget，导致晚加载的新组件直接被挤掉了。

本插件在设计上参考了类似 Claude Code 的按需发现与渐进式加载思路。从使用表现来看，deep seek harness 似乎也存在与原生 Antigravity 相似的提示词底噪问题，这套本地索引与按需路由方案的设计思路同样可以移植到 DSH 中。不过，也不排除未来 Antigravity 或 DSH 在官方版本更新后通过原生机制修复这一问题。

### 工作机制
- **移出常驻底噪**：配合 `agy plugin disable <plugin>` 关闭低频插件后，将闲置 Skill 描述与 MCP 声明移出每轮全局系统提示词。
- **本地离线树状索引**：索引生成在插件目录内（`skill-index/`），不主动注入每轮对话上下文；普通问答与常规编码阶段不触发外部插件检索。
- **按需 BM25 + 2 层领域树检索**：仅当任务明确涉及特定专业领域时，由本地 Python 脚本执行 **2 层领域树 + BM25 检索**（支持中英文同义词扩展与基于文件指纹的自动重建），只向模型返回 Top-K 精简摘要和 `SKILL.md` 路径。
- **启用状态感知与分级激活**：实时读取 `config.json` 判断插件启用状态：
  - `mode: direct`：即使插件处于禁用状态，也可直接读取 `SKILL.md` 执行（附带可选开启链接）；
  - `needs-mcp` / `needs-sidecar` / `needs-plugin`：在未启用时提示用户先启用插件，再调用对应工具。

### 常用检索命令
```powershell
# 关键词检索（支持中/英文，返回 Top-3 及启用状态、激活模式、SKILL.md 路径）
python "$env:USERPROFILE\.gemini\config\plugins\budget-orchestrator\scripts\skill_find.py" search "学术论文 arxiv" -k 3

# 逐层浏览 2 层领域树
python "$env:USERPROFILE\.gemini\config\plugins\budget-orchestrator\scripts\skill_find.py" tree
python "$env:USERPROFILE\.gemini\config\plugins\budget-orchestrator\scripts\skill_find.py" tree science/literature

# 显式重建索引（增删或更新插件后，首次 search / tree 也会自动重建）
python "$env:USERPROFILE\.gemini\config\plugins\budget-orchestrator\scripts\skill_find.py" rebuild
```

### 实测效果与示例
在实测环境中关闭非高频领域插件后，每轮注入上下文的插件数量变化：**插件 Skill** 从 **118 个** 降至 **6 个** ， **插件 MCP Server** 从 **17 个** 降至 **1 个**（避免内置 `browser` 等子代理因上下文或预算限制被挤占）

即使在提问中完全不提及英文插件名，本地中文检索也能直接命中对应的、已经关闭的插件，并在获得指令后直接暂时取用：
- 查询 `做网页前端` → 命中已禁用的 `modern-web-guidance-plugin`（`modern-web-guidance`、`chrome-extensions`，`mode: direct`）和 `chrome-devtools-plugin`（`debug-optimize-lcp`）。
- 查询 `阅读论文` → 命中已禁用的 `scientific-literature` 插件（如 `literature-search-arxiv`、`literature-search-biorxiv`、`literature-search-europepmc`）。

<details>
<summary><sub>查看精简检索日志示例（search "做网页前端" -k 3）</sub></summary>

<pre><small>Query: 做网页前端 (matched 14 skills, showing top 3)
[1] modern-web-guidance | web/modern-web | plugin: modern-web-guidance-plugin (disabled) | mode: direct | score: 40.89
    SKILL: C:\Users\&lt;USER&gt;\.gemini\config\plugins\modern-web-guidance-plugin\skills\modern-web-guidance\SKILL.md
[2] chrome-extensions | web/modern-web | plugin: modern-web-guidance-plugin (disabled) | mode: direct | score: 33.32
    SKILL: C:\Users\&lt;USER&gt;\.gemini\config\plugins\modern-web-guidance-plugin\skills\chrome-extensions\SKILL.md
[3] debug-optimize-lcp | web/devtools | plugin: chrome-devtools-plugin (disabled) | mode: direct | score: 23.91
    SKILL: C:\Users\&lt;USER&gt;\.gemini\config\plugins\chrome-devtools-plugin\skills\debug-optimize-lcp\SKILL.md</small></pre>

</details>

---

## 2. 子代理集群调度与配额管控

### 子代理调度节约策略 （可能已经被官方更新的orchestrater替代？不清楚，先留着）
- **并发阈值审批（≥3）**：准备并发启动 3 个及以上子代理前，先向用户展示任务拆分与按复杂度匹配的模型层级建议（复杂推理或深度重构使用主模型/`pro`，轻量化检索使用 `flash`/`flash_lite`），确认后再启动。
- **阶段性上下文重置**：子代理完成阶段任务后，通过销毁重建或发送精简交接摘要的方式重置上下文，控制多阶段长任务的 token 累积， 尤其是无法触发缓存命中的时候。

### 按需后台配额监控（`client_quota_watcher.py`）
- **本地 RPC 实时读取**：通过 Antigravity 客户端本地调试端口（读取 `DevToolsActivePort` 或探测进程端口）调用内部接口 `retrieveUserQuotaSummary` 获取实时配额，不依赖客户端界面延迟刷新。
- **按需静默启动与空闲退出**：多步任务或子代理任务启动时通过 PowerShell 在后台拉起，与主对话进程解耦：
  ```powershell
  Start-Process -FilePath "python.exe" -ArgumentList "$env:USERPROFILE\.gemini\config\plugins\budget-orchestrator\scripts\client_quota_watcher.py", "--convo-id", "<CONVERSATION_ID>", "--model-group", "<CURRENT_MODEL>" -WindowStyle Hidden
  ```
  脚本每 5 秒轮询一次配额并检查会话数据库写入时间，连续 2 次无活动（约 10 秒）后输出 `Auto-terminating watcher` 并退出，不常驻后台，也不占用聊天界面的任务状态槽。
- **活跃模型组隔离**：仅监控当前对话正在使用的模型组（`Gemini Models`、`Claude and GPT models` 或 `Gemini 4 Argon`），其他模型组余量不影响当前任务。
- **阶梯提醒与三级预警**：5 小时限额每消耗 10%、周限额每消耗 5%、Credit 每消耗 100 时，触发系统提示音与 Windows 托盘通知；进入最后 3 个阶梯（5h 剩余 ≤30% / ≤20% / ≤10%；周限额剩余 ≤15% / ≤10% / ≤5%）时，触发低余量预警。

---

## 3. 执行可靠性与交互反馈

- **安全停车与断点保存（`checkpoint.md`）**：触发低余量预警、HTTP 429/402 或连续 3 次工具报错时，等待正在进行的文件写入到达完整语法边界后暂停，并将已完成项（`- [x]`）与待办项（`- [ ]`）保存至 Antigravity 原生 Artifact 目录下的 `checkpoint.md`，不污染项目工作区。
- **首次工具调用前简短提示**：收到用户请求后，仅在首次工具调用前输出一句简短的操作说明（自动排除启动监控脚本等插件内部动作），随后恢复客户端原生汇报行为。
- **纯英文规则描述**：`rules/AGENTS.md`、索引输出与监控脚本采用英文编写，与客户端底层系统提示词保持一致，减少中英混写导致的回复语种偏移，同时严格跟随用户最新提问的语言回复。

---

## 4. 自定义配置与项目结构

### 配置调整
- **配额轮询参数**：可修改 `scripts/client_quota_watcher.py` 顶部的全局常量：
  - `CHECK_INTERVAL_SECONDS = 5.0`（轮询间隔秒数）
  - `MAX_INACTIVE_STRIKES = 2`（连续空闲几次后退出）
  - `ACTIVE_WINDOW_SECONDS = 8.0`（判断会话活跃的时间窗口）
- **Skill 路由词表与领域映射**：如需补充领域分类、双语同义词表（`CN_EN_SYNONYMS`）或激活模式判定逻辑，可编辑 `scripts/build_skill_index.py` 后执行 `skill_find.py rebuild`。

### 项目结构
```text
BetterGravity/
├── plugin.json                     # Antigravity 全局插件清单 (budget-orchestrator v1.1.0)
├── rules/
│   └── AGENTS.md                   # 全局规则：Skill 路由、子代理调度、配额护栏与反馈规范
├── scripts/
│   ├── build_skill_index.py        # 扫描本机插件与 ~/.agents/skills 生成 2 层树与 BM25 索引
│   ├── skill_find.py               # 本机离线检索 CLI（含指纹校验自动重建与启用状态检查）
│   ├── client_quota_watcher.py     # 配额实时监控与低余量告警脚本
│   ├── start_watcher.bat           # Windows 批处理启动脚本
│   └── start_watcher.vbs           # Windows 无窗口启动脚本
├── install.ps1                     # 安装/同步至全局插件目录并初始化索引
└── README.md
```

---

## 5. 安装指引

**一键安装（推荐）：** 在 PowerShell 中进入项目目录运行 `install.ps1`（自动同步文件至全局插件目录，并在检测到 Python 时初始化 `skill-index/`）：
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install.ps1
```

**手动安装：** 将项目文件复制至以下全局插件目录，并执行一次 `skill_find.py rebuild`（或等待首次检索时自动生成 `skill-index\`）：
```text
%USERPROFILE%\.gemini\config\plugins\budget-orchestrator\
```

安装完成后，可使用 `agy plugin disable <插件名>`  或者直接在GUI设置栏的conversation页里，关闭低频领域插件，交由 `skill_find.py` 按需检索，仅保持日常高频插件启用。重启 Antigravity 客户端或新建会话后生效。

---

## License
MIT License.
