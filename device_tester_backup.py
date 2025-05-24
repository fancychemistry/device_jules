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

# 引入适配器
from backend.pubsub import Broadcaster
from backend.services.adapters.printer_adapter import PrinterAdapter
from backend.services.adapters.pump_adapter import PumpAdapter
from backend.services.adapters.relay_adapter import RelayAdapter
from backend.services.adapters.chi_adapter import CHIAdapter

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("device_tester.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("device_tester")

# 引入新的WebSocket监听器
try:
    from core_api.moonraker_listener import MoonrakerWebsocketListener
    logger.info("成功导入MoonrakerWebsocketListener，将使用WebSocket获取精确泵参数")
except ImportError:
    logger.warning("无法导入MoonrakerWebsocketListener，将使用传统方式估算泵参数")
    MoonrakerWebsocketListener = None

# FastAPI 应用
app = FastAPI(title="设备测试器")

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
    ic: float  # 阴极电流
    ia: float  # 阳极电流
    tc: float  # 阴极时间
    ta: float  # 阳极时间
    eh: Optional[float] = 10.0  # 高电位限制
    el: Optional[float] = -10.0  # 低电位限制
    pn: Optional[str] = 'p'  # 第一步电流极性
    si: Optional[float] = 0.1  # 数据存储间隔
    cl: Optional[int] = 1  # 段数/循环数
    priority: Optional[str] = 'time'  # 优先模式，'time'或'potential'
    file_name: Optional[str] = None

class ACVAPIParams(BaseModel):
    ei: float  # 初始电位
    ef: float  # 最终电位
    incre: float  # 电位增量
    amp: float  # 交流振幅
    freq: float  # 交流频率
    quiet: Optional[float] = 2.0  # 静息时间
    sens: Optional[float] = 1e-5  # 灵敏度
    file_name: Optional[str] = None

class CAAPIParams(BaseModel):
    ei: float  # 初始电位
    eh: float  # 高电位
    el: float  # 低电位
    cl: int  # 阶跃数
    pw: float  # 脉冲宽度
    si: float  # 采样间隔
    sens: Optional[float] = 1e-5  # 灵敏度
    qt: Optional[float] = 2.0  # 静置时间
    pn: Optional[str] = 'p'  # 初始极性
    file_name: Optional[str] = None  # 文件名
    autosens: Optional[bool] = False  # 是否自动灵敏度

class CVAPIParams(BaseModel):
    ei: float  # 初始电位
    eh: float  # 高电位
    el: float  # 低电位
    v: float  # 扫描速率
    si: float  # 采样间隔
    cl: int  # 循环次数
    sens: Optional[float] = 1e-5  # 灵敏度
    qt: Optional[float] = 2.0  # 静置时间
    pn: Optional[str] = 'p'  # 初始扫描方向
    file_name: Optional[str] = None  # 文件名
    autosens: Optional[bool] = False  # 是否自动灵敏度

class ITAPIParams(BaseModel):
    ei: float  # 恒定电位
    st: float  # 总采样时间
    si: float  # 采样间隔
    sens: Optional[float] = 1e-5  # 灵敏度
    file_name: Optional[str] = None  # 文件名

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

# 添加CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局变量
broadcaster = Broadcaster()
config = {
    "moonraker_addr": "http://192.168.51.168:7125",
    "results_dir": "./experiment_results",
    "chi_path": "C:/CHI760E/chi760e/chi760e.exe"  # 默认CHI路径
}
devices = {
    "printer": None,  # PrinterAdapter
    "pump": None,     # PumpAdapter
    "relay": None,    # RelayAdapter
    "chi": None       # CHIAdapter
}
# WebSocket监听器实例
moonraker_listener = None

# 确保结果目录存在
os.makedirs(config["results_dir"], exist_ok=True)

# HTML前端
@app.get("/", response_class=HTMLResponse)
async def get_html():
    try:
        html_path = Path(__file__).parent.absolute() / "device_tester.html"
        if html_path.exists():
            with open(html_path, "r", encoding="utf-8") as f:
                html = f.read()
            return HTMLResponse(content=html)
        else:
            logger.error(f"HTML文件不存在: {html_path}")
            return HTMLResponse(content=f"<html><body><h1>错误: HTML文件不存在</h1><p>{html_path}</p></body></html>")
    except Exception as e:
        logger.error(f"读取HTML文件失败: {e}")
        return HTMLResponse(content=f"<html><body><h1>错误: {str(e)}</h1></body></html>")

# WebSocket连接
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info(f"WebSocket连接已建立: {websocket.client}")
    await broadcaster.connect(websocket)
    try:
        while True:
            # 心跳检测
            await websocket.receive_text()
            await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        logger.info(f"WebSocket断开连接: {websocket.client}")
        await broadcaster.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket错误: {e}")
        try:
            await broadcaster.disconnect(websocket)
        except:
            pass

# 获取配置
@app.get("/api/config")
async def get_config():
    return config

# 保存配置
@app.post("/api/config")
async def save_config(new_config: Dict[str, str]):
    global config, moonraker_listener
    
    # 记录原始Moonraker地址，用于检查是否需要重新初始化监听器
    old_moonraker_addr = config.get("moonraker_addr")
    
    # 验证配置
    if "moonraker_addr" in new_config:
        config["moonraker_addr"] = new_config["moonraker_addr"]
    
    if "results_dir" in new_config:
        results_dir = new_config["results_dir"]
        try:
            os.makedirs(results_dir, exist_ok=True)
            config["results_dir"] = results_dir
        except Exception as e:
            return {"error": True, "message": f"创建结果目录失败: {e}"}
    
    if "chi_path" in new_config:
        config["chi_path"] = new_config["chi_path"]
    
    # 保存配置到文件
    try:
        with open("device_config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"保存配置到文件失败: {e}")
    
    # 如果Moonraker地址变更，重新初始化WebSocket监听器
    if old_moonraker_addr != config.get("moonraker_addr") and MoonrakerWebsocketListener is not None:
        if moonraker_listener:
            # 停止旧的监听器
            asyncio.create_task(moonraker_listener.stop())
        
        # 创建新的WebSocket监听器URL
        ws_url = _get_websocket_url_from_http(config["moonraker_addr"])
        if ws_url:
            # 创建并启动新的监听器
            moonraker_listener = MoonrakerWebsocketListener(ws_url)
            asyncio.create_task(moonraker_listener.start())
            logger.info(f"已重新初始化WebSocket监听器，连接到: {ws_url}")
    
    return {"error": False, "message": "配置已保存"}

# 辅助函数：从HTTP地址获取WebSocket URL
def _get_websocket_url_from_http(http_url: str) -> str:
    """从HTTP URL构建WebSocket URL

    Args:
        http_url: Moonraker HTTP URL，例如 "http://192.168.1.100:7125"

    Returns:
        str: WebSocket URL，例如 "ws://192.168.1.100:7125/websocket"
    """
    if not http_url:
        return None
    
    try:
        # 替换协议
        if http_url.startswith("https://"):
            ws_url = "wss://" + http_url[8:]
        elif http_url.startswith("http://"):
            ws_url = "ws://" + http_url[7:]
        else:
            # 假设是裸IP或主机名
            ws_url = "ws://" + http_url
        
        # 确保URL末尾没有斜杠
        ws_url = ws_url.rstrip("/")
        
        # 添加WebSocket路径
        ws_url += "/websocket"
        
        return ws_url
    except Exception as e:
        logger.error(f"构建WebSocket URL时出错: {e}")
        return None

# 添加辅助函数检查CHI是否已初始化
def is_chi_initialized():
    """检查CHI适配器是否已正确初始化
    
    Returns:
        bool: 是否已初始化
    """
    return devices["chi"] is not None and hasattr(devices["chi"], "chi_setup") and devices["chi"].chi_setup is not None

@app.get("/api/status")
async def get_status():
    """获取所有设备状态"""
    return {
        "chi": {"initialized": devices["chi"] is not None and is_chi_initialized()},
        "printer": {"initialized": devices["printer"] is not None and devices["printer"].initialized},
        "pump": {"initialized": devices["pump"] is not None and devices["pump"].initialized},
        "relay": {"initialized": devices["relay"] is not None and devices["relay"].initialized}
    }

# =========== 打印机API ===========

# 初始化打印机
@app.post("/api/printer/initialize")
async def initialize_printer():
    global devices
    
    # 如果已经初始化，先关闭之前的实例
    if devices["printer"] is not None:
        await devices["printer"].close()
    
    try:
        devices["printer"] = PrinterAdapter(
            moonraker_addr=config["moonraker_addr"],
            broadcaster=broadcaster
        )
        await devices["printer"].initialize()
        return {"error": False, "message": "打印机已初始化"}
    except Exception as e:
        logger.error(f"初始化打印机失败: {e}")
        return {"error": True, "message": f"初始化打印机失败: {e}"}

# 移动打印机
@app.post("/api/printer/move")
async def move_printer(position: Dict[str, float]):
    if devices["printer"] is None or not devices["printer"].initialized:
        return {"error": True, "message": "打印机未初始化"}
    
    try:
        x = position.get("x", None)
        y = position.get("y", None)
        z = position.get("z", None)
        
        await devices["printer"].move_to(x=x, y=y, z=z)
        return {"error": False, "message": f"打印机正在移动到 X={x}, Y={y}, Z={z}"}
    except Exception as e:
        logger.error(f"移动打印机失败: {e}")
        return {"error": True, "message": f"移动打印机失败: {e}"}

# 移动到网格位置
@app.post("/api/printer/grid")
async def move_to_grid(data: Dict[str, int]):
    if devices["printer"] is None or not devices["printer"].initialized:
        return {"error": True, "message": "打印机未初始化"}
    
    try:
        position = data.get("position", 1)
        
        await devices["printer"].move_to_grid(position)
        return {"error": False, "message": f"打印机正在移动到网格位置 {position}"}
    except Exception as e:
        logger.error(f"移动到网格位置失败: {e}")
        return {"error": True, "message": f"移动到网格位置失败: {e}"}

# 归位打印机
@app.post("/api/printer/home")
async def home_printer():
    if devices["printer"] is None or not devices["printer"].initialized:
        return {"error": True, "message": "打印机未初始化"}
    
    try:
        await devices["printer"].home()
        return {"error": False, "message": "打印机正在归位"}
    except Exception as e:
        logger.error(f"归位打印机失败: {e}")
        return {"error": True, "message": f"归位打印机失败: {e}"}

# 获取打印机位置
@app.get("/api/printer/position")
async def get_printer_position():
    if devices["printer"] is None or not devices["printer"].initialized:
        return {"error": True, "message": "打印机未初始化"}
    
    try:
        position = await devices["printer"].get_position()
        return {"error": False, "position": position}
    except Exception as e:
        logger.error(f"获取打印机位置失败: {e}")
        return {"error": True, "message": f"获取打印机位置失败: {e}"}

# 获取打印机详细信息（包括网格配置）
@app.get("/api/printer/info", response_model=PrinterInfoResponse)
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

# =========== 泵API ===========

# 初始化泵
@app.post("/api/pump/initialize")
async def initialize_pump():
    global devices, moonraker_listener
    
    # 如果已经初始化，先关闭之前的实例
    if devices["pump"] is not None:
        await devices["pump"].close()
    
    try:
        # 初始化WebSocket监听器（如果尚未初始化）
        if moonraker_listener is None and MoonrakerWebsocketListener is not None:
            ws_url = _get_websocket_url_from_http(config["moonraker_addr"])
            if ws_url:
                moonraker_listener = MoonrakerWebsocketListener(ws_url)
                asyncio.create_task(moonraker_listener.start())
                logger.info(f"已初始化WebSocket监听器，连接到: {ws_url}")
        
        # 创建新的泵适配器实例，传入WebSocket监听器
        devices["pump"] = PumpAdapter(
            moonraker_addr=config["moonraker_addr"],
            broadcaster=broadcaster,
            ws_listener=moonraker_listener
        )
        await devices["pump"].initialize()
        return {"error": False, "message": "泵已初始化"}
    except Exception as e:
        logger.error(f"初始化泵失败: {e}")
        return {"error": True, "message": f"初始化泵失败: {e}"}

# 自动泵送
@app.post("/api/pump/dispense_auto")
async def dispense_auto(data: Dict[str, Any]):
    if devices["pump"] is None or not devices["pump"].initialized:
        return {"error": True, "message": "泵未初始化"}
    
    try:
        pump_index = int(data.get("pump_index", 0))
        volume = float(data.get("volume", 100))
        speed = data.get("speed", "medium")
        direction = int(data.get("direction", 1))
        
        # 速度转换
        speed_map = {"slow": "slow", "medium": "normal", "fast": "fast"}
        speed_value = speed_map.get(speed, "normal")
        
        await devices["pump"].dispense_auto(
            pump_index=pump_index,
            volume=volume,
            speed=speed_value,
            direction=direction
        )
        return {"error": False, "message": f"泵 {pump_index} 正在自动泵送 {volume} μL"}
    except Exception as e:
        logger.error(f"自动泵送失败: {e}")
        return {"error": True, "message": f"自动泵送失败: {e}"}

# 定时泵送
@app.post("/api/pump/dispense_timed")
async def dispense_timed(data: Dict[str, Any]):
    if devices["pump"] is None or not devices["pump"].initialized:
        return {"error": True, "message": "泵未初始化"}
    
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
        return {"error": False, "message": f"泵 {pump_index} 正在以 {rpm} RPM 的速度定时泵送 {duration} 秒"}
    except Exception as e:
        logger.error(f"定时泵送失败: {e}")
        return {"error": True, "message": f"定时泵送失败: {e}"}

# 停止泵
@app.post("/api/pump/stop")
async def stop_pump(data: Dict[str, int]):
    if devices["pump"] is None or not devices["pump"].initialized:
        return {"error": True, "message": "泵未初始化"}
    
    try:
        pump_index = data.get("pump_index", 0)
        
        await devices["pump"].stop(pump_index)
        return {"error": False, "message": f"泵 {pump_index} 已停止"}
    except Exception as e:
        logger.error(f"停止泵失败: {e}")
        return {"error": True, "message": f"停止泵失败: {e}"}

# 获取泵状态
@app.get("/api/pump/status")
async def get_pump_status(pump_index: int = 0):
    if devices["pump"] is None or not devices["pump"].initialized:
        return {"error": True, "message": "泵未初始化"}
    
    try:
        status = await devices["pump"].get_status(pump_index)
        return {"error": False, "status": status}
    except Exception as e:
        logger.error(f"获取泵状态失败: {e}")
        return {"error": True, "message": f"获取泵状态失败: {e}"}

# =========== 继电器API ===========

# 初始化继电器
@app.post("/api/relay/initialize")
async def initialize_relay():
    global devices
    
    # 如果已经初始化，先关闭之前的实例
    if devices["relay"] is not None:
        await devices["relay"].close()
    
    try:
        devices["relay"] = RelayAdapter(
            moonraker_addr=config["moonraker_addr"],
            broadcaster=broadcaster
        )
        await devices["relay"].initialize()
        return {"error": False, "message": "继电器已初始化"}
    except Exception as e:
        logger.error(f"初始化继电器失败: {e}")
        return {"error": True, "message": f"初始化继电器失败: {e}"}

# 切换继电器
@app.post("/api/relay/toggle")
async def toggle_relay(data: Dict[str, Any]):
    if devices["relay"] is None or not devices["relay"].initialized:
        return {"error": True, "message": "继电器未初始化"}
    
    try:
        relay_id = int(data.get("relay_id", 1))
        state = data.get("state", None)
        
        await devices["relay"].toggle(relay_id, state)
        return {"error": False, "message": f"继电器 {relay_id} 已切换"}
    except Exception as e:
        logger.error(f"切换继电器失败: {e}")
        return {"error": True, "message": f"切换继电器失败: {e}"}

# 获取继电器状态
@app.get("/api/relay/status")
async def get_relay_status():
    if devices["relay"] is None or not devices["relay"].initialized:
        return {"error": True, "message": "继电器未初始化"}
    
    try:
        # 获取继电器状态字典
        states_dict = await devices["relay"].get_status()
        
        # 转换布尔值为字符串格式，使前端更容易解析
        formatted_states = {}
        for key, value in states_dict.items():
            formatted_states[str(key)] = "on" if value else "off"
        
        logger.info(f"继电器状态: {formatted_states}")
        return {"error": False, "states": formatted_states}
    except Exception as e:
        logger.error(f"获取继电器状态失败: {e}")
        return {"error": True, "message": f"获取继电器状态失败: {e}"}

# =========== CHI API ===========

# 当前CHI测试状态
chi_test_state = {
    "status": "idle",      # idle, initializing, running, completed, error
    "test_type": None,     # CV, CA, EIS, etc.
    "start_time": None,
    "progress": 0.0,       # 0.0 - 1.0
    "elapsed_time": 0,
    "result_file": None
}

# CHI测试调用锁定
chi_test_lock = asyncio.Lock()

# 初始化CHI工作站
@app.post("/api/chi/initialize")
async def initialize_chi():
    global devices
    
    # 如果已经初始化，先关闭之前的实例
    if devices["chi"] is not None:
        await devices["chi"].close()
    
    try:
        # 修改：使用从backend.services.adapters.chi_adapter导入的CHIAdapter类
        # 并确保参数符合backend.services.adapters.chi_adapter.CHIAdapter的__init__方法
        devices["chi"] = CHIAdapter(
            broadcaster=broadcaster,
            results_base_dir=config["results_dir"],  # 注意：改为results_base_dir（与导入的CHIAdapter参数名一致）
            chi_path=config["chi_path"]
        )
        await devices["chi"].initialize()
        return {"error": False, "message": "CHI工作站已初始化"}
    except Exception as e:
        logger.error(f"初始化CHI工作站失败: {e}")
        return {"error": True, "message": f"初始化CHI工作站失败: {e}"}

# 运行CV测试
@app.post("/api/chi/cv")
async def run_cv_test(payload: CVAPIParams, background_tasks: BackgroundTasks):
    if devices["chi"] is None or not is_chi_initialized():
        return {"error": True, "message": "CHI未初始化"}
    
    try:
        # 提取文件名
        file_name = payload.file_name or f"CV_{int(time.time())}"
        
        # 创建参数字典
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
        
        # 后台运行测试
        background_tasks.add_task(devices["chi"].run_cv_test, file_name=file_name, params=params)
        
        logger.info(f"CV测试已在后台启动: {file_name}")
        return {"error": False, "message": f"CV测试已在后台启动", "file_name": file_name}
    except Exception as e:
        logger.error(f"运行CV测试失败: {e}")
        return {"error": True, "message": f"运行CV测试失败: {e}"}

# 运行CA测试
@app.post("/api/chi/ca")
async def run_ca_test(payload: CAAPIParams, background_tasks: BackgroundTasks):
    if devices["chi"] is None or not is_chi_initialized():
        return {"error": True, "message": "CHI工作站未初始化"}
    
    try:
        # 提取文件名，从数据中移除
        file_name = payload.file_name or f"CA_{int(time.time())}"
        
        # 创建参数字典
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
        
        # 后台运行测试
        background_tasks.add_task(devices["chi"].run_ca_test, file_name=file_name, params=params)
        
        logger.info(f"CA测试已在后台启动: {file_name}")
        return {"error": False, "message": f"CA测试已在后台启动", "file_name": file_name}
    except Exception as e:
        logger.error(f"运行CA测试失败: {e}")
        return {"error": True, "message": f"运行CA测试失败: {e}"}

# 运行EIS测试
@app.post("/api/chi/eis")
async def run_eis_test(data: Dict[str, Any], background_tasks: BackgroundTasks):
    if devices["chi"] is None or not is_chi_initialized():
        return {"error": True, "message": "CHI工作站未初始化"}
    
    try:
        # 提取文件名，从数据中移除
        file_name = data.pop("file_name", f"EIS_{int(time.time())}")
        
        # 创建参数字典，与backend.services.adapters.chi_adapter.run_eis_test方法所需参数一致
        params = {
            "ei": float(data.get("voltage", 0)),            # 直流电位
            "fl": float(data.get("freq_final", 0.1)),       # 低频（结束频率）
            "fh": float(data.get("freq_init", 100000)),     # 高频（起始频率）
            "amp": float(data.get("amplitude", 10)),        # 交流振幅
            "sens": float(data.get("sens", 1e-5)),          # 灵敏度
            "impautosens": bool(data.get("impautosens", True))  # 自动灵敏度
        }
        
        # 获取模式参数，默认为'impsf'
        mode = data.get("mode", "impsf")
        if mode in ["impsf", "impft"]:
            params["mode"] = mode
        
        # 后台运行测试
        background_tasks.add_task(devices["chi"].run_eis_test, file_name=file_name, params=params)
        
        logger.info(f"EIS测试已在后台启动: {file_name}")
        return {"error": False, "message": f"EIS测试已在后台启动", "file_name": file_name}
    except Exception as e:
        logger.error(f"运行EIS测试失败: {e}")
        return {"error": True, "message": f"运行EIS测试失败: {e}"}

# 运行LSV测试
@app.post("/api/chi/lsv")
async def run_lsv_test(data: Dict[str, Any], background_tasks: BackgroundTasks):
    if devices["chi"] is None or not is_chi_initialized():
        return {"error": True, "message": "CHI未初始化"}
    
    try:
        # 提取文件名，从数据中移除
        file_name = data.pop("file_name", f"LSV_{int(time.time())}")
        
        # 创建参数字典，与backend.services.adapters.chi_adapter.run_lsv_test方法所需参数一致
        params = {
            "ei": float(data.get("initial_v", -0.5)),    # 初始电位
            "ef": float(data.get("final_v", 0.5)),       # 最终电位
            "v": float(data.get("scan_rate", 0.1)),      # 扫描速率
            "si": float(data.get("interval", 0.001)),    # 采样间隔
            "sens": float(data.get("sens", 1e-5))        # 灵敏度
        }
        
        # 后台运行测试
        background_tasks.add_task(devices["chi"].run_lsv_test, file_name=file_name, params=params)
        
        logger.info(f"LSV测试已在后台启动: {file_name}")
        return {"error": False, "message": f"LSV测试已在后台启动", "file_name": file_name}
    except Exception as e:
        logger.error(f"运行LSV测试失败: {e}")
        return {"error": True, "message": f"运行LSV测试失败: {e}"}

# 运行IT测试
@app.post("/api/chi/it")
async def run_it_test(payload: ITAPIParams, background_tasks: BackgroundTasks):
    if devices["chi"] is None or not is_chi_initialized():
        logger.error("CHI未初始化，无法运行i-t测试")
        raise HTTPException(status_code=503, detail="CHI设备未初始化")
    
    try:
        # 确定要传递给适配器的文件名
        effective_file_name = payload.file_name if payload.file_name is not None else f'IT_{int(time.time())}'
        
        # 创建参数字典，与backend.services.adapters.chi_adapter.run_it_test方法所需参数一致
        params = {
            "ei": payload.ei,     # 恒定电位
            "si": payload.si,     # 采样间隔
            "st": payload.st,     # 总采样时间
            "sens": payload.sens  # 灵敏度
        }
        
        # 记录完整参数信息，便于调试
        logger.info(f"i-t测试参数: {params}")
        
        # 后台运行测试
        background_tasks.add_task(devices["chi"].run_it_test, file_name=effective_file_name, params=params)
        
        logger.info(f"i-t测试已在后台启动: {effective_file_name}")
        return {"error": False, "message": "i-t测试已在后台启动", "file_name": effective_file_name}
    except Exception as e:
        logger.error(f"运行i-t测试失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"运行i-t测试失败: {str(e)}")

# 运行OCP测试
@app.post("/api/chi/ocp")
async def run_ocp_test_endpoint(payload: OCPAPIParams, background_tasks: BackgroundTasks):
    if devices["chi"] is None or not is_chi_initialized():
        logger.error("CHI未初始化，无法运行OCP测试")
        raise HTTPException(status_code=503, detail="CHI设备未初始化")

    try:
        # 确定要传递给适配器的文件名
        effective_file_name = payload.file_name if payload.file_name is not None else 'OCP'
        
        # 创建参数字典，与backend.services.adapters.chi_adapter.run_ocp_test方法所需参数一致
        params = {
            "st": payload.st,  # 运行时间 (必需)
            "si": payload.si,  # 采样间隔 (必需)
        }
        # 只有当提供了eh和el参数时才添加到params字典中
        if payload.eh is not None:
            params["eh"] = payload.eh
        if payload.el is not None:
            params["el"] = payload.el
        
        # 在后台运行测试
        background_tasks.add_task(
            devices["chi"].run_ocp_test, 
            file_name=effective_file_name, 
            params=params
        )
        
        logger.info(f"OCP测试已在后台启动: {effective_file_name}")
        return {"error": False, "message": "OCP测试已在后台启动", "file_name": effective_file_name}
    except Exception as e:
        logger.error(f"运行OCP测试失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"运行OCP测试失败: {str(e)}")

# 运行DPV测试
@app.post("/api/chi/dpv")
async def run_dpv_test_endpoint(payload: DPVAPIParams, background_tasks: BackgroundTasks):
    if devices["chi"] is None or not is_chi_initialized():
        logger.error("CHI未初始化，无法运行DPV测试")
        raise HTTPException(status_code=503, detail="CHI设备未初始化")

    try:
        # 确定要传递给适配器的文件名
        effective_file_name = payload.file_name if payload.file_name is not None else f'DPV_{int(time.time())}'
        
        # 创建参数字典
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
        # 只有当未使用autosens且提供了sens参数时才添加sens
        if not payload.autosens and payload.sens is not None:
            params["sens"] = payload.sens
        
        # 在后台运行测试
        background_tasks.add_task(
            devices["chi"].run_dpv_test, 
            file_name=effective_file_name, 
            params=params
        )
        
        logger.info(f"DPV测试已在后台启动: {effective_file_name}")
        return {"error": False, "message": "DPV测试已在后台启动", "file_name": effective_file_name}
    except Exception as e:
        logger.error(f"运行DPV测试失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"运行DPV测试失败: {str(e)}")

# 运行SCV测试
@app.post("/api/chi/scv")
async def run_scv_test_endpoint(payload: SCVAPIParams, background_tasks: BackgroundTasks):
    if devices["chi"] is None or not is_chi_initialized():
        logger.error("CHI未初始化，无法运行SCV测试")
        raise HTTPException(status_code=503, detail="CHI设备未初始化")

    try:
        # 确定要传递给适配器的文件名
        effective_file_name = payload.file_name if payload.file_name is not None else f'SCV_{int(time.time())}'
        
        # 创建参数字典
        params = {
            "ei": payload.ei,
            "ef": payload.ef,
            "incre": payload.incre,
            "sw": payload.sw,
            "prod": payload.prod,
            "qt": payload.qt,
            "autosens": payload.autosens
        }
        # 只有当未使用autosens且提供了sens参数时才添加sens
        if not payload.autosens and payload.sens is not None:
            params["sens"] = payload.sens
        
        # 在后台运行测试
        background_tasks.add_task(
            devices["chi"].run_scv_test, 
            file_name=effective_file_name, 
            params=params
        )
        
        logger.info(f"SCV测试已在后台启动: {effective_file_name}")
        return {"error": False, "message": "SCV测试已在后台启动", "file_name": effective_file_name}
    except Exception as e:
        logger.error(f"运行SCV测试失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"运行SCV测试失败: {str(e)}")

# 运行CP测试
@app.post("/api/chi/cp")
async def run_cp_test_endpoint(params: CPAPIParams):
    """运行计时电位法测试 (CP)"""
    try:
        # 记录请求
        logging.info(f"接收到CP测试请求: {params.dict()}")
        
        # 提取文件名或创建默认文件名
        file_name = params.file_name or f"CP_Test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 调用适配器运行CP测试
        result = await devices["chi"].run_cp_test(file_name, params.dict())
        
        if result:
            return {"error": False, "message": "CP测试已启动", "file_name": file_name}
        else:
            return {"error": True, "message": "CP测试启动失败"}
    
    except Exception as e:
        logging.exception("CP测试请求处理失败")
        return {"error": True, "message": f"处理CP测试请求时出错: {str(e)}"}

# 运行ACV测试
@app.post("/api/chi/acv")
async def run_acv_test_endpoint(params: ACVAPIParams):
    """运行交流伏安法测试 (ACV)"""
    try:
        # 记录请求
        logging.info(f"接收到ACV测试请求: {params.dict()}")
        
        # 提取文件名或创建默认文件名
        file_name = params.file_name or f"ACV_Test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 调用适配器运行ACV测试
        result = await devices["chi"].run_acv_test(file_name, params.dict())
        
        if result:
            return {"error": False, "message": "ACV测试已启动", "file_name": file_name}
        else:
            return {"error": True, "message": "ACV测试启动失败"}
    
    except Exception as e:
        logging.exception("ACV测试请求处理失败")
        return {"error": True, "message": f"处理ACV测试请求时出错: {str(e)}"}

# 停止CHI测试
@app.post("/api/chi/stop")
async def stop_chi_test():
    if devices["chi"] is None or not is_chi_initialized():
        return {"error": True, "message": "CHI工作站未初始化"}
    
    try:
        # 调用CHI停止方法
        await devices["chi"].stop_test()
        
        return {"error": False, "message": "CHI测试已停止"}
    except Exception as e:
        logger.error(f"停止CHI测试失败: {e}")
        return {"error": True, "message": f"停止CHI测试失败: {e}"}

# 获取CHI测试状态
@app.get("/api/chi/status")
async def get_chi_status():
    if devices["chi"] is None or not is_chi_initialized():
        return {"error": True, "message": "CHI工作站未初始化"}
    
    try:
        # 调用CHI状态方法
        status = await devices["chi"].get_status()
        return {"error": False, "status": status}
    except Exception as e:
        logger.error(f"获取CHI状态失败: {e}")
        return {"error": True, "message": f"获取CHI状态失败: {e}"}

# 获取CHI测试结果列表
@app.get("/api/chi/results")
async def get_chi_results():
    if devices["chi"] is None or not is_chi_initialized():
        return {"error": True, "message": "CHI工作站未初始化"}
    
    try:
        # 调用CHI获取结果方法
        results = await devices["chi"].get_results()
        return {"error": False, "results": results}
    except Exception as e:
        logger.error(f"获取CHI测试结果列表失败: {e}")
        return {"error": True, "message": f"获取CHI测试结果列表失败: {e}"}

# 下载CHI测试结果文件
@app.get("/api/chi/download")
async def download_chi_result(file: str):
    try:
        file_path = Path(file)
        
        # 安全检查：确保文件位于结果目录内
        if not str(file_path).startswith(config["results_dir"]):
            return {"error": True, "message": "文件路径无效"}
        
        if not file_path.exists():
            return {"error": True, "message": "文件不存在"}
        
        return FileResponse(
            path=file_path,
            filename=file_path.name,
            media_type="text/plain"
        )
    except Exception as e:
        logger.error(f"下载CHI测试结果文件失败: {e}")
        return {"error": True, "message": f"下载CHI测试结果文件失败: {e}"}

# =========== 辅助函数 ===========

# 后台运行CHI测试
async def run_chi_test_background(test_type, **kwargs):
    try:
        # 更新状态为运行中
        chi_test_state["status"] = "running"
        
        # 根据测试类型调用不同的方法
        result_file = None
        if test_type == "cv":
            # 调用CV测试
            result_file = await devices["chi"].run_cv_test(**kwargs)
            
            # 发送进度更新 - 这里简单模拟进度
            for i in range(1, 101):
                if chi_test_state["status"] != "running":
                    break  # 测试已被停止
                
                chi_test_state["progress"] = i / 100.0
                
                # 模拟测试耗时，根据循环次数调整
                cycle_time = 5 * kwargs.get("cycles", 3)
                await asyncio.sleep(cycle_time / 100)
        
        elif test_type == "ca":
            # 调用CA测试
            result_file = await devices["chi"].run_ca_test(**kwargs)
            
            # 发送进度更新 - 这里使用测试时间来计算进度
            test_time = kwargs.get("time", 10)
            start_time = time.time()
            
            while time.time() - start_time < test_time:
                if chi_test_state["status"] != "running":
                    break  # 测试已被停止
                
                elapsed = time.time() - start_time
                progress = min(elapsed / test_time, 1.0)
                chi_test_state["progress"] = progress
                
                await asyncio.sleep(0.5)
        
        elif test_type == "eis":
            # 调用EIS测试
            result_file = await devices["chi"].run_eis_test(**kwargs)
            
            # 发送进度更新 - EIS测试可能需要较长时间，这里模拟进度
            estimated_time = 60  # 估计60秒完成
            start_time = time.time()
            
            while time.time() - start_time < estimated_time:
                if chi_test_state["status"] != "running":
                    break  # 测试已被停止
                
                elapsed = time.time() - start_time
                progress = min(elapsed / estimated_time, 1.0)
                chi_test_state["progress"] = progress
                
                await asyncio.sleep(1)
        
        # 测试完成，更新状态
        if chi_test_state["status"] == "running":  # 只有当测试仍在运行时才更新为完成状态
            chi_test_state.update({
                "status": "completed",
                "progress": 1.0,
                "result_file": result_file
            })
    
    except Exception as e:
        # 测试出错，更新状态
        logger.error(f"CHI测试出错: {e}")
        chi_test_state.update({
            "status": "error",
            "progress": 0.0
        })

# 获取CHI文件类型
def get_chi_file_type(filename):
    """根据文件名推断CHI测试类型"""
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
        return "未知"

# 启动时加载配置
def load_config():
    global config
    try:
        if os.path.exists("device_config.json"):
            with open("device_config.json", "r", encoding="utf-8") as f:
                loaded_config = json.load(f)
                config.update(loaded_config)
            logger.info("已加载配置文件")
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")

# 辅助器类实现
class PrinterAdapter:
    def __init__(self, moonraker_addr, broadcaster):
        try:
            from device_control.control_printer import PrinterControl
            self.printer = PrinterControl(ip=moonraker_addr.split("//")[1].split(":")[0])
            self.broadcaster = broadcaster
            self.initialized = False
            self.position = {"x": 0, "y": 0, "z": 0}
            logger.info(f"打印机适配器已创建，连接到 {moonraker_addr}")
        except Exception as e:
            logger.error(f"初始化打印机适配器失败: {e}")
            self.printer = None
            self.broadcaster = broadcaster
            self.initialized = False
            self.position = {"x": 0, "y": 0, "z": 0}
        
    async def initialize(self):
        # 初始化打印机
        try:
            if self.printer is None:
                raise ValueError("打印机控制器初始化失败")
                
            self.initialized = True
            position = self.printer.get_current_position()
            if position:
                self.position = {"x": position[0], "y": position[1], "z": position[2]}
            await self.broadcast_status()
            logger.info("打印机初始化成功")
            return True
        except Exception as e:
            logger.error(f"打印机初始化失败: {e}")
            self.initialized = False
            await self.broadcast_status()
            raise
        
    async def close(self):
        self.initialized = False
        
    async def move_to(self, x, y, z):
        if not self.initialized:
            raise ValueError("打印机未初始化")
        
        # 移动打印机
        result = self.printer.move_to(x, y, z)
        
        # 更新位置
        position = self.printer.get_current_position()
        if position:
            self.position = {"x": position[0], "y": position[1], "z": position[2]}
        
        await self.broadcast_status()
        return result
    
    async def move_to_grid(self, position):
        if not self.initialized:
            raise ValueError("打印机未初始化")
        
        # 移动打印机到网格位置
        result = self.printer.move_to_grid_position(position)
        
        # 更新位置
        printer_position = self.printer.get_current_position()
        if printer_position:
            self.position = {"x": printer_position[0], "y": printer_position[1], "z": printer_position[2]}
        
        await self.broadcast_status()
        return result
    
    async def home(self):
        if not self.initialized:
            raise ValueError("打印机未初始化")
        
        # 归位打印机
        result = self.printer.home()
        
        # 更新位置
        position = self.printer.get_current_position()
        if position:
            self.position = {"x": position[0], "y": position[1], "z": position[2]}
        
        await self.broadcast_status()
        return result
    
    async def get_position(self):
        if not self.initialized:
            raise ValueError("打印机未初始化")
        
        position = self.printer.get_current_position()
        if position:
            self.position = {"x": position[0], "y": position[1], "z": position[2]}
        
        return self.position
    
    async def broadcast_status(self):
        await self.broadcaster.broadcast({
            "type": "printer_status",
            "position": self.position,
            "initialized": self.initialized
        })

class PumpAdapter:
    def __init__(self, moonraker_addr, broadcaster, ws_listener=None):
        from core_api.pump_proxy import PumpProxy  # 正确导入PumpProxy
        
        # 传入WebSocket监听器实例
        self.pump_proxy = PumpProxy(moonraker_addr, listener=ws_listener)
        self.broadcaster = broadcaster
        self.initialized = False
        self.status = {
            "running": False,
            "pump_index": 0,
            "volume": 0,        # 原始请求的体积 (μL)
            "progress": 0,
            "direction": 1,
            "elapsed_time_seconds": 0,
            "total_duration_seconds": 0, # 预估的总时长 (将从PumpProxy获取)
            "rpm": None,                 # 从PumpProxy获取的RPM (解析或估算)
            "revolutions": None,         # 从PumpProxy获取的圈数 (解析或估算)
            "raw_response": None         # Moonraker的原始响应日志 (可选)
        }
        self._stop_event = False  # 用于控制进度监控循环的标志
        
    async def initialize(self):
        self.initialized = True
        # 在初始化时广播一个干净的状态
        self.status = {
            "running": False, "pump_index": 0, "volume": 0, "progress": 0, "direction": 1,
            "elapsed_time_seconds": 0, "total_duration_seconds": 0, 
            "rpm": None, "revolutions": None, "raw_response": None
        }
        await self.broadcast_status()
        return True
        
    async def close(self):
        self.initialized = False
        self._stop_event = True  # 确保在关闭时停止所有进度监控任务
        current_pump_index = self.status.get("pump_index", 0)
        # 广播泵已停止的状态
        self.status.update({"running": False, "progress": self.status.get("progress",0)}) # 保留进度
        await self.broadcast_status()
        
    async def dispense_auto(self, pump_index, volume, speed, direction=1):
        if not self.initialized:
            logger.error("PumpAdapter未初始化，无法执行dispense_auto")
            raise ValueError("泵未初始化")
        
        self._stop_event = False # 重置停止标志
        
        # 记录API调用开始时间点
        api_call_start_time = time.time()
        
        # 更新初始状态，标记为运行中，但总时长等信息待定
        self.status = {
            "running": True,
            "pump_index": pump_index,
            "volume": volume, # μL
            "progress": 0,
            "direction": direction,
            "elapsed_time_seconds": 0, # 泵送操作的已过时间，初始为0
            "total_duration_seconds": 0, # 预期总时长，稍后从proxy获取
            "rpm": None,
            "revolutions": None,
            "raw_response": "正在请求泵服务..."
        }
        await self.broadcast_status() # 立即广播，让前端知道操作已开始

        try:
            # 调用泵代理 (volume转换为ml)
            proxy_response = await self.pump_proxy.dispense_auto(
                volume_ml=(volume / 1000.0), 
                speed=speed, 
                direction=direction
            )
            
            # 计算API调用和参数获取所花费的时间
            command_send_and_param_fetch_duration = time.time() - api_call_start_time
            logger.info(f"从发送命令到获取参数用时: {command_send_and_param_fetch_duration:.2f}秒")
            
            if not proxy_response.get("success", False):
                logger.error(f"泵 {pump_index} dispense_auto 指令发送失败或PumpProxy内部错误。")
                self.status.update({
                    "running": False, 
                    "raw_response": proxy_response.get("raw_response", "指令发送失败")
                })
                await self.broadcast_status()
                return False

            # 从proxy_response更新状态
            actual_pump_duration = proxy_response.get("estimated_duration", 0) # 这是物理泵送的预期总时长
            self.status["rpm"] = proxy_response.get("rpm")
            self.status["revolutions"] = proxy_response.get("revolutions")
            self.status["total_duration_seconds"] = actual_pump_duration # UI显示的总时长
            self.status["elapsed_time_seconds"] = 0 # 泵送操作的已过时间，从0开始计数
            self.status["raw_response"] = proxy_response.get("raw_response", "")
            
            source = proxy_response.get("source", "unknown")
            logger.info(f"泵 {pump_index} dispense_auto: 数据来源={source}, "
                        f"RPM={self.status['rpm']}, 圈数={self.status['revolutions']}, "
                        f"实际泵送时长={actual_pump_duration:.2f}s")

            if actual_pump_duration > 0:
                await self.broadcast_status() # 再次广播，包含正确的总时长和初始为0的已过时间
                # 启动进度监控，监控物理泵送操作
                asyncio.create_task(self._monitor_pump_progress(
                    total_duration_seconds_to_monitor=actual_pump_duration, # 监控循环运行这么久
                    initial_elapsed_for_progress_calc=0,                    # 进度计算的初始耗时为0
                    total_estimated_for_progress_calc=actual_pump_duration  # 进度是相对于这个总时长计算的
                ))
                return True
            else:
                logger.error(f"泵 {pump_index} dispense_auto 未能获取有效的预估时长 "
                              f"(actual_pump_duration: {actual_pump_duration})。泵送可能已开始，但进度无法显示。")
                self.status["running"] = False
                self.status["progress"] = 1.0 if actual_pump_duration == 0 else 0 # 如果时长为0，则认为已完成
                self.status["elapsed_time_seconds"] = 0
                self.status["raw_response"] += "\\\\n错误：无法确定泵送总时长。"
                await self.broadcast_status()
                return False

        except Exception as e:
            logger.error(f"泵 {pump_index} dispense_auto 执行异常: {e}", exc_info=True)
            self.status.update({"running": False, "raw_response": f"执行错误: {str(e)}"})
            await self.broadcast_status()
            return False
    
    async def dispense_timed(self, pump_index, duration, rpm, direction=1):
        if not self.initialized:
            logger.error("PumpAdapter未初始化，无法执行dispense_timed")
            raise ValueError("泵未初始化")
        
        self._stop_event = False
        user_specified_duration = float(duration) # 这是物理泵送的预期总时长
        
        # 记录API调用开始时间点
        api_call_start_time = time.time()

        self.status = {
            "running": True,
            "pump_index": pump_index,
            "volume": None, # 对于定时泵送，体积是计算出来的，初始未知
            "progress": 0,
            "direction": direction,
            "elapsed_time_seconds": 0, # 泵送操作的已过时间，初始为0
            "total_duration_seconds": user_specified_duration, # UI显示的总时长
            "rpm": rpm,
            "revolutions": None, # 稍后从proxy获取
            "raw_response": "正在请求泵服务..."
        }
        await self.broadcast_status()

        try:
            # 调用泵代理
            proxy_response = await self.pump_proxy.dispense_speed(
                volume_ml=0.1, # 此处体积仅为估算或占位
                speed_rpm=rpm, 
                direction=direction
            )
            
            # 计算API调用和参数获取所花费的时间
            command_send_and_param_fetch_duration = time.time() - api_call_start_time
            logger.info(f"从发送命令到获取参数用时: {command_send_and_param_fetch_duration:.2f}秒")
            
            if not proxy_response.get("success", False):
                logger.error(f"泵 {pump_index} dispense_timed 指令发送失败或PumpProxy内部错误。")
                self.status.update({
                    "running": False, 
                    "raw_response": proxy_response.get("raw_response", "指令发送失败")
                })
                await self.broadcast_status()
                return False

            # 更新状态中的圈数和原始响应
            self.status["revolutions"] = proxy_response.get("revolutions")
            self.status["raw_response"] = proxy_response.get("raw_response", "")
            
            source = proxy_response.get("source", "unknown")
            if self.status["revolutions"] and self.status["rpm"]:
                # 估算体积 (如果需要)
                # ml_per_rev_guess = 0.08 
                # self.status["volume"] = self.status["revolutions"] * ml_per_rev_guess * 1000
                pass
            
            logger.info(f"泵 {pump_index} dispense_timed: 数据来源={source}, "
                        f"RPM={self.status['rpm']}, 估算圈数={self.status.get('revolutions')}, "
                        f"指定实际泵送时长={user_specified_duration:.2f}s, "
                        f"估算体积={self.status.get('volume', '未知')}μL")
            
            actual_pump_duration = user_specified_duration # 在定时模式下，用户指定的时长就是实际泵送时长

            if actual_pump_duration > 0:
                # elapsed_time_seconds 已经在前面被设为0, total_duration_seconds 已经是 user_specified_duration
                await self.broadcast_status() # 再次广播，确保状态一致
                
                # 启动进度监控，监控物理泵送操作
                asyncio.create_task(self._monitor_pump_progress(
                    total_duration_seconds_to_monitor=actual_pump_duration,
                    initial_elapsed_for_progress_calc=0,
                    total_estimated_for_progress_calc=actual_pump_duration
                ))
                return True
            else:
                logger.error(f"泵 {pump_index} dispense_timed 无效的泵送时长 ({actual_pump_duration})。")
                self.status["running"] = False
                self.status["progress"] = 1.0 if actual_pump_duration == 0 else 0
                self.status["elapsed_time_seconds"] = 0
                self.status["raw_response"] += "\\\\n错误：泵送时长无效。"
                await self.broadcast_status()
                return False
            
        except Exception as e:
            logger.error(f"泵 {pump_index} dispense_timed 执行异常: {e}", exc_info=True)
            self.status.update({"running": False, "raw_response": f"执行错误: {str(e)}"})
            await self.broadcast_status()
            return False
    
    async def stop(self, pump_index):
        if not self.initialized:
            logger.warning(f"尝试停止泵 {pump_index}，但PumpAdapter未初始化。")
            # 即使未初始化，也尝试发送停止事件，以防有正在运行的监控任务
            self._stop_event = True 
            # 更新本地状态并广播
            self.status.update({"running": False, "pump_index": pump_index})
            await self.broadcast_status()
            return False # 表示可能未成功停止，因为未初始化

        logger.info(f"接收到停止泵 {pump_index} 的请求。")
        self._stop_event = True # 设置停止标志，通知_monitor_pump_progress停止监控
        
        current_running_status = self.status.get("running", False)
        
        # 立即更新状态并广播，让前端知道停止指令已接收
        self.status.update({
            "running": False,
            "pump_index": pump_index,
            # progress 和 elapsed_time_seconds 会在 _monitor_pump_progress 结束时最终确定
        })
        await self.broadcast_status() 
        
        if current_running_status: # 仅当之前状态为运行时才发送物理停止命令
            try:
                response = self.pump_proxy.emergency_stop()
                logger.info(f"泵 {pump_index} 已发送物理停止命令。响应: {response.get('raw_response','')}")
                self.status["raw_response"] = response.get('raw_response','已发送停止命令')
            except Exception as e:
                logger.error(f"发送泵物理停止命令失败 for pump {pump_index}: {e}", exc_info=True)
                self.status["raw_response"] = f"停止命令发送错误: {str(e)}"
        else:
            logger.info(f"泵 {pump_index} 当前并非运行状态，仅更新逻辑状态为停止。")
            self.status["raw_response"] = "泵已逻辑停止（之前非运行状态）。"

        await self.broadcast_status() # 再次广播包含raw_response的最终状态
        return True
    
    async def get_status(self, pump_index=0): # pump_index 参数在这里暂时未使用，因为我们只有一个共享状态
        if not self.initialized:
            logger.warning("PumpAdapter未初始化，get_status返回空状态。")
            # 返回一个表示未初始化的状态
            return {
                "running": False, "pump_index": pump_index, "volume": 0, "progress": 0, "direction": 1,
                "elapsed_time_seconds": 0, "total_duration_seconds": 0, 
                "rpm": None, "revolutions": None, "raw_response": "泵未初始化"
            }
        return self.status # 返回当前缓存的状态
    
    async def _monitor_pump_progress(self, total_duration_seconds_to_monitor, initial_elapsed_for_progress_calc, total_estimated_for_progress_calc):
        """监控泵送进度
        
        Args:
            total_duration_seconds_to_monitor: 监控循环将运行这么久 (秒)
            initial_elapsed_for_progress_calc: 用于计算进度的初始已过时间 (秒)
            total_estimated_for_progress_calc: 用于计算进度的总预估时长 (秒)
        """
        if not isinstance(total_duration_seconds_to_monitor, (int, float)) or total_duration_seconds_to_monitor <= 0:
            logger.error(f"_monitor_pump_progress: 无效的监控时长 ({total_duration_seconds_to_monitor}), 无法监控进度。泵: {self.status['pump_index']}")
            self.status["running"] = False
            self.status["progress"] = 0 
            self.status["raw_response"] = (self.status.get("raw_response","") + 
                                          f"\\\\n错误: 监控时长无效 ({total_duration_seconds_to_monitor})").strip()
            await self.broadcast_status()
            return

        update_interval = 0.1  # 秒, 广播频率
        loop_start_time = time.time() # 监控循环的开始时间
        
        if total_estimated_for_progress_calc is None or total_estimated_for_progress_calc <= 0:
            logger.error(f"_monitor_pump_progress: 无效的总预估时长 ({total_estimated_for_progress_calc}) for progress calculation. Pump: {self.status['pump_index']}")
            # Fallback or error handling if total_estimated is invalid
            total_estimated_for_progress_calc = total_duration_seconds_to_monitor # Use monitor duration as a fallback for progress calculation
            if total_estimated_for_progress_calc <= 0: # Still invalid
                self.status["running"] = False
                self.status["progress"] = 1.0 # Or 0.0, mark as complete or error
                await self.broadcast_status()
                return

        initial_progress = initial_elapsed_for_progress_calc / total_estimated_for_progress_calc if total_estimated_for_progress_calc > 0 else 0
            
        logger.info(f"开始监控泵 {self.status['pump_index']} 进度: "
                   f"监控循环将运行 {total_duration_seconds_to_monitor:.2f}秒, "
                   f"初始已过时间(用于进度计算)={initial_elapsed_for_progress_calc:.2f}秒, "
                   f"总预估时长(用于进度计算)={total_estimated_for_progress_calc:.2f}秒, "
                   f"计算出的初始进度={initial_progress:.2%}, RPM={self.status['rpm']}")
        
        if not self.status["running"]:
            logger.warning(f"泵 {self.status['pump_index']} 在 _monitor_pump_progress 开始时状态已非running，取消监控。")
            await self.broadcast_status()
            return

        try:
            self.status["progress"] = min(max(initial_progress, 0.0), 1.0)
            self.status["elapsed_time_seconds"] = round(initial_elapsed_for_progress_calc, 2)
            logger.info(f"[MONITOR Pump {self.status['pump_index']}] Initial broadcast: Progress={self.status['progress']:.2%}, Elapsed={self.status['elapsed_time_seconds']:.2f}s")
            await self.broadcast_status() # Broadcast initial state
            
            while time.time() - loop_start_time < total_duration_seconds_to_monitor:
                if self._stop_event:
                    logger.info(f"泵 {self.status['pump_index']} 进度监控被外部停止。")
                    self.status["running"] = False
                    break
                
                monitor_loop_elapsed_time = time.time() - loop_start_time
                current_total_elapsed_for_progress = initial_elapsed_for_progress_calc + monitor_loop_elapsed_time
                
                progress = current_total_elapsed_for_progress / total_estimated_for_progress_calc
                
                self.status["progress"] = min(max(progress, 0.0), 1.0)
                self.status["elapsed_time_seconds"] = round(current_total_elapsed_for_progress, 2)
                
                logger.info(f"[MONITOR Pump {self.status['pump_index']}] In Loop: Progress={self.status['progress']:.2%}, Elapsed={self.status['elapsed_time_seconds']:.2f}s. Broadcasting...")
                await self.broadcast_status()
                await asyncio.sleep(update_interval)
            
            final_elapsed_time_in_loop = time.time() - loop_start_time
            final_total_elapsed_for_progress = initial_elapsed_for_progress_calc + final_elapsed_time_in_loop
        
            if not self._stop_event and self.status["running"]:
                self.status["progress"] = 1.0
                self.status["elapsed_time_seconds"] = round(total_estimated_for_progress_calc, 2)
                logger.info(f"泵 {self.status['pump_index']} 正常完成: 总时长={total_estimated_for_progress_calc:.2f}秒, 最终进度={self.status['progress']:.2%}")
            else:
                current_progress = final_total_elapsed_for_progress / total_estimated_for_progress_calc
                self.status["progress"] = min(max(current_progress,0.0),1.0)
                self.status["elapsed_time_seconds"] = round(final_total_elapsed_for_progress, 2)
                if self._stop_event:
                    logger.info(f"泵 {self.status['pump_index']} 泵送被中断: 已运行={self.status['elapsed_time_seconds']:.2f}秒 / "
                                f"总时长={total_estimated_for_progress_calc:.2f}秒. 最终进度={self.status['progress']:.2%}")

        except Exception as e:
            logger.error(f"泵 {self.status['pump_index']} 在 _monitor_pump_progress 中发生错误: {e}", exc_info=True)
            self.status["raw_response"] = (self.status.get("raw_response","") + f"\\\\n监控错误: {str(e)}").strip()
        finally:
            self.status["running"] = False
            self._stop_event = False
            logger.info(f"[MONITOR Pump {self.status['pump_index']}] Final broadcast: Progress={self.status['progress']:.2%}, Elapsed={self.status['elapsed_time_seconds']:.2f}s")
            await self.broadcast_status()
    
    async def broadcast_status(self):
        # Create a copy to avoid modifying the original dict during iteration by other tasks potentially
        status_to_broadcast = self.status.copy()
        
        # Ensure key numerical fields are valid numbers or None for rpm/revolutions
        # 确保关键数值字段存在且为有效数字，避免前端JS错误
        for key in ["volume", "progress", "elapsed_time_seconds", "total_duration_seconds", "rpm", "revolutions"]:
            if status_to_broadcast.get(key) is None: # 如果是None，设为0或特定值
                 status_to_broadcast[key] = 0 if key not in ["rpm", "revolutions"] else None
            elif not isinstance(status_to_broadcast[key], (int, float)):
                 # 如果不是数字也不是None (例如错误字符串)，尝试转换，失败则设为0或None
                 try:
                     status_to_broadcast[key] = float(status_to_broadcast[key])
                 except (ValueError, TypeError):
                     status_to_broadcast[key] = 0 if key not in ["rpm", "revolutions"] else None
        
        # 确保 progress 在 0-1 之间
        if status_to_broadcast.get("progress") is not None:
            status_to_broadcast["progress"] = min(max(float(status_to_broadcast["progress"]), 0.0), 1.0)


        await self.broadcaster.broadcast({
            "type": "pump_status",
            "status": status_to_broadcast,
            "initialized": self.initialized
        })

class RelayAdapter:
    def __init__(self, moonraker_addr, broadcaster):
        try:
            from core_api.relay_proxy import RelayProxy
            self.relay_proxy = RelayProxy(moonraker_addr)
            self.broadcaster = broadcaster
            self.initialized = False
            # 继电器状态从1开始索引
            self.states = {1: False, 2: False, 3: False, 4: False}
            logger.info(f"继电器适配器已创建，连接到 {moonraker_addr}")
        except Exception as e:
            logger.error(f"初始化继电器适配器失败: {e}")
            self.relay_proxy = None
            self.broadcaster = broadcaster
            self.initialized = False
            self.states = {1: False, 2: False, 3: False, 4: False}
        
    async def initialize(self):
        try:
            if self.relay_proxy is None:
                raise ValueError("继电器控制器初始化失败")
                
            self.initialized = True
            await self.broadcast_status()
            logger.info("继电器初始化成功")
            return True
        except Exception as e:
            logger.error(f"继电器初始化失败: {e}")
            self.initialized = False
            await self.broadcast_status()
            raise
        
    async def close(self):
        self.initialized = False
        
    async def toggle(self, relay_id, state=None):
        if not self.initialized:
            raise ValueError("继电器未初始化")
        
        # 切换继电器状态
        if state is None:
            # 如果没有提供状态，则切换当前状态
            state = "on" if not self.states[relay_id] else "off"
        elif isinstance(state, bool):
            # 如果是布尔值，转换为字符串
            state = "on" if state else "off"
            
        # 调用继电器API
        try:
            self.relay_proxy.toggle(relay_id, state)
            
            # 更新状态
            self.states[relay_id] = (state.lower() == "on")
            
            # 记录日志
            logger.info(f"继电器 {relay_id} 已切换到 {state}")
            
            # 立即广播状态更新
            await self.broadcast_status()
            return True
        except Exception as e:
            logger.error(f"切换继电器失败: {e}")
            raise
    
    async def get_status(self):
        if not self.initialized:
            raise ValueError("继电器未初始化")
        
        try:
            # 直接使用本地缓存的状态
            # 注意：对于完整实现，应该添加查询真实硬件状态的功能
            # 但目前relay_proxy不支持query_status方法
            
            # 日志记录当前状态
            logger.info(f"继电器当前状态: {self.states}")
            
            return self.states
        except Exception as e:
            logger.error(f"获取继电器状态失败: {e}")
            return self.states
    
    async def broadcast_status(self):
        # 将状态转换为前端可以理解的格式
        # 将Python布尔值转换为前端可以正确解析的字符串
        json_states = {}
        for key, value in self.states.items():
            json_states[str(key)] = "on" if value else "off"
            
        await self.broadcaster.broadcast({
            "type": "relay_status",
            "states": json_states,
            "initialized": self.initialized
        })
        logger.info(f"广播继电器状态: {{'type': 'relay_status', 'states': {json_states}, 'initialized': {self.initialized}}}")

# 在启动时初始化WebSocket监听器
@app.on_event("startup")
async def startup_event():
    global moonraker_listener, config
    
    # 先加载配置，确保有正确的Moonraker地址
    load_config()
    logger.info(f"设备测试器启动，已加载配置: Moonraker地址={config['moonraker_addr']}")
    
    # 初始化WebSocket监听器
    if MoonrakerWebsocketListener is not None:
        ws_url = _get_websocket_url_from_http(config["moonraker_addr"])
        if ws_url:
            try:
                logger.info(f"正在初始化WebSocket监听器，连接到: {ws_url}")
                moonraker_listener = MoonrakerWebsocketListener(ws_url)
                
                # 创建监听任务并保存引用
                ws_listener_task = asyncio.create_task(moonraker_listener.start())
                
                # 添加回调以处理任务完成或失败
                def on_task_done(task):
                    try:
                        # 获取任务结果（如果有异常会抛出）
                        task.result()
                    except Exception as e:
                        logger.error(f"WebSocket监听器任务失败: {e}", exc_info=True)
                    else:
                        logger.warning("WebSocket监听器任务正常结束（不应该发生）") 
                
                ws_listener_task.add_done_callback(on_task_done)
                
                logger.info(f"已初始化WebSocket监听器，连接到: {ws_url}")
            except Exception as e:
                logger.error(f"初始化WebSocket监听器失败: {e}", exc_info=True)
                moonraker_listener = None
        else:
            logger.error(f"无法从Moonraker地址 {config['moonraker_addr']} 构建WebSocket URL")

# 在应用关闭时清理资源
@app.on_event("shutdown")
async def shutdown_event():
    global moonraker_listener
    
    # 停止WebSocket监听器
    if moonraker_listener:
        try:
            await moonraker_listener.stop()
            logger.info("应用关闭时已停止WebSocket监听器")
        except Exception as e:
            logger.error(f"停止WebSocket监听器失败: {e}")

if __name__ == "__main__":
    # 查找可用端口
    port = find_available_port(8001, 10)
    if port is None:
        print("错误：无法找到可用端口，请检查是否有太多程序占用了端口。")
        sys.exit(1)
        
    print("设备测试服务器正在启动...")
    print(f"请使用浏览器访问: http://localhost:{port}")
    
    # 启动FastAPI应用
    uvicorn.run(app, host="0.0.0.0", port=port) 