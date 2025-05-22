import sys
import os
import socket

# 检查端口是否被占用
def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

# 寻找可用端口
def find_available_port(start_port=8001, max_attempts=10):
    port = start_port
    for _ in range(max_attempts):
        if not is_port_in_use(port):
            return port
        port += 1
    return None

# 设置控制台编码，解决中文显示问题
if sys.platform.startswith('win'):
    try:
        # 尝试设置控制台代码页为UTF-8
        os.system('chcp 65001 > nul')
    except:
        pass

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks, HTTPException, Depends, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn
import asyncio
import logging
import json
import time
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
from pathlib import Path
import glob
from pydantic import BaseModel
from copy import deepcopy # Added for test config, might be used by ExperimentController too

# 引入适配器 (Real adapters - will be replaced by mocks for the test run)
from backend.pubsub import Broadcaster
# These are the real adapters, they will be mocked in the test section
# from backend.services.adapters.printer_adapter import PrinterAdapter
# from backend.services.adapters.pump_adapter import PumpAdapter
# from backend.services.adapters.relay_adapter import RelayAdapter
# from backend.services.adapters.chi_adapter import CHIAdapter

# 配置日志
# logger will be configured in run_controller_test for test, 
# and by uvicorn/FastAPI for server run.
# Default logger for when this file is imported:
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler() 
    ]
)
logger = logging.getLogger("experiment_run_module")


# 引入新的WebSocket监听器
try:
    from core_api.moonraker_listener import MoonrakerWebsocketListener
    logger.info("成功导入MoonrakerWebsocketListener，将使用WebSocket获取精确泵参数")
except ImportError:
    logger.warning("无法导入MoonrakerWebsocketListener，将使用传统方式估算泵参数")
    MoonrakerWebsocketListener = None

# FastAPI 应用
app = FastAPI(title="实验运行器")

# Pydantic Models (Keep them for potential ExperimentController use if it relies on them for validation)
class OCPAPIParams(BaseModel):
    st: float; si: float; eh: Optional[float] = None; el: Optional[float] = None; file_name: Optional[str] = None
class DPVAPIParams(BaseModel):
    ei: float; ef: float; incre: float; amp: float; pw: float; sw: float; prod: float
    sens: Optional[float] = None; qt: Optional[float] = 2.0; file_name: Optional[str] = None; autosens: Optional[bool] = False
class SCVAPIParams(BaseModel):
    ei: float; ef: float; incre: float; sw: float; prod: float
    sens: Optional[float] = None; qt: Optional[float] = 2.0; file_name: Optional[str] = None; autosens: Optional[bool] = False
class CPAPIParams(BaseModel):
    ic: float; ia: float; tc: float; ta: float; eh: Optional[float] = 10.0; el: Optional[float] = -10.0
    pn: Optional[str] = 'p'; si: Optional[float] = 0.1; cl: Optional[int] = 1; priority: Optional[str] = 'time'; file_name: Optional[str] = None
class ACVAPIParams(BaseModel):
    ei: float; ef: float; incre: float; amp: float; freq: float
    quiet: Optional[float] = 2.0; sens: Optional[float] = 1e-5; file_name: Optional[str] = None
class CAAPIParams(BaseModel):
    ei: float; eh: float; el: float; cl: int; pw: float; si: float
    sens: Optional[float] = 1e-5; qt: Optional[float] = 2.0; pn: Optional[str] = 'p'; file_name: Optional[str] = None; autosens: Optional[bool] = False
class CVAPIParams(BaseModel):
    ei: float; eh: float; el: float; v: float; si: float; cl: int
    sens: Optional[float] = 1e-5; qt: Optional[float] = 2.0; pn: Optional[str] = 'p'; file_name: Optional[str] = None; autosens: Optional[bool] = False
class ITAPIParams(BaseModel):
    ei: float; st: float; si: float
    sens: Optional[float] = 1e-5; file_name: Optional[str] = None
class GeneralLimits(BaseModel):
    min_x: float; max_x: float; min_y: float; max_y: float; min_z: float; max_z: float
class GridCell(BaseModel):
    grid_number: int; row: int; col: int; center_x: float; center_y: float
