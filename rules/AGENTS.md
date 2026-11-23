# BetterGravity Global Rules

### 1. Language & Opening Notice
- **Language**: Always reply in the exact language of the user's latest `<USER_REQUEST>`.
- **First Tool-Call Notice**: Only when the immediately preceding message is `<USER_REQUEST>` and you are invoking the very first tool call for it, output one brief sentence stating the user-facing task action (exclude plugin housekeeping such as launching the quota watcher), then revert to native default reporting.

### 2. On-Demand Quota Watcher
When starting a multi-step task or spawning subagents, launch the detached watcher (auto-exits after ~10s idle):
```powershell
Start-Process -FilePath "python.exe" -ArgumentList "$env:USERPROFILE\.gemini\config\plugins\budget-orchestrator\scripts\client_quota_watcher.py", "--convo-id", "<CONVERSATION_ID>", "--model-group", "<CURRENT_MODEL>" -WindowStyle Hidden
```

### 3. Subagent Orchestration
- **Concurrency Gate (>=3)**: Before concurrently launching >=3 subagents, pause and present the task breakdown with complexity-matched model tiers (main/`pro` for math or deep refactoring; `flash`/`flash_lite` for light lookups). Wait for approval, and pragmatically adapt vague or constrained feedback.
- **Stage Handoff**: Compact or reset a subagent's context (terminate and respawn, or send condensed handoff) between stages.

### 4. Safe Parking & Checkpointing
- **Triggers**: Active model entering its final 3 quota alert steps (5h <=30%/20%/10%; weekly <=15%/10%/5%), HTTP 429/402, or 3 consecutive tool errors (other model groups do not affect the active model).
- **Action**: Let in-flight file writes finish at a clean syntax boundary, save state to native Artifact `<Artifact Directory>/checkpoint.md` (`- [x]` completed, `- [ ]` pending, with clickable file links), and pause.

### 5. On-Demand Local Skill Router
- **Trigger**: Only when the user explicitly requests specialized domain work not covered by active `<skills>`/`<mcp_servers>` (e.g., academic papers/literature, cloud data, web perf/mobile, or custom local skills). Skip for normal chat and general coding.
- **Lookup**: Query the local CPU index (auto-rebuilds on plugin changes; never load full skill catalogs):
  `python "$env:USERPROFILE\.gemini\config\plugins\budget-orchestrator\scripts\skill_find.py" search "<keywords>" -k 3`
  (Use `tree` or `tree <domain>` only when broad browsing is needed.)
- **Activation**: Read only the top 1-2 matched `SKILL.md` files via `read_file`. For `mode: direct`, follow `SKILL.md` directly (and mention its disabled `[<plugin>](customization://<plugin>)` if helpful). For disabled `needs-mcp`/`needs-sidecar`/`needs-plugin` matches, prompt the user to enable `[<plugin>](customization://<plugin>)` (or run `agy plugin enable <plugin>`) before calling plugin tools.
