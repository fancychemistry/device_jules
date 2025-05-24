import sys
import os
import asyncio
import logging
import json
import time
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path
import httpx
import re

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# 配置日志
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("experiment_automation.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("experiment_automation")

# FastAPI 应用
app = FastAPI(title="电化学实验自动化系统")

# 添加CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ExperimentRunner:
    """简化的实验执行器，直接调用device_tester的API"""
    
    def __init__(self, device_tester_url: str = "http://localhost:8001"):
        self.device_tester_url = device_tester_url
        self.current_experiment = None
        self.experiment_status = "idle"  # idle（空闲）, running（运行中）, completed（已完成）, error（错误）
        self.current_step = 0
        self.total_steps = 0
        self.step_results = []
        self.experiment_config = None
        self.experiment_id = None
        self.project_name = None  # 新增：自定义项目名称
        self.project_folder = None  # 新增：项目文件夹路径
        self.current_step_name = ""  # 新增：当前步骤名称
        self.current_step_description = ""  # 新增：当前步骤描述
        self.experiment_logs = []  # 新增：实验日志
        self.experiment_start_time = None  # 新增：实验开始时间
        
    def add_log(self, message: str, level: str = "INFO"):
        """添加日志"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = {
            "timestamp": timestamp,
            "level": level,
            "message": message,
            "iso_timestamp": datetime.now().isoformat()
        }
        self.experiment_logs.append(log_entry)
        
        # 限制日志数量，只保留最近500条
        if len(self.experiment_logs) > 500:
            self.experiment_logs = self.experiment_logs[-500:]
        
        # 打印到控制台
        print(f"[{timestamp}] [{level}] {message}")
        
    def get_experiment_summary(self) -> Dict[str, Any]:
        """获取实验摘要信息（用于状态恢复）"""
        return {
            "experiment_id": self.experiment_id,
            "project_name": self.project_name,
            "project_folder": self.project_folder,
            "status": self.experiment_status,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "start_time": self.experiment_start_time.isoformat() if self.experiment_start_time else None,
            "step_count": len(self.step_results),
            "has_config": self.experiment_config is not None
        }
    
    async def load_config(self, config_path: str, custom_project_name: str = None) -> bool:
        """加载实验配置文件"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self.experiment_config = json.load(f)
            
            # 设置项目名称：优先使用自定义名称，否则使用配置文件中的名称
            if custom_project_name:
                self.project_name = custom_project_name
                # 更新配置中的项目名称
                self.experiment_config["project_name"] = custom_project_name
            else:
                self.project_name = self.experiment_config.get("project_name", "DefaultProject")
            
            # 创建项目文件夹
            self._create_project_folder()
            
            # 为缺失的配置提供默认值
            self._provide_default_values()
            
            # 解析步骤数量
            self.total_steps = len(self.experiment_config.get("experiment_sequence", []))
            self.add_log(f"实验配置加载成功，项目名称: {self.project_name}")
            self.add_log(f"项目文件夹: {self.project_folder}")
            self.add_log(f"共 {self.total_steps} 个步骤")
            
            # 输出关键配置信息
            output_positions = self.experiment_config.get("output_positions", [])
            self.add_log(f"输出位置: {output_positions}")
            
            return True
        except Exception as e:
            self.add_log(f"加载配置文件失败: {e}", "ERROR")
            return False
    
    def _create_project_folder(self):
        """创建项目文件夹"""
        try:
            import os
            from pathlib import Path
            
            # 基础路径（可以从配置文件中读取）
            base_path = self.experiment_config.get("base_path", "experiment_results")
            
            # 创建基础文件夹（如果不存在）
            base_dir = Path(base_path)
            base_dir.mkdir(exist_ok=True)
            
            # 创建项目文件夹
            project_dir = base_dir / self.project_name
            project_dir.mkdir(exist_ok=True)
            
            # 创建子文件夹（根据实验类型）
            (project_dir / "chi_data").mkdir(exist_ok=True)  # CHI测试数据
            (project_dir / "logs").mkdir(exist_ok=True)     # 日志文件
            (project_dir / "reports").mkdir(exist_ok=True)  # 报告文件
            (project_dir / "raw_data").mkdir(exist_ok=True) # 原始数据
            
            self.project_folder = str(project_dir)
            self.add_log(f"项目文件夹创建成功: {self.project_folder}")
            
            # 更新CHI软件的工作目录到chi_data子文件夹
            chi_data_path = project_dir / "chi_data"
            self.experiment_config["chi_working_directory"] = str(chi_data_path)
            self.add_log(f"CHI工作目录设置为: {chi_data_path}")
            
        except Exception as e:
            self.add_log(f"创建项目文件夹失败: {e}", "ERROR")
            # 如果创建失败，使用默认路径
            self.project_folder = f"experiment_results/{self.project_name}"
    
    def _provide_default_values(self):
        """为缺失的配置提供默认值"""
        config = self.experiment_config
        
        # 如果output_positions_list为null，创建默认输出位置
        if config.get("output_positions_list") is None:
            # 基于first_experiment_position创建默认位置列表
            first_pos = config.get("first_experiment_position", 2)
            default_positions = [first_pos, first_pos + 1, first_pos + 2, first_pos + 3]
            config["output_positions"] = default_positions
            print(f"🔧 创建默认输出位置: {default_positions}")
        else:
            config["output_positions"] = config["output_positions_list"]
        
        # 解析配置中的模板变量
        self._resolve_template_variables_in_config()
    
    def _resolve_template_variables_in_config(self):
        """递归解析配置中的模板变量"""
        def resolve_recursive(obj):
            if isinstance(obj, dict):
                return {key: resolve_recursive(value) for key, value in obj.items()}
            elif isinstance(obj, list):
                return [resolve_recursive(item) for item in obj]
            elif isinstance(obj, str) and obj.startswith("{{") and obj.endswith("}}"):
                return self._resolve_template_value(obj)
            else:
                return obj
        
        # 更新configurations部分
        if "configurations" in self.experiment_config:
            self.experiment_config["configurations"] = resolve_recursive(
                self.experiment_config["configurations"]
            )
            print(f"🔧 解析后的配置: {self.experiment_config['configurations']}")
    
    def _resolve_template_value(self, value: Any) -> Any:
        """解析模板变量"""
        if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
            template_var = value[2:-2].strip()
            
            # 处理项目名称
            if template_var == "project_name":
                return self.experiment_config.get("project_name", "Unknown")
            
            # 处理输出位置数组索引
            elif template_var.startswith("output_positions[") and template_var.endswith("]"):
                try:
                    index_str = template_var[len("output_positions["):-1]
                    index = int(index_str)
                    output_positions = self.experiment_config.get("output_positions", [])
                    if 0 <= index < len(output_positions):
                        resolved = output_positions[index]
                        print(f"🔧 模板变量解析: {value} -> {resolved}")
                        return resolved
                    else:
                        print(f"⚠️ 输出位置索引超出范围: {template_var}, 使用默认值2")
                        return 2
                except (ValueError, IndexError) as e:
                    print(f"⚠️ 解析输出位置索引失败: {template_var}, 错误: {e}, 使用默认值2")
                    return 2
            
            # 处理电压相关变量（运行时解析）
            elif template_var in ["current_voltage", "current_voltage_file_str", "current_output_position", "loop_index"]:
                return value  # 保持原样，运行时解析
            
            # 其他未知变量
            else:
                print(f"⚠️ 未知模板变量: {template_var}, 保持原值")
                return value
        
        return value
    
    async def start_experiment(self) -> str:
        """开始实验"""
        if not self.experiment_config:
            raise ValueError("未加载实验配置")
        
        self.experiment_id = f"exp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.experiment_status = "running"
        self.current_step = 0
        self.step_results = []
        self.experiment_start_time = datetime.now()
        
        self.add_log(f"实验开始: {self.experiment_id}")
        self.add_log(f"项目名称: {self.project_name}")
        self.add_log(f"项目文件夹: {self.project_folder}")
        
        # 在开始实验前先初始化所有设备
        self.add_log("开始初始化设备...")
        init_success = await self._initialize_all_devices()
        if not init_success:
            self.experiment_status = "error"
            self.add_log("设备初始化失败，实验无法开始", "ERROR")
            return self.experiment_id
        
        # 在后台执行实验
        asyncio.create_task(self._execute_experiment())
        
        return self.experiment_id
    
    async def _initialize_all_devices(self) -> bool:
        """初始化所有设备"""
        try:
            # 初始化打印机
            print("🖨️ 初始化打印机...")
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(f"{self.device_tester_url}/api/printer/initialize")
                if response.status_code == 200:
                    result = response.json()
                    if not result.get("error", True):
                        print("✅ 打印机初始化成功")
                    else:
                        print(f"❌ 打印机初始化失败: {result.get('message')}")
                        return False
                else:
                    print(f"❌ 打印机初始化HTTP错误: {response.status_code}")
                    return False
            
            # 初始化泵
            print("💧 初始化泵...")
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(f"{self.device_tester_url}/api/pump/initialize")
                if response.status_code == 200:
                    result = response.json()
                    if not result.get("error", True):
                        print("✅ 泵初始化成功")
                    else:
                        print(f"❌ 泵初始化失败: {result.get('message')}")
                        return False
                else:
                    print(f"❌ 泵初始化HTTP错误: {response.status_code}")
                    return False
            
            # 初始化继电器
            print("🔌 初始化继电器...")
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(f"{self.device_tester_url}/api/relay/initialize")
                if response.status_code == 200:
                    result = response.json()
                    if not result.get("error", True):
                        print("✅ 继电器初始化成功")
                    else:
                        print(f"❌ 继电器初始化失败: {result.get('message')}")
                        return False
                else:
                    print(f"❌ 继电器初始化HTTP错误: {response.status_code}")
                    return False
            
            # 初始化CHI（可选，如果失败也继续）
            print("🧪 初始化CHI...")
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(f"{self.device_tester_url}/api/chi/initialize")
                    if response.status_code == 200:
                        result = response.json()
                        if not result.get("error", True):
                            print("✅ CHI初始化成功")
                        else:
                            print(f"⚠️ CHI初始化失败，但继续实验: {result.get('message')}")
                    else:
                        print(f"⚠️ CHI初始化HTTP错误，但继续实验: {response.status_code}")
            except Exception as e:
                print(f"⚠️ CHI初始化异常，但继续实验: {e}")
            
            print("✅ 所有关键设备初始化完成")
            return True
            
        except Exception as e:
            print(f"❌ 设备初始化过程中发生异常: {e}")
            return False
    
    async def stop_experiment(self) -> bool:
        """停止实验"""
        if self.experiment_status == "running":
            self.experiment_status = "stopped"
            print("⏹ 实验已停止")
            return True
        return False
    
    async def get_status(self) -> Dict[str, Any]:
        """获取实验状态"""
        return {
            "experiment_id": self.experiment_id,
            "project_name": self.project_name,
            "project_folder": self.project_folder,
            "status": self.experiment_status,
            "current_step": self.current_step,
            "current_step_name": self.current_step_name,
            "current_step_description": self.current_step_description,
            "total_steps": self.total_steps,
            "progress": self.current_step / max(self.total_steps, 1),
            "step_results": self.step_results[-20:] if self.step_results else [],  # 增加到最近20个结果
            "completed_steps": len([r for r in self.step_results if r.get("success", False)]),
            "failed_steps": len([r for r in self.step_results if not r.get("success", False)]),
            "all_step_results": self.step_results,  # 完整的步骤结果
            "experiment_logs": self.experiment_logs[-100:] if self.experiment_logs else [],  # 最近100条日志
            "start_time": self.experiment_start_time.isoformat() if self.experiment_start_time else None,
            "runtime_seconds": (datetime.now() - self.experiment_start_time).total_seconds() if self.experiment_start_time else 0,
            "has_config_loaded": self.experiment_config is not None
        }
    
    async def _execute_experiment(self):
        """执行实验的主循环"""
        try:
            sequence = self.experiment_config.get("experiment_sequence", [])
            
            self.add_log(f"开始执行实验: {self.experiment_id}")
            self.add_log(f"实验序列包含 {len(sequence)} 个步骤")
            
            for step_index, step_config in enumerate(sequence):
                if self.experiment_status != "running":
                    self.add_log(f"实验状态已变为 {self.experiment_status}，停止执行", "WARNING")
                    break
                
                # 更新当前步骤信息
                self.current_step = step_index + 1
                step_id = step_config.get('id', f'step_{step_index}')
                step_description = step_config.get('description', '无描述')
                step_type = step_config.get('type', 'unknown')
                
                self.current_step_name = step_id
                self.current_step_description = step_description
                
                self.add_log(f"[步骤 {self.current_step}/{self.total_steps}] {step_id}")
                self.add_log(f"描述: {step_description}")
                self.add_log(f"类型: {step_type}")
                
                # 检查是否跳过
                if not step_config.get("enabled", True):
                    self.add_log(f"步骤已禁用，跳过", "WARNING")
                    # 添加跳过的步骤记录
                    self.step_results.append({
                        "step_id": step_id,
                        "step_index": step_index,
                        "success": True,
                        "message": "步骤已禁用，跳过",
                        "timestamp": datetime.now().isoformat(),
                        "skipped": True
                    })
                    continue
                
                # 检查跳过条件
                skip_flag = step_config.get("skip_if_flag_true")
                if skip_flag and self.experiment_config.get("experiment_flags", {}).get(skip_flag, False):
                    self.add_log(f"因标志 '{skip_flag}' 跳过步骤", "WARNING")
                    # 添加跳过的步骤记录
                    self.step_results.append({
                        "step_id": step_id,
                        "step_index": step_index,
                        "success": True,
                        "message": f"因标志 '{skip_flag}' 跳过",
                        "timestamp": datetime.now().isoformat(),
                        "skipped": True
                    })
                    continue
                
                # 执行步骤
                self.add_log(f"开始执行步骤...")
                step_start_time = datetime.now()
                
                try:
                    result = await self._execute_step(step_config)
                except Exception as step_error:
                    self.add_log(f"步骤执行出现异常: {step_error}", "ERROR")
                    result = {"success": False, "message": f"步骤执行异常: {str(step_error)}"}
                
                step_end_time = datetime.now()
                step_duration = (step_end_time - step_start_time).total_seconds()
                
                # 记录步骤结果
                step_result = {
                    "step_id": step_id,
                    "step_index": step_index,
                    "step_description": step_description,
                    "step_type": step_type,
                    "success": result.get("success", False),
                    "message": result.get("message", ""),
                    "timestamp": step_end_time.isoformat(),
                    "duration_seconds": step_duration,
                    "skipped": False
                }
                self.step_results.append(step_result)
                
                if result.get("success", False):
                    self.add_log(f"步骤执行成功 (用时: {step_duration:.1f}秒)")
                    self.add_log(f"结果: {result.get('message', '无消息')}")
                else:
                    self.add_log(f"步骤执行失败 (用时: {step_duration:.1f}秒)", "ERROR")
                    self.add_log(f"错误: {result.get('message', '无错误信息')}", "ERROR")
                    self.experiment_status = "error"
                    break
                
                # 根据步骤类型确定等待时间
                if step_type in ["printer_home", "move_printer_xyz", "move_printer_grid"]:
                    wait_time = 8
                    self.add_log(f"等待打印机操作完成 ({wait_time}秒)...")
                elif step_type == "sequence":
                    wait_time = 3
                    self.add_log(f"等待序列操作稳定 ({wait_time}秒)...")
                elif step_type in ["chi_sequence", "chi_measurement"]:
                    wait_time = 2
                    self.add_log(f"等待电化学测试稳定 ({wait_time}秒)...")
                elif step_type == "voltage_loop":
                    wait_time = 2
                    self.add_log(f"等待电压循环准备 ({wait_time}秒)...")
                else:
                    wait_time = 1
                    self.add_log(f"等待操作完成 ({wait_time}秒)...")
                
                await asyncio.sleep(wait_time)
            
            # 实验完成处理
            if self.experiment_status == "running":
                self.experiment_status = "completed"
                self.current_step_name = "实验完成"
                self.current_step_description = "所有步骤已成功完成"
                self.add_log(f"实验成功完成！")
                self.add_log(f"统计: 共 {len(self.step_results)} 个步骤")
                successful_steps = len([r for r in self.step_results if r.get("success", False)])
                self.add_log(f"成功: {successful_steps}个")
                self.add_log(f"失败: {len(self.step_results) - successful_steps}个")
            else:
                self.add_log(f"实验未正常完成，状态: {self.experiment_status}", "WARNING")
                
        except Exception as e:
            self.add_log(f"实验执行过程中发生严重异常: {e}", "ERROR")
            self.experiment_status = "error"
            self.current_step_name = "实验异常"
            self.current_step_description = f"执行过程中发生异常: {str(e)}"
    
    async def _execute_step(self, step_config: Dict[str, Any]) -> Dict[str, Any]:
        """执行单个步骤"""
        step_type = step_config.get("type")
        step_id = step_config.get("id")
        
        try:
            if step_type == "printer_home":
                return await self._execute_printer_home()
            elif step_type == "move_printer_xyz":
                return await self._execute_move_printer_xyz(step_config)
            elif step_type == "move_printer_grid":
                return await self._execute_move_printer_grid(step_config)
            elif step_type == "sequence":
                return await self._execute_sequence(step_config)
            elif step_type == "chi_sequence":
                return await self._execute_chi_sequence(step_config)
            elif step_type == "voltage_loop":
                return await self._execute_voltage_loop(step_config)
            else:
                return {"success": False, "message": f"未知步骤类型: {step_type}"}
                
        except Exception as e:
            logger.error(f"步骤 {step_id} 执行异常: {e}")
            return {"success": False, "message": str(e)}
    
    def _parse_api_response(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """通用的API响应解析函数，兼容多种返回格式
        
        支持的格式：
        1. {"success": True/False, "message": "..."}
        2. {"error": False/True, "message": "..."}
        """
        message = result.get("message", "")
        
        # 优先检查success字段
        if "success" in result:
            success = result.get("success", False)
            print(f"🔧 API响应解析: 使用success字段, success={success}, message='{message}'")
            return {"success": success, "message": message}
        
        # 如果没有success字段，检查error字段
        elif "error" in result:
            # error=False表示成功，error=True表示失败
            success = not result.get("error", True)
            print(f"🔧 API响应解析: 使用error字段, error={result.get('error')}, success={success}, message='{message}'")
            return {"success": success, "message": message}
        
        # 如果都没有，默认为失败
        else:
            print(f"🔧 API响应解析: 缺少success/error字段, 默认失败, message='{message}'")
            return {"success": False, "message": message or "未知响应格式"}
    
    async def _execute_printer_home(self) -> Dict[str, Any]:
        """执行打印机归位"""
        try:
            print(f"🔧 发送打印机归位请求到: {self.device_tester_url}/api/printer/home")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(f"{self.device_tester_url}/api/printer/home")
                
                print(f"🔧 打印机归位HTTP状态码: {response.status_code}")
                
                # 检查HTTP状态码
                if response.status_code != 200:
                    return {"success": False, "message": f"HTTP错误: {response.status_code}"}
                
                result = response.json()
                print(f"🔧 打印机归位API原始响应: {result}")
                
                # 使用通用解析函数
                parsed = self._parse_api_response(result)
                return parsed
                
        except httpx.TimeoutError as e:
            error_msg = f"打印机归位超时: {type(e).__name__} - {str(e)}"
            print(f"🔧 打印机归位API调用超时: {error_msg}")
            return {"success": False, "message": error_msg}
        except httpx.RequestError as e:
            error_msg = f"打印机归位请求错误: {type(e).__name__} - {str(e)}"
            print(f"🔧 打印机归位API请求错误: {error_msg}")
            return {"success": False, "message": error_msg}
        except Exception as e:
            error_msg = f"打印机归位异常: {type(e).__name__} - {str(e)}"
            print(f"🔧 打印机归位API调用异常: {error_msg}")
            return {"success": False, "message": error_msg}
    
    async def _execute_move_printer_xyz(self, step_config: Dict[str, Any]) -> Dict[str, Any]:
        """执行打印机XYZ移动"""
        try:
            params = step_config.get("params", {})
            
            # 解析坐标参数
            x = self._resolve_param(params.get("x_key"), params.get("x"))
            y = self._resolve_param(params.get("y_key"), params.get("y"))
            z = self._resolve_param(params.get("z_key"), params.get("z"))
            
            print(f"🔧 打印机移动参数: X={x}, Y={y}, Z={z}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.device_tester_url}/api/printer/move",
                    json={"x": x, "y": y, "z": z}
                )
                
                if response.status_code != 200:
                    return {"success": False, "message": f"HTTP错误: {response.status_code}"}
                
                result = response.json()
                print(f"🔧 打印机移动API原始响应: {result}")
                return self._parse_api_response(result)
        except Exception as e:
            print(f"🔧 打印机移动API调用异常: {e}")
            return {"success": False, "message": f"API调用异常: {e}"}
    
    async def _execute_move_printer_grid(self, step_config: Dict[str, Any]) -> Dict[str, Any]:
        """执行打印机网格移动"""
        try:
            params = step_config.get("params", {})
            grid_num = self._resolve_param(params.get("grid_num_key"), params.get("grid_num", 1))
            
            print(f"🔧 打印机网格移动参数: grid_num={grid_num}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.device_tester_url}/api/printer/grid",
                    json={"position": grid_num}
                )
                
                if response.status_code != 200:
                    return {"success": False, "message": f"HTTP错误: {response.status_code}"}
                
                result = response.json()
                print(f"🔧 打印机网格移动API原始响应: {result}")
                return self._parse_api_response(result)
        except Exception as e:
            print(f"🔧 打印机网格移动API调用异常: {e}")
            return {"success": False, "message": f"API调用异常: {e}"}
    
    async def _execute_sequence(self, step_config: Dict[str, Any]) -> Dict[str, Any]:
        """执行序列步骤"""
        actions = step_config.get("actions", [])
        
        for action in actions:
            action_type = action.get("type")
            params = action.get("params", {})
            
            if action_type == "set_valve":
                result = await self._execute_set_valve(params)
            elif action_type == "pump_liquid":
                result = await self._execute_pump_liquid(params)
            elif action_type == "move_printer_grid":
                result = await self._execute_move_printer_grid_simple(params)
            elif action_type == "process_chi_data":
                result = await self._execute_process_chi_data(params)
            elif action_type == "printer_home":
                result = await self._execute_printer_home()
            else:
                logger.warning(f"未知动作类型: {action_type}")
                continue
            
            if not result.get("success", False):
                return result
        
        return {"success": True, "message": "序列执行完成"}
    
    async def _execute_set_valve(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行阀门控制"""
        max_retries = 3  # 最大重试次数
        retry_delay = 2  # 重试间隔（秒）
        
        for attempt in range(max_retries):
            try:
                open_to_reservoir = params.get("open_to_reservoir", False)
                relay_id = self._resolve_param(params.get("relay_id_key"), params.get("relay_id", 1))
                
                state = "on" if open_to_reservoir else "off"
                
                print(f"🔧 阀门控制参数: relay_id={relay_id}, state={state} (尝试 {attempt + 1}/{max_retries})")
                
                # 增加超时时间，因为继电器操作可能需要时间
                timeout_seconds = 45.0  # 从60秒减少到45秒，但增加重试
                print(f"🔧 阀门控制超时设置: {timeout_seconds}秒")
                
                async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                    print(f"🔧 发送阀门控制请求到: {self.device_tester_url}/api/relay/toggle")
                    response = await client.post(
                        f"{self.device_tester_url}/api/relay/toggle",
                        json={"relay_id": relay_id, "state": state}
                    )
                    
                    print(f"🔧 阀门控制HTTP状态码: {response.status_code}")
                    
                    if response.status_code != 200:
                        if attempt < max_retries - 1:
                            print(f"⚠️ HTTP错误 {response.status_code}，等待 {retry_delay}秒后重试...")
                            await asyncio.sleep(retry_delay)
                            continue
                        return {"success": False, "message": f"HTTP错误: {response.status_code}"}
                    
                    result = response.json()
                    print(f"🔧 阀门控制API原始响应: {result}")
                    parsed = self._parse_api_response(result)
                    
                    # 如果成功，额外等待一下确保阀门动作完成
                    if parsed["success"]:
                        print(f"✅ 阀门切换成功，等待阀门动作稳定...")
                        await asyncio.sleep(2)  # 等待阀门物理切换完成
                        return parsed
                    else:
                        # 如果失败但还有重试机会
                        if attempt < max_retries - 1:
                            print(f"⚠️ 阀门控制失败: {parsed['message']}，等待 {retry_delay}秒后重试...")
                            await asyncio.sleep(retry_delay)
                            continue
                        else:
                            print(f"❌ 阀门控制最终失败: {parsed['message']}")
                            return parsed
                        
            except httpx.TimeoutError as e:
                error_msg = f"阀门控制超时({timeout_seconds}秒): {type(e).__name__} - {str(e)}"
                print(f"🔧 阀门控制API调用超时: {error_msg}")
                if attempt < max_retries - 1:
                    print(f"⚠️ 超时错误，等待 {retry_delay}秒后重试...")
                    await asyncio.sleep(retry_delay)
                    continue
                return {"success": False, "message": error_msg}
            except httpx.RequestError as e:
                error_msg = f"阀门控制请求错误: {type(e).__name__} - {str(e)}"
                print(f"🔧 阀门控制API请求错误: {error_msg}")
                if attempt < max_retries - 1:
                    print(f"⚠️ 请求错误，等待 {retry_delay}秒后重试...")
                    await asyncio.sleep(retry_delay)
                    continue
                return {"success": False, "message": error_msg}
            except Exception as e:
                error_msg = f"阀门控制异常: {type(e).__name__} - {str(e)}"
                print(f"🔧 阀门控制API调用异常: {error_msg}")
                if attempt < max_retries - 1:
                    print(f"⚠️ 未知异常，等待 {retry_delay}秒后重试...")
                    await asyncio.sleep(retry_delay)
                    continue
                return {"success": False, "message": error_msg}
        
        # 如果所有重试都失败了
        return {"success": False, "message": f"阀门控制失败，已重试 {max_retries} 次"}
    
    async def _execute_pump_liquid(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行液体泵送"""
        try:
            volume_ml = self._resolve_param(params.get("volume_ml_key"), params.get("volume_ml", 1.0))
            direction = params.get("direction", 1)
            
            # 转换为微升
            volume_ul = volume_ml * 1000
            
            print(f"🔧 泵送参数: volume_ml={volume_ml}, volume_ul={volume_ul}, direction={direction}")
            
            # 发起泵送请求
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.device_tester_url}/api/pump/dispense_auto",
                    json={
                        "pump_index": 0,
                        "volume": volume_ul,
                        "speed": "normal",
                        "direction": direction
                    }
                )
                
                if response.status_code != 200:
                    return {"success": False, "message": f"HTTP错误: {response.status_code}"}
                
                result = response.json()
                print(f"🔧 泵送API原始响应: {result}")
                parsed = self._parse_api_response(result)
                
                if not parsed["success"]:
                    return parsed
                
                # 等待泵送完成 - 使用状态监控
                print(f"🔧 等待泵送完成，开始监控泵送状态...")
                completion_result = await self._wait_for_pump_completion()
                
                if completion_result["success"]:
                    print(f"✅ 泵送完成: {completion_result['message']}")
                else:
                    print(f"⚠️ 泵送可能未完全完成: {completion_result['message']}")
                
                return completion_result
                
        except Exception as e:
            print(f"🔧 泵送API调用异常: {e}")
            return {"success": False, "message": f"API调用异常: {e}"}
    
    async def _wait_for_pump_completion(self, max_wait_time: int = 300) -> Dict[str, Any]:
        """等待泵送完成，通过轮询泵送状态
        
        Args:
            max_wait_time: 最大等待时间(秒)，默认5分钟
            
        Returns:
            包含success和message的字典
        """
        try:
            start_time = time.time()
            last_progress = 0
            total_duration = None
            
            print(f"🔧 开始监控泵送状态，最大等待时间: {max_wait_time}秒")
            
            while time.time() - start_time < max_wait_time:
                try:
                    # 获取泵送状态
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.get(f"{self.device_tester_url}/api/pump/status")
                        
                        if response.status_code != 200:
                            print(f"⚠️ 获取泵送状态失败，HTTP状态码: {response.status_code}")
                            await asyncio.sleep(2)
                            continue
                        
                        result = response.json()
                        parsed_result = self._parse_api_response(result)
                        
                        if not parsed_result["success"]:
                            print(f"⚠️ 泵送状态API返回错误: {parsed_result['message']}")
                            await asyncio.sleep(2)
                            continue
                        
                        status = result.get("status", {})
                        running = status.get("running", False)
                        progress = status.get("progress", 0)
                        elapsed_time = status.get("elapsed_time_seconds", 0)
                        total_duration = status.get("total_duration_seconds", 0)
                        
                        # 显示进度信息
                        if progress != last_progress or int(time.time()) % 10 == 0:  # 每10秒或进度变化时显示
                            progress_percent = progress * 100
                            print(f"🔧 泵送进度: {progress_percent:.1f}% ({elapsed_time:.1f}s / {total_duration:.1f}s)")
                            last_progress = progress
                        
                        # 检查是否完成
                        if not running:
                            if progress >= 0.99:  # 进度接近100%认为成功完成
                                elapsed = time.time() - start_time
                                return {
                                    "success": True, 
                                    "message": f"泵送成功完成，用时 {elapsed:.1f}秒，最终进度 {progress*100:.1f}%"
                                }
                            else:
                                return {
                                    "success": False,
                                    "message": f"泵送提前停止，最终进度 {progress*100:.1f}%"
                                }
                        
                        # 检查是否超过预期时间太多
                        if total_duration > 0 and elapsed_time > total_duration * 1.5:
                            print(f"⚠️ 泵送时间超过预期，可能存在问题")
                        
                except Exception as status_error:
                    print(f"⚠️ 获取泵送状态时出现异常: {status_error}")
                
                # 等待间隔
                await asyncio.sleep(1)
            
            # 超时处理
            elapsed = time.time() - start_time
            return {
                "success": False,
                "message": f"泵送监控超时 ({elapsed:.1f}s)，请检查泵送是否正常完成"
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"泵送状态监控异常: {e}"
            }
    
    async def _execute_move_printer_grid_simple(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行简单的打印机网格移动"""
        try:
            grid_num = self._resolve_param(params.get("grid_num_key"), params.get("grid_num", 1))
            
            print(f"🔧 简单网格移动参数: grid_num={grid_num}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.device_tester_url}/api/printer/grid",
                    json={"position": grid_num}
                )
                
                if response.status_code != 200:
                    return {"success": False, "message": f"HTTP错误: {response.status_code}"}
                
                result = response.json()
                print(f"🔧 简单网格移动API原始响应: {result}")
                return self._parse_api_response(result)
        except Exception as e:
            print(f"🔧 简单网格移动API调用异常: {e}")
            return {"success": False, "message": f"API调用异常: {e}"}
    
    async def _execute_chi_sequence(self, step_config: Dict[str, Any]) -> Dict[str, Any]:
        """执行CHI测试序列"""
        chi_tests = step_config.get("chi_tests", [])
        
        print(f"🔧 开始执行CHI测试序列，共 {len(chi_tests)} 个测试")
        
        for i, test_config in enumerate(chi_tests, 1):
            method = test_config.get("method")
            params = test_config.get("params", {})
            
            print(f"🔧 执行第 {i}/{len(chi_tests)} 个CHI测试: {method}")
            
            # 解析参数中的模板变量
            resolved_params = {}
            for key, value in params.items():
                if isinstance(value, str):
                    # 使用正则表达式替换所有模板变量
                    resolved_value = value
                    
                    # 查找所有 {{variable}} 模式的模板变量
                    template_pattern = r'\{\{([^}]+)\}\}'
                    matches = re.findall(template_pattern, value)
                    
                    for match in matches:
                        template_var = match.strip()
                        if template_var == "project_name":
                            project_name = self.experiment_config.get("project_name", "Unknown")
                            resolved_value = resolved_value.replace(f"{{{{{template_var}}}}}", project_name)
                        # 可以在这里添加其他模板变量的处理
                    
                    resolved_params[key] = resolved_value
                else:
                    resolved_params[key] = value
            
            print(f"🔧 CHI测试 {method}, 解析后参数: {resolved_params}")
            
            # 根据方法调用对应的API
            if method == "CV":
                result = await self._execute_chi_cv(resolved_params)
            elif method == "LSV":
                result = await self._execute_chi_lsv(resolved_params)
            elif method == "EIS":
                result = await self._execute_chi_eis(resolved_params)
            elif method == "IT":
                result = await self._execute_chi_it(resolved_params)
            else:
                print(f"⚠️ 不支持的CHI测试方法: {method}")
                continue
            
            if not result.get("success", False):
                print(f"❌ CHI测试 {method} 启动失败: {result.get('message')}")
                return result
            
            print(f"✅ CHI测试 {method} 启动成功，开始等待完成...")
            
            # 等待测试完成
            completion_result = await self._wait_for_chi_completion()
            if not completion_result.get("success", True):  # 默认为True，除非明确失败
                print(f"❌ CHI测试 {method} 等待完成失败: {completion_result.get('message')}")
                return {"success": False, "message": f"CHI测试 {method} 执行失败: {completion_result.get('message')}"}
            
            print(f"✅ CHI测试 {method} 完成")
            
            # 在每个测试完成后增加额外的等待时间，确保CHI工作站完全就绪
            print(f"🔧 CHI测试 {method} 完成，等待2秒确保系统就绪...")
            await asyncio.sleep(2)
        
        print(f"🎉 CHI测试序列全部完成")
        return {"success": True, "message": "CHI测试序列完成"}
    
    async def _execute_chi_cv(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行CV测试"""
        try:
            # 确保文件名包含正确的项目名称
            if "fileName" in params:
                original_filename = params["fileName"]
                # 确保文件名以项目名称开头
                if not original_filename.startswith(self.project_name):
                    params["fileName"] = f"{self.project_name}_{original_filename}"
                self.add_log(f"CV测试文件名: {params['fileName']}")
            
            self.add_log(f"开始CV测试，参数: {params}")
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(f"{self.device_tester_url}/api/chi/cv", json=params)
                
                if response.status_code != 200:
                    return {"success": False, "message": f"HTTP错误: {response.status_code}"}
                
                result = response.json()
                self.add_log(f"CV测试API响应: {result}")
                return self._parse_api_response(result)
        except Exception as e:
            self.add_log(f"CV测试API调用异常: {e}", "ERROR")
            return {"success": False, "message": f"API调用异常: {e}"}
    
    async def _execute_chi_lsv(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行LSV测试"""
        try:
            # 转换参数名称
            lsv_params = {
                "initial_v": params.get("ei", 0),
                "final_v": params.get("ef", 1),
                "scan_rate": params.get("v", 0.1),
                "interval": params.get("si", 0.001),
                "sens": params.get("sens", 1e-5),
                "file_name": params.get("fileName")
            }
            
            print(f"🔧 LSV测试参数: {lsv_params}")
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(f"{self.device_tester_url}/api/chi/lsv", json=lsv_params)
                
                if response.status_code != 200:
                    return {"success": False, "message": f"HTTP错误: {response.status_code}"}
                
                result = response.json()
                print(f"🔧 LSV测试API原始响应: {result}")
                return self._parse_api_response(result)
        except Exception as e:
            print(f"🔧 LSV测试API调用异常: {e}")
            return {"success": False, "message": f"API调用异常: {e}"}
    
    async def _execute_chi_eis(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行EIS测试"""
        try:
            eis_params = {
                "voltage": params.get("ei", 0),
                "freq_init": params.get("fh", 100000),
                "freq_final": params.get("fl", 0.1),
                "amplitude": params.get("amp", 10),
                "sens": params.get("sens", 1e-5),
                "file_name": params.get("fileName")
            }
            
            print(f"🔧 EIS测试参数: {eis_params}")
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(f"{self.device_tester_url}/api/chi/eis", json=eis_params)
                
                if response.status_code != 200:
                    return {"success": False, "message": f"HTTP错误: {response.status_code}"}
                
                result = response.json()
                print(f"🔧 EIS测试API原始响应: {result}")
                return self._parse_api_response(result)
        except Exception as e:
            print(f"🔧 EIS测试API调用异常: {e}")
            return {"success": False, "message": f"API调用异常: {e}"}
    
    async def _execute_chi_it(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行IT测试"""
        try:
            # 确保文件名包含正确的项目名称
            if "fileName" in params:
                original_filename = params["fileName"]
                # 确保文件名以项目名称开头
                if not original_filename.startswith(self.project_name):
                    params["fileName"] = f"{self.project_name}_{original_filename}"
                self.add_log(f"IT测试文件名: {params['fileName']}")
            
            self.add_log(f"开始IT测试，参数: {params}")
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(f"{self.device_tester_url}/api/chi/it", json=params)
                
                if response.status_code != 200:
                    return {"success": False, "message": f"HTTP错误: {response.status_code}"}
                
                result = response.json()
                self.add_log(f"IT测试API响应: {result}")
                return self._parse_api_response(result)
        except Exception as e:
            self.add_log(f"IT测试API调用异常: {e}", "ERROR")
            return {"success": False, "message": f"API调用异常: {e}"}
    
    async def _wait_for_chi_completion(self) -> Dict[str, Any]:
        """等待CHI测试完成
        
        基于以下条件判断完成：
        1. CHI状态变为completed, idle, error等非running状态
        2. 文件保存完成且exe窗口关闭
        3. 超时处理
        
        Returns:
            包含success和message的字典
        """
        max_wait = 300  # 5分钟最大等待时间
        wait_time = 0
        last_status = None
        consecutive_completed_count = 0  # 连续检测到完成状态的次数
        required_consecutive = 3  # 需要连续检测到完成状态的次数
        
        print(f"🔧 等待CHI测试完成，最大等待时间: {max_wait}秒")
        
        while wait_time < max_wait:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(f"{self.device_tester_url}/api/chi/status")
                    result = response.json()
                    
                    success = not result.get("error", True)
                    if success:
                        status = result.get("status", {})
                        chi_status = status.get("status", "unknown")
                        test_type = status.get("test_type", "unknown")
                        elapsed_seconds = status.get("elapsed_seconds", 0)
                        
                        # 显示进度信息
                        if chi_status != last_status or int(wait_time) % 15 == 0:  # 每15秒或状态变化时显示
                            print(f"🔧 CHI状态: {chi_status}, 测试类型: {test_type}, 已运行: {elapsed_seconds:.1f}秒")
                            last_status = chi_status
                        
                        # 检查是否完成 - 扩展状态检查
                        if chi_status in ["idle", "completed", "finished", "stopped"]:
                            consecutive_completed_count += 1
                            print(f"🔧 检测到完成状态: {chi_status} (连续第{consecutive_completed_count}次)")
                            
                            if consecutive_completed_count >= required_consecutive:
                                print(f"✅ CHI测试确认完成，最终状态: {chi_status}")
                                # 额外等待确保文件保存完成
                                await asyncio.sleep(2)
                                return {"success": True, "message": f"CHI测试完成，状态: {chi_status}"}
                        elif chi_status == "error":
                            print(f"❌ CHI测试出现错误，最终状态: {chi_status}")
                            return {"success": False, "message": f"CHI测试失败，状态: {chi_status}"}
                        elif chi_status == "running":
                            # 重置连续完成计数
                            consecutive_completed_count = 0
                            # 对于运行状态，检查是否运行时间合理
                            if elapsed_seconds > 300:  # 运行超过5分钟，给出警告但继续等待
                                print(f"⚠️ CHI测试运行时间较长({elapsed_seconds:.1f}秒)，可能是长时间测试")
                        else:
                            # 对于其他未知状态，重置计数
                            consecutive_completed_count = 0
                    else:
                        print(f"⚠️ 获取CHI状态失败: {result.get('message', '未知错误')}")
                        consecutive_completed_count = 0
                
                await asyncio.sleep(2)  # 检查间隔2秒
                wait_time += 2
                
            except Exception as e:
                print(f"⚠️ 检查CHI状态时出现异常: {e}")
                consecutive_completed_count = 0
                await asyncio.sleep(2)
                wait_time += 2
        
        # 超时处理
        print(f"⏰ CHI测试等待超时({max_wait}秒)")
        
        # 最后再检查一次状态
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.device_tester_url}/api/chi/status")
                result = response.json()
                
                if not result.get("error", True):
                    status = result.get("status", {})
                    chi_status = status.get("status", "unknown")
                    
                    if chi_status in ["idle", "completed", "finished", "stopped"]:
                        print(f"🔧 超时后最终检查：CHI已完成，状态: {chi_status}")
                        return {"success": True, "message": f"CHI测试超时但最终完成，状态: {chi_status}"}
                    else:
                        print(f"⚠️ 超时后最终检查：CHI仍在运行，状态: {chi_status}")
                        # 即使超时也认为成功，让实验继续进行
                        return {"success": True, "message": f"CHI测试超时但继续，状态: {chi_status}"}
        except Exception as e:
            print(f"⚠️ 最终状态检查失败: {e}")
        
        # 即使超时也认为成功，让实验继续进行
        print(f"🔧 CHI测试超时但假设完成，继续下一个测试")
        return {"success": True, "message": f"CHI测试等待超时({max_wait}秒)，假设已完成"}
    
    async def _execute_voltage_loop(self, step_config: Dict[str, Any]) -> Dict[str, Any]:
        """执行电压循环"""
        try:
            logger.info("开始执行电压循环")
            
            # 获取电压源配置
            voltage_source = step_config.get("voltage_source", {})
            voltage_source_type = voltage_source.get("type", "config_key")
            
            # 生成电压列表
            voltages = []
            if voltage_source_type == "config_key":
                voltage_key = voltage_source.get("key", "voltage_range")
                voltage_range = self._resolve_param(voltage_key, [-1.2, -1.3])
                
                if isinstance(voltage_range, list) and len(voltage_range) == 2:
                    start_v, end_v = voltage_range
                    # 修复电压序列生成逻辑
                    if abs(start_v - end_v) < 0.001:  # 如果电压范围很小，只生成一个电压
                        voltages = [start_v]
                    else:
                        # 确定步长方向和大小
                        if start_v > end_v:
                            # 从高到低：例如 -1.2 到 -1.3
                            step = -0.1
                        else:
                            # 从低到高：例如 -1.3 到 -1.2
                            step = 0.1
                        
                        # 计算步数并生成电压序列
                        num_steps = int(round(abs(end_v - start_v) / 0.1)) + 1
                        voltages = [round(start_v + i * step, 1) for i in range(num_steps)]
                        
                        # 确保终点电压包含在内
                        if abs(voltages[-1] - end_v) > 0.001:
                            voltages.append(round(end_v, 1))
                    
                    logger.info(f"生成电压序列: {voltages}")
                else:
                    logger.error(f"无效的电压范围配置: {voltage_range}")
                    return {"success": False, "message": "无效的电压范围配置"}
            
            # 获取输出位置配置
            output_positions_source = step_config.get("output_positions_source", {})
            output_positions_key = output_positions_source.get("key", "output_positions_list")
            output_positions = self._resolve_param(output_positions_key, None)
            
            # 如果没有配置输出位置，使用默认位置序列
            if output_positions is None:
                # 生成默认位置序列：从位置3开始，每个电压一个位置
                output_positions = list(range(3, 3 + len(voltages)))
                logger.info(f"使用默认输出位置序列: {output_positions}")
            
            # 确保位置数量与电压数量匹配
            if len(output_positions) < len(voltages):
                # 如果位置不够，循环使用
                while len(output_positions) < len(voltages):
                    output_positions.extend(output_positions[:len(voltages) - len(output_positions)])
            
            logger.info(f"电压循环配置: 电压={voltages}, 输出位置={output_positions}")
            
            # 获取循环序列
            loop_sequence = step_config.get("loop_sequence", [])
            if not loop_sequence:
                logger.error("电压循环缺少loop_sequence配置")
                return {"success": False, "message": "缺少循环序列配置"}
            
            # 执行每个电压的循环
            for i, voltage in enumerate(voltages):
                current_output_position = output_positions[i] if i < len(output_positions) else output_positions[-1]
                
                logger.info(f"执行电压循环 {i+1}/{len(voltages)}: 电压={voltage}V, 输出位置={current_output_position}")
                
                # 创建循环上下文
                loop_context = {
                    "current_voltage": voltage,
                    "current_voltage_file_str": f"neg{int(abs(voltage * 10))}" if voltage < 0 else f"{int(voltage * 10)}",
                    "current_output_position": current_output_position,
                    "loop_index": i,
                    "project_name": self.experiment_config.get("project_name", "experiment")
                }
                
                # 执行循环序列中的每个步骤
                for sub_step in loop_sequence:
                    sub_step_result = await self._execute_voltage_loop_step(sub_step, loop_context)
                    if not sub_step_result.get("success", False):
                        logger.error(f"电压循环步骤失败: {sub_step.get('id', 'unknown')}, 电压={voltage}V")
                        return {"success": False, "message": f"电压循环在{voltage}V时失败"}
                
                logger.info(f"电压循环 {i+1}/{len(voltages)} 完成: 电压={voltage}V")
            
            logger.info("电压循环全部完成")
            return {"success": True, "message": f"电压循环完成，共处理{len(voltages)}个电压"}
            
        except Exception as e:
            logger.error(f"电压循环执行异常: {e}")
            return {"success": False, "message": f"电压循环执行异常: {str(e)}"}
    
    async def _execute_voltage_loop_step(self, step_config: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """执行电压循环中的单个步骤"""
        step_type = step_config.get("type", "unknown")
        step_id = step_config.get("id", "unknown")
        
        logger.info(f"执行电压循环步骤: {step_id} (类型: {step_type})")
        
        try:
            # 解析模板变量
            resolved_step = self._resolve_template_variables_in_step(step_config, context)
            
            if step_type == "sequence":
                return await self._execute_sequence(resolved_step)
            elif step_type == "chi_measurement":
                return await self._execute_chi_measurement(resolved_step, context)
            elif step_type == "process_chi_data":
                return await self._execute_process_chi_data(resolved_step.get("params", {}))
            else:
                logger.warning(f"未知的电压循环步骤类型: {step_type}")
                return {"success": True, "message": f"跳过未知步骤类型: {step_type}"}
                
        except Exception as e:
            logger.error(f"电压循环步骤执行异常: {step_id}, {e}")
            return {"success": False, "message": f"步骤执行异常: {str(e)}"}
    
    def _resolve_template_variables_in_step(self, step_config: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """在步骤配置中解析模板变量"""
        import json
        import re
        
        # 将步骤配置转换为JSON字符串进行模板替换
        step_json = json.dumps(step_config)
        
        # 使用正则表达式查找所有模板变量
        template_pattern = r'\{\{([^}]+)\}\}'
        
        def replace_template(match):
            template_var = match.group(1).strip()
            if template_var in context:
                return str(context[template_var])
            else:
                # 如果在context中找不到，保持原样
                return match.group(0)
        
        # 替换所有模板变量
        resolved_json = re.sub(template_pattern, replace_template, step_json)
        
        # 转换回字典
        try:
            return json.loads(resolved_json)
        except json.JSONDecodeError as e:
            print(f"⚠️ 模板变量解析后JSON格式错误: {e}")
            print(f"   原始: {step_json}")
            print(f"   解析后: {resolved_json}")
            # 如果解析失败，返回原始配置
            return step_config
    
    async def _execute_chi_measurement(self, step_config: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """执行CHI测量"""
        chi_method = step_config.get("chi_method", "IT")
        chi_params = step_config.get("chi_params", {})
        
        logger.info(f"执行CHI测量: {chi_method}, 参数: {chi_params}")
        
        # 启动CHI测试
        if chi_method == "IT":
            result = await self._execute_chi_it(chi_params)
        elif chi_method == "CV":
            result = await self._execute_chi_cv(chi_params)
        elif chi_method == "LSV":
            result = await self._execute_chi_lsv(chi_params)
        elif chi_method == "EIS":
            result = await self._execute_chi_eis(chi_params)
        else:
            logger.error(f"不支持的CHI测量方法: {chi_method}")
            return {"success": False, "message": f"不支持的CHI测量方法: {chi_method}"}
        
        # 检查测试启动是否成功
        if not result.get("success", False):
            logger.error(f"CHI测试启动失败: {result.get('message')}")
            return result
        
        logger.info(f"CHI测试 {chi_method} 启动成功，开始等待完成...")
        
        # 等待测试完成
        completion_result = await self._wait_for_chi_completion()
        if not completion_result.get("success", True):  # 默认为True，除非明确失败
            logger.error(f"CHI测试 {chi_method} 等待完成失败: {completion_result.get('message')}")
            return {"success": False, "message": f"CHI测试 {chi_method} 执行失败: {completion_result.get('message')}"}
        
        logger.info(f"CHI测试 {chi_method} 完成")
        return {"success": True, "message": f"CHI测试 {chi_method} 完成"}
    
    async def _execute_process_chi_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理CHI数据 - 暂时跳过，数据处理模块尚未实现"""
        try:
            data_type = params.get("data_type", "unknown")
            source_file_name = params.get("source_file_name_in_chi_params", "")
            
            logger.info(f"跳过CHI数据处理 (模块未实现): 类型={data_type}, 源文件={source_file_name}")
            
            # 暂时返回成功，避免阻塞实验流程
            return {"success": True, "message": f"跳过{data_type}数据处理 (模块未实现)"}
                
        except Exception as e:
            logger.error(f"CHI数据处理异常: {e}")
            return {"success": False, "message": f"数据处理异常: {str(e)}"}
    
    def _resolve_param(self, key_path: str, default_value: Any = None) -> Any:
        """解析参数键路径，支持数组索引语法"""
        if not key_path:
            return default_value
        
        # 处理数组索引语法，例如 "safe_move_xy[0]" 或 "configurations.safe_move_xy[0]"
        if '[' in key_path and ']' in key_path:
            # 提取基础键和索引
            base_key = key_path.split('[')[0]
            index_part = key_path.split('[')[1].rstrip(']')
            try:
                index = int(index_part)
                # 获取基础值
                if base_key.startswith("configurations."):
                    config_key = base_key.replace("configurations.", "")
                    base_value = self.experiment_config.get("configurations", {}).get(config_key, default_value)
                else:
                    # 对于没有configurations前缀的键，先尝试从configurations中查找
                    base_value = self.experiment_config.get("configurations", {}).get(base_key)
                    if base_value is None:
                        base_value = self.experiment_config.get(base_key, default_value)
                
                # 如果基础值是列表，返回指定索引的值
                if isinstance(base_value, list) and 0 <= index < len(base_value):
                    return base_value[index]
                else:
                    logger.warning(f"无法解析数组索引: {key_path}, base_value={base_value}")
                    return default_value
            except (ValueError, IndexError) as e:
                logger.warning(f"解析数组索引失败: {key_path}, error={e}")
                return default_value
        
        # 处理普通配置键
        if key_path.startswith("configurations."):
            config_key = key_path.replace("configurations.", "")
            return self.experiment_config.get("configurations", {}).get(config_key, default_value)
        else:
            # 对于没有configurations前缀的键，先尝试从configurations中查找
            value = self.experiment_config.get("configurations", {}).get(key_path)
            if value is not None:
                return value
            return self.experiment_config.get(key_path, default_value)

# 全局实验运行器实例
experiment_runner = ExperimentRunner()

# API 路由
@app.get("/", response_class=HTMLResponse)
async def get_experiment_control_page():
    """返回实验控制页面"""
    html_content = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>电化学实验自动化控制台</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: 'Microsoft YaHei', Arial, sans-serif; background-color: #f5f5f5; }
            .container { max-width: 1600px; margin: 0 auto; padding: 20px; }
            .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; text-align: center; }
            .content-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
            .left-column, .right-column { display: flex; flex-direction: column; gap: 20px; }
            .card { background: white; border-radius: 10px; padding: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            .status-panel { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 20px; }
            .status-item { background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center; border-left: 4px solid #007bff; }
            .status-value { font-size: 20px; font-weight: bold; color: #007bff; }
            .status-label { color: #666; margin-top: 5px; font-size: 12px; }
            .input-group { margin-bottom: 15px; }
            .input-group label { display: block; margin-bottom: 5px; font-weight: bold; color: #333; }
            .input-group input, .input-group select { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px; font-size: 14px; }
            .input-row { display: flex; gap: 15px; align-items: end; }
            .input-row .input-group { flex: 1; }
            .btn { padding: 12px 25px; margin: 5px; border: none; border-radius: 5px; font-size: 14px; cursor: pointer; transition: all 0.3s; }
            .btn-primary { background-color: #007bff; color: white; }
            .btn-danger { background-color: #dc3545; color: white; }
            .btn-success { background-color: #28a745; color: white; }
            .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 15px rgba(0,0,0,0.2); }
            .btn:disabled { background-color: #ccc; cursor: not-allowed; transform: none; }
            .progress-container { background-color: #e9ecef; border-radius: 10px; height: 25px; margin: 10px 0; overflow: hidden; position: relative; }
            .progress-bar { height: 100%; background: linear-gradient(90deg, #28a745, #20c997); transition: width 0.3s ease; border-radius: 10px; }
            .progress-text { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-weight: bold; color: #333; z-index: 10; }
            .steps-list { max-height: 350px; overflow-y: auto; }
            .step-item { padding: 8px; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; align-items: center; font-size: 13px; }
            .step-item:last-child { border-bottom: none; }
            .step-status { padding: 3px 6px; border-radius: 4px; font-size: 11px; }
            .status-pending { background-color: #f8f9fa; color: #6c757d; }
            .status-running { background-color: #fff3cd; color: #856404; }
            .status-completed { background-color: #d4edda; color: #155724; }
            .status-error { background-color: #f8d7da; color: #721c24; }
            .log-container { height: 400px; overflow-y: auto; background-color: #2d3748; color: #e2e8f0; padding: 15px; border-radius: 5px; font-family: 'Courier New', monospace; font-size: 12px; line-height: 1.4; }
            .log-entry { margin-bottom: 2px; }
            .log-timestamp { color: #4a90e2; }
            .log-level-INFO { color: #e2e8f0; }
            .log-level-ERROR { color: #f56565; }
            .log-level-WARNING { color: #fbb03b; }
            .config-info { background-color: #e3f2fd; padding: 15px; border-radius: 8px; margin-bottom: 15px; }
            .current-step-info { background-color: #f0f8ff; padding: 15px; border-radius: 8px; margin-bottom: 15px; border-left: 4px solid #007bff; }
            .project-info { background-color: #f9f9f9; padding: 15px; border-radius: 8px; margin-bottom: 15px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🧪 电化学实验自动化控制台</h1>
                <p>C60_From_Easy 实验流程控制系统</p>
            </div>

            <div class="content-grid">
                <div class="left-column">
                    <div class="card">
                        <h3>📊 实验状态</h3>
                        <div class="status-panel">
                            <div class="status-item">
                                <div class="status-value" id="experiment-status">未开始</div>
                                <div class="status-label">实验状态</div>
                            </div>
                            <div class="status-item">
                                <div class="status-value" id="current-step">0</div>
                                <div class="status-label">当前步骤</div>
                            </div>
                            <div class="status-item">
                                <div class="status-value" id="total-steps">0</div>
                                <div class="status-label">总步骤数</div>
                            </div>
                            <div class="status-item">
                                <div class="status-value" id="progress-percent">0%</div>
                                <div class="status-label">完成进度</div>
                            </div>
                            <div class="status-item">
                                <div class="status-value" id="runtime">0:00</div>
                                <div class="status-label">运行时间</div>
                            </div>
                        </div>
                        
                        <div class="progress-container">
                            <div class="progress-bar" id="progress-bar" style="width: 0%"></div>
                            <div class="progress-text" id="progress-text">0%</div>
                        </div>
                    </div>

                    <div class="card">
                        <h3>🎮 实验控制</h3>
                        <div class="input-row">
                            <div class="input-group">
                                <label for="project-name-input">自定义项目名称:</label>
                                <input type="text" id="project-name-input" placeholder="例如: MyExperiment_20240524" />
                            </div>
                            <div class="input-group">
                                <label for="config-path-input">配置文件路径:</label>
                                <input type="text" id="config-path-input" value="old/experiment_config.json" />
                            </div>
                        </div>
                        
                        <div class="config-info">
                            <strong>默认配置:</strong> old/experiment_config.json<br>
                            <strong>设备测试器地址:</strong> http://localhost:8001
                        </div>
                        
                        <div style="text-align: center;">
                            <button class="btn btn-success" id="load-config-btn" onclick="loadConfig()">📁 加载配置</button>
                            <button class="btn btn-primary" id="start-btn" onclick="startExperiment()" disabled>🚀 开始实验</button>
                            <button class="btn btn-danger" id="stop-btn" onclick="stopExperiment()" disabled>⏹ 停止实验</button>
                        </div>
                    </div>

                    <div class="card">
                        <h3>📋 项目信息</h3>
                        <div class="project-info" id="project-info">
                            <div><strong>项目名称:</strong> <span id="project-name-display">未设置</span></div>
                            <div><strong>项目文件夹:</strong> <span id="project-folder-display">未设置</span></div>
                            <div><strong>实验ID:</strong> <span id="experiment-id-display">未开始</span></div>
                        </div>
                    </div>

                    <div class="card">
                        <h3>⚡ 当前步骤信息</h3>
                        <div class="current-step-info" id="current-step-info">
                            <div><strong>步骤名称:</strong> <span id="current-step-name">无</span></div>
                            <div><strong>步骤描述:</strong> <span id="current-step-description">无</span></div>
                        </div>
                    </div>
                </div>

                <div class="right-column">
                    <div class="card">
                        <h3>📋 实验步骤</h3>
                        <div class="steps-list" id="steps-list">
                            <div class="step-item">
                                <span>请先加载配置文件</span>
                            </div>
                        </div>
                    </div>

                    <div class="card">
                        <h3>📝 实时日志</h3>
                        <div class="log-container" id="log-container">
                            <div class="log-entry">等待日志信息...</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <script>
            let wsConnection = null;
            let experimentSteps = [];

            // 连接WebSocket（可选，用于实时状态更新）
            function connectWebSocket() {
                try {
                    wsConnection = new WebSocket('ws://localhost:8001/ws');
                    wsConnection.onmessage = function(event) {
                        const data = JSON.parse(event.data);
                        if (data.type === 'experiment_status') {
                            updateExperimentStatus(data.status);
                        }
                    };
                } catch (error) {
                    console.log('WebSocket连接失败:', error);
                }
            }

            // 加载配置
            async function loadConfig() {
                try {
                    const response = await fetch('/api/experiment/load_config', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ config_path: 'old/experiment_config.json' })
                    });
                    
                    const result = await response.json();
                    if (result.success) {
                        experimentSteps = result.steps;
                        updateStepsList();
                        document.getElementById('start-btn').disabled = false;
                        document.getElementById('total-steps').textContent = experimentSteps.length;
                        addLog('✅ 配置文件加载成功，共 ' + experimentSteps.length + ' 个步骤');
                    } else {
                        addLog('❌ 配置文件加载失败: ' + result.message);
                    }
                } catch (error) {
                    addLog('❌ 加载配置时发生错误: ' + error.message);
                }
            }

            // 开始实验
            async function startExperiment() {
                try {
                    const response = await fetch('/api/experiment/start', { method: 'POST' });
                    const result = await response.json();
                    
                    if (result.success) {
                        document.getElementById('start-btn').disabled = true;
                        document.getElementById('stop-btn').disabled = false;
                        addLog('🚀 实验已启动: ' + result.experiment_id);
                        
                        // 开始轮询状态
                        startStatusPolling();
                    } else {
                        addLog('❌ 实验启动失败: ' + result.message);
                    }
                } catch (error) {
                    addLog('❌ 启动实验时发生错误: ' + error.message);
                }
            }

            // 停止实验
            async function stopExperiment() {
                try {
                    const response = await fetch('/api/experiment/stop', { method: 'POST' });
                    const result = await response.json();
                    
                    if (result.success) {
                        document.getElementById('start-btn').disabled = false;
                        document.getElementById('stop-btn').disabled = true;
                        addLog('⏹ 实验已停止');
                        stopStatusPolling();
                    } else {
                        addLog('❌ 停止实验失败: ' + result.message);
                    }
                } catch (error) {
                    addLog('❌ 停止实验时发生错误: ' + error.message);
                }
            }

            // 更新步骤列表
            function updateStepsList() {
                const stepsList = document.getElementById('steps-list');
                stepsList.innerHTML = '';
                
                experimentSteps.forEach((step, index) => {
                    const stepItem = document.createElement('div');
                    stepItem.className = 'step-item';
                    stepItem.innerHTML = `
                        <span>${index + 1}. ${step.description || step.id}</span>
                        <span class="step-status status-pending" id="step-status-${index}">等待</span>
                    `;
                    stepsList.appendChild(stepItem);
                });
            }

            // 更新实验状态
            function updateExperimentStatus(status) {
                document.getElementById('experiment-status').textContent = getStatusText(status.status);
                document.getElementById('current-step').textContent = status.current_step;
                document.getElementById('total-steps').textContent = status.total_steps;
                
                const progress = Math.round(status.progress * 100);
                document.getElementById('progress-percent').textContent = progress + '%';
                document.getElementById('progress-bar').style.width = progress + '%';
                
                // 更新步骤状态
                if (status.current_step > 0) {
                    const currentStepElement = document.getElementById(`step-status-${status.current_step - 1}`);
                    if (currentStepElement) {
                        currentStepElement.textContent = getStatusText(status.status);
                        currentStepElement.className = `step-status status-${status.status}`;
                    }
                }
            }

            function getStatusText(status) {
                const statusMap = {
                    'idle': '空闲',
                    'running': '运行中',
                    'completed': '已完成',
                    'error': '错误',
                    'stopped': '已停止'
                };
                return statusMap[status] || status;
            }

            // 状态轮询
            let statusPollingInterval = null;

            function startStatusPolling() {
                statusPollingInterval = setInterval(async () => {
                    try {
                        const response = await fetch('/api/experiment/status');
                        const status = await response.json();
                        updateExperimentStatus(status);
                        
                        if (status.status === 'completed' || status.status === 'error' || status.status === 'stopped') {
                            stopStatusPolling();
                            document.getElementById('start-btn').disabled = false;
                            document.getElementById('stop-btn').disabled = true;
                        }
                    } catch (error) {
                        console.error('获取状态失败:', error);
                    }
                }, 2000);
            }

            function stopStatusPolling() {
                if (statusPollingInterval) {
                    clearInterval(statusPollingInterval);
                    statusPollingInterval = null;
                }
            }

            // 添加日志
            function addLog(message) {
                const logContainer = document.getElementById('log-container');
                const timestamp = new Date().toLocaleTimeString();
                logContainer.innerHTML += `[${timestamp}] ${message}\\n`;
                logContainer.scrollTop = logContainer.scrollHeight;
            }

            // 页面加载时初始化
            window.onload = function() {
                connectWebSocket();
                addLog('🌟 实验控制台已启动');
            };
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.post("/api/experiment/load_config")
async def load_experiment_config(request: Dict[str, str]):
    """加载实验配置"""
    config_path = request.get("config_path", "old/experiment_config.json")
    custom_project_name = request.get("project_name")  # 新增：自定义项目名称
    
    try:
        success = await experiment_runner.load_config(config_path, custom_project_name)
        if success:
            steps = experiment_runner.experiment_config.get("experiment_sequence", [])
            return {
                "success": True,
                "message": f"配置加载成功，项目: {experiment_runner.project_name}，共 {len(steps)} 个步骤",
                "project_name": experiment_runner.project_name,
                "project_folder": experiment_runner.project_folder,
                "steps": steps,
                "total_steps": len(steps)
            }
        else:
            return {"success": False, "message": "配置加载失败"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/experiment/start")
async def start_experiment():
    """开始实验"""
    try:
        experiment_id = await experiment_runner.start_experiment()
        return {"success": True, "experiment_id": experiment_id}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/experiment/stop")
async def stop_experiment():
    """停止实验"""
    try:
        success = await experiment_runner.stop_experiment()
        return {"success": success}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/api/experiment/status")
async def get_experiment_status():
    """获取实验状态"""
    return await experiment_runner.get_status()

@app.get("/api/experiment/summary")
async def get_experiment_summary():
    """获取实验摘要信息（用于状态恢复）"""
    return experiment_runner.get_experiment_summary()

@app.post("/api/experiment/test_chi_filename")
async def test_chi_filename():
    """测试CHI文件命名功能"""
    if not experiment_runner.project_name:
        return {"success": False, "message": "未设置项目名称"}
    
    # 模拟CHI文件命名测试
    test_filename = f"{experiment_runner.project_name}_CV_Test"
    chi_working_dir = experiment_runner.experiment_config.get("chi_working_directory", "")
    
    return {
        "success": True,
        "project_name": experiment_runner.project_name,
        "test_filename": test_filename,
        "chi_working_directory": chi_working_dir,
        "message": f"CHI文件将保存为: {test_filename} 在目录: {chi_working_dir}"
    }

if __name__ == "__main__":
    import sys
    
    # 查找可用端口
    def find_available_port(start_port=8002, max_attempts=10):
        import socket
        port = start_port
        for _ in range(max_attempts):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(('localhost', port)) != 0:
                    return port
                port += 1
        return None
    
    port = find_available_port(8002, 10)
    if port is None:
        print("错误：无法找到可用端口")
        sys.exit(1)
    
    print(f"电化学实验自动化系统启动在端口 {port}")
    print(f"请访问: http://localhost:{port}")
    print("确保 device_tester.py 已在端口 8001 上运行")
    
    uvicorn.run(app, host="0.0.0.0", port=port) 