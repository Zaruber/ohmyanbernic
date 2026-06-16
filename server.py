#!/usr/bin/env python3
"""
Anbernic RG405V Dashboard Server v2
File manager, process manager, script runner.
No external dependencies — Python stdlib only.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
import threading
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from collections import deque

PORT = 8080
SERVE_DIR = Path(__file__).parent
HOME_DIR = Path.home()

# ─── Script Session Manager ─────────────────────────────────

class SessionManager:
    """Track running Python script sessions."""

    def __init__(self):
        self.sessions = {}  # pid -> {process, name, started, output_file}

    def run(self, script_path):
        """Launch a Python script in background."""
        script = Path(script_path)
        if not script.exists():
            return {"error": f"File not found: {script_path}"}
        if not script.suffix == ".py":
            return {"error": "Only .py files can be run"}

        output_file = HOME_DIR / f".dashboard_session_{int(time.time())}.log"

        with open(output_file, "w") as f:
            proc = subprocess.Popen(
                [sys.executable, str(script)],
                stdout=f,
                stderr=subprocess.STDOUT,
                cwd=str(script.parent),
                start_new_session=True,
            )

        self.sessions[proc.pid] = {
            "process": proc,
            "name": script.name,
            "path": str(script),
            "started": time.time(),
            "output_file": str(output_file),
        }

        return {"pid": proc.pid, "name": script.name, "status": "running"}

    def list_sessions(self):
        """List all tracked sessions with status."""
        result = []
        dead_pids = []

        for pid, info in self.sessions.items():
            proc = info["process"]
            poll = proc.poll()
            status = "running" if poll is None else f"exited ({poll})"

            elapsed = time.time() - info["started"]
            if elapsed < 60:
                duration = f"{int(elapsed)}s"
            elif elapsed < 3600:
                duration = f"{int(elapsed // 60)}m {int(elapsed % 60)}s"
            else:
                duration = f"{int(elapsed // 3600)}h {int((elapsed % 3600) // 60)}m"

            result.append({
                "pid": pid,
                "name": info["name"],
                "path": info["path"],
                "status": status,
                "duration": duration,
                "started": info["started"],
            })

            # Clean up sessions that exited more than 1 hour ago
            if poll is not None and elapsed > 3600:
                dead_pids.append(pid)

        for pid in dead_pids:
            self._cleanup(pid)

        return result

    def get_output(self, pid):
        """Get stdout/stderr of a session."""
        pid = int(pid)
        if pid not in self.sessions:
            return {"error": "Session not found"}

        output_file = self.sessions[pid]["output_file"]
        try:
            with open(output_file, "r", errors="replace") as f:
                # Read last 200 lines
                lines = f.readlines()
                tail = lines[-200:] if len(lines) > 200 else lines
                return {"pid": pid, "output": "".join(tail), "total_lines": len(lines)}
        except FileNotFoundError:
            return {"pid": pid, "output": "", "total_lines": 0}

    def kill(self, pid):
        """Kill a session."""
        pid = int(pid)
        if pid not in self.sessions:
            return {"error": "Session not found"}

        proc = self.sessions[pid]["process"]
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                proc.terminate()

        return {"pid": pid, "status": "killed"}

    def _cleanup(self, pid):
        """Remove session and its log file."""
        if pid in self.sessions:
            output_file = self.sessions[pid].get("output_file")
            if output_file and os.path.exists(output_file):
                try:
                    os.unlink(output_file)
                except OSError:
                    pass
            del self.sessions[pid]


sessions = SessionManager()


# ─── Metrics History ─────────────────────────────────────────

class MetricsHistory:
    """Collect and store metrics over time."""

    def __init__(self, max_points=360):
        # 360 points × 10s interval = 1 hour of history
        self.max_points = max_points
        self.data = deque(maxlen=max_points)
        self._lock = threading.Lock()

    def record(self):
        """Take a snapshot of current metrics."""
        cpu = get_cpu_usage()
        mem = get_memory_info()
        bat = get_battery_info()

        point = {
            "ts": time.time(),
            "cpu": cpu,
            "ram": mem["percent"],
            "ram_used": mem["used_mb"],
            "bat": bat["percent"],
            "bat_temp": bat.get("temperature", 0),
        }

        with self._lock:
            self.data.append(point)

    def get_history(self):
        """Return all recorded data points."""
        with self._lock:
            return list(self.data)

    def start_collector(self, interval=10):
        """Start background collection thread."""
        def _run():
            while True:
                try:
                    self.record()
                except Exception:
                    pass
                time.sleep(interval)

        t = threading.Thread(target=_run, daemon=True)
        t.start()


metrics = MetricsHistory()


# ─── System Stats ────────────────────────────────────────────

def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        return result.stdout.strip()
    except Exception:
        return ""


def get_cpu_usage():
    try:
        load = run_cmd("cat /proc/loadavg")
        if load:
            cpu_count = os.cpu_count() or 4
            load_1m = float(load.split()[0])
            return min(round((load_1m / cpu_count) * 100, 1), 100.0)
    except Exception:
        pass
    return 0.0


def get_memory_info():
    try:
        meminfo = run_cmd("cat /proc/meminfo")
        info = {}
        for line in meminfo.splitlines():
            parts = line.split(":")
            if len(parts) == 2:
                key = parts[0].strip()
                val = int(parts[1].strip().split()[0])
                info[key] = val
        total = info.get("MemTotal", 0)
        available = info.get("MemAvailable", info.get("MemFree", 0))
        used = total - available
        return {
            "total_mb": round(total / 1024),
            "used_mb": round(used / 1024),
            "percent": round((used / total) * 100, 1) if total else 0,
        }
    except Exception:
        return {"total_mb": 0, "used_mb": 0, "percent": 0}


def get_storage_info():
    try:
        df_output = run_cmd("df -h /data/data/com.termux 2>/dev/null || df -h $HOME")
        lines = df_output.splitlines()
        if len(lines) >= 2:
            parts = lines[-1].split()
            return {
                "total": parts[1] if len(parts) > 1 else "?",
                "used": parts[2] if len(parts) > 2 else "?",
                "available": parts[3] if len(parts) > 3 else "?",
                "percent": int(parts[4].replace("%", "")) if len(parts) > 4 else 0,
            }
    except Exception:
        pass
    return {"total": "?", "used": "?", "available": "?", "percent": 0}


def get_battery_info():
    try:
        bat = run_cmd("termux-battery-status 2>/dev/null")
        if bat:
            data = json.loads(bat)
            return {
                "percent": data.get("percentage", -1),
                "status": data.get("status", "UNKNOWN"),
                "temperature": data.get("temperature", 0),
            }
    except Exception:
        pass
    try:
        capacity = run_cmd("cat /sys/class/power_supply/battery/capacity 2>/dev/null")
        status = run_cmd("cat /sys/class/power_supply/battery/status 2>/dev/null")
        temp = run_cmd("cat /sys/class/power_supply/battery/temp 2>/dev/null")
        return {
            "percent": int(capacity) if capacity else -1,
            "status": status or "UNKNOWN",
            "temperature": round(int(temp) / 10, 1) if temp else 0,
        }
    except Exception:
        return {"percent": -1, "status": "UNKNOWN", "temperature": 0}


def get_uptime():
    try:
        raw = run_cmd("cat /proc/uptime")
        if raw:
            seconds = int(float(raw.split()[0]))
            days = seconds // 86400
            hours = (seconds % 86400) // 3600
            minutes = (seconds % 3600) // 60
            if days > 0:
                return f"{days}d {hours}h {minutes}m"
            elif hours > 0:
                return f"{hours}h {minutes}m"
            else:
                return f"{minutes}m"
    except Exception:
        pass
    return "N/A"


def get_system_stats():
    return {
        "cpu_percent": get_cpu_usage(),
        "memory": get_memory_info(),
        "storage": get_storage_info(),
        "battery": get_battery_info(),
        "uptime": get_uptime(),
        "device": "Anbernic RG405V",
    }


def get_network_info():
    hostname = socket.gethostname()
    ip = run_cmd("hostname -I 2>/dev/null || ip route get 1 2>/dev/null | awk '{print $NF; exit}'")
    return {
        "hostname": hostname,
        "ip": ip.split()[0] if ip else "N/A",
        "port": PORT,
        "ssh_port": 8022,
    }


# ─── File Manager ────────────────────────────────────────────

def safe_path(requested_path):
    """Ensure path stays within HOME_DIR."""
    base = HOME_DIR.resolve()
    target = (base / requested_path).resolve()
    if not str(target).startswith(str(base)):
        return None
    return target


def list_files(dir_path):
    """List files in a directory."""
    target = safe_path(dir_path)
    if target is None:
        return {"error": "Access denied"}
    if not target.exists():
        return {"error": "Directory not found"}
    if not target.is_dir():
        return {"error": "Not a directory"}

    items = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            try:
                stat = entry.stat()
                items.append({
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": stat.st_size if not entry.is_dir() else 0,
                    "modified": stat.st_mtime,
                    "path": str(entry.relative_to(HOME_DIR)),
                })
            except (PermissionError, OSError):
                items.append({
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": 0,
                    "modified": 0,
                    "path": str(entry.relative_to(HOME_DIR)),
                    "error": "permission denied",
                })
    except PermissionError:
        return {"error": "Permission denied"}

    return {
        "path": str(target.relative_to(HOME_DIR)) if target != HOME_DIR else "",
        "items": items,
        "parent": str(target.parent.relative_to(HOME_DIR)) if target != HOME_DIR else None,
    }


def read_file_content(file_path):
    """Read a text file (max 50KB)."""
    target = safe_path(file_path)
    if target is None:
        return {"error": "Access denied"}
    if not target.exists():
        return {"error": "File not found"}
    if not target.is_file():
        return {"error": "Not a file"}
    if target.stat().st_size > 50 * 1024:
        return {"error": "File too large (>50KB)"}

    try:
        content = target.read_text(errors="replace")
        return {"path": file_path, "content": content, "size": len(content)}
    except Exception as e:
        return {"error": str(e)}


def delete_file(file_path):
    """Delete a file or empty directory."""
    target = safe_path(file_path)
    if target is None:
        return {"error": "Access denied"}
    if not target.exists():
        return {"error": "File not found"}
    if target == HOME_DIR:
        return {"error": "Cannot delete home directory"}

    try:
        if target.is_dir():
            target.rmdir()  # Only empty dirs
        else:
            target.unlink()
        return {"deleted": file_path}
    except OSError as e:
        return {"error": str(e)}


# ─── Process Manager ────────────────────────────────────────

def get_processes():
    """List running processes."""
    try:
        output = run_cmd("ps aux 2>/dev/null || ps -ef 2>/dev/null")
        if not output:
            return []

        lines = output.splitlines()
        if not lines:
            return []

        processes = []
        for line in lines[1:]:  # Skip header
            parts = line.split(None, 10)
            if len(parts) < 4:
                continue

            try:
                # ps aux format: USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND
                proc = {
                    "user": parts[0],
                    "pid": int(parts[1]),
                    "cpu": parts[2],
                    "mem": parts[3],
                    "command": parts[-1][:80] if parts else "",
                }
                processes.append(proc)
            except (ValueError, IndexError):
                continue

        # Sort by CPU usage descending
        processes.sort(key=lambda p: float(p.get("cpu", 0)), reverse=True)
        return processes[:50]  # Top 50
    except Exception:
        return []


def kill_process(pid):
    """Kill a process by PID."""
    try:
        pid = int(pid)
        os.kill(pid, signal.SIGTERM)
        return {"killed": pid}
    except ProcessLookupError:
        return {"error": "Process not found"}
    except PermissionError:
        return {"error": "Permission denied"}
    except Exception as e:
        return {"error": str(e)}


# ─── HTTP Handler ────────────────────────────────────────────

class DashboardHandler(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SERVE_DIR), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path == "/api/stats":
            self.send_json(get_system_stats())
        elif path == "/api/network":
            self.send_json(get_network_info())
        elif path == "/api/files":
            dir_path = params.get("path", [""])[0]
            self.send_json(list_files(dir_path))
        elif path == "/api/files/read":
            file_path = params.get("path", [""])[0]
            self.send_json(read_file_content(file_path))
        elif path == "/api/processes":
            self.send_json(get_processes())
        elif path == "/api/scripts/sessions":
            self.send_json(sessions.list_sessions())
        elif path == "/api/scripts/output":
            pid = params.get("pid", [""])[0]
            self.send_json(sessions.get_output(pid))
        elif path == "/api/history":
            self.send_json(metrics.get_history())
        elif path == "/":
            self.path = "/index.html"
            super().do_GET()
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))

        if path == "/api/scripts/run":
            body = json.loads(self.rfile.read(content_length))
            script_path = body.get("path", "")
            # Resolve relative to HOME
            full_path = HOME_DIR / script_path
            self.send_json(sessions.run(str(full_path)))

        elif path == "/api/files/upload":
            # Parse multipart form data (simplified)
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" in content_type:
                self._handle_upload(content_type, content_length)
            else:
                self.send_json({"error": "Expected multipart/form-data"})
        else:
            self.send_json({"error": "Not found"}, 404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path == "/api/files":
            file_path = params.get("path", [""])[0]
            self.send_json(delete_file(file_path))
        elif path == "/api/processes":
            pid = params.get("pid", [""])[0]
            self.send_json(kill_process(pid))
        elif path == "/api/scripts/kill":
            pid = params.get("pid", [""])[0]
            self.send_json(sessions.kill(pid))
        else:
            self.send_json({"error": "Not found"}, 404)

    def _handle_upload(self, content_type, content_length):
        """Handle file upload via multipart form data."""
        try:
            # Extract boundary
            boundary = content_type.split("boundary=")[1].strip()
            raw = self.rfile.read(content_length)

            # Parse parts
            parts = raw.split(f"--{boundary}".encode())
            upload_dir = ""
            file_data = None
            file_name = ""

            for part in parts:
                if b"Content-Disposition" not in part:
                    continue

                header_end = part.find(b"\r\n\r\n")
                if header_end < 0:
                    continue

                header = part[:header_end].decode(errors="replace")
                body = part[header_end + 4:]
                if body.endswith(b"\r\n"):
                    body = body[:-2]

                if 'name="dir"' in header:
                    upload_dir = body.decode(errors="replace").strip()
                elif 'name="file"' in header:
                    # Extract filename
                    for h in header.split("\r\n"):
                        if "filename=" in h:
                            file_name = h.split('filename="')[1].split('"')[0]
                    file_data = body

            if file_data and file_name:
                target_dir = safe_path(upload_dir) if upload_dir else HOME_DIR
                if target_dir is None:
                    self.send_json({"error": "Access denied"})
                    return

                target_file = target_dir / file_name
                target_file.write_bytes(file_data)
                self.send_json({"uploaded": file_name, "size": len(file_data)})
            else:
                self.send_json({"error": "No file provided"})

        except Exception as e:
            self.send_json({"error": f"Upload failed: {str(e)}"})

    def send_json(self, data, status=200):
        response = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format, *args):
        pass  # Quiet


# ─── Main ────────────────────────────────────────────────────

if __name__ == "__main__":
    # Start metrics collection (every 10 seconds)
    metrics.record()  # First point immediately
    metrics.start_collector(interval=10)

    server = HTTPServer(("0.0.0.0", PORT), DashboardHandler)
    net = get_network_info()

    print(f"""
  ┌──────────────────────────────────────┐
  │  ANBERNIC DASHBOARD v2              │
  │  http://{net['ip']}:{PORT:<5}             │
  │  Ctrl+C to stop                     │
  └──────────────────────────────────────┘
""")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()
