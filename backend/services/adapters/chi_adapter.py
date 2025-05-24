import asyncio
import sys
import os
import logging
import time
import tempfile
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
from pathlib import Path
import json
import glob

from backend.pubsub import Broadcaster
from .base_adapter import BaseAdapter

# 添加项目根目录到系统路径，以便导入device_control
# sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../'))) # REMOVED
from device_control.control_chi import Setup, CV, LSV, CA, IT, OCP, EIS, DPV, SCV, CP, ACV, stop_all

logger = logging.getLogger(__name__)

class CHIStatus:
    """CHI状态常量定义"""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"

class CHIAdapter(BaseAdapter):
    """CHI电化学工作站适配器，监控测试状态并通过WebSocket广播"""
    
    def __init__(self, broadcaster: Broadcaster, 
                 results_base_dir: str = "./experiment_results",
                 chi_path: str = "C:\\CHI760E\\chi760e\\chi760e.exe"):
        """初始化CHI适配器
        
        Args:
            broadcaster: WebSocket广播器
            results_base_dir: 结果文件保存的基础目录
            chi_path: CHI软件可执行文件路径
        """
        super().__init__("CHI电化学工作站")
        self.broadcaster = broadcaster
        self.results_base_dir = os.path.abspath(results_base_dir)
        self.chi_path = chi_path
        self.chi_setup = None
        self.topic = "hardware_status:chi"
        
        # 当前测试状态
        self.current_test = None       # 当前测试类型
        self.current_technique = None  # 当前技术实例
        self.start_time = None         # 开始时间
        self.test_params = None        # 测试参数
        self.file_name = None          # 文件名
        self.project_name = None       # 项目名称
        self.result_files = []         # 生成的结果文件
        
        # 文件监控间隔（秒）
        self.file_check_interval = 2.0
    
    async def initialize(self) -> bool:
        """初始化CHI连接
        
        Returns:
            连接是否成功
        """
        try:
            # 创建Setup实例
            self.chi_setup = Setup(path=self.chi_path, folder=self.results_base_dir)
            
            # 确保结果目录存在
            os.makedirs(self.results_base_dir, exist_ok=True)
            
            logger.info(f"CHI初始化成功，结果路径: {self.results_base_dir}")
            await self.update_status({"status": CHIStatus.IDLE})
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"CHI初始化失败: {e}", exc_info=True)
            return False
    
    async def get_status(self) -> Dict[str, Any]:
        """获取当前CHI状态
        
        Returns:
            包含CHI状态的字典
        """
        status = self._status.copy()
        
        # 如果正在运行测试，添加测试时间信息
        if self.start_time and self._status.get("status") == CHIStatus.RUNNING:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            status["elapsed_seconds"] = elapsed
            
        return status
    
    async def run_cv_test(self, file_name: str, params: Dict[str, Any]) -> bool:
        """运行循环伏安法测试
        
        Args:
            file_name: 保存结果的文件名
            params: 测试参数字典，包含CV所需的所有参数
            
        Returns:
            测试是否成功启动
        """
        if not self.chi_setup:
            logger.error("CHI未初始化")
            return False
            
        try:
            # 如果当前有测试正在运行，先停止
            if self._status.get("status") == CHIStatus.RUNNING:
                await self.stop_test()
            
            # 设置测试参数
            self.current_test = "CV"
            self.file_name = file_name
            self.test_params = params
            self.start_time = datetime.now()
            self.result_files = []
            
            # 创建CV实例
            cv = CV(
                ei=params.get("ei", 0),
                eh=params.get("eh", 1),
                el=params.get("el", -1),
                v=params.get("v", 0.1),
                si=params.get("si", 0.001),
                cl=params.get("cl", 2),
                sens=params.get("sens", 1e-5),
                qt=params.get("qt", 2),
                pn=params.get("pn", 'p'),
                fileName=file_name,
                autosens=params.get("autosens", False)
            )
            
            # 保存技术实例，用于后续停止
            self.current_technique = cv
            
            # 启动测试
            cv.run()
            
            # 更新状态
            await self.update_status({
                "status": CHIStatus.RUNNING,
                "test_type": "CV",
                "file_name": file_name,
                "params": params,
                "start_time": self.start_time.isoformat()
            })
            
            logger.info(f"CV测试启动成功: {file_name}")
            
            # 启动监控循环前确保监控标志设置为True
            self.monitoring = True
            asyncio.create_task(self._monitor_loop())
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"CV测试启动失败: {e}", exc_info=True)
            await self.update_status({
                "status": CHIStatus.ERROR,
                "error": str(e)
            })
            return False
    
    async def run_lsv_test(self, file_name: str, params: Dict[str, Any]) -> bool:
        """运行线性扫描伏安法测试
        
        Args:
            file_name: 保存结果的文件名
            params: 测试参数字典，包含LSV所需的所有参数
            
        Returns:
            测试是否成功启动
        """
        if not self.chi_setup:
            logger.error("CHI未初始化")
            return False
            
        try:
            # 如果当前有测试正在运行，先停止
            if self._status.get("status") == CHIStatus.RUNNING:
                await self.stop_test()
            
            # 设置测试参数
            self.current_test = "LSV"
            self.file_name = file_name
            self.test_params = params
            self.start_time = datetime.now()
            self.result_files = []
            
            # 创建LSV实例
            lsv = LSV(
                ei=params.get("ei", 0),
                ef=params.get("ef", 1),
                v=params.get("v", 0.1),
                si=params.get("si", 0.001),
                sens=params.get("sens", 1e-5),
                qt=params.get("qt", 2),
                fileName=file_name
            )
            
            # 保存技术实例，用于后续停止
            self.current_technique = lsv
            
            # 启动测试
            lsv.run()
            
            # 更新状态
            await self.update_status({
                "status": CHIStatus.RUNNING,
                "test_type": "LSV",
                "file_name": file_name,
                "params": params,
                "start_time": self.start_time.isoformat()
            })
            
            logger.info(f"LSV测试启动成功: {file_name}")
            
            # 启动监控循环前确保监控标志设置为True
            self.monitoring = True
            asyncio.create_task(self._monitor_loop())
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"LSV测试启动失败: {e}", exc_info=True)
            await self.update_status({
                "status": CHIStatus.ERROR,
                "error": str(e)
            })
            return False
    
    async def run_it_test(self, file_name: str, params: Dict[str, Any]) -> bool:
        """运行i-t曲线测试
        
        Args:
            file_name: 保存结果的文件名
            params: 测试参数字典，包含IT所需的所有参数
            
        Returns:
            测试是否成功启动
        """
        if not self.chi_setup:
            logger.error("CHI未初始化")
            return False
            
        try:
            # 如果当前有测试正在运行，先停止
            if self._status.get("status") == CHIStatus.RUNNING:
                await self.stop_test()
            
            # 设置测试参数
            self.current_test = "IT"
            self.file_name = file_name
            self.test_params = params
            self.start_time = datetime.now()
            self.result_files = []
            
            # 创建IT实例
            it = IT(
                ei=params.get("ei", 0),
                si=params.get("si", 0.05),
                st=params.get("st", 60),
                sens=params.get("sens", 1e-5),
                qt=params.get("qt", 2),
                fileName=file_name
            )
            
            # 保存技术实例，用于后续停止
            self.current_technique = it
            
            # 启动测试
            it.run()
            
            # 更新状态
            await self.update_status({
                "status": CHIStatus.RUNNING,
                "test_type": "IT",
                "file_name": file_name,
                "params": params,
                "start_time": self.start_time.isoformat()
            })
            
            logger.info(f"IT测试启动成功: {file_name}")
            
            # 启动监控循环前确保监控标志设置为True
            self.monitoring = True
            asyncio.create_task(self._monitor_loop())
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"IT测试启动失败: {e}", exc_info=True)
            await self.update_status({
                "status": CHIStatus.ERROR,
                "error": str(e)
            })
            return False
    
    async def run_ca_test(self, file_name: str, params: Dict[str, Any]) -> bool:
        """运行计时安培法测试
        
        Args:
            file_name: 保存结果的文件名
            params: 测试参数字典，包含CA所需的所有参数
            
        Returns:
            测试是否成功启动
        """
        if not self.chi_setup:
            logger.error("CHI未初始化")
            return False
            
        try:
            # 如果当前有测试正在运行，先停止
            if self._status.get("status") == CHIStatus.RUNNING:
                await self.stop_test()
            
            # 设置测试参数
            self.current_test = "CA"
            self.file_name = file_name
            self.test_params = params
            self.start_time = datetime.now()
            self.result_files = []
            
            # 创建CA实例
            ca = CA(
                ei=params.get("ei", 0),
                eh=params.get("eh", 0.5),
                el=params.get("el", -0.5),
                cl=params.get("cl", 2),
                pw=params.get("pw", 0.5),
                si=params.get("si", 0.001),
                sens=params.get("sens", 1e-5),
                qt=params.get("qt", 2),
                pn=params.get("pn", 'p'),
                fileName=file_name,
                autosens=params.get("autosens", False)
            )
            
            # 保存技术实例，用于后续停止
            self.current_technique = ca
            
            # 启动测试
            ca.run()
            
            # 更新状态
            await self.update_status({
                "status": CHIStatus.RUNNING,
                "test_type": "CA",
                "file_name": file_name,
                "params": params,
                "start_time": self.start_time.isoformat()
            })
            
            logger.info(f"CA测试启动成功: {file_name}")
            
            # 启动监控循环前确保监控标志设置为True
            self.monitoring = True
            asyncio.create_task(self._monitor_loop())
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"CA测试启动失败: {e}", exc_info=True)
            await self.update_status({
                "status": CHIStatus.ERROR,
                "error": str(e)
            })
            return False
    
    async def run_eis_test(self, file_name: str, params: Dict[str, Any]) -> bool:
        """运行电化学阻抗谱测试
        
        Args:
            file_name: 保存结果的文件名
            params: 测试参数字典，包含EIS所需的所有参数
            
        Returns:
            测试是否成功启动
        """
        if not self.chi_setup:
            logger.error("CHI未初始化")
            return False
            
        try:
            # 如果当前有测试正在运行，先停止
            if self._status.get("status") == CHIStatus.RUNNING:
                await self.stop_test()
            
            # 设置测试参数
            self.current_test = "EIS"
            self.file_name = file_name
            self.test_params = params
            self.start_time = datetime.now()
            self.result_files = []
            
            # 创建EIS实例
            eis = EIS(
                ei=params.get("ei", 0),
                fl=params.get("fl", 0.1),
                fh=params.get("fh", 100000),
                amp=params.get("amp", 0.01),
                sens=params.get("sens", 1e-5),
                qt=params.get("qt", 2),
                fileName=file_name
            )
            
            # 保存技术实例，用于后续停止
            self.current_technique = eis
            
            # 启动测试
            eis.run()
            
            # 更新状态
            await self.update_status({
                "status": CHIStatus.RUNNING,
                "test_type": "EIS",
                "file_name": file_name,
                "params": params,
                "start_time": self.start_time.isoformat()
            })
            
            logger.info(f"EIS测试启动成功: {file_name}")
            
            # 启动监控循环前确保监控标志设置为True
            self.monitoring = True
            asyncio.create_task(self._monitor_loop())
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"EIS测试启动失败: {e}", exc_info=True)
            await self.update_status({
                "status": CHIStatus.ERROR,
                "error": str(e)
            })
            return False
    
    async def run_ocp_test(self, file_name: str, params: Dict[str, Any]) -> bool:
        """运行开路电位测试 (OCP)
        
        Args:
            file_name: 保存结果的文件名
            params: 测试参数字典，包含OCP所需的所有参数
            
        Returns:
            测试是否成功启动
        """
        if not self.chi_setup:
            logger.error("CHI未初始化")
            return False
            
        try:
            # 如果当前有测试正在运行，先停止
            if self._status.get("status") == CHIStatus.RUNNING:
                await self.stop_test()
            
            # 设置测试参数
            self.current_test = "OCP"
            self.file_name = file_name
            self.test_params = params
            self.start_time = datetime.now()
            self.result_files = []
            
            # 从params中提取OCP参数，如果不存在则使用OCP类中的默认值
            ocp_params = {
                "st": params["st"], # st 是必需的
                "si": params["si"], # si 是必需的
            }
            if "eh" in params and params["eh"] is not None:
                ocp_params["eh"] = params["eh"]
            if "el" in params and params["el"] is not None:
                ocp_params["el"] = params["el"]
            
            ocp_params["fileName"] = file_name

            # 创建OCP实例
            logger.debug(f"Creating OCP instance with params: {ocp_params}") # DEBUG LOG
            ocp_instance = OCP(**ocp_params)
            
            # 保存技术实例，用于后续停止
            self.current_technique = ocp_instance
            
            # 启动测试
            logger.info(f"Calling run() on OCP instance for {file_name}") # DEBUG LOG
            self.current_technique.run() # 使用 self.current_technique.run()
            logger.info(f"OCP instance run() method called for {file_name}") # DEBUG LOG
            
            # 更新状态
            await self.update_status({
                "status": CHIStatus.RUNNING,
                "test_type": "OCP",
                "file_name": file_name,
                "params": params, # 使用原始传入的params记录
                "start_time": self.start_time.isoformat()
            })
            
            logger.info(f"OCP测试启动成功: {file_name}")
            
            # 启动监控循环前确保监控标志设置为True
            self.monitoring = True
            asyncio.create_task(self._monitor_loop())
            return True
        except KeyError as e:
            error_msg = f"OCP测试启动失败: 缺少必要参数 {e}"
            logger.error(error_msg, exc_info=True)
            await self.update_status({
                "status": CHIStatus.ERROR,
                "error": error_msg
            })
            return False
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"OCP测试启动失败: {e}", exc_info=True)
            await self.update_status({
                "status": CHIStatus.ERROR,
                "error": str(e)
            })
            return False
            
    async def run_dpv_test(self, file_name: str, params: Dict[str, Any]) -> bool:
        """运行差分脉冲伏安法测试 (DPV)
        
        Args:
            file_name: 保存结果的文件名
            params: 测试参数字典，包含DPV所需的所有参数
            
        Returns:
            测试是否成功启动
        """
        if not self.chi_setup:
            logger.error("CHI未初始化")
            return False
            
        try:
            # 如果当前有测试正在运行，先停止
            if self._status.get("status") == CHIStatus.RUNNING:
                await self.stop_test()
            
            # 设置测试参数
            self.current_test = "DPV"
            self.file_name = file_name
            self.test_params = params
            self.start_time = datetime.now()
            self.result_files = []
            
            # 处理参数
            dpv_params = {
                "ei": params.get("ei", 0),
                "ef": params.get("ef", 0.5),
                "incre": params.get("incre", 0.004),
                "amp": params.get("amp", 0.05),
                "pw": params.get("pw", 0.05),
                "sw": params.get("sw", 0.001),
                "prod": params.get("prod", 0.2),
                "sens": params.get("sens", 1e-5),
                "qt": params.get("qt", 2.0),
                "fileName": file_name,
                "autosens": params.get("autosens", False)
            }
            
            # 创建DPV实例
            dpv = DPV(**dpv_params)
            
            # 保存技术实例，用于后续停止
            self.current_technique = dpv
            
            # 启动测试
            dpv.run()
            
            # 更新状态
            await self.update_status({
                "status": CHIStatus.RUNNING,
                "test_type": "DPV",
                "file_name": file_name,
                "params": params,
                "start_time": self.start_time.isoformat()
            })
            
            logger.info(f"DPV测试启动成功: {file_name}")
            
            # 启动监控循环前确保监控标志设置为True
            self.monitoring = True
            asyncio.create_task(self._monitor_loop())
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"DPV测试启动失败: {e}", exc_info=True)
            await self.update_status({
                "status": CHIStatus.ERROR,
                "error": str(e)
            })
            return False
    
    async def run_scv_test(self, file_name: str, params: Dict[str, Any]) -> bool:
        """运行阶梯伏安法测试 (SCV)
        
        Args:
            file_name: 保存结果的文件名
            params: 测试参数字典，包含SCV所需的所有参数
            
        Returns:
            测试是否成功启动
        """
        if not self.chi_setup:
            logger.error("CHI未初始化")
            return False
            
        try:
            # 如果当前有测试正在运行，先停止
            if self._status.get("status") == CHIStatus.RUNNING:
                await self.stop_test()
            
            # 设置测试参数
            self.current_test = "SCV"
            self.file_name = file_name
            self.test_params = params
            self.start_time = datetime.now()
            self.result_files = []
            
            # 处理参数
            scv_params = {
                "ei": params.get("ei", 0),
                "ef": params.get("ef", 0.5),
                "incre": params.get("incre", 0.004),
                "sw": params.get("sw", 0.001),
                "prod": params.get("prod", 0.2),
                "sens": params.get("sens", 1e-5),
                "qt": params.get("qt", 2.0),
                "fileName": file_name,
                "autosens": params.get("autosens", False)
            }
            
            # 创建SCV实例
            scv = SCV(**scv_params)
            
            # 保存技术实例，用于后续停止
            self.current_technique = scv
            
            # 启动测试
            scv.run()
            
            # 更新状态
            await self.update_status({
                "status": CHIStatus.RUNNING,
                "test_type": "SCV",
                "file_name": file_name,
                "params": params,
                "start_time": self.start_time.isoformat()
            })
            
            logger.info(f"SCV测试启动成功: {file_name}")
            
            # 启动监控循环前确保监控标志设置为True
            self.monitoring = True
            asyncio.create_task(self._monitor_loop())
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"SCV测试启动失败: {e}", exc_info=True)
            await self.update_status({
                "status": CHIStatus.ERROR,
                "error": str(e)
            })
            return False
    
    async def run_cp_test(self, file_name: str, params: Dict[str, Any]) -> bool:
        """运行计时电位法测试 (CP)
        
        Args:
            file_name: 保存结果的文件名
            params: 测试参数字典，包含CP所需的所有参数
            
        Returns:
            测试是否成功启动
        """
        if not self.chi_setup:
            logger.error("CHI未初始化")
            return False
            
        try:
            # 如果当前有测试正在运行，先停止
            if self._status.get("status") == CHIStatus.RUNNING:
                await self.stop_test()
            
            # 设置测试参数
            self.current_test = "CP"
            self.file_name = file_name
            self.test_params = params
            self.start_time = datetime.now()
            self.result_files = []
            
            # 生成默认文件名（如果未提供）
            if not file_name:
                file_name = f"CP_Test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                self.file_name = file_name
                
            # 创建CP实例
            cp = CP(
                ic=params.get("ic"),
                ia=params.get("ia"),
                tc=params.get("tc"),
                ta=params.get("ta"),
                eh=params.get("eh", 10.0),
                el=params.get("el", -10.0),
                pn=params.get("pn", 'p'),
                si=params.get("si", 0.1),
                cl=params.get("cl", 1),
                priority=params.get("priority", 'time'),
                fileName=file_name
            )
            
            # 保存技术实例，用于后续停止
            self.current_technique = cp
            
            # 启动测试
            cp.run()
            
            # 更新状态
            await self.update_status({
                "status": CHIStatus.RUNNING,
                "test_type": "CP",
                "file_name": file_name,
                "params": params,
                "start_time": self.start_time.isoformat()
            })
            
            logger.info(f"CP测试启动成功: {file_name}")
            
            # 启动监控循环前确保监控标志设置为True
            self.monitoring = True
            asyncio.create_task(self._monitor_loop())
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"CP测试过程中发生错误: {e}", exc_info=True)
            await self.update_status({
                "status": CHIStatus.ERROR,
                "error": str(e)
            })
            return False
    
    async def run_acv_test(self, file_name: str, params: Dict[str, Any]) -> bool:
        """运行交流伏安法测试 (ACV)
        
        Args:
            file_name: 保存结果的文件名
            params: 测试参数字典，包含ACV所需的所有参数
            
        Returns:
            测试是否成功启动
        """
        if not self.chi_setup:
            logger.error("CHI未初始化")
            return False
            
        try:
            # 如果当前有测试正在运行，先停止
            if self._status.get("status") == CHIStatus.RUNNING:
                await self.stop_test()
                
            # 设置测试参数
            self.current_test = "ACV"
            self.file_name = file_name
            self.test_params = params
            self.start_time = datetime.now()
            self.result_files = []
            
            # 生成默认文件名（如果未提供）
            if not file_name:
                file_name = f"ACV_Test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                self.file_name = file_name
                
            # 创建ACV实例
            acv = ACV(
                ei=params.get("ei"),
                ef=params.get("ef"),
                incre=params.get("incre"),
                amp=params.get("amp"),
                freq=params.get("freq"),
                quiet=params.get("quiet", 2.0),
                sens=params.get("sens", 1e-5),
                fileName=file_name
            )
            
            # 保存技术实例，用于后续停止
            self.current_technique = acv
            
            # 启动测试
            acv.run()
            
            # 更新状态
            await self.update_status({
                "status": CHIStatus.RUNNING,
                "test_type": "ACV",
                "file_name": file_name,
                "params": params,
                "start_time": self.start_time.isoformat()
            })
            
            logger.info(f"ACV测试启动成功: {file_name}")
            
            # 启动监控循环前确保监控标志设置为True
            self.monitoring = True
            asyncio.create_task(self._monitor_loop())
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"ACV测试过程中发生错误: {e}", exc_info=True)
            await self.update_status({
                "status": CHIStatus.ERROR,
                "error": str(e)
            })
            return False
    
    async def stop_test(self) -> bool:
        """停止当前CHI测试
        
        Returns:
            停止操作是否成功
        """
        try:
            # 停止监控循环
            self.monitoring = False
            
            # 如果有当前技术实例，使用其stop方法
            if self.current_technique:
                self.current_technique.stop()
            else:
                # 否则使用全局stop_all
                stop_all()
                
            logger.info("CHI测试已停止")
            
            # 更新状态
            await self.update_status({
                "status": CHIStatus.IDLE,
                "stop_time": datetime.now().isoformat()
            })
            
            # 清理当前测试信息
            self.current_test = None
            self.current_technique = None
            self.file_name = None
            
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"停止CHI测试失败: {e}", exc_info=True)
            return False
    
    async def _monitor_loop(self):
        """CHI状态监控循环，主要用于检测文件变化"""
        logger.info("CHI状态监控开始")
        
        while self.monitoring:
            try:
                # 仅当有测试在运行时进行文件监控
                if self._status.get("status") == CHIStatus.RUNNING and self.file_name:
                    await self._check_result_files()
            except Exception as e:
                logger.error(f"CHI状态监控异常: {e}", exc_info=True)
                
            # 文件检查间隔
            await asyncio.sleep(self.file_check_interval)
            
        logger.info("CHI状态监控停止")
    
    async def _check_result_files(self):
        """检查结果文件变化
        
        检测生成的.txt和.png文件，并发布文件生成事件
        """
        # 只有在有正在运行的测试时才检查
        if not self.file_name or not self.current_test:
            return
            
        try:
            # 检查.txt文件（原始数据）
            txt_pattern = os.path.join(self.results_base_dir, f"{self.file_name}.txt")
            logger.debug(f"_check_result_files: Looking for txt file: {txt_pattern}")
            
            # 检查文件是否存在
            if os.path.exists(txt_pattern):
                txt_file = txt_pattern
                
                # 检查是否是新文件
                if txt_file not in self.result_files:
                    logger.info(f"检测到新的CHI数据文件: {txt_file}")
                    self.result_files.append(txt_file)
                    
                    file_size = os.path.getsize(txt_file)
                    file_mtime = os.path.getmtime(txt_file)
                    
                    # 文件生成事件
                    event_data = {
                        "event_type": "data_file_generated",
                        "file_type": "txt",
                        "file_name": os.path.basename(txt_file),
                        "file_path": txt_file,
                        "file_size": file_size,
                        "modified_time": datetime.fromtimestamp(file_mtime).isoformat(),
                        "test_type": self.current_test
                    }
                    
                    await self.broadcaster.publish(f"{self.topic}:event", event_data)
                    logger.info(f"发布文件生成事件: {os.path.basename(txt_file)}")
                
                # 检查文件是否完成（无论是否是新文件）
                file_size = os.path.getsize(txt_file)
                if file_size > 0:
                    logger.debug(f"文件 {txt_file} 当前大小: {file_size} bytes")
                    
                    # 等待一段时间，确认文件大小不再变化
                    await asyncio.sleep(3)
                    current_size = os.path.getsize(txt_file)
                    logger.debug(f"文件 {txt_file} 等待后大小: {current_size} bytes")
                    
                    if current_size == file_size:
                        # 文件大小稳定，再次检查文件最后修改时间
                        file_mtime = os.path.getmtime(txt_file)
                        time_since_modified = time.time() - file_mtime
                        
                        # 如果文件在过去5秒内没有被修改，认为测试完成
                        if time_since_modified >= 5:
                            logger.info(f"CHI测试完成检测: 文件大小稳定({file_size} bytes)且修改时间稳定({time_since_modified:.1f}s前)")
                            
                            # 更新状态
                            await self.update_status({
                                "status": CHIStatus.COMPLETED,
                                "end_time": datetime.now().isoformat(),
                                "result_file": os.path.basename(txt_file)
                            })
                            
                            # 发布测试完成事件
                            completion_data = {
                                "event_type": "test_completed",
                                "test_type": self.current_test,
                                "file_name": os.path.basename(txt_file),
                                "elapsed_seconds": (datetime.now() - self.start_time).total_seconds() if self.start_time else None
                            }
                            
                            await self.broadcaster.publish(f"{self.topic}:event", completion_data)
                            logger.info(f"发布测试完成事件: {self.current_test}")
                            
                            # 测试完成，停止监控
                            self.monitoring = False
                            
                            # 清理当前测试信息
                            self.current_test = None
                            self.current_technique = None
                            self.file_name = None
                            
                            logger.info(f"CHI测试完成，监控已停止")
                            return  # 提前返回，避免继续检查
                        else:
                            logger.debug(f"文件最近被修改({time_since_modified:.1f}s前)，继续等待")
                    else:
                        logger.debug(f"文件大小仍在变化: {file_size} -> {current_size}")
                else:
                    logger.debug(f"文件 {txt_file} 大小为0，继续等待")
            else:
                logger.debug(f"文件 {txt_pattern} 尚不存在")
            
            # 检查.png文件（图表）
            png_pattern = os.path.join(self.results_base_dir, f"{self.file_name}*.png")
            png_files = glob.glob(png_pattern)
            
            for png_file in png_files:
                # 检查是否是新文件
                if png_file not in self.result_files:
                    self.result_files.append(png_file)
                    
                    # 图表生成事件
                    event_data = {
                        "event_type": "chart_generated",
                        "file_type": "png",
                        "file_name": os.path.basename(png_file),
                        "file_path": png_file,
                        "test_type": self.current_test
                    }
                    
                    await self.broadcaster.publish(f"{self.topic}:event", event_data)
                    logger.info(f"检测到CHI图表文件: {png_file}")
                    
        except Exception as e:
            logger.error(f"检查结果文件异常: {e}", exc_info=True)
    
    async def update_status(self, status_data: Dict[str, Any], topic: Optional[str] = None):
        """更新状态并广播
        
        Args:
            status_data: 状态数据
            topic: 自定义主题，默认使用chi主题
        """
        # 更新内部状态
        self._status.update(status_data)
        
        # 广播到WebSocket
        await self.broadcaster.publish(topic or self.topic, status_data) 