import threading
from collections import deque
import copy

class SharedState:
    def __init__(self, max_log_lines=500):
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._version = 0
        
        # State Data
        self.log_lines = deque(maxlen=max_log_lines)
        self.progress = {"processed": 0, "total": 0, "percent": 0.0}
        self.eta = {"time_remaining": "--:--", "finish_time": "--:--"}
        self.cost = {"main": 0.0, "judge": 0.0, "display": "Cost: $0.00"}
        self.timer = {"seconds": -1, "estimate": -1, "is_retry": False, "label": ""}
        self.status = {"text": "Idle", "color": "#7f8c8d"}
        self.is_running = False
        self.segments = deque(maxlen=50) # Last 50 items: {idx, time, eng, heb}
        self.upcoming = [] # Next 2 items: {idx, time, eng}

    def _bump_version(self):
        self._version += 1
        self._event.set()
        self._event.clear()

    def append_log(self, line: str):
        with self._lock:
            # Strip any trailing newlines as the frontend will handle them
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

    def update_timer(self, label: str):
        """Expects label like '⏱️ 0:15 / 📦 Est: 2:30' or '⏱️ 🔄 RETRY 0:05'"""
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
                self.upcoming = [] # Clear upcoming on finish
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
        """Expects list of {idx, time, text}"""
        with self._lock:
            self.upcoming = segments
            self._bump_version()

    def snapshot(self):
        """Returns a JSON-serializable deep copy of the state."""
        with self._lock:
            return {
                "version": self._version,
                "is_running": self.is_running,
                "progress": copy.deepcopy(self.progress),
                "eta": copy.deepcopy(self.eta),
                "cost": copy.deepcopy(self.cost),
                "timer": copy.deepcopy(self.timer),
                "status": copy.deepcopy(self.status),
                "log_lines": list(self.log_lines),
                "segments": list(self.segments),
                "upcoming": list(self.upcoming)
            }

    def wait_for_change(self, timeout=None):
        """Blocks until version increments or shutdown is called."""
        return self._event.wait(timeout)

    def shutdown(self):
        """Wakes up all background listeners to allow for a clean exit."""
        self._event.set()