class GridConfig(BaseModel):
    rows: int; cols: int; x_min: float; x_max: float; y_min: float; y_max: float; z_height: float; grid_mapping: List[GridCell]
class PrinterInfoResponse(BaseModel):
    general_limits: GeneralLimits; grid_config: GridConfig

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# Global variables for server mode (will be populated by server startup logic)
# For test mode, these will be replaced by mocks or test-specific instances.
broadcaster_server = Broadcaster() # Renamed to avoid conflict with test's mock_broadcaster
config_server = {
    "moonraker_addr": "http://192.168.51.168:7125",
    "results_dir": "./experiment_results",
    "chi_path": "C:/CHI760E/chi760e/chi760e.exe"
}
devices_server = {"printer": None, "pump": None, "relay": None, "chi": None}
moonraker_listener_server = None
experiment_controller_server: Optional['ExperimentController'] = None # Forward declaration

# Ensure results_dir exists for server mode
os.makedirs(config_server["results_dir"], exist_ok=True)

from experiment_controller import ExperimentController # Real controller for server mode

# --- Server Mode Functions (unchanged, but using _server suffixed globals) ---
@app.get("/", response_class=HTMLResponse)
async def get_html_server():
    html_path = Path(__file__).parent.absolute() / "experiment_run.html"
    if html_path.exists():
        with open(html_path, "r", encoding="utf-8") as f: return HTMLResponse(content=f.read())
    logger.error(f"HTML文件不存在: {html_path}"); return HTMLResponse(content="HTML file not found")

@app.websocket("/ws")
async def websocket_endpoint_server(websocket: WebSocket):
    await broadcaster_server.connect(websocket)
    try:
        while True: await websocket.receive_text(); await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect: logger.info(f"WebSocket断开连接: {websocket.client}"); await broadcaster_server.disconnect(websocket)
    except Exception as e: logger.error(f"WebSocket错误: {e}"); await broadcaster_server.disconnect(websocket)

@app.get("/api/config")
async def get_config_endpoint_server(): return config_server

@app.post("/api/config")
async def save_config_endpoint_server(new_config: Dict[str, str]):
    global config_server, moonraker_listener_server
    # ... (rest of the server's save_config logic, using _server globals)
    old_moonraker_addr = config_server.get("moonraker_addr")
    if "moonraker_addr" in new_config: config_server["moonraker_addr"] = new_config["moonraker_addr"]
    if "results_dir" in new_config:
        try: os.makedirs(new_config["results_dir"], exist_ok=True); config_server["results_dir"] = new_config["results_dir"]
        except Exception as e: return {"error": True, "message": f"创建结果目录失败: {e}"}
    if "chi_path" in new_config: config_server["chi_path"] = new_config["chi_path"]
    try:
        with open("device_config.json", "w", encoding="utf-8") as f: json.dump(config_server, f, indent=2, ensure_ascii=False)
    except Exception as e: logger.error(f"保存配置到文件失败: {e}")
    # Re-init listener if addr changed (simplified)
    return {"error": False, "message": "配置已保存"}


def _get_websocket_url_from_http_server(http_url: str) -> Optional[str]:
    if not http_url: return None
    try:
        protocol_prefix = "ws://"
        if http_url.startswith("https://"): protocol_prefix = "wss://"; http_url = http_url[8:]
        elif http_url.startswith("http://"): http_url = http_url[7:]
        return f"{protocol_prefix}{http_url.rstrip('/')}/websocket"
    except Exception as e: logger.error(f"构建WebSocket URL时出错: {e}"); return None


# --- Device Initialization and Status for Server Mode ---
# These will use the REAL adapters imported earlier (now commented out for clarity in test context)
# For the test run, these specific classes (PrinterAdapter, PumpAdapter, etc.) will be mocked.
# We need to ensure the names don't clash or that the test uses its own instances.
# To avoid issues, I'll assume the test will provide its own mock classes with the same names for now.
# If this file were split, the real adapters would be imported here.
# For now, placeholder classes for server mode to make the file runnable if not in __main__ test.

if 'PrinterAdapter' not in globals(): # If not running test which defines mocks
    from backend.services.adapters.printer_adapter import PrinterAdapter
    from backend.services.adapters.pump_adapter import PumpAdapter
    from backend.services.adapters.relay_adapter import RelayAdapter
    from backend.services.adapters.chi_adapter import CHIAdapter


