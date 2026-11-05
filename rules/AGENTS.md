# 全局配额守护与子代理调度准则 (Global Budget & Subagent Guard)

---

### 一、首步工具调用前简短告知 (First Tool-Call Notice)
每次收到用户主动发出的 Prompt 并完成初始思考后，在发起本轮**第一个工具调用（Tool Call，含读写文件、执行命令、网络搜索、启动子代理等）之前/同时**，必须先输出**一句话**简短告知用户马上要做什么（无需等待用户回复，直接继续执行工具；每次用户 Prompt 仅在最开始触发一次，避免用户误判工作尚未开始）。

---

### 二、按需启动 Watcher
长任务或派发子代理时，通过独立后台进程拉起会话监控（不占任务槽，闲置约10秒自动退出）：
```powershell
Start-Process -FilePath "python.exe" -ArgumentList "$env:USERPROFILE\.gemini\config\plugins\budget-orchestrator\scripts\client_quota_watcher.py", "--convo-id", "<CONVERSATION_ID>", "--model-group", "<CURRENT_MODEL>" -WindowStyle Hidden
```

---

### 三、子代理启动门禁与模型协商
1. **启动审批**：即将并发启动 **>2 个 Subagent** 时，必须暂停并向用户简报分工结构与建议的模型档位，待用户确认后启动。
2. **合理定级**：按任务实际复杂度（如复杂数学推导、深度重构建议保持主模型/高强度，轻量检索可用 flash）建议模型，不强制降级。
3. **弹性采纳意见**：参考用户的反馈调整推理强度；若用户要求模糊、存在歧义或不符合技术约束，结合实际技术可行性合理适配，无需死板照搬。

---

### 四、阶段交接与上下文精简
Subagent 完成阶段任务汇报后，必须压缩或清理上下文（终结旧子代理开辟新上下文，或下发精简指令）再接新活，防止长上下文拖慢响应或引发幻觉。

---

### 五、多级安全停车与原生 Artifact 断点协议
1. **模型隔离**：仅监控当前任务活跃的模型族系，不同模型互不干扰。
2. **三重危险线**：活跃模型剩余额度进入最后 3 次警报区间（5h 剩余 ≤30%、≤20%、≤10%；周剩余 ≤15%、≤10%、≤5%）时，每次步长触发均为必须刹车的危险线。
3. **安全点收敛与原生 Artifact 存盘**：
   - 严禁半截腰斩，等待当前语法闭合、文件落盘；
   - 直接使用 Antigravity 原生 **Artifact Markdown** 格式写入会话 Artifact 目录（`<Artifact Directory>/checkpoint.md`），用清晰的 Markdown 任务列表（`- [x]` 已完成、` - [ ]` 待继续）及文件链接记录断点，不向用户代码库写入冗余 JSON 垃圾文件。
4. **异常熔断**：遇到 429/402 或连续报错 3 次立即按上述原生 Artifact 格式存盘退出，杜绝死循环。
