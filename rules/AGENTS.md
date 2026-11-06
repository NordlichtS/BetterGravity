# Global Budget & Subagent Orchestration Rules

Always respond in the exact language used by the user in their latest `<USER_REQUEST>`.

---

### 1. Single Opening Notice per `<USER_REQUEST>` (Strict Anti-Repeat Rule)
- **Trigger Condition**: Emit a brief one-sentence notice of what you are about to do **ONLY** when BOTH conditions hold:
  1. The immediately preceding message in the conversation is a direct user prompt enclosed in `<USER_REQUEST>` tags (NOT a tool execution result, NOT a `<SYSTEM_MESSAGE>`, and NOT a subagent notification), AND
  2. You are about to invoke your very first tool call for that `<USER_REQUEST>`.
- **Strict Silence Afterwards**: After emitting that single opening sentence once for a `<USER_REQUEST>`, **DO NOT** output any status notices before subsequent tool calls in the same task, and **DO NOT** trigger this notice on wakeups from background tasks, subagents, or `<SYSTEM_MESSAGE>` events.

---

### 2. On-Demand Session Quota Watcher
When starting a multi-step task or spawning subagents, launch the detached session watcher in the background (occupies no UI task slot and auto-exits after ~10s of inactivity):
```powershell
Start-Process -FilePath "python.exe" -ArgumentList "$env:USERPROFILE\.gemini\config\plugins\budget-orchestrator\scripts\client_quota_watcher.py", "--convo-id", "<CONVERSATION_ID>", "--model-group", "<CURRENT_MODEL>" -WindowStyle Hidden
```

---

### 3. Subagent Concurrency Gate & Model Negotiation
1. **Approval Gate**: Before concurrently launching **>2 subagents** (3 or more), pause and briefly present the task breakdown and suggested model tiers to the user, waiting for approval before invoking them.
2. **Complexity-Based Tiering**: Suggest model tiers based on actual task complexity (e.g., retain the main/high-reasoning model for mathematical derivations or deep refactoring; use `flash` / `flash_lite` for lightweight lookups). Never force a blanket downgrade.
3. **Flexible Adaptation**: Incorporate user feedback on model tiers; if the user's instructions are vague, ambiguous, or conflict with technical constraints, adapt pragmatically without rigid literalism.

---

### 4. Handoff Context Compaction
When a subagent completes a stage and reports back, compact or clear its context (either terminate the old subagent and spawn a fresh one, or send a condensed instruction) before assigning follow-up work to prevent context bloat and hallucinations.

---

### 5. Multi-Tier Safe Parking & Native Artifact Checkpointing
1. **Active-Model Isolation**: Monitor quota only for the model family active in the current conversation; other model groups do not affect the current run.
2. **Triple Danger Net**: When the active model's remaining quota enters the final 3 alert thresholds (5h limit <=30%, <=20%, <=10%; or weekly limit <=15%, <=10%, <=5%), every threshold crossed is a mandatory safe-parking trigger.
3. **Safe Boundary & Native Artifact Persistence**:
   - Never abort mid-edit or leave broken syntax; let the current file write flush cleanly.
   - Persist the checkpoint as a native Antigravity **Artifact Markdown** file at `<Artifact Directory>/checkpoint.md` using a clean task list (`- [x]` completed, `- [ ]` pending) and clickable file links. Do not write redundant JSON checkpoint files into the user's project workspace.
4. **Circuit Breaker**: On HTTP 429/402 or 3 consecutive tool errors, immediately save `<Artifact Directory>/checkpoint.md` and pause safely to prevent infinite retry loops.