@app.get("/api/status")
async def get_status_server():
    chi_init = devices_server["chi"] is not None and devices_server["chi"].initialized
    return {
        "chi": {"initialized": chi_init },
        "printer": {"initialized": devices_server["printer"] is not None and devices_server["printer"].initialized},
        "pump": {"initialized": devices_server["pump"] is not None and devices_server["pump"].initialized},
        "relay": {"initialized": devices_server["relay"] is not None and devices_server["relay"].initialized}
    }

@app.post("/api/printer/initialize")
async def initialize_printer_server():
    if devices_server["printer"] is not None: await devices_server["printer"].close()
    devices_server["printer"] = PrinterAdapter(config_server["moonraker_addr"], broadcaster_server)
    await devices_server["printer"].initialize(); return {"error": False, "message": "打印机已初始化"}
# ... (other server mode API endpoints for printer, pump, relay, chi init and status) ...
@app.get("/api/printer/position")
async def get_printer_position_server():
    if not devices_server["printer"] or not devices_server["printer"].initialized: return {"error": True, "message":"Printer not init"}
    return {"error": False, "position": await devices_server["printer"].get_position()}
@app.get("/api/printer/info", response_model=PrinterInfoResponse)
async def get_printer_info_server(): # Simplified for brevity
    return PrinterInfoResponse(general_limits={"min_x":0,"max_x":100,"min_y":0,"max_y":100,"min_z":0,"max_z":100}, grid_config={"rows":5,"cols":10,"x_min":0,"x_max":100,"y_min":0,"y_max":100,"z_height":0, "grid_mapping":[]})

@app.post("/api/pump/initialize")
async def initialize_pump_server():
    if devices_server["pump"] is not None: await devices_server["pump"].close()
    devices_server["pump"] = PumpAdapter(config_server["moonraker_addr"], broadcaster_server, moonraker_listener_server)
    await devices_server["pump"].initialize(); return {"error": False, "message": "泵已初始化"}
@app.get("/api/pump/status")
async def get_pump_status_server(pump_index: int = 0):
    if not devices_server["pump"] or not devices_server["pump"].initialized: return {"error": True, "message":"Pump not init"}
    return {"error": False, "status": await devices_server["pump"].get_status(pump_index)}

@app.post("/api/relay/initialize")
async def initialize_relay_server():
    if devices_server["relay"] is not None: await devices_server["relay"].close()
    devices_server["relay"] = RelayAdapter(config_server["moonraker_addr"], broadcaster_server)
    await devices_server["relay"].initialize(); return {"error": False, "message": "继电器已初始化"}
@app.get("/api/relay/status")
async def get_relay_status_server():
    if not devices_server["relay"] or not devices_server["relay"].initialized: return {"error": True, "message":"Relay not init"}
    return {"error": False, "states": await devices_server["relay"].get_status()}
    
@app.post("/api/chi/initialize")
async def initialize_chi_server():
    if devices_server["chi"] is not None: await devices_server["chi"].close()
    devices_server["chi"] = CHIAdapter(broadcaster_server, config_server["results_dir"], config_server["chi_path"])
    await devices_server["chi"].initialize(); return {"error": False, "message": "CHI已初始化"}
@app.get("/api/chi/status")
async def get_chi_status_server():
    if not devices_server["chi"] or not devices_server["chi"].initialized: return {"error": True, "message":"CHI not init"}
    return {"error": False, "status": await devices_server["chi"].get_status()}
@app.get("/api/chi/results")
async def get_chi_results_server():
    if not devices_server["chi"] or not devices_server["chi"].initialized: return {"error": True, "message":"CHI not init"}
    return {"error": False, "results": await devices_server["chi"].get_results()}
@app.get("/api/chi/download")
async def download_chi_result_server(file: str):
    file_path = Path(config_server["results_dir"]) / Path(file).name # Basic security
    if not file_path.exists() or not str(file_path).startswith(config_server["results_dir"]): return {"error":True, "message":"Invalid path"}
    return FileResponse(path=file_path, filename=file_path.name, media_type="text/plain")

