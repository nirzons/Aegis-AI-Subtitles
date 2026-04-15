import threading
from collections import deque
import copy

class SharedState:
    def __init__(self, max_log_lines=500):
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._version = 0
        
        # Original State Data
        self.log_lines = deque(maxlen=max_log_lines)
        self.progress = {"processed": 0, "total": 0, "percent": 0.0}
        self.eta = {"time_remaining": "--:--", "finish_time": "--:--"}
        self.cost = {"main": 0.0, "judge": 0.0, "display": "Cost: $0.00"}
        self.timer = {"seconds": -1, "estimate": -1, "is_retry": False, "label": ""}
        self.status = {"text": "Idle", "color": "#7f8c8d"}
        self.is_running = False
        self.segments = deque(maxlen=50) # Last 50 items: {idx, time, eng, heb}
        self.upcoming = [] # Next 2 items: {idx, time, eng}
        self.active_clients = 0

        # NEW V3 State Data
        self.telemetry = {
            "cache_hit_percent": 0,
            "tokens_per_sec": 0.0,
            "speed_history": deque(maxlen=15)
        }
        self.audit = {
            "last_decision": "System Initialized",
            "batch_size": 0,
            "batch_trend": 0 
        }

    def _bump_version(self):
        self._version += 1
        self._event.set()
        self._event.clear()

    def append_log(self, line: str):
        with self._lock:
            self.log_lines.append(line.rstrip())
            self._bump_version()

    def update_progress(self, processed: int, total: int):
        with self._lock:
            percent = (processed / total * 100) if total > 0 else 0
            self.progress = {"processed": processed, "total": total, "percent": round(percent, 1)}
            self._bump_version()

    def update_eta(self, time_remaining: str, finish_time: str):
        with self._lock:
            self.eta = {"time_remaining": time_remaining, "finish_time": finish_time}
            self._bump_version()

    def update_cost(self, main_cost: float, judge_cost: float, display_text: str = None):
        with self._lock:
            self.cost["main"] = main_cost
            self.cost["judge"] = judge_cost
            if display_text:
                self.cost["display"] = display_text
            self._bump_version()

    # --- THE MISSING V3 METHODS ---
    def update_telemetry(self, cache_hit_percent: int = None, tokens_per_sec: float = None):
        with self._lock:
            if cache_hit_percent is not None:
                self.telemetry["cache_hit_percent"] = cache_hit_percent
            if tokens_per_sec is not None:
                self.telemetry["tokens_per_sec"] = tokens_per_sec
                self.telemetry["speed_history"].append(tokens_per_sec)
            self._bump_version()

    def update_audit(self, last_decision: str = None, batch_size: int = None, batch_trend: int = None):
        with self._lock:
            if last_decision is not None:
                self.audit["last_decision"] = last_decision
            if batch_size is not None:
                self.audit["batch_size"] = batch_size
            if batch_trend is not None:
                self.audit["batch_trend"] = batch_trend
            self._bump_version()
    # ------------------------------

    def update_timer(self, label: str):
        with self._lock:
            self.timer["label"] = label
            self._bump_version()

    def update_status(self, text: str, color: str = "#3498db"):
        with self._lock:
            self.status = {"text": text, "color": color}
            self._bump_version()

    def set_running(self, running: bool):
        with self._lock:
            self.is_running = running
            if not running:
                self.status = {"text": "Finished", "color": "#27ae60"}
                self.upcoming = [] 
            self._bump_version()

    def add_segment(self, idx, time, eng, heb):
        with self._lock:
            self.segments.append({
                "index": idx,
                "time": time,
                "eng": eng,
                "heb": heb
            })
            self._bump_version()

    def set_upcoming(self, segments):
        with self._lock:
            self.upcoming = segments
            self._bump_version()

    def change_active_clients(self, delta):
        with self._lock:
            self.active_clients = max(0, self.active_clients + delta)
            self._bump_version()

    def snapshot(self):
        with self._lock:
            return {
                "version": self._version,
                "is_running": self.is_running,
                "progress": copy.deepcopy(self.progress),
                "eta": copy.deepcopy(self.eta),
                "cost": copy.deepcopy(self.cost),
                "timer": copy.deepcopy(self.timer),
                "status": copy.deepcopy(self.status),
                "telemetry": {
                    "cost_main": self.cost.get("main", 0.0),
                    "cost_judge": self.cost.get("judge", 0.0),
                    "cache_hit_percent": self.telemetry["cache_hit_percent"],
                    "tokens_per_sec": self.telemetry["tokens_per_sec"],
                    "speed_history": list(self.telemetry["speed_history"])
                },
                "audit": copy.deepcopy(self.audit),
                "log_lines": list(self.log_lines),
                "segments": list(self.segments),
                "upcoming": list(self.upcoming),
                "active_clients": self.active_clients
            }

    def wait_for_change(self, timeout=None):
        return self._event.wait(timeout)

    def shutdown(self):
        self._event.set()