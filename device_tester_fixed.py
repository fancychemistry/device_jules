import sys
import os
import socket

# 妫€鏌ョ鍙ｆ槸鍚﹁鍗犵敤
def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

# 瀵绘壘鍙敤绔彛
def find_available_port(start_port=8001, max_attempts=10):
    port = start_port
    for _ in range(max_attempts):
        if not is_port_in_use(port):
            return port
        port += 1
    return None

# 璁剧疆鎺у埗鍙扮紪鐮侊紝瑙ｅ喅涓枃鏄剧ず闂
if sys.platform.startswith('win'):
    try:
        # 灏濊瘯璁剧疆鎺у埗鍙颁唬鐮侀〉涓篣TF-8
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

# 寮曞叆閫傞厤鍣?from backend.pubsub import Broadcaster
from backend.services.adapters.printer_adapter import PrinterAdapter
from backend.services.adapters.pump_adapter import PumpAdapter
from backend.services.adapters.relay_adapter import RelayAdapter
from backend.services.adapters.chi_adapter import CHIAdapter

# 閰嶇疆鏃ュ織
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("device_tester.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("device_tester")

# 寮曞叆鏂扮殑WebSocket鐩戝惉鍣?try:
    from core_api.moonraker_listener import MoonrakerWebsocketListener
    logger.info("鎴愬姛瀵煎叆MoonrakerWebsocketListener锛屽皢浣跨敤WebSocket鑾峰彇绮剧‘娉靛弬鏁?)
except ImportError:
    logger.warning("鏃犳硶瀵煎叆MoonrakerWebsocketListener锛屽皢浣跨敤浼犵粺鏂瑰紡浼扮畻娉靛弬鏁?)
    MoonrakerWebsocketListener = None

# FastAPI 搴旂敤
app = FastAPI(title="璁惧娴嬭瘯鍣?)

# Pydantic Models for API requests
class OCPAPIParams(BaseModel):
    st: float
    si: float
    eh: Optional[float] = None
    el: Optional[float] = None
    file_name: Optional[str] = None

class DPVAPIParams(BaseModel):
    ei: float
    ef: float
    incre: float
    amp: float
    pw: float
    sw: float
    prod: float
    sens: Optional[float] = None
    qt: Optional[float] = 2.0
    file_name: Optional[str] = None
    autosens: Optional[bool] = False

class SCVAPIParams(BaseModel):
    ei: float
    ef: float
    incre: float
    sw: float
    prod: float
    sens: Optional[float] = None
    qt: Optional[float] = 2.0
    file_name: Optional[str] = None
    autosens: Optional[bool] = False

class CPAPIParams(BaseModel):
    ic: float  # 闃存瀬鐢垫祦
    ia: float  # 闃虫瀬鐢垫祦
    tc: float  # 闃存瀬鏃堕棿
    ta: float  # 闃虫瀬鏃堕棿
    eh: Optional[float] = 10.0  # 楂樼數浣嶉檺鍒?    el: Optional[float] = -10.0  # 浣庣數浣嶉檺鍒?    pn: Optional[str] = 'p'  # 绗竴姝ョ數娴佹瀬鎬?    si: Optional[float] = 0.1  # 鏁版嵁瀛樺偍闂撮殧
    cl: Optional[int] = 1  # 娈垫暟/寰幆鏁?    priority: Optional[str] = 'time'  # 浼樺厛妯″紡锛?time'鎴?potential'
    file_name: Optional[str] = None

class ACVAPIParams(BaseModel):
    ei: float  # 鍒濆鐢典綅
    ef: float  # 鏈€缁堢數浣?    incre: float  # 鐢典綅澧為噺
    amp: float  # 浜ゆ祦鎸箙
    freq: float  # 浜ゆ祦棰戠巼
    quiet: Optional[float] = 2.0  # 闈欐伅鏃堕棿
    sens: Optional[float] = 1e-5  # 鐏垫晱搴?    file_name: Optional[str] = None

class CAAPIParams(BaseModel):
    ei: float  # 鍒濆鐢典綅
    eh: float  # 楂樼數浣?    el: float  # 浣庣數浣?    cl: int  # 闃惰穬鏁?    pw: float  # 鑴夊啿瀹藉害
    si: float  # 閲囨牱闂撮殧
    sens: Optional[float] = 1e-5  # 鐏垫晱搴?    qt: Optional[float] = 2.0  # 闈欑疆鏃堕棿
    pn: Optional[str] = 'p'  # 鍒濆鏋佹€?    file_name: Optional[str] = None  # 鏂囦欢鍚?    autosens: Optional[bool] = False  # 鏄惁鑷姩鐏垫晱搴?
class CVAPIParams(BaseModel):
    ei: float  # 鍒濆鐢典綅
    eh: float  # 楂樼數浣?    el: float  # 浣庣數浣?    v: float  # 鎵弿閫熺巼
    si: float  # 閲囨牱闂撮殧
    cl: int  # 寰幆娆℃暟
    sens: Optional[float] = 1e-5  # 鐏垫晱搴?    qt: Optional[float] = 2.0  # 闈欑疆鏃堕棿
    pn: Optional[str] = 'p'  # 鍒濆鎵弿鏂瑰悜
    file_name: Optional[str] = None  # 鏂囦欢鍚?    autosens: Optional[bool] = False  # 鏄惁鑷姩鐏垫晱搴?
class ITAPIParams(BaseModel):
    ei: float  # 鎭掑畾鐢典綅
    st: float  # 鎬婚噰鏍锋椂闂?    si: float  # 閲囨牱闂撮殧
    sens: Optional[float] = 1e-5  # 鐏垫晱搴?    file_name: Optional[str] = None  # 鏂囦欢鍚?
# Pydantic Models for Printer Info API
class GeneralLimits(BaseModel):
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    min_z: float
    max_z: float

class GridCell(BaseModel):
    grid_number: int
    row: int
    col: int
    center_x: float
    center_y: float

class GridConfig(BaseModel):
    rows: int
    cols: int
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_height: float
    grid_mapping: List[GridCell]

class PrinterInfoResponse(BaseModel):
    general_limits: GeneralLimits
    grid_config: GridConfig

# 娣诲姞CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 鍏ㄥ眬鍙橀噺
broadcaster = Broadcaster()
config = {
    "moonraker_addr": "http://192.168.51.168:7125",
    "results_dir": "./experiment_results",
    "chi_path": "C:/CHI760E/chi760e/chi760e.exe"  # 榛樿CHI璺緞
}
devices = {
    "printer": None,  # PrinterAdapter
    "pump": None,     # PumpAdapter
    "relay": None,    # RelayAdapter
    "chi": None       # CHIAdapter
}
# WebSocket鐩戝惉鍣ㄥ疄渚?moonraker_listener = None

# 纭繚缁撴灉鐩綍瀛樺湪
os.makedirs(config["results_dir"], exist_ok=True)

# HTML鍓嶇
@app.get("/", response_class=HTMLResponse)
async def get_html():
    try:
        html_path = Path(__file__).parent.absolute() / "device_tester.html"
        if html_path.exists():
            with open(html_path, "r", encoding="utf-8") as f:
                html = f.read()
            return HTMLResponse(content=html)
        else:
            logger.error(f"HTML鏂囦欢涓嶅瓨鍦? {html_path}")
            return HTMLResponse(content=f"<html><body><h1>閿欒: HTML鏂囦欢涓嶅瓨鍦?/h1><p>{html_path}</p></body></html>")
    except Exception as e:
        logger.error(f"璇诲彇HTML鏂囦欢澶辫触: {e}")
        return HTMLResponse(content=f"<html><body><h1>閿欒: {str(e)}</h1></body></html>")

# WebSocket杩炴帴
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info(f"WebSocket杩炴帴宸插缓绔? {websocket.client}")
    await broadcaster.connect(websocket)
    try:
        while True:
            # 蹇冭烦妫€娴?            await websocket.receive_text()
            await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        logger.info(f"WebSocket鏂紑杩炴帴: {websocket.client}")
        await broadcaster.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket閿欒: {e}")
        try:
            await broadcaster.disconnect(websocket)
        except:
            pass

# 鑾峰彇閰嶇疆
@app.get("/api/config")
async def get_config():
    return config

# 淇濆瓨閰嶇疆
@app.post("/api/config")
async def save_config(new_config: Dict[str, str]):
    global config, moonraker_listener
    
    # 璁板綍鍘熷Moonraker鍦板潃锛岀敤浜庢鏌ユ槸鍚﹂渶瑕侀噸鏂板垵濮嬪寲鐩戝惉鍣?    old_moonraker_addr = config.get("moonraker_addr")
    
    # 楠岃瘉閰嶇疆
    if "moonraker_addr" in new_config:
        config["moonraker_addr"] = new_config["moonraker_addr"]
    
    if "results_dir" in new_config:
        results_dir = new_config["results_dir"]
        try:
            os.makedirs(results_dir, exist_ok=True)
            config["results_dir"] = results_dir
        except Exception as e:
            return {"error": True, "message": f"鍒涘缓缁撴灉鐩綍澶辫触: {e}"}
    
    if "chi_path" in new_config:
        config["chi_path"] = new_config["chi_path"]
    
    # 淇濆瓨閰嶇疆鍒版枃浠?    try:
        with open("device_config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"淇濆瓨閰嶇疆鍒版枃浠跺け璐? {e}")
    
    # 濡傛灉Moonraker鍦板潃鍙樻洿锛岄噸鏂板垵濮嬪寲WebSocket鐩戝惉鍣?    if old_moonraker_addr != config.get("moonraker_addr") and MoonrakerWebsocketListener is not None:
        if moonraker_listener:
            # 鍋滄鏃х殑鐩戝惉鍣?            asyncio.create_task(moonraker_listener.stop())
        
        # 鍒涘缓鏂扮殑WebSocket鐩戝惉鍣║RL
        ws_url = _get_websocket_url_from_http(config["moonraker_addr"])
        if ws_url:
            # 鍒涘缓骞跺惎鍔ㄦ柊鐨勭洃鍚櫒
            moonraker_listener = MoonrakerWebsocketListener(ws_url)
            asyncio.create_task(moonraker_listener.start())
            logger.info(f"宸查噸鏂板垵濮嬪寲WebSocket鐩戝惉鍣紝杩炴帴鍒? {ws_url}")
    
    return {"error": False, "message": "閰嶇疆宸蹭繚瀛?}

# 杈呭姪鍑芥暟锛氫粠HTTP鍦板潃鑾峰彇WebSocket URL
def _get_websocket_url_from_http(http_url: str) -> str:
    """浠嶩TTP URL鏋勫缓WebSocket URL

    Args:
        http_url: Moonraker HTTP URL锛屼緥濡?"http://192.168.1.100:7125"

    Returns:
        str: WebSocket URL锛屼緥濡?"ws://192.168.1.100:7125/websocket"
    """
    if not http_url:
        return None
    
    try:
        # 鏇挎崲鍗忚
        if http_url.startswith("https://"):
            ws_url = "wss://" + http_url[8:]
        elif http_url.startswith("http://"):
            ws_url = "ws://" + http_url[7:]
        else:
            # 鍋囪鏄８IP鎴栦富鏈哄悕
            ws_url = "ws://" + http_url
        
        # 纭繚URL鏈熬娌℃湁鏂滄潬
        ws_url = ws_url.rstrip("/")
        
        # 娣诲姞WebSocket璺緞
        ws_url += "/websocket"
        
        return ws_url
    except Exception as e:
        logger.error(f"鏋勫缓WebSocket URL鏃跺嚭閿? {e}")
        return None

# 娣诲姞杈呭姪鍑芥暟妫€鏌HI鏄惁宸插垵濮嬪寲
def is_chi_initialized():
    """妫€鏌HI閫傞厤鍣ㄦ槸鍚﹀凡姝ｇ‘鍒濆鍖?    
    Returns:
        bool: 鏄惁宸插垵濮嬪寲
    """
    return devices["chi"] is not None and hasattr(devices["chi"], "chi_setup") and devices["chi"].chi_setup is not None

@app.get("/api/status")
async def get_status():
    """鑾峰彇鎵€鏈夎澶囩姸鎬?""
    return {
        "chi": {"initialized": devices["chi"] is not None and is_chi_initialized()},
        "printer": {"initialized": devices["printer"] is not None and devices["printer"].initialized},
        "pump": {"initialized": devices["pump"] is not None and devices["pump"].initialized},
        "relay": {"initialized": devices["relay"] is not None and devices["relay"].initialized}
    }

# =========== 鎵撳嵃鏈篈PI ===========

# 鍒濆鍖栨墦鍗版満
@app.post("/api/printer/initialize")
async def initialize_printer():
    global devices
    
    # 濡傛灉宸茬粡鍒濆鍖栵紝鍏堝叧闂箣鍓嶇殑瀹炰緥
    if devices["printer"] is not None:
        await devices["printer"].close()
    
    try:
        devices["printer"] = PrinterAdapter(
            moonraker_addr=config["moonraker_addr"],
            broadcaster=broadcaster
        )
        await devices["printer"].initialize()
        return {"error": False, "message": "鎵撳嵃鏈哄凡鍒濆鍖?}
    except Exception as e:
        logger.error(f"鍒濆鍖栨墦鍗版満澶辫触: {e}")
        return {"error": True, "message": f"鍒濆鍖栨墦鍗版満澶辫触: {e}"}

# 绉诲姩鎵撳嵃鏈?@app.post("/api/printer/move")
async def move_printer(position: Dict[str, float]):
    if devices["printer"] is None or not devices["printer"].initialized:
        return {"error": True, "message": "鎵撳嵃鏈烘湭鍒濆鍖?}
    
    try:
        x = position.get("x", None)
        y = position.get("y", None)
        z = position.get("z", None)
        
        await devices["printer"].move_to(x=x, y=y, z=z)
        return {"error": False, "message": f"鎵撳嵃鏈烘鍦ㄧЩ鍔ㄥ埌 X={x}, Y={y}, Z={z}"}
    except Exception as e:
        logger.error(f"绉诲姩鎵撳嵃鏈哄け璐? {e}")
        return {"error": True, "message": f"绉诲姩鎵撳嵃鏈哄け璐? {e}"}

# 绉诲姩鍒扮綉鏍间綅缃?@app.post("/api/printer/grid")
async def move_to_grid(data: Dict[str, int]):
    if devices["printer"] is None or not devices["printer"].initialized:
        return {"error": True, "message": "鎵撳嵃鏈烘湭鍒濆鍖?}
    
    try:
        position = data.get("position", 1)
        
        await devices["printer"].move_to_grid(position)
        return {"error": False, "message": f"鎵撳嵃鏈烘鍦ㄧЩ鍔ㄥ埌缃戞牸浣嶇疆 {position}"}
    except Exception as e:
        logger.error(f"绉诲姩鍒扮綉鏍间綅缃け璐? {e}")
        return {"error": True, "message": f"绉诲姩鍒扮綉鏍间綅缃け璐? {e}"}

# 褰掍綅鎵撳嵃鏈?@app.post("/api/printer/home")
async def home_printer():
    if devices["printer"] is None or not devices["printer"].initialized:
        return {"error": True, "message": "鎵撳嵃鏈烘湭鍒濆鍖?}
    
    try:
        await devices["printer"].home()
        return {"error": False, "message": "鎵撳嵃鏈烘鍦ㄥ綊浣?}
    except Exception as e:
        logger.error(f"褰掍綅鎵撳嵃鏈哄け璐? {e}")
        return {"error": True, "message": f"褰掍綅鎵撳嵃鏈哄け璐? {e}"}

# 鑾峰彇鎵撳嵃鏈轰綅缃?@app.get("/api/printer/position")
async def get_printer_position():
    if devices["printer"] is None or not devices["printer"].initialized:
        return {"error": True, "message": "鎵撳嵃鏈烘湭鍒濆鍖?}
    
    try:
        position = await devices["printer"].get_position()
        return {"error": False, "position": position}
    except Exception as e:
        logger.error(f"鑾峰彇鎵撳嵃鏈轰綅缃け璐? {e}")
        return {"error": True, "message": f"鑾峰彇鎵撳嵃鏈轰綅缃け璐? {e}"}

# 鑾峰彇鎵撳嵃鏈鸿缁嗕俊鎭紙鍖呮嫭缃戞牸閰嶇疆锛?@app.get("/api/printer/info", response_model=PrinterInfoResponse)
async def get_printer_info():
    # Default values based on PrinterControl class in control_printer.py
    general_min_x, general_min_y, general_min_z = 0.0, 0.0, 75.0
    general_max_x, general_max_y, general_max_z = 215.0, 190.0, 200.0

    grid_rows = 5
    grid_cols = 10
    grid_area_x_min, grid_area_x_max = 6.0, 174.0  # Grid X boundaries
    grid_area_y_min, grid_area_y_max = 100.0, 173.0 # Grid Y boundaries
    grid_z_height = 75.0

    grid_mapping_list = []
    for grid_number_abs in range(1, (grid_rows * grid_cols) + 1):
        row_calc = (grid_number_abs - 1) // grid_cols + 1
        col_calc = (grid_number_abs - 1) % grid_cols + 1

        center_x_calc = grid_area_x_max - (col_calc - 1) * (grid_area_x_max - grid_area_x_min) / (grid_cols - 1 if grid_cols > 1 else 1)
        center_y_calc = grid_area_y_max - (row_calc - 1) * (grid_area_y_max - grid_area_y_min) / (grid_rows - 1 if grid_rows > 1 else 1)
        
        grid_mapping_list.append(
            GridCell(
                grid_number=grid_number_abs,
                row=row_calc,
                col=col_calc,
                center_x=round(center_x_calc, 2),
                center_y=round(center_y_calc, 2)
            )
        )

    return PrinterInfoResponse(
        general_limits=GeneralLimits(
            min_x=general_min_x, max_x=general_max_x,
            min_y=general_min_y, max_y=general_max_y,
            min_z=general_min_z, max_z=general_max_z
        ),
        grid_config=GridConfig(
            rows=grid_rows,
            cols=grid_cols,
            x_min=grid_area_x_min,
            x_max=grid_area_x_max,
            y_min=grid_area_y_min,
            y_max=grid_area_y_max,
            z_height=grid_z_height,
            grid_mapping=grid_mapping_list
        )
    )

# =========== 娉礎PI ===========

# 鍒濆鍖栨车
@app.post("/api/pump/initialize")
async def initialize_pump():
    global devices, moonraker_listener
    
    # 濡傛灉宸茬粡鍒濆鍖栵紝鍏堝叧闂箣鍓嶇殑瀹炰緥
    if devices["pump"] is not None:
        await devices["pump"].close()
    
    try:
        # 鍒濆鍖朩ebSocket鐩戝惉鍣紙濡傛灉灏氭湭鍒濆鍖栵級
        if moonraker_listener is None and MoonrakerWebsocketListener is not None:
            ws_url = _get_websocket_url_from_http(config["moonraker_addr"])
            if ws_url:
                moonraker_listener = MoonrakerWebsocketListener(ws_url)
                asyncio.create_task(moonraker_listener.start())
                logger.info(f"宸插垵濮嬪寲WebSocket鐩戝惉鍣紝杩炴帴鍒? {ws_url}")
        
        # 鍒涘缓鏂扮殑娉甸€傞厤鍣ㄥ疄渚嬶紝浼犲叆WebSocket鐩戝惉鍣?        devices["pump"] = PumpAdapter(
            moonraker_addr=config["moonraker_addr"],
            broadcaster=broadcaster,
            ws_listener=moonraker_listener
        )
        await devices["pump"].initialize()
        return {"error": False, "message": "娉靛凡鍒濆鍖?}
    except Exception as e:
        logger.error(f"鍒濆鍖栨车澶辫触: {e}")
        return {"error": True, "message": f"鍒濆鍖栨车澶辫触: {e}"}

# 鑷姩娉甸€?@app.post("/api/pump/dispense_auto")
async def dispense_auto(data: Dict[str, Any]):
    if devices["pump"] is None or not devices["pump"].initialized:
        return {"error": True, "message": "娉垫湭鍒濆鍖?}
    
    try:
        pump_index = int(data.get("pump_index", 0))
        volume = float(data.get("volume", 100))
        speed = data.get("speed", "medium")
        direction = int(data.get("direction", 1))
        
        # 閫熷害杞崲
        speed_map = {"slow": "slow", "medium": "normal", "fast": "fast"}
        speed_value = speed_map.get(speed, "normal")
        
        await devices["pump"].dispense_auto(
            pump_index=pump_index,
            volume=volume,
            speed=speed_value,
            direction=direction
        )
        return {"error": False, "message": f"娉?{pump_index} 姝ｅ湪鑷姩娉甸€?{volume} 渭L"}
    except Exception as e:
        logger.error(f"鑷姩娉甸€佸け璐? {e}")
        return {"error": True, "message": f"鑷姩娉甸€佸け璐? {e}"}

# 瀹氭椂娉甸€?@app.post("/api/pump/dispense_timed")
async def dispense_timed(data: Dict[str, Any]):
    if devices["pump"] is None or not devices["pump"].initialized:
        return {"error": True, "message": "娉垫湭鍒濆鍖?}
    
    try:
        pump_index = int(data.get("pump_index", 0))
        duration = float(data.get("duration", 5))
        rpm = float(data.get("rpm", 30))
        direction = int(data.get("direction", 1))
        
        await devices["pump"].dispense_timed(
            pump_index=pump_index,
            duration=duration,
            rpm=rpm,
            direction=direction
        )
        return {"error": False, "message": f"娉?{pump_index} 姝ｅ湪浠?{rpm} RPM 鐨勯€熷害瀹氭椂娉甸€?{duration} 绉?}
    except Exception as e:
        logger.error(f"瀹氭椂娉甸€佸け璐? {e}")
        return {"error": True, "message": f"瀹氭椂娉甸€佸け璐? {e}"}

# 鍋滄娉?@app.post("/api/pump/stop")
async def stop_pump(data: Dict[str, int]):
    if devices["pump"] is None or not devices["pump"].initialized:
        return {"error": True, "message": "娉垫湭鍒濆鍖?}
    
    try:
        pump_index = data.get("pump_index", 0)
        
        await devices["pump"].stop(pump_index)
        return {"error": False, "message": f"娉?{pump_index} 宸插仠姝?}
    except Exception as e:
        logger.error(f"鍋滄娉靛け璐? {e}")
        return {"error": True, "message": f"鍋滄娉靛け璐? {e}"}

# 鑾峰彇娉电姸鎬?@app.get("/api/pump/status")
async def get_pump_status(pump_index: int = 0):
    if devices["pump"] is None or not devices["pump"].initialized:
        return {"error": True, "message": "娉垫湭鍒濆鍖?}
    
    try:
        status = await devices["pump"].get_status(pump_index)
        return {"error": False, "status": status}
    except Exception as e:
        logger.error(f"鑾峰彇娉电姸鎬佸け璐? {e}")
        return {"error": True, "message": f"鑾峰彇娉电姸鎬佸け璐? {e}"}

# =========== 缁х數鍣ˋPI ===========

# 鍒濆鍖栫户鐢靛櫒
@app.post("/api/relay/initialize")
async def initialize_relay():
    global devices
    
    # 濡傛灉宸茬粡鍒濆鍖栵紝鍏堝叧闂箣鍓嶇殑瀹炰緥
    if devices["relay"] is not None:
        await devices["relay"].close()
    
    try:
        devices["relay"] = RelayAdapter(
            moonraker_addr=config["moonraker_addr"],
            broadcaster=broadcaster
        )
        await devices["relay"].initialize()
        return {"error": False, "message": "缁х數鍣ㄥ凡鍒濆鍖?}
    except Exception as e:
        logger.error(f"鍒濆鍖栫户鐢靛櫒澶辫触: {e}")
        return {"error": True, "message": f"鍒濆鍖栫户鐢靛櫒澶辫触: {e}"}

# 鍒囨崲缁х數鍣?@app.post("/api/relay/toggle")
async def toggle_relay(data: Dict[str, Any]):
    if devices["relay"] is None or not devices["relay"].initialized:
        return {"error": True, "message": "缁х數鍣ㄦ湭鍒濆鍖?}
    
    try:
        relay_id = int(data.get("relay_id", 1))
        state = data.get("state", None)
        
        await devices["relay"].toggle(relay_id, state)
        return {"error": False, "message": f"缁х數鍣?{relay_id} 宸插垏鎹?}
    except Exception as e:
        logger.error(f"鍒囨崲缁х數鍣ㄥけ璐? {e}")
        return {"error": True, "message": f"鍒囨崲缁х數鍣ㄥけ璐? {e}"}

# 鑾峰彇缁х數鍣ㄧ姸鎬?@app.get("/api/relay/status")
async def get_relay_status():
    if devices["relay"] is None or not devices["relay"].initialized:
        return {"error": True, "message": "缁х數鍣ㄦ湭鍒濆鍖?}
    
    try:
        # 鑾峰彇缁х數鍣ㄧ姸鎬佸瓧鍏?        states_dict = await devices["relay"].get_status()
        
        # 杞崲甯冨皵鍊间负瀛楃涓叉牸寮忥紝浣垮墠绔洿瀹规槗瑙ｆ瀽
        formatted_states = {}
        for key, value in states_dict.items():
            formatted_states[str(key)] = "on" if value else "off"
        
        logger.info(f"缁х數鍣ㄧ姸鎬? {formatted_states}")
        return {"error": False, "states": formatted_states}
    except Exception as e:
        logger.error(f"鑾峰彇缁х數鍣ㄧ姸鎬佸け璐? {e}")
        return {"error": True, "message": f"鑾峰彇缁х數鍣ㄧ姸鎬佸け璐? {e}"}

# =========== CHI API ===========

# 褰撳墠CHI娴嬭瘯鐘舵€?chi_test_state = {
    "status": "idle",      # idle, initializing, running, completed, error
    "test_type": None,     # CV, CA, EIS, etc.
    "start_time": None,
    "progress": 0.0,       # 0.0 - 1.0
    "elapsed_time": 0,
    "result_file": None
}

# CHI娴嬭瘯璋冪敤閿佸畾
chi_test_lock = asyncio.Lock()

# 鍒濆鍖朇HI宸ヤ綔绔?@app.post("/api/chi/initialize")
async def initialize_chi():
    global devices
    
    # 濡傛灉宸茬粡鍒濆鍖栵紝鍏堝叧闂箣鍓嶇殑瀹炰緥
    if devices["chi"] is not None:
        await devices["chi"].close()
    
    try:
        # 淇敼锛氫娇鐢ㄤ粠backend.services.adapters.chi_adapter瀵煎叆鐨凜HIAdapter绫?        # 骞剁‘淇濆弬鏁扮鍚坆ackend.services.adapters.chi_adapter.CHIAdapter鐨刜_init__鏂规硶
        devices["chi"] = CHIAdapter(
            broadcaster=broadcaster,
            results_base_dir=config["results_dir"],  # 娉ㄦ剰锛氭敼涓簉esults_base_dir锛堜笌瀵煎叆鐨凜HIAdapter鍙傛暟鍚嶄竴鑷达級
            chi_path=config["chi_path"]
        )
        await devices["chi"].initialize()
        return {"error": False, "message": "CHI宸ヤ綔绔欏凡鍒濆鍖?}
    except Exception as e:
        logger.error(f"鍒濆鍖朇HI宸ヤ綔绔欏け璐? {e}")
        return {"error": True, "message": f"鍒濆鍖朇HI宸ヤ綔绔欏け璐? {e}"}

# 杩愯CV娴嬭瘯
@app.post("/api/chi/cv")
async def run_cv_test(payload: CVAPIParams, background_tasks: BackgroundTasks):
    if devices["chi"] is None or not is_chi_initialized():
        return {"error": True, "message": "CHI鏈垵濮嬪寲"}
    
    try:
        # 鎻愬彇鏂囦欢鍚?        file_name = payload.file_name or f"CV_{int(time.time())}"
        
        # 鍒涘缓鍙傛暟瀛楀吀
        params = {
            "ei": payload.ei,
            "eh": payload.eh,
            "el": payload.el,
            "v": payload.v,
            "si": payload.si,
            "cl": payload.cl,
            "sens": payload.sens,
            "qt": payload.qt,
            "pn": payload.pn,
            "autosens": payload.autosens
        }
        
        # 鍚庡彴杩愯娴嬭瘯
        background_tasks.add_task(devices["chi"].run_cv_test, file_name=file_name, params=params)
        
        logger.info(f"CV娴嬭瘯宸插湪鍚庡彴鍚姩: {file_name}")
        return {"error": False, "message": f"CV娴嬭瘯宸插湪鍚庡彴鍚姩", "file_name": file_name}
    except Exception as e:
        logger.error(f"杩愯CV娴嬭瘯澶辫触: {e}")
        return {"error": True, "message": f"杩愯CV娴嬭瘯澶辫触: {e}"}

# 杩愯CA娴嬭瘯
@app.post("/api/chi/ca")
async def run_ca_test(payload: CAAPIParams, background_tasks: BackgroundTasks):
    if devices["chi"] is None or not is_chi_initialized():
        return {"error": True, "message": "CHI宸ヤ綔绔欐湭鍒濆鍖?}
    
    try:
        # 鎻愬彇鏂囦欢鍚嶏紝浠庢暟鎹腑绉婚櫎
        file_name = payload.file_name or f"CA_{int(time.time())}"
        
        # 鍒涘缓鍙傛暟瀛楀吀
        params = {
            "ei": payload.ei,
            "eh": payload.eh,
            "el": payload.el,
            "cl": payload.cl,
            "pw": payload.pw,
            "si": payload.si,
            "sens": payload.sens,
            "qt": payload.qt,
            "pn": payload.pn,
            "autosens": payload.autosens
        }
        
        # 鍚庡彴杩愯娴嬭瘯
        background_tasks.add_task(devices["chi"].run_ca_test, file_name=file_name, params=params)
        
        logger.info(f"CA娴嬭瘯宸插湪鍚庡彴鍚姩: {file_name}")
        return {"error": False, "message": f"CA娴嬭瘯宸插湪鍚庡彴鍚姩", "file_name": file_name}
    except Exception as e:
        logger.error(f"杩愯CA娴嬭瘯澶辫触: {e}")
        return {"error": True, "message": f"杩愯CA娴嬭瘯澶辫触: {e}"}

# 杩愯EIS娴嬭瘯
@app.post("/api/chi/eis")
async def run_eis_test(data: Dict[str, Any], background_tasks: BackgroundTasks):
    if devices["chi"] is None or not is_chi_initialized():
        return {"error": True, "message": "CHI宸ヤ綔绔欐湭鍒濆鍖?}
    
    try:
        # 鎻愬彇鏂囦欢鍚嶏紝浠庢暟鎹腑绉婚櫎
        file_name = data.pop("file_name", f"EIS_{int(time.time())}")
        
        # 鍒涘缓鍙傛暟瀛楀吀锛屼笌backend.services.adapters.chi_adapter.run_eis_test鏂规硶鎵€闇€鍙傛暟涓€鑷?        params = {
            "ei": float(data.get("voltage", 0)),            # 鐩存祦鐢典綅
            "fl": float(data.get("freq_final", 0.1)),       # 浣庨锛堢粨鏉熼鐜囷級
            "fh": float(data.get("freq_init", 100000)),     # 楂橀锛堣捣濮嬮鐜囷級
            "amp": float(data.get("amplitude", 10)),        # 浜ゆ祦鎸箙
            "sens": float(data.get("sens", 1e-5)),          # 鐏垫晱搴?            "impautosens": bool(data.get("impautosens", True))  # 鑷姩鐏垫晱搴?        }
        
        # 鑾峰彇妯″紡鍙傛暟锛岄粯璁や负'impsf'
        mode = data.get("mode", "impsf")
        if mode in ["impsf", "impft"]:
            params["mode"] = mode
        
        # 鍚庡彴杩愯娴嬭瘯
        background_tasks.add_task(devices["chi"].run_eis_test, file_name=file_name, params=params)
        
        logger.info(f"EIS娴嬭瘯宸插湪鍚庡彴鍚姩: {file_name}")
        return {"error": False, "message": f"EIS娴嬭瘯宸插湪鍚庡彴鍚姩", "file_name": file_name}
    except Exception as e:
        logger.error(f"杩愯EIS娴嬭瘯澶辫触: {e}")
        return {"error": True, "message": f"杩愯EIS娴嬭瘯澶辫触: {e}"}

# 杩愯LSV娴嬭瘯
@app.post("/api/chi/lsv")
async def run_lsv_test(data: Dict[str, Any], background_tasks: BackgroundTasks):
    if devices["chi"] is None or not is_chi_initialized():
        return {"error": True, "message": "CHI鏈垵濮嬪寲"}
    
    try:
        # 鎻愬彇鏂囦欢鍚嶏紝浠庢暟鎹腑绉婚櫎
        file_name = data.pop("file_name", f"LSV_{int(time.time())}")
        
        # 鍒涘缓鍙傛暟瀛楀吀锛屼笌backend.services.adapters.chi_adapter.run_lsv_test鏂规硶鎵€闇€鍙傛暟涓€鑷?        params = {
            "ei": float(data.get("initial_v", -0.5)),    # 鍒濆鐢典綅
            "ef": float(data.get("final_v", 0.5)),       # 鏈€缁堢數浣?            "v": float(data.get("scan_rate", 0.1)),      # 鎵弿閫熺巼
            "si": float(data.get("interval", 0.001)),    # 閲囨牱闂撮殧
            "sens": float(data.get("sens", 1e-5))        # 鐏垫晱搴?        }
        
        # 鍚庡彴杩愯娴嬭瘯
        background_tasks.add_task(devices["chi"].run_lsv_test, file_name=file_name, params=params)
        
        logger.info(f"LSV娴嬭瘯宸插湪鍚庡彴鍚姩: {file_name}")
        return {"error": False, "message": f"LSV娴嬭瘯宸插湪鍚庡彴鍚姩", "file_name": file_name}
    except Exception as e:
        logger.error(f"杩愯LSV娴嬭瘯澶辫触: {e}")
        return {"error": True, "message": f"杩愯LSV娴嬭瘯澶辫触: {e}"}

# 杩愯IT娴嬭瘯
@app.post("/api/chi/it")
async def run_it_test(payload: ITAPIParams, background_tasks: BackgroundTasks):
    if devices["chi"] is None or not is_chi_initialized():
        logger.error("CHI鏈垵濮嬪寲锛屾棤娉曡繍琛宨-t娴嬭瘯")
        raise HTTPException(status_code=503, detail="CHI璁惧鏈垵濮嬪寲")
    
    try:
        # 纭畾瑕佷紶閫掔粰閫傞厤鍣ㄧ殑鏂囦欢鍚?        effective_file_name = payload.file_name if payload.file_name is not None else f'IT_{int(time.time())}'
        
        # 鍒涘缓鍙傛暟瀛楀吀锛屼笌backend.services.adapters.chi_adapter.run_it_test鏂规硶鎵€闇€鍙傛暟涓€鑷?        params = {
            "ei": payload.ei,     # 鎭掑畾鐢典綅
            "si": payload.si,     # 閲囨牱闂撮殧
            "st": payload.st,     # 鎬婚噰鏍锋椂闂?            "sens": payload.sens  # 鐏垫晱搴?        }
        
        # 璁板綍瀹屾暣鍙傛暟淇℃伅锛屼究浜庤皟璇?        logger.info(f"i-t娴嬭瘯鍙傛暟: {params}")
        
        # 鍚庡彴杩愯娴嬭瘯
        background_tasks.add_task(devices["chi"].run_it_test, file_name=effective_file_name, params=params)
        
        logger.info(f"i-t娴嬭瘯宸插湪鍚庡彴鍚姩: {effective_file_name}")
        return {"error": False, "message": "i-t娴嬭瘯宸插湪鍚庡彴鍚姩", "file_name": effective_file_name}
    except Exception as e:
        logger.error(f"杩愯i-t娴嬭瘯澶辫触: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"杩愯i-t娴嬭瘯澶辫触: {str(e)}")

# 杩愯OCP娴嬭瘯
@app.post("/api/chi/ocp")
async def run_ocp_test_endpoint(payload: OCPAPIParams, background_tasks: BackgroundTasks):
    if devices["chi"] is None or not is_chi_initialized():
        logger.error("CHI鏈垵濮嬪寲锛屾棤娉曡繍琛孫CP娴嬭瘯")
        raise HTTPException(status_code=503, detail="CHI璁惧鏈垵濮嬪寲")

    try:
        # 纭畾瑕佷紶閫掔粰閫傞厤鍣ㄧ殑鏂囦欢鍚?        effective_file_name = payload.file_name if payload.file_name is not None else 'OCP'
        
        # 鍒涘缓鍙傛暟瀛楀吀锛屼笌backend.services.adapters.chi_adapter.run_ocp_test鏂规硶鎵€闇€鍙傛暟涓€鑷?        params = {
            "st": payload.st,  # 杩愯鏃堕棿 (蹇呴渶)
            "si": payload.si,  # 閲囨牱闂撮殧 (蹇呴渶)
        }
        # 鍙湁褰撴彁渚涗簡eh鍜宔l鍙傛暟鏃舵墠娣诲姞鍒皃arams瀛楀吀涓?        if payload.eh is not None:
            params["eh"] = payload.eh
        if payload.el is not None:
            params["el"] = payload.el
        
        # 鍦ㄥ悗鍙拌繍琛屾祴璇?        background_tasks.add_task(
            devices["chi"].run_ocp_test, 
            file_name=effective_file_name, 
            params=params
        )
        
        logger.info(f"OCP娴嬭瘯宸插湪鍚庡彴鍚姩: {effective_file_name}")
        return {"error": False, "message": "OCP娴嬭瘯宸插湪鍚庡彴鍚姩", "file_name": effective_file_name}
    except Exception as e:
        logger.error(f"杩愯OCP娴嬭瘯澶辫触: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"杩愯OCP娴嬭瘯澶辫触: {str(e)}")

# 杩愯DPV娴嬭瘯
@app.post("/api/chi/dpv")
async def run_dpv_test_endpoint(payload: DPVAPIParams, background_tasks: BackgroundTasks):
    if devices["chi"] is None or not is_chi_initialized():
        logger.error("CHI鏈垵濮嬪寲锛屾棤娉曡繍琛孌PV娴嬭瘯")
        raise HTTPException(status_code=503, detail="CHI璁惧鏈垵濮嬪寲")

    try:
        # 纭畾瑕佷紶閫掔粰閫傞厤鍣ㄧ殑鏂囦欢鍚?        effective_file_name = payload.file_name if payload.file_name is not None else f'DPV_{int(time.time())}'
        
        # 鍒涘缓鍙傛暟瀛楀吀
        params = {
            "ei": payload.ei,
            "ef": payload.ef,
            "incre": payload.incre,
            "amp": payload.amp,
            "pw": payload.pw,
            "sw": payload.sw,
            "prod": payload.prod,
            "qt": payload.qt,
            "autosens": payload.autosens
        }
        # 鍙湁褰撴湭浣跨敤autosens涓旀彁渚涗簡sens鍙傛暟鏃舵墠娣诲姞sens
        if not payload.autosens and payload.sens is not None:
            params["sens"] = payload.sens
        
        # 鍦ㄥ悗鍙拌繍琛屾祴璇?        background_tasks.add_task(
            devices["chi"].run_dpv_test, 
            file_name=effective_file_name, 
            params=params
        )
        
        logger.info(f"DPV娴嬭瘯宸插湪鍚庡彴鍚姩: {effective_file_name}")
        return {"error": False, "message": "DPV娴嬭瘯宸插湪鍚庡彴鍚姩", "file_name": effective_file_name}
    except Exception as e:
        logger.error(f"杩愯DPV娴嬭瘯澶辫触: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"杩愯DPV娴嬭瘯澶辫触: {str(e)}")

# 杩愯SCV娴嬭瘯
@app.post("/api/chi/scv")
async def run_scv_test_endpoint(payload: SCVAPIParams, background_tasks: BackgroundTasks):
    if devices["chi"] is None or not is_chi_initialized():
        logger.error("CHI鏈垵濮嬪寲锛屾棤娉曡繍琛孲CV娴嬭瘯")
        raise HTTPException(status_code=503, detail="CHI璁惧鏈垵濮嬪寲")

    try:
        # 纭畾瑕佷紶閫掔粰閫傞厤鍣ㄧ殑鏂囦欢鍚?        effective_file_name = payload.file_name if payload.file_name is not None else f'SCV_{int(time.time())}'
        
        # 鍒涘缓鍙傛暟瀛楀吀
        params = {
            "ei": payload.ei,
            "ef": payload.ef,
            "incre": payload.incre,
            "sw": payload.sw,
            "prod": payload.prod,
            "qt": payload.qt,
            "autosens": payload.autosens
        }
        # 鍙湁褰撴湭浣跨敤autosens涓旀彁渚涗簡sens鍙傛暟鏃舵墠娣诲姞sens
        if not payload.autosens and payload.sens is not None:
            params["sens"] = payload.sens
        
        # 鍦ㄥ悗鍙拌繍琛屾祴璇?        background_tasks.add_task(
            devices["chi"].run_scv_test, 
            file_name=effective_file_name, 
            params=params
        )
        
        logger.info(f"SCV娴嬭瘯宸插湪鍚庡彴鍚姩: {effective_file_name}")
        return {"error": False, "message": "SCV娴嬭瘯宸插湪鍚庡彴鍚姩", "file_name": effective_file_name}
    except Exception as e:
        logger.error(f"杩愯SCV娴嬭瘯澶辫触: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"杩愯SCV娴嬭瘯澶辫触: {str(e)}")

# 杩愯CP娴嬭瘯
@app.post("/api/chi/cp")
async def run_cp_test_endpoint(params: CPAPIParams):
    """杩愯璁℃椂鐢典綅娉曟祴璇?(CP)"""
    try:
        # 璁板綍璇锋眰
        logging.info(f"鎺ユ敹鍒癈P娴嬭瘯璇锋眰: {params.dict()}")
        
        # 鎻愬彇鏂囦欢鍚嶆垨鍒涘缓榛樿鏂囦欢鍚?        file_name = params.file_name or f"CP_Test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 璋冪敤閫傞厤鍣ㄨ繍琛孋P娴嬭瘯
        result = await devices["chi"].run_cp_test(file_name, params.dict())
        
        if result:
            return {"error": False, "message": "CP娴嬭瘯宸插惎鍔?, "file_name": file_name}
        else:
            return {"error": True, "message": "CP娴嬭瘯鍚姩澶辫触"}
    
    except Exception as e:
        logging.exception("CP娴嬭瘯璇锋眰澶勭悊澶辫触")
        return {"error": True, "message": f"澶勭悊CP娴嬭瘯璇锋眰鏃跺嚭閿? {str(e)}"}

# 杩愯ACV娴嬭瘯
@app.post("/api/chi/acv")
async def run_acv_test_endpoint(params: ACVAPIParams):
    """杩愯浜ゆ祦浼忓畨娉曟祴璇?(ACV)"""
    try:
        # 璁板綍璇锋眰
        logging.info(f"鎺ユ敹鍒癆CV娴嬭瘯璇锋眰: {params.dict()}")
        
        # 鎻愬彇鏂囦欢鍚嶆垨鍒涘缓榛樿鏂囦欢鍚?        file_name = params.file_name or f"ACV_Test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 璋冪敤閫傞厤鍣ㄨ繍琛孉CV娴嬭瘯
        result = await devices["chi"].run_acv_test(file_name, params.dict())
        
        if result:
            return {"error": False, "message": "ACV娴嬭瘯宸插惎鍔?, "file_name": file_name}
        else:
            return {"error": True, "message": "ACV娴嬭瘯鍚姩澶辫触"}
    
    except Exception as e:
        logging.exception("ACV娴嬭瘯璇锋眰澶勭悊澶辫触")
        return {"error": True, "message": f"澶勭悊ACV娴嬭瘯璇锋眰鏃跺嚭閿? {str(e)}"}

# 鍋滄CHI娴嬭瘯
@app.post("/api/chi/stop")
async def stop_chi_test():
    if devices["chi"] is None or not is_chi_initialized():
        return {"error": True, "message": "CHI宸ヤ綔绔欐湭鍒濆鍖?}
    
    try:
        # 璋冪敤CHI鍋滄鏂规硶
        await devices["chi"].stop_test()
        
        return {"error": False, "message": "CHI娴嬭瘯宸插仠姝?}
    except Exception as e:
        logger.error(f"鍋滄CHI娴嬭瘯澶辫触: {e}")
        return {"error": True, "message": f"鍋滄CHI娴嬭瘯澶辫触: {e}"}

# 鑾峰彇CHI娴嬭瘯鐘舵€?@app.get("/api/chi/status")
async def get_chi_status():
    if devices["chi"] is None or not is_chi_initialized():
        return {"error": True, "message": "CHI宸ヤ綔绔欐湭鍒濆鍖?}
    
    try:
        # 璋冪敤CHI鐘舵€佹柟娉?        status = await devices["chi"].get_status()
        return {"error": False, "status": status}
    except Exception as e:
        logger.error(f"鑾峰彇CHI鐘舵€佸け璐? {e}")
        return {"error": True, "message": f"鑾峰彇CHI鐘舵€佸け璐? {e}"}

# 鑾峰彇CHI娴嬭瘯缁撴灉鍒楄〃
@app.get("/api/chi/results")
async def get_chi_results():
    if devices["chi"] is None or not is_chi_initialized():
        return {"error": True, "message": "CHI宸ヤ綔绔欐湭鍒濆鍖?}
    
    try:
        # 璋冪敤CHI鑾峰彇缁撴灉鏂规硶
        results = await devices["chi"].get_results()
        return {"error": False, "results": results}
    except Exception as e:
        logger.error(f"鑾峰彇CHI娴嬭瘯缁撴灉鍒楄〃澶辫触: {e}")
        return {"error": True, "message": f"鑾峰彇CHI娴嬭瘯缁撴灉鍒楄〃澶辫触: {e}"}

# 涓嬭浇CHI娴嬭瘯缁撴灉鏂囦欢
@app.get("/api/chi/download")
async def download_chi_result(file: str):
    try:
        file_path = Path(file)
        
        # 瀹夊叏妫€鏌ワ細纭繚鏂囦欢浣嶄簬缁撴灉鐩綍鍐?        if not str(file_path).startswith(config["results_dir"]):
            return {"error": True, "message": "鏂囦欢璺緞鏃犳晥"}
        
        if not file_path.exists():
            return {"error": True, "message": "鏂囦欢涓嶅瓨鍦?}
        
        return FileResponse(
            path=file_path,
            filename=file_path.name,
            media_type="text/plain"
        )
    except Exception as e:
        logger.error(f"涓嬭浇CHI娴嬭瘯缁撴灉鏂囦欢澶辫触: {e}")
        return {"error": True, "message": f"涓嬭浇CHI娴嬭瘯缁撴灉鏂囦欢澶辫触: {e}"}

# =========== 杈呭姪鍑芥暟 ===========

# 鍚庡彴杩愯CHI娴嬭瘯
async def run_chi_test_background(test_type, **kwargs):
    try:
        # 鏇存柊鐘舵€佷负杩愯涓?        chi_test_state["status"] = "running"
        
        # 鏍规嵁娴嬭瘯绫诲瀷璋冪敤涓嶅悓鐨勬柟娉?        result_file = None
        if test_type == "cv":
            # 璋冪敤CV娴嬭瘯
            result_file = await devices["chi"].run_cv_test(**kwargs)
            
            # 鍙戦€佽繘搴︽洿鏂?- 杩欓噷绠€鍗曟ā鎷熻繘搴?            for i in range(1, 101):
                if chi_test_state["status"] != "running":
                    break  # 娴嬭瘯宸茶鍋滄
                
                chi_test_state["progress"] = i / 100.0
                
                # 妯℃嫙娴嬭瘯鑰楁椂锛屾牴鎹惊鐜鏁拌皟鏁?                cycle_time = 5 * kwargs.get("cycles", 3)
                await asyncio.sleep(cycle_time / 100)
        
        elif test_type == "ca":
            # 璋冪敤CA娴嬭瘯
            result_file = await devices["chi"].run_ca_test(**kwargs)
            
            # 鍙戦€佽繘搴︽洿鏂?- 杩欓噷浣跨敤娴嬭瘯鏃堕棿鏉ヨ绠楄繘搴?            test_time = kwargs.get("time", 10)
            start_time = time.time()
            
            while time.time() - start_time < test_time:
                if chi_test_state["status"] != "running":
                    break  # 娴嬭瘯宸茶鍋滄
                
                elapsed = time.time() - start_time
                progress = min(elapsed / test_time, 1.0)
                chi_test_state["progress"] = progress
                
                await asyncio.sleep(0.5)
        
        elif test_type == "eis":
            # 璋冪敤EIS娴嬭瘯
            result_file = await devices["chi"].run_eis_test(**kwargs)
            
            # 鍙戦€佽繘搴︽洿鏂?- EIS娴嬭瘯鍙兘闇€瑕佽緝闀挎椂闂达紝杩欓噷妯℃嫙杩涘害
            estimated_time = 60  # 浼拌60绉掑畬鎴?            start_time = time.time()
            
            while time.time() - start_time < estimated_time:
                if chi_test_state["status"] != "running":
                    break  # 娴嬭瘯宸茶鍋滄
                
                elapsed = time.time() - start_time
                progress = min(elapsed / estimated_time, 1.0)
                chi_test_state["progress"] = progress
                
                await asyncio.sleep(1)
        
        # 娴嬭瘯瀹屾垚锛屾洿鏂扮姸鎬?        if chi_test_state["status"] == "running":  # 鍙湁褰撴祴璇曚粛鍦ㄨ繍琛屾椂鎵嶆洿鏂颁负瀹屾垚鐘舵€?            chi_test_state.update({
                "status": "completed",
                "progress": 1.0,
                "result_file": result_file
            })
    
    except Exception as e:
        # 娴嬭瘯鍑洪敊锛屾洿鏂扮姸鎬?        logger.error(f"CHI娴嬭瘯鍑洪敊: {e}")
        chi_test_state.update({
            "status": "error",
            "progress": 0.0
        })

# 鑾峰彇CHI鏂囦欢绫诲瀷
def get_chi_file_type(filename):
    """鏍规嵁鏂囦欢鍚嶆帹鏂瑿HI娴嬭瘯绫诲瀷"""
    lower_name = filename.lower()
    
    if "cv" in lower_name:
        return "CV"
    elif "ca" in lower_name:
        return "CA"
    elif "eis" in lower_name or "impedance" in lower_name:
        return "EIS"
    elif "lsv" in lower_name:
        return "LSV"
    elif "ocp" in lower_name:
        return "OCP"
    elif "it" in lower_name:
        return "IT"
    else:
        return "鏈煡"

# 鍚姩鏃跺姞杞介厤缃?def load_config():
    global config
    try:
        if os.path.exists("device_config.json"):
            with open("device_config.json", "r", encoding="utf-8") as f:
                loaded_config = json.load(f)
                config.update(loaded_config)
            logger.info("宸插姞杞介厤缃枃浠?)
    except Exception as e:
        logger.error(f"鍔犺浇閰嶇疆鏂囦欢澶辫触: {e}")

# 杈呭姪鍣ㄧ被瀹炵幇
class PrinterAdapter:
    def __init__(self, moonraker_addr, broadcaster):
        try:
            from device_control.control_printer import PrinterControl
            self.printer = PrinterControl(ip=moonraker_addr.split("//")[1].split(":")[0])
            self.broadcaster = broadcaster
            self.initialized = False
            self.position = {"x": 0, "y": 0, "z": 0}
            logger.info(f"鎵撳嵃鏈洪€傞厤鍣ㄥ凡鍒涘缓锛岃繛鎺ュ埌 {moonraker_addr}")
        except Exception as e:
            logger.error(f"鍒濆鍖栨墦鍗版満閫傞厤鍣ㄥけ璐? {e}")
            self.printer = None
            self.broadcaster = broadcaster
            self.initialized = False
            self.position = {"x": 0, "y": 0, "z": 0}
        
    async def initialize(self):
        # 鍒濆鍖栨墦鍗版満
        try:
            if self.printer is None:
                raise ValueError("鎵撳嵃鏈烘帶鍒跺櫒鍒濆鍖栧け璐?)
                
            self.initialized = True
            position = self.printer.get_current_position()
            if position:
                self.position = {"x": position[0], "y": position[1], "z": position[2]}
            await self.broadcast_status()
            logger.info("鎵撳嵃鏈哄垵濮嬪寲鎴愬姛")
            return True
        except Exception as e:
            logger.error(f"鎵撳嵃鏈哄垵濮嬪寲澶辫触: {e}")
            self.initialized = False
            await self.broadcast_status()
            raise
        
    async def close(self):
        self.initialized = False
        
    async def move_to(self, x, y, z):
        if not self.initialized:
            raise ValueError("鎵撳嵃鏈烘湭鍒濆鍖?)
        
        # 绉诲姩鎵撳嵃鏈?        result = self.printer.move_to(x, y, z)
        
        # 鏇存柊浣嶇疆
        position = self.printer.get_current_position()
        if position:
            self.position = {"x": position[0], "y": position[1], "z": position[2]}
        
        await self.broadcast_status()
        return result
    
    async def move_to_grid(self, position):
        if not self.initialized:
            raise ValueError("鎵撳嵃鏈烘湭鍒濆鍖?)
        
        # 绉诲姩鎵撳嵃鏈哄埌缃戞牸浣嶇疆
        result = self.printer.move_to_grid_position(position)
        
        # 鏇存柊浣嶇疆
        printer_position = self.printer.get_current_position()
        if printer_position:
            self.position = {"x": printer_position[0], "y": printer_position[1], "z": printer_position[2]}
        
        await self.broadcast_status()
        return result
    
    async def home(self):
        if not self.initialized:
            raise ValueError("鎵撳嵃鏈烘湭鍒濆鍖?)
        
        # 褰掍綅鎵撳嵃鏈?        result = self.printer.home()
        
        # 鏇存柊浣嶇疆
        position = self.printer.get_current_position()
        if position:
            self.position = {"x": position[0], "y": position[1], "z": position[2]}
        
        await self.broadcast_status()
        return result
