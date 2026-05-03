import asyncio
import uvicorn
import threading
import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from utils.shared_state import SharedState
import os

# Fixed file for web server connection events (keeps terminal clean)
_WEB_LOG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "web_server.log")

def _wlog(msg: str):
    """Append a timestamped connection event to web_server.log only (not terminal)."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(_WEB_LOG, 'a', encoding='utf-8') as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass  # Never crash the web server over a log write failure

def create_app(shared_state: SharedState, log_queue=None):
    app = FastAPI(title="Aegis Web Dashboard")

    # Static files directory (in project root)
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
    os.makedirs(static_dir, exist_ok=True)

    @app.get("/")
    async def index():
        return FileResponse(os.path.join(static_dir, "index.html"))

    @app.get("/api/status")
    async def get_status():
        return shared_state.snapshot()

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        
        # Track connection
        shared_state.change_active_clients(1)
        _wlog(f"🌐 [Web GUI] New client connected. Total: {shared_state.active_clients}")
            
        # Send initial snapshot immediately
        await websocket.send_json(shared_state.snapshot())
        
        last_version = shared_state.snapshot()["version"]
        
        try:
            while True:
                # Wait for next state change (non-blocking for the event loop)
                changed = await asyncio.to_thread(shared_state.wait_for_change, timeout=5.0)
                
                snap = shared_state.snapshot()
                if snap["version"] != last_version:
                    await websocket.send_json(snap)
                    last_version = snap["version"]
        except WebSocketDisconnect:
            pass
        except Exception as e:
            if log_queue:
                log_queue.put(f"⚠️ [Web GUI] WebSocket error: {e}")
        finally:
            shared_state.change_active_clients(-1)
            _wlog(f"🌐 [Web GUI] Client disconnected. Total: {shared_state.active_clients}")


    # Mount static assets (css, js)
    app.mount("/web", StaticFiles(directory=static_dir), name="static")
    
    return app

def find_free_port(start=7860, end=7870):
    """Return the first port in [start, end] that is not currently in use."""
    import socket
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if s.connect_ex(('127.0.0.1', port)) != 0:
                return port  # port not listening → available
    return None  # all ports in range are occupied


class NoSignalServer(uvicorn.Server):
    """Custom server class that disables signal handling for threaded use."""
    def install_signal_handlers(self) -> None:
        pass

def start_web_server(shared_state: SharedState, host="0.0.0.0", port=None, log_queue=None):
    import sys
    import os
    
    # Safeguard for .pyw (windowed) execution where stdout/stderr might be None
    if sys.stdout is None: sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None: sys.stderr = open(os.devnull, 'w')

    try:
        # Auto-discover a free port in the 7860-7870 range if none specified
        if port is None:
            port = find_free_port(7860, 7870)
            if port is None:
                error_msg = "❌ [Web GUI] No free port found in range 7860-7870. Cannot start dashboard."
                if log_queue:
                    log_queue.put(error_msg)
                return

        # Publish the chosen port back to the UI before blocking on server.run()
        shared_state.web_port = port

        # Create and set a new event loop for this thread (required for sub-threads)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        app = create_app(shared_state, log_queue=log_queue)
        # log_config=None prevents the 'Unable to configure formatter default' crash in pyw environments
        config = uvicorn.Config(app, host=host, port=port, log_config=None, loop="asyncio", ws_ping_interval=None, ws_ping_timeout=None)
        server = NoSignalServer(config)
        
        if log_queue:
            log_queue.put(f"🌐 [Web GUI] Dashboard running → http://localhost:{port}")
            
        # Store server instance in shared_state for graceful shutdown
        shared_state._web_server = server
        server.run()
    except Exception as e:
        error_msg = f"❌ [Web GUI] CRITICAL ERROR: {e}"
        if log_queue:
            log_queue.put(error_msg)

if __name__ == "__main__":
    # For testing isolation
    st = SharedState()
    start_web_server(st)
