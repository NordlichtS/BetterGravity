"""
Active Quota Watcher for Google Antigravity Client (Windows)
Project: BetterGravity (Budget & Subagent Orchestration Suite)

Core Capabilities:
1. Direct connection to Antigravity internal debugging port (CDP).
2. Calls internal RPC retrieveUserQuotaSummary() for live real-time quota data.
3. Check cadence: Exactly once every 5 seconds.
4. Auto-Exit (Zero Resource Leak):
   - Monitors conversation activity (DB / WAL write timestamps).
   - If conversation is detected inactive on 2 consecutive queries (~10s idle),
     the watcher automatically and safely terminates itself.
5. Sound alert & Windows Native Toast notification (non-blocking).
   - 5h limit: every 10% consumed
   - Weekly limit: every 5% consumed
   - Credit: every 100 consumed
6. Triple Danger Safety Net for active model:
   - When remaining limit enters the final 3 steps (<= 30% for 5h, <= 15% for weekly),
     every step triggers double alert and writes .danger_parking_alert flag to workspace.
7. Model isolation: Only monitors the model group active in current conversation.
"""

import socket
import json
import urllib.request
import base64
import os
import sys
import time
import subprocess
import argparse
from datetime import datetime

# ==============================================================================
# 全局可调配置常量 (Global Configuration Constants)
# 用户可在此根据个人偏好调整轮询间隔与自动退出灵敏度
# ==============================================================================
CHECK_INTERVAL_SECONDS = 5.0     # 统一轮询间隔（秒）：每隔多少秒执行一次“活跃检测 + 余额配额同步”
MAX_INACTIVE_STRIKES = 2        # 连续无活动次数上限：连续多少次检测到对话未在运行后自动退出进程
ACTIVE_WINDOW_SECONDS = 8.0     # 判定活跃的时间窗口（秒）：最后一次文件写入距离当前小于该值视为活跃