# --- Experiment Control API Endpoints for Server Mode ---
@app.post("/api/experiment/start")
async def start_experiment_endpoint_server(background_tasks: BackgroundTasks):
    global experiment_controller_server
    if experiment_controller_server and experiment_controller_server.is_running:
        raise HTTPException(status_code=400, detail="实验已在运行中。")
    for device_name, device_instance in devices_server.items(): # Check server devices
        if device_instance is None or not device_instance.initialized:
            # Simplified init call for server mode
            if device_name == "printer": await initialize_printer_server()
            elif device_name == "pump": await initialize_pump_server()
            elif device_name == "relay": await initialize_relay_server()
            elif device_name == "chi": await initialize_chi_server()
            if devices_server[device_name] is None or not devices_server[device_name].initialized:
                 raise HTTPException(status_code=503, detail=f"设备 {device_name} 初始化失败。")
    experiment_controller_server = ExperimentController(
        config_path="old/experiment_config.json", broadcaster=broadcaster_server, devices=devices_server, logger_instance=logger)
    background_tasks.add_task(experiment_controller_server.run)
    return {"error": False, "message": "实验已启动。"}

@app.post("/api/experiment/stop")
async def stop_experiment_endpoint_server():
    if not experiment_controller_server or not experiment_controller_server.is_running: raise HTTPException(status_code=400, detail="实验未在运行中。")
    experiment_controller_server.request_stop(); return {"error": False, "message": "实验停止请求已发送。"}

@app.get("/api/experiment/status")
async def get_experiment_status_endpoint_server():
    if not experiment_controller_server: return {"is_running": False, "message": "控制器未初始化"}
    return experiment_controller_server.get_experiment_status()

@app.get("/api/experiment/config")
async def get_experiment_config_endpoint_server():
    global experiment_controller_server
    if experiment_controller_server and experiment_controller_server.config_data and experiment_controller_server.config_path != "old/experiment_config.json": # Check if in-memory config is primary
         return experiment_controller_server.config_data
    try:
        with open("old/experiment_config.json", 'r', encoding='utf-8') as f: return json.load(f)
    except Exception as e: raise HTTPException(status_code=500, detail=f"无法加载实验配置: {e}")

@app.post("/api/experiment/config")
async def set_experiment_config_endpoint_server(new_exp_config: Dict[Any, Any]):
    global experiment_controller_server
    if experiment_controller_server and experiment_controller_server.is_running: raise HTTPException(status_code=400, detail="实验正在运行，无法修改配置。")
    controller_to_use = experiment_controller_server or ExperimentController(config_path="old/experiment_config.json", broadcaster=broadcaster_server, devices=devices_server) # temp if needed
    if not controller_to_use.update_config(new_exp_config): raise HTTPException(status_code=500, detail="实验配置更新失败。")
    if experiment_controller_server and experiment_controller_server is not controller_to_use : # sync if global one exists and was not used
        experiment_controller_server.config_data = deepcopy(new_exp_config)
        experiment_controller_server.experiment_flags = experiment_controller_server.config_data.get("experiment_flags", {})
    return {"error": False, "message": "实验配置已成功更新并保存。"}

@app.post("/api/experiment/pause")
async def pause_experiment_endpoint_server():
    if not experiment_controller_server or not experiment_controller_server.is_running: raise HTTPException(status_code=400, detail="实验未在运行中。")
    if experiment_controller_server.is_paused or experiment_controller_server.pause_requested: raise HTTPException(status_code=400, detail="实验已暂停或正在请求暂停。")
    experiment_controller_server.request_pause(); return {"error": False, "message": "实验暂停请求已发送。"}

@app.post("/api/experiment/resume")
async def resume_experiment_endpoint_server():
    if not experiment_controller_server or not experiment_controller_server.is_running: raise HTTPException(status_code=400, detail="实验未在运行中。")
    if not experiment_controller_server.is_paused: raise HTTPException(status_code=400, detail="实验未暂停。")
    await experiment_controller_server.resume(); return {"error": False, "message": "实验恢复请求已发送。"}

