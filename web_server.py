import asyncio
import uvicorn
import threading
import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from shared_state import SharedState
import os

# Fixed file for web server connection events (keeps terminal clean)
_WEB_LOG = os.path.join(os.path.dirname(__file__), "web_server.log")

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

    # Static files directory
    static_dir = os.path.join(os.path.dirname(__file__), "web")
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

class NoSignalServer(uvicorn.Server):
    """Custom server class that disables signal handling for threaded use."""
    def install_signal_handlers(self) -> None:
        pass

def start_web_server(shared_state: SharedState, host="0.0.0.0", port=7860, log_queue=None):
    import sys
    import os
    
    # Safeguard for .pyw (windowed) execution where stdout/stderr might be None
    if sys.stdout is None: sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None: sys.stderr = open(os.devnull, 'w')

    try:
        # Create and set a new event loop for this thread (required for sub-threads)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        app = create_app(shared_state, log_queue=log_queue)
        # log_config=None prevents the 'Unable to configure formatter default' crash in pyw environments
        config = uvicorn.Config(app, host=host, port=port, log_config=None, loop="asyncio")
        server = NoSignalServer(config)
        
        if log_queue:
            log_queue.put(f"🌐 [Web GUI] Server listener starting on http://{host}:{port}")
            
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