STATE_DIR = os.path.expanduser(r"~\.gemini\config\plugins\budget-orchestrator")
LOG_FILE = os.path.join(STATE_DIR, "watcher.log")

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        sys.stdout.buffer.write((line + "\n").encode('utf-8', errors='replace'))
        sys.stdout.flush()
    except Exception:
        pass
    try:
        if not os.path.exists(STATE_DIR):
            os.makedirs(STATE_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def play_sound(is_danger=False):
    try:
        if is_danger:
            cmd = '[System.Media.SystemSounds]::Hand.Play(); Start-Sleep -Milliseconds 250; [System.Media.SystemSounds]::Hand.Play()'
        else:
            cmd = '[System.Media.SystemSounds]::Asterisk.Play()'
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log(f"Sound error: {e}")

def show_toast(title, message, is_danger=False):
    log(f"TOAST: [{title}] {message} (Danger={is_danger})")
    play_sound(is_danger)
    ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
$notify = New-Object System.Windows.Forms.NotifyIcon
$icon = [System.Drawing.SystemIcons]::Information
if ("{is_danger}" -eq "True") {{
    $icon = [System.Drawing.SystemIcons]::Warning
}}
$notify.Icon = $icon
$notify.Visible = $true
$tipIcon = [System.Windows.Forms.ToolTipIcon]::Info
if ("{is_danger}" -eq "True") {{
    $tipIcon = [System.Windows.Forms.ToolTipIcon]::Warning
}}
$notify.ShowBalloonTip(6000, "{title}", "{message}", $tipIcon)
Start-Sleep -Seconds 6
$notify.Dispose()
"""
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log(f"Toast error: {e}")

_cached_port = None

def get_antigravity_target():
    global _cached_port
    candidates = []
    if _cached_port:
        candidates.append(_cached_port)

    # Read Electron DevToolsActivePort if available
    devtools_file = os.path.expandvars(r"%APPDATA%\Antigravity\DevToolsActivePort")
    if os.path.exists(devtools_file):
        try:
            with open(devtools_file, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                if first_line.isdigit():
                    p = int(first_line)
                    if p not in candidates:
                        candidates.append(p)
        except Exception:
            pass

    for port in candidates:
        try:
            req = urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=0.3)
            targets = json.loads(req.read().decode())
            for t in targets:
                if "Antigravity" in t.get("title", ""):
                    _cached_port = port
                    return port, t
        except Exception:
            pass

    # Dynamic fallback port discovery for Antigravity processes
    try:
        res = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetTCPConnection -State Listen -OwningProcess (Get-Process -Name Antigravity -ErrorAction SilentlyContinue).Id -ErrorAction SilentlyContinue | Select-Object -ExpandProperty LocalPort"],
            text=True
        )
        for line in res.splitlines():
            line = line.strip()
            if line.isdigit():
                p = int(line)
                if p in candidates:
                    continue
                try:
                    req = urllib.request.urlopen(f"http://127.0.0.1:{p}/json", timeout=0.2)
                    targets = json.loads(req.read().decode())
                    for t in targets:
                        if "Antigravity" in t.get("title", ""):
                            _cached_port = p
                            return p, t
                except Exception:
                    continue
    except Exception:
        pass
    return None, None

def fetch_live_quota(port, target):
    s = socket.socket()
    s.settimeout(3.0)
    s.connect(("127.0.0.1", port))
    key = base64.b64encode(os.urandom(16)).decode("utf-8")
    headers = (
        f"GET /devtools/page/{target['id']} HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n\r\n"
    )
    s.sendall(headers.encode())
    s.recv(4096)

    def send_frame(msg):
        data = msg.encode("utf-8")
        frame = bytearray([0x81])
        length = len(data)
        if length <= 125:
            frame.append(0x80 | length)
        elif length <= 65535:
            frame.extend([0x80 | 126, (length >> 8) & 0xFF, length & 0xFF])
        mask = os.urandom(4)
        frame.extend(mask)
        frame.extend(bytearray(b ^ mask[i % 4] for i, b in enumerate(data)))
        s.sendall(frame)

    js_code = """
    (async function() {
        try {
            var root = document.querySelector('#root');
            if (!root) return JSON.stringify({ error: 'no_root' });
            var fiberKey = Object.keys(root).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactContainer'));
            var fiber = root[fiberKey];
            var quotaService = null;
            
            function walk(node, d) {
                if (!node || d > 60 || quotaService) return;
                if (node.memoizedProps) {
                    for (var key in node.memoizedProps) {
                        if (node.memoizedProps[key] && typeof node.memoizedProps[key].retrieveUserQuotaSummary === 'function') {
                            quotaService = node.memoizedProps[key];
                            return;
                        }
                    }
                }
                if (node.memoizedState) {
                    var s = node.memoizedState;
                    while (s) {
                        if (s.memoizedState && typeof s.memoizedState.retrieveUserQuotaSummary === 'function') {
                            quotaService = s.memoizedState;
                            return;
                        }
                        s = s.next;
                    }
                }
                walk(node.child, d + 1);
                walk(node.sibling, d);
            }
            walk(fiber, 0);
            
            if (quotaService) {
                var raw = await quotaService.retrieveUserQuotaSummary();
                return JSON.stringify(raw, (k, v) => typeof v === 'bigint' ? v.toString() : v);
            }
            return JSON.stringify({ error: 'service_not_found' });
        } catch(err) {
            return JSON.stringify({ error: err.toString() });
        }
    })()
    """

    send_frame(json.dumps({
        "id": 1,
        "method": "Runtime.evaluate",
        "params": {"expression": js_code, "awaitPromise": True, "returnByValue": True}
    }))

    data = bytearray()
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > 2:
            plen = data[1] & 0x7F
            hlen = 2
            if plen == 126:
                hlen = 4
                plen = (data[2] << 8) | data[3]
            elif plen == 127:
                hlen = 10
                plen = int.from_bytes(data[2:10], "big")
            if len(data) >= hlen + plen:
                raw_json = json.loads(data[hlen:hlen+plen].decode("utf-8"))
                val_str = raw_json.get("result", {}).get("result", {}).get("value")
                s.close()
                if val_str:
                    return json.loads(val_str)
                break
    s.close()
    return None

def is_convo_active(convo_id, threshold_seconds=8.0):
    """
    Returns True if conversation database / WAL / SHM was modified within threshold_seconds.
    """
    if not convo_id:
        return False
    base_path = os.path.expanduser(f"~\\.gemini\\antigravity\\conversations\\{convo_id}.db")
    times = []
    for f in [base_path, base_path + "-wal", base_path + "-shm"]:
        if os.path.exists(f):
            try:
                times.append(os.path.getmtime(f))
            except Exception:
                pass
    if times:
        elapsed = time.time() - max(times)
        return elapsed < threshold_seconds
    return False

def run_watcher(convo_id=None, target_model_prefix=None, workspace_dir=None):
    log(f"Active Session Quota Watcher started for Convo [{convo_id}], Model Prefix: [{target_model_prefix}]")
    
    buckets_state = {}
    check_interval = CHECK_INTERVAL_SECONDS
    inactive_consecutive_count = 0
    max_inactive_strikes = MAX_INACTIVE_STRIKES

    while True:
        # Check active status of the conversation
        if convo_id:
            active = is_convo_active(convo_id, threshold_seconds=ACTIVE_WINDOW_SECONDS)
            if not active:
                inactive_consecutive_count += 1
                log(f"Convo [{convo_id}] inactive check {inactive_consecutive_count}/{max_inactive_strikes}")
                if inactive_consecutive_count >= max_inactive_strikes:
                    log(f"Convo [{convo_id}] inactive for {max_inactive_strikes} consecutive cycles (~{int(max_inactive_strikes * check_interval)}s). Auto-terminating watcher.")
                    break
            else:
                # Active! Reset consecutive strike counter
                if inactive_consecutive_count > 0:
                    log(f"Convo [{convo_id}] activity resumed, resetting inactive counter.")
                inactive_consecutive_count = 0

        # Query live quota
        try:
            port, target = get_antigravity_target()
            if port and target:
                quota_resp = fetch_live_quota(port, target)
                if quota_resp and "response" in quota_resp:
                    groups = quota_resp["response"].get("groups", [])
                    for grp in groups:
                        grp_name = grp.get("displayName", "")
                        
                        # Filter by active model scope
                        if target_model_prefix:
                            p = target_model_prefix.lower()
                            if ("claude" in p or "gpt" in p) and "claude" not in grp_name.lower():
                                continue
                            elif "argon" in p and "argon" not in grp_name.lower():
                                continue
                            elif "gemini" in p and "argon" not in p and "gemini models" not in grp_name.lower():
                                continue

                        for b in grp.get("buckets", []):
                            b_id = b.get("bucketId")
                            b_name = b.get("displayName")
                            window = b.get("window")
                            rem_val = b.get("remaining", {}).get("value", 0.0)
                            rem_pct = rem_val * 100.0

                            if b.get("disabled", False):
                                continue

                            step_size = 5.0 if window == "weekly" else 10.0
                            danger_threshold = step_size * 3.0
                            consumed_pct = 100.0 - rem_pct
                            curr_step = int(consumed_pct // step_size)

                            if b_id not in buckets_state:
                                buckets_state[b_id] = curr_step
                                log(f"Tracking [{grp_name} - {b_name}]: {rem_pct:.1f}% (Step {curr_step})")
                            elif curr_step > buckets_state[b_id]:
                                is_danger = rem_pct <= danger_threshold
                                title = f"Antigravity 额度消耗提醒 ({grp_name})"
                                if is_danger:
                                    title = f"⚠️ [危险线停车预警] {grp_name} 配额严重不足!"
                                    desc = f"【最后3次警戒区】{b_name} 剩余 {rem_pct:.1f}%！请在最近安全代码闭合点存盘收敛。"
                                    if workspace_dir and os.path.exists(workspace_dir):
                                        try:
                                            with open(os.path.join(workspace_dir, ".danger_parking_alert"), "w", encoding="utf-8") as f:
                                                f.write(f"DANGER: {grp_name} {b_name} remaining {rem_pct:.1f}%\n")
                                        except Exception:
                                            pass
                                else:
                                    desc = f"{b_name} 消耗达新台阶，当前剩余 {rem_pct:.1f}%。"

                                show_toast(title, desc, is_danger=is_danger)
                                buckets_state[b_id] = curr_step
                            elif curr_step < buckets_state[b_id]:
                                buckets_state[b_id] = curr_step
        except Exception as e:
            log(f"Watch query error: {e}")

        time.sleep(check_interval)

    log(f"Session Quota Watcher exited cleanly for Convo [{convo_id}].")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--convo-id", type=str, default="")
    parser.add_argument("--model-group", type=str, default="")
    parser.add_argument("--workspace", nargs="*", default=[])
    args, _ = parser.parse_known_args()
    ws = " ".join(args.workspace) if isinstance(args.workspace, list) else str(args.workspace)
    run_watcher(args.convo_id, args.model_group, ws)