@app.on_event("startup")
async def startup_event_server():
    global moonraker_listener_server
    load_config() # Loads device_config.json into global config_server
    logger.info(f"实验运行器 (服务器模式) 启动, Moonraker: {config_server.get('moonraker_addr')}")
    if MoonrakerWebsocketListener is not None:
        ws_url = _get_websocket_url_from_http_server(config_server.get("moonraker_addr"))
        if ws_url:
            moonraker_listener_server = MoonrakerWebsocketListener(ws_url)
            asyncio.create_task(moonraker_listener_server.start()) # Start listener

@app.on_event("shutdown")
async def shutdown_event_server():
    if moonraker_listener_server: await moonraker_listener_server.stop()
    if experiment_controller_server and experiment_controller_server.is_running:
        experiment_controller_server.request_stop()

# --- Test Code Starts Here ---
test_config_data = {
    "project_name": "InMemoryTest_Experiment",
    "base_path": "experiment_results_json",
    "moonraker_addr": "http://mock_moonraker:7125",
    "chi_path": "C:/Mock_CHI/chi.exe",
    "results_dir": "./experiment_results_inmemory_test",
    "configurations": {
        "safe_move_xy": [51.0, 52.0], 
        "safe_move_z_high": 88.0,
        "electrolyte_volume_fill_ml": 0.5, 
        "default_pump_index": 0,
        "default_pump_speed": "fast", 
        "valve_relay_id": 1
    },
    "experiment_sequence": [
        {
            "id": "MOCK_INIT_00_HOME_PRINTER",
            "description": "模拟打印机归位",
            "type": "printer_home",
            "enabled": True
        },
        {
            "id": "MOCK_FIRST_01_MOVE_TO_SAFE_POINT",
            "description": "模拟移动到安全点",
            "type": "move_printer_xyz",
            "enabled": True,
            "params": {
                "x_key": "configurations.safe_move_xy[0]",
                "y_key": "configurations.safe_move_xy[1]",
                "z_key": "configurations.safe_move_z_high"
            }
        },
        {
            "id": "MOCK_TEST_02_PUMP_ELECTROLYTE",
            "description": "模拟泵送少量电解液",
            "type": "sequence",
            "enabled": True,
            "actions": [
                {
                    "id": "MOCK_PUMP_SEQ_01_OPEN_VALVE",
                    "type": "set_valve",
                    "description": "模拟打开阀门",
                    "params": {"relay_id_key": "configurations.valve_relay_id", "open_to_reservoir": True}
                },
                {
                    "id": "MOCK_PUMP_SEQ_02_PUMP",
                    "type": "pump_liquid",
                    "description": "模拟泵送液体",
                    "params": {
                        "volume_ml_key": "configurations.electrolyte_volume_fill_ml",
                        "direction": 1,
                        "pump_index_key": "configurations.default_pump_index",
                        "speed_key": "configurations.default_pump_speed"
                    }
                },
                {
                    "id": "MOCK_PUMP_SEQ_03_CLOSE_VALVE",
                    "type": "set_valve",
                    "description": "模拟关闭阀门",
                    "params": {"relay_id_key": "configurations.valve_relay_id", "open_to_reservoir": False}
                }
            ]
        }
    ],
    "experiment_flags": {}
}

class MockBroadcaster:
    def __init__(self, logger_instance):
        self.logger = logger_instance
        self.broadcast_messages = []
    async def broadcast(self, message):
        self.logger.info(f"MockBroadcaster: Broadcasting message: {json.dumps(message)}") # Log as JSON string
        self.broadcast_messages.append(message)
    async def connect(self, websocket): self.logger.info("MockBroadcaster: connect called") # No-op
    async def disconnect(self, websocket): self.logger.info("MockBroadcaster: disconnect called") # No-op

