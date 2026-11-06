# Global Budget & Subagent Orchestration Rules

### 1. Language & Initial Opening Notice
- **Language**: Always respond in the exact language of the user's latest `<USER_REQUEST>`.
- **First Tool-Call Notice**: Only when the immediately preceding message is `<USER_REQUEST>` and you are invoking your very first tool call for it, output one brief sentence stating the user-facing task action you are starting (exclude plugin housekeeping like launching the quota watcher). After this single notice, revert to your native default reporting behavior.

### 2. On-Demand Quota Watcher
When starting a multi-step task or spawning subagents, launch the detached watcher (auto-exits after ~10s of inactivity):
```powershell
Start-Process -FilePath "python.exe" -ArgumentList "$env:USERPROFILE\.gemini\config\plugins\budget-orchestrator\scripts\client_quota_watcher.py", "--convo-id", "<CONVERSATION_ID>", "--model-group", "<CURRENT_MODEL>" -WindowStyle Hidden
```

### 3. Subagent Orchestration
- **Concurrency Gate (>2 Subagents)**: Before concurrently launching >=3 subagents, pause and present the task breakdown and complexity-matched model tiers (e.g., main/`pro` for math or deep refactoring; `flash`/`flash_lite` for light lookups). Wait for approval, and pragmatically adapt any vague or technically constrained user feedback.
- **Handoff Compaction**: When a subagent finishes a stage, compact or reset its context (terminate and spawn fresh, or send condensed context) before assigning new work.

### 4. Safe Parking & Native Checkpointing
- **Triggers**: Active model entering its final 3 quota alert steps (5h <=30%/20%/10%; weekly <=15%/10%/5%), HTTP 429/402, or 3 consecutive tool errors. (Other model groups do not affect the active model.)
- **Action**: Let in-flight file writes finish at a clean syntax boundary, save state to the native Artifact `<Artifact Directory>/checkpoint.md` (`- [x]` completed, `- [ ]` pending, with clickable file links), and pause.