class MockPrinterAdapter:
    def __init__(self, moonraker_addr, broadcaster, logger_instance): # Added logger_instance
        self.logger = logger_instance
        self.broadcaster = broadcaster
        self.initialized = False
        self.position={"x":0,"y":0,"z":0}
    async def initialize(self): self.initialized = True; self.logger.info("MockPrinterAdapter: Initialized"); await self.broadcast_status()
    async def home(self): self.logger.info("MockPrinterAdapter: home() called"); self.position={"x":0,"y":0,"z":0}; await self.broadcast_status(); return True
    async def move_to(self, x, y, z): self.logger.info(f"MockPrinterAdapter: move_to(x={x}, y={y}, z={z}) called"); self.position={"x":x,"y":y,"z":z}; await self.broadcast_status(); return True
    async def move_to_grid(self, position): self.logger.info(f"MockPrinterAdapter: move_to_grid(position={position}) called"); self.position={"x":position,"y":-1,"z":-1}; await self.broadcast_status(); return True 
    async def get_position(self): return self.position
    async def broadcast_status(self): 
        if self.broadcaster: await self.broadcaster.broadcast({"type": "printer_status", "position": self.position, "initialized": self.initialized})
    async def close(self): self.initialized = False; self.logger.info("MockPrinterAdapter: Closed")

class MockPumpAdapter:
    def __init__(self, moonraker_addr, broadcaster, ws_listener, logger_instance): # Added logger_instance
        self.logger = logger_instance
        self.broadcaster = broadcaster
        self.initialized = False
        self.status = {} # Store current status
    async def initialize(self): self.initialized = True; self.logger.info("MockPumpAdapter: Initialized"); await self.broadcast_status()
    async def dispense_auto(self, pump_index, volume, speed, direction):
        self.logger.info(f"MockPumpAdapter: dispense_auto(pump_index={pump_index}, volume={volume}ul, speed={speed}, direction={direction}) called")
        self.status = {"running": True, "pump_index": pump_index, "volume": volume, "progress": 0, "direction": direction, "total_duration_seconds": (volume/1000.0) * 0.2, "elapsed_time_seconds": 0} # Mock duration (0.2s per mL)
        await self.broadcast_status()
        start_time = time.time()
        total_duration = self.status["total_duration_seconds"]
        while time.time() - start_time < total_duration:
            await asyncio.sleep(0.02) # Small delay to allow other tasks
            elapsed = time.time() - start_time
            self.status["progress"] = min(1.0, elapsed / total_duration)
            self.status["elapsed_time_seconds"] = round(elapsed,2)
            await self.broadcast_status()
        self.status["progress"] = 1.0; self.status["running"] = False; self.status["elapsed_time_seconds"] = round(total_duration,2)
        await self.broadcast_status()
        self.logger.info(f"MockPumpAdapter: dispense_auto finished for pump_index={pump_index}")
        return {"success": True, "estimated_duration": total_duration}
    async def stop(self, pump_index): self.logger.info(f"MockPumpAdapter: stop(pump_index={pump_index}) called"); self.status["running"] = False; await self.broadcast_status()
    async def get_status(self, pump_index=0): return self.status
    async def broadcast_status(self): 
        if self.broadcaster: await self.broadcaster.broadcast({"type": "pump_status", "status": self.status.copy(), "initialized": self.initialized})
    async def close(self): self.initialized = False; self.logger.info("MockPumpAdapter: Closed")

class MockRelayAdapter:
    def __init__(self, moonraker_addr, broadcaster, logger_instance): # Added logger_instance
        self.logger = logger_instance
        self.broadcaster = broadcaster
        self.initialized = False
        self.states = {1:False, 2:False, 3:False, 4:False}
    async def initialize(self): self.initialized = True; self.logger.info("MockRelayAdapter: Initialized"); await self.broadcast_status()
    async def toggle(self, relay_id, state): 
        self.logger.info(f"MockRelayAdapter: toggle(relay_id={relay_id}, state={state}) called") # state is True/False from controller
        self.states[int(relay_id)] = bool(state) 
        await self.broadcast_status()
        return True
    async def get_status(self): return self.states 
    async def broadcast_status(self): 
        if self.broadcaster: await self.broadcaster.broadcast({"type": "relay_status", "states": {str(k): ('on' if v else 'off') for k,v in self.states.items()}, "initialized": self.initialized})
    async def close(self): self.initialized = False; self.logger.info("MockRelayAdapter: Closed")

class MockCHIAdapter:
    def __init__(self, broadcaster, results_base_dir, chi_path, logger_instance): # Added logger_instance
        self.logger = logger_instance
        self.broadcaster = broadcaster
        self.results_base_dir = results_base_dir # Store for run_test
        self.initialized = False
        self.current_test_status = {"status": "idle", "error": False, "message": "CHI Mock Idle"}
    async def initialize(self): self.initialized = True; self.logger.info("MockCHIAdapter: Initialized"); await self.broadcast_chi_status_internal()
    async def run_test(self, test_type, params, file_name): 
        self.logger.info(f"MockCHIAdapter: run_test(type={test_type}, params={params}, file_name={file_name}) called")
        self.current_test_status = {"status": "running", "test_type": test_type, "file_name": file_name, "error": False, "message": f"{test_type} running", "progress": 0.0, "elapsed_time": 0}
        await self.broadcast_chi_status_internal()
        
        # Simulate test duration and progress
        simulated_duration = params.get("st", 0.2) # Use 'st' from IT params, or default to 0.2s
        if test_type == "CV": simulated_duration = params.get("cl", 1) * 0.1 # cycles * time_per_cycle
        
        start_time = time.time()
        while time.time() - start_time < simulated_duration:
            await asyncio.sleep(0.02)
            elapsed = time.time() - start_time
            progress = min(1.0, elapsed / simulated_duration)
            self.current_test_status["progress"] = round(progress,2)
            self.current_test_status["elapsed_time"] = round(elapsed,2)
            await self.broadcast_chi_status_internal()

        self.current_test_status = {"status": "completed", "test_type": test_type, "file_name": file_name, "result_file": f"{file_name}.txt", "error": False, "message": f"{test_type} completed", "progress": 1.0, "elapsed_time": round(simulated_duration,2)}
        await self.broadcast_chi_status_internal()
        self.logger.info(f"MockCHIAdapter: run_test for {file_name} completed.")
        
        # Reset to idle after a short delay to allow "completed" to be processed
        await asyncio.sleep(0.01)
        self.current_test_status = {"status": "idle", "error": False, "message": "CHI Mock Idle after test"}
        await self.broadcast_chi_status_internal()
        
        # Ensure the directory for the mock result file exists
        if self.results_base_dir:
            os.makedirs(self.results_base_dir, exist_ok=True)
            return os.path.join(self.results_base_dir, f"{file_name}.txt")
        return f"{file_name}.txt" 
        
    async def get_status(self): return self.current_test_status.copy()
    async def stop_test(self): self.logger.info("MockCHIAdapter: stop_test() called"); self.current_test_status = {"status": "idle", "error": False, "message": "CHI Mock Stopped/Idle"}; await self.broadcast_chi_status_internal()
    async def broadcast_chi_status_internal(self): # Renamed to avoid confusion with BaseAdapter's broadcast_status
        if self.broadcaster: await self.broadcaster.broadcast({"type": "chi_status", "status_data": self.current_test_status.copy(), "initialized": self.initialized})
    async def close(self): self.initialized = False; self.logger.info("MockCHIAdapter: Closed")
    async def get_results(self): return [{"name": "mock_result.txt", "path": os.path.join(self.results_base_dir or "mock_results", "mock_result.txt"), "type": "CV", "size": 1024, "time": time.time()}]


async def run_controller_test():
    # Setup basic logging to console for the test
    test_logger = logging.getLogger("ExperimentControllerTest")
    test_logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout) # Ensure output goes to stdout
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    if not test_logger.handlers: # Avoid adding multiple handlers if run multiple times
        test_logger.addHandler(handler)
    
    # Also configure the logger used by ExperimentController if it's different
    # For this test, we pass logger_instance, so ExperimentController will use test_logger
    # controller_logger = logging.getLogger("experiment_controller") # Default name if not passed
    # if not controller_logger.handlers:
    #     controller_logger.setLevel(logging.INFO)
    #     controller_logger.addHandler(handler)


    mock_broadcaster_instance = MockBroadcaster(test_logger) # Corrected variable name
    
    # Instantiate mock devices
    mock_printer = MockPrinterAdapter("mock_addr", mock_broadcaster_instance, test_logger)
    mock_pump = MockPumpAdapter("mock_addr", mock_broadcaster_instance, None, test_logger) # ws_listener can be None for mock
    mock_relay = MockRelayAdapter("mock_addr", mock_broadcaster_instance, test_logger)
    mock_chi = MockCHIAdapter(mock_broadcaster_instance, "mock_results", "mock_chi_path", test_logger)

    await mock_printer.initialize()
    await mock_pump.initialize()
    await mock_relay.initialize()
    await mock_chi.initialize()

    mock_devices = { # Renamed to avoid conflict with server's 'devices'
        "printer": mock_printer,
        "pump": mock_pump,
        "relay": mock_relay,
        "chi": mock_chi
    }

    # test_config_data is defined globally in this script
    global test_config_data 
    
    test_logger.info("--- Creating ExperimentController with In-Memory Test Config ---")
    controller = ExperimentController(
        config_data=deepcopy(test_config_data), # Use deepcopy to avoid modification issues if controller modifies config
        broadcaster=mock_broadcaster_instance,
        devices=mock_devices,
        logger_instance=test_logger # Pass the test-specific logger
    )

    test_logger.info("--- Starting ExperimentController Run ---")
    success = await controller.run() # Capture success status
    test_logger.info(f"--- ExperimentController Run Finished (Success: {success}) ---")

    test_logger.info("--- Broadcast Messages: ---")
    for i, msg in enumerate(mock_broadcaster_instance.broadcast_messages):
        test_logger.info(f"Message {i+1}: {msg}")
    
    # Verify that the number of 'completed' step messages matches the number of enabled steps.
    completed_step_messages = [
        msg for msg in mock_broadcaster_instance.broadcast_messages 
        if msg.get("type") == "experiment_step_update" and msg.get("status") == "completed"
    ]
    # Count enabled, non-sequence steps in the test_config_data (sequence steps don't emit their own 'completed' directly)
    # This count needs to be accurate based on how _execute_step increments completed_steps
    # _execute_step increments for each direct step type it handles successfully, excluding 'sequence' itself (actions within are counted)
    
    num_expected_top_level_successful_steps = 0
    for step_cfg in test_config_data["experiment_sequence"]:
        if step_cfg.get("enabled", True):
            if step_cfg["type"] == "sequence": # Count actions within the sequence
                 for action_cfg in step_cfg.get("actions", []):
                      if action_cfg.get("enabled", True): # Assuming actions can also be disabled
                           num_expected_top_level_successful_steps +=1
            else: # Non-sequence steps
                num_expected_top_level_successful_steps += 1


    if len(completed_step_messages) == num_expected_top_level_successful_steps:
        test_logger.info(f"SUCCESS: Number of completed step messages ({len(completed_step_messages)}) matches number of expected successful steps ({num_expected_top_level_successful_steps}).")
    else:
        test_logger.error(f"FAILURE: Number of completed step messages ({len(completed_step_messages)}) does NOT match number of expected successful steps ({num_expected_top_level_successful_steps}).")

    # Check for specific parameter usage in logs (example)
    # This requires the mock adapters to log the parameters they receive.
    # Example: Printer move to specific coords from test_config_data
    expected_x = test_config_data["configurations"]["safe_move_xy"][0]
    expected_y = test_config_data["configurations"]["safe_move_xy"][1]
    expected_z = test_config_data["configurations"]["safe_move_z_high"]
    
    # This part requires log capture or checking mock adapter internal state.
    # For now, manual log inspection would be needed if not programmatically capturing logs.
    # The logger in mock adapters will print this info.
    test_logger.info(f"Expected printer move: x={expected_x}, y={expected_y}, z={expected_z}")
    test_logger.info(f"Expected pump volume: {test_config_data['configurations']['electrolyte_volume_fill_ml']*1000}ul, speed: {test_config_data['configurations']['default_pump_speed']}")


# --- End of Test Code Definitions ---

if __name__ == "__main__":
    # This will now run the test instead of the uvicorn server
    # Check if a specific environment variable is set to run server, otherwise run test
    if os.environ.get("RUN_SERVER_MODE") == "true":
        server_port = find_available_port(8002, 10) 
        if server_port is None:
            print("错误：无法找到可用端口 (服务器模式)。")
            sys.exit(1)
        print(f"实验运行服务器 (服务器模式) 正在启动...")
        print(f"请使用浏览器访问: http://localhost:{server_port}")
        uvicorn.run(app, host="0.0.0.0", port=server_port)
    else:
        print("--- Running ExperimentController Integration Test ---")
        asyncio.run(run_controller_test())
