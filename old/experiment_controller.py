import os
import time
import json
import logging
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt # 仍然需要matplotlib来生成图表文件

# 导入你的模块
from core_api.pump_proxy import PumpProxy # 假设路径正确
from core_api.relay_proxy import RelayProxy # 假设路径正确
from device_control.control_printer import PrinterControl # 假设路径正确
from device_control.control_chi import Setup as CHI_Setup, CV, LSV, EIS, IT, OCP, CA, run_sequence as chi_run_sequence, stop_all as chi_stop_all # 假设路径正确
from utils.excel_reporting import ExcelReporter # 假设路径正确
from utils.util_addr import normalize as normalize_moonraker_addr # 假设路径正确

# --- 日志配置 ---
log = logging.getLogger(__name__)
# (在主程序入口处配置日志基础设置)

class ExperimentController:
    def __init__(self, config_file_path: str):
        """
        初始化实验控制器。
        :param config_file_path: JSON配置文件的路径。
        """
        self.config_file_path = config_file_path
        self.config = self._load_config()
        self._configure_logging()

        log.info(f"===== 初始化实验控制器: {self.config.get('project_name', 'DefaultProject')} =====")

        # --- 基本路径和项目名 ---
        self.project_name = self.config['project_name']
        self.base_path = self.config['base_path']
        self.project_path = os.path.join(self.base_path, self.project_name)
        os.makedirs(self.project_path, exist_ok=True)
        log.info(f"项目路径: {self.project_path}")

        # --- Moonraker 和设备代理初始化 ---
        try:
            moonraker_addr = self.config['moonraker_addr']
            host, port, base_url = normalize_moonraker_addr(moonraker_addr)
            self.moonraker_base_url = base_url
            log.info(f"Moonraker 服务地址: {self.moonraker_base_url}")

            self.printer = PrinterControl(ip=host) # PrinterControl只需要IP
            self.pump_proxy = PumpProxy(self.moonraker_base_url)
            self.relay_proxy = RelayProxy(self.moonraker_base_url)

            log.info("尝试连接到 Klipper/Moonraker...")
            test_pos = self.printer.get_current_position()
            if test_pos is None:
                log.error("无法从 Klipper 获取打印机初始位置。请检查连接和 Moonraker 服务。")
                raise ConnectionError("Klipper 连接失败")
            log.info(f"Klipper 连接成功。打印机初始位置: {test_pos}")

        except ConnectionError as e:
            log.critical(f"初始化设备连接失败: {e}")
            raise
        except Exception as e:
            log.critical(f"初始化过程中发生未知错误: {e}", exc_info=True)
            raise

        # --- CHI 电化学工作站设置 ---
        self.chi_setup = CHI_Setup(
            folder=self.project_path,
            path=self.config.get('chi_software_path', 'C:\\CHI760E\\chi760e\\chi760e.exe')
        )
        log.info(f"CHI 电化学配置完成，数据将保存到: {self.project_path}")

        # --- 其他配置参数 ---
        self.position_tolerance = self.config.get('position_tolerance', 0.5)
        self.default_wait_times = self.config.get('default_wait_times', {})
        self.configurations = self.config.get('configurations', {})
        self.experiment_flags = self.config.get('experiment_flags', {})
        self.excel_report_anchors = self.config.get('excel_report_anchors', {}) # Excel锚点

        # --- 电压和输出位置处理 ---
        voltage_range_cfg = self.config['voltage_range']
        if voltage_range_cfg[0] < voltage_range_cfg[1]: # 递增
            self.voltages = np.round(np.arange(voltage_range_cfg[0], voltage_range_cfg[1] + 0.1, 0.1), 1)
        else: # 递减或相等
            start, end = voltage_range_cfg[0], voltage_range_cfg[1]
            # 确保至少有一个点，并且步长近似0.1
            num_points = int(round(abs(end - start) / 0.1)) + 1 if start != end else 1
            self.voltages = np.round(np.linspace(start, end, num_points), 1)
        log.info(f"电压序列: {self.voltages}")

        output_positions_list_cfg = self.config.get('output_positions_list')
        first_experiment_pos_cfg = self.config.get('first_experiment_position', 2)
        if output_positions_list_cfg is None:
            self.output_positions = list(range(first_experiment_pos_cfg, first_experiment_pos_cfg + len(self.voltages)))
        elif len(output_positions_list_cfg) != len(self.voltages):
            log.error("output_positions_list 数量必须与电压点数量相同。")
            raise ValueError("输出位置数量与电压数量不匹配")
        else:
            self.output_positions = output_positions_list_cfg
        log.info(f"样品输出位置序列: {self.output_positions}")
        
        # 将解析后的voltages和output_positions存入configurations，方便模板引用
        self.configurations['voltages_calculated'] = self.voltages.tolist()
        self.configurations['output_positions_calculated'] = self.output_positions

        # --- ExcelReporter 初始化 ---
        self.excel_project_path = os.path.join(self.project_path, f'{self.project_name}_results.xlsx')
        self.excel_central_path = os.path.join(self.base_path, 'ALL_Experiments_Summary.xlsx') # 统一文件名
        try:
            # 从excel_report_anchors创建layout_map
            layout_map = {
                'cv_plot': self.excel_report_anchors.get('project_cv_plot', 'E2'),
                'cv_cdl_plot': self.excel_report_anchors.get('project_cv_cdl_plot', 'J2'),
                'lsv_plot': self.excel_report_anchors.get('project_lsv_plot', 'E16'),
                'it_gallery_start': self.excel_report_anchors.get('project_it_gallery_start', 'E30'),
                'central_cv_plot': self.excel_report_anchors.get('central_cv_plot', 'H2'),
                'central_cv_cdl_plot': self.excel_report_anchors.get('central_cv_cdl_plot', 'L2'),
                'central_lsv_plot': self.excel_report_anchors.get('central_lsv_plot', 'P2'),
                'central_it_gallery_start': self.excel_report_anchors.get('central_it_gallery_start', 'H20')
            }
            
            self.reporter = ExcelReporter(
                project_name=self.project_name,
                project_excel_path=self.excel_project_path,
                central_excel_path=self.excel_central_path,
                voltages_list=self.voltages.tolist(), # ExcelReporter需要列表
                positions_list=[str(p) for p in self.output_positions], # ExcelReporter需要字符串列表
                layout_map=layout_map  # 添加layout_map参数
            )
            log.info("ExcelReporter 初始化成功。")
        except Exception as e_reporter:
            log.error(f"ExcelReporter 初始化失败: {e_reporter}", exc_info=True)
            self.reporter = None
            log.warning("Excel报告模块初始化失败，报告功能可能不可用。")

        self.it_plot_info_list = [] # 用于收集IT图信息给ExcelReporter的图库功能
        self.grid_positions_cache = {} # 用于缓存打印机网格位置的实际XYZ坐标

        log.info("实验控制器初始化完毕。")

    def _load_config(self):
        """加载JSON配置文件"""
        try:
            with open(self.config_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            log.critical(f"配置文件未找到: {self.config_file_path}")
            raise
        except json.JSONDecodeError as e:
            log.critical(f"配置文件解析错误: {self.config_file_path} - {e}")
            raise

    def _configure_logging(self):
        """根据配置设置日志级别"""
        log_level_str = self.config.get("log_level", "INFO").upper()
        numeric_level = getattr(logging, log_level_str, logging.INFO)
        # 假设基础日志配置在主程序入口处完成，这里只调整当前logger级别
        log.setLevel(numeric_level)
        # 可以考虑为其他模块的logger也设置级别

    def _resolve_template(self, template_string: str, context: dict) -> any:
        """
        解析字符串中的模板占位符。
        支持 {{variable}}, {{config.key}}, {{configurations.key}}, {{voltages_calculated[i]}} 等。
        如果模板字符串本身就是一个占位符且解析结果不是字符串（例如数字或列表），则返回原始类型。
        """
        if not isinstance(template_string, str):
            return template_string # 如果不是字符串，直接返回

        original_template = template_string
        
        # 简单检查是否整个字符串就是一个占位符
        is_single_placeholder = template_string.startswith("{{") and template_string.endswith("}}") and template_string.count("{{") == 1

        # 替换 {{config.xxx}} 或 {{configurations.xxx}}
        for config_key_prefix in ["config.", "configurations."]:
            start_idx = 0
            while True:
                match_start = template_string.find("{{" + config_key_prefix, start_idx)
                if match_start == -1:
                    break
                match_end = template_string.find("}}", match_start)
                if match_end == -1:
                    break
                
                full_placeholder = template_string[match_start : match_end+2]
                key_path_str = template_string[match_start+2+len(config_key_prefix) : match_end]
                
                # 支持简单索引，如 key[0]
                key_parts = key_path_str.split('[')
                actual_key = key_parts[0]
                index = None
                if len(key_parts) > 1 and key_parts[1].endswith(']'):
                    try:
                        index = int(key_parts[1][:-1])
                    except ValueError:
                        log.warning(f"模板解析：无法解析索引 '{key_parts[1][:-1]}' 在 '{full_placeholder}'")
                        start_idx = match_end + 2
                        continue
                
                value = self.configurations.get(actual_key)
                if value is not None and index is not None:
                    if isinstance(value, list) and 0 <= index < len(value):
                        value = value[index]
                    else:
                        log.warning(f"模板解析：索引 {index} 超出范围或值不是列表，对于键 '{actual_key}' 在 '{full_placeholder}'")
                        value = full_placeholder # 无法解析，保留原样
                elif value is None:
                     log.warning(f"模板解析：在configurations中未找到键 '{actual_key}' 对于 '{full_placeholder}'")
                     value = full_placeholder # 无法解析，保留原样
                
                if is_single_placeholder and full_placeholder == original_template:
                    return value # 如果是单个占位符，且解析成功，返回原始类型
                template_string = template_string.replace(full_placeholder, str(value))
                start_idx = match_start + len(str(value)) # 更新搜索起始位置
        
        # 替换上下文变量 {{variable}}
        for key, value in context.items():
            placeholder = f"{{{{{key}}}}}"
            if placeholder == original_template and is_single_placeholder:
                 return value # 单个占位符，返回原始类型
            template_string = template_string.replace(placeholder, str(value))
            
        # 替换顶层配置 {{project_name}}, {{base_path}}等
        for key in ["project_name", "base_path", "moonraker_addr"]: # 可扩展
            placeholder = f"{{{{{key}}}}}"
            if placeholder == original_template and is_single_placeholder:
                return self.config.get(key, placeholder)
            template_string = template_string.replace(placeholder, str(self.config.get(key, placeholder)))

        return template_string

    def _parse_params(self, params_config: dict, context: dict) -> dict:
        """解析步骤参数对象，对所有字符串值应用模板解析。"""
        if params_config is None:
            return {}
        parsed_params = {}
        for key, value in params_config.items():
            if isinstance(value, str):
                parsed_params[key] = self._resolve_template(value, context)
            elif isinstance(value, dict):
                parsed_params[key] = self._parse_params(value, context) # 递归解析嵌套字典
            elif isinstance(value, list):
                parsed_params[key] = [self._resolve_template(item, context) if isinstance(item, str) else item for item in value]
            else:
                parsed_params[key] = value
        return parsed_params

    # --- 设备控制的封装方法 (与之前版本类似，但参数从JSON获取) ---
    def _wait_and_log(self, step_params: dict, context: dict):
        """等待并记录日志"""
        wait_duration_key = step_params.get('seconds_key')
        if wait_duration_key:
            wait_duration = self.default_wait_times.get(wait_duration_key, 5.0) # 默认5秒
        else:
            wait_duration = float(step_params.get('seconds', self.default_wait_times.get('default', 1.0)))

        message = step_params.get('message', "等待中...")
        log.info(f"{self._resolve_template(message, context)} 等待 {wait_duration:.1f} 秒...")
        time.sleep(wait_duration)
        return True

    def _log_message(self, step_params: dict, context: dict):
        """记录自定义日志消息"""
        message = self._resolve_template(step_params.get('message', ''), context)
        level_str = step_params.get('level', 'info').upper()
        if level_str == 'INFO':
            log.info(message)
        elif level_str == 'WARNING':
            log.warning(message)
        elif level_str == 'ERROR':
            log.error(message)
        elif level_str == 'DEBUG':
            log.debug(message)
        else:
            log.info(message) # 默认为info
        return True

    def _verify_printer_position(self, expected_x=None, expected_y=None, expected_z=None, grid_position_num=None):
        """验证打印机当前位置，如果网格位置未缓存，则不进行精确XY验证"""
        current_pos_tuple = self.printer.get_current_position()
        if current_pos_tuple is None:
            log.warning("无法获取打印机当前位置进行验证。")
            return False
        current_x, current_y, current_z = current_pos_tuple
        log.debug(f"验证位置: 当前 ({current_x:.2f}, {current_y:.2f}, {current_z:.2f})")

        target_x, target_y, target_z = expected_x, expected_y, expected_z

        if grid_position_num is not None:
            if grid_position_num in self.grid_positions_cache:
                cached_x, cached_y, cached_z = self.grid_positions_cache[grid_position_num]
                target_x, target_y = cached_x, cached_y
                # Z轴通常是固定的，除非特别指定
                if target_z is None : target_z = cached_z if cached_z is not None else self.printer.grid_min_pos[2] # 假设PrinterControl有grid_min_pos
                log.debug(f"网格 {grid_position_num} 缓存目标: (X:{target_x:.2f}, Y:{target_y:.2f}, Z:{target_z:.2f})")
            else:
                # 如果网格位置不在缓存中，我们无法验证XY。只验证Z（如果提供）。
                log.warning(f"网格 {grid_position_num} 不在缓存中。仅验证Z轴（如果提供）。")
                if target_z is not None and abs(current_z - target_z) > self.position_tolerance:
                    log.error(f"Z轴位置错误: 当前 {current_z:.2f}, 预期 {target_z:.2f}")
                    return False
                return True # 无法验证XY，但Z通过或未提供Z

        position_ok = True
        if target_x is not None and abs(current_x - target_x) > self.position_tolerance:
            log.error(f"X轴位置错误: 当前 {current_x:.2f}, 预期 {target_x:.2f}")
            position_ok = False
        if target_y is not None and abs(current_y - target_y) > self.position_tolerance:
            log.error(f"Y轴位置错误: 当前 {current_y:.2f}, 预期 {target_y:.2f}")
            position_ok = False
        if target_z is not None and abs(current_z - target_z) > self.position_tolerance:
            log.error(f"Z轴位置错误: 当前 {current_z:.2f}, 预期 {target_z:.2f}")
            position_ok = False
        return position_ok

    def _safe_printer_move_to_xyz(self, step_params: dict, context: dict):
        """移动打印机到指定XYZ坐标"""
        # 先解析x_key, y_key, z_key的模板，获取实际键名
        x_key = step_params.get('x_key', '')
        y_key = step_params.get('y_key', '')
        z_key = step_params.get('z_key', '')
        
        # 如果直接提供了x, y, z的值，使用它们
        if 'x' in step_params:
            x = float(step_params['x'])
        elif x_key:  # 否则，尝试从配置中解析
            # 从configurations中获取值，支持数组索引，如safe_move_xy[0]
            if '[' in x_key and ']' in x_key:
                base_key, index_str = x_key.split('[', 1)
                index = int(index_str.strip(']'))
                base_value = self.configurations.get(base_key, [])
                if isinstance(base_value, list) and 0 <= index < len(base_value):
                    x = float(base_value[index])
                else:
                    log.error(f"无法从配置中解析x_key: {x_key}，值列表不存在或索引超出范围")
                    return False
            else:
                x = float(self.configurations.get(x_key, 0))
        else:
            log.error("未指定x或x_key")
            return False
            
        # 同样处理y
        if 'y' in step_params:
            y = float(step_params['y'])
        elif y_key:
            if '[' in y_key and ']' in y_key:
                base_key, index_str = y_key.split('[', 1)
                index = int(index_str.strip(']'))
                base_value = self.configurations.get(base_key, [])
                if isinstance(base_value, list) and 0 <= index < len(base_value):
                    y = float(base_value[index])
                else:
                    log.error(f"无法从配置中解析y_key: {y_key}，值列表不存在或索引超出范围")
                    return False
            else:
                y = float(self.configurations.get(y_key, 0))
        else:
            log.error("未指定y或y_key")
            return False
            
        # 同样处理z
        if 'z' in step_params:
            z = float(step_params['z'])
        elif z_key:
            if '[' in z_key and ']' in z_key:
                base_key, index_str = z_key.split('[', 1)
                index = int(index_str.strip(']'))
                base_value = self.configurations.get(base_key, [])
                if isinstance(base_value, list) and 0 <= index < len(base_value):
                    z = float(base_value[index])
                else:
                    log.error(f"无法从配置中解析z_key: {z_key}，值列表不存在或索引超出范围")
                    return False
            else:
                z = float(self.configurations.get(z_key, 0))
        else:
            log.error("未指定z或z_key")
            return False
            
        description = self._resolve_template(step_params.get('description', "指定坐标"), context)

        log.info(f"打印机移动: {description} -> (X:{x:.2f}, Y:{y:.2f}, Z:{z:.2f})")
        if not self.printer.move_to(x, y, z): # 假设 PrinterControl.move_to 返回 bool
            log.error(f"打印机移动到 {description} 失败 (命令发送层面)。")
            return False
        
        wait_time = self.default_wait_times.get('after_printer_move', 2.0)
        log.info(f"移动命令已发送，等待 {wait_time} 秒稳定时间...")
        time.sleep(wait_time)

        if self._verify_printer_position(expected_x=x, expected_y=y, expected_z=z):
            log.info(f"打印机成功移动到 {description}.")
            return True
        else:
            log.error(f"打印机移动到 {description} 后位置验证失败。")
            return False

    def _safe_printer_move_to_grid(self, step_params: dict, context: dict):
        """移动打印机到指定网格位置"""
        # 获取网格位置参数
        if 'grid_num' in step_params:
            # 网格号直接提供
            try:
                grid_num = int(step_params['grid_num'])
            except ValueError:
                # 可能是一个模板字符串，已解析但仍为字符串
                grid_num_str = str(step_params['grid_num'])
                try:
                    grid_num = int(float(grid_num_str))
                except ValueError:
                    log.error(f"无法将提供的网格号 '{grid_num_str}' 转换为整数")
                    return False
        elif 'grid_num_key' in step_params:
            # 从配置中获取网格号
            grid_num_key = step_params['grid_num_key']
            
            # 特殊处理initial_char_grid_position，它被设置为{{output_positions[0]}}
            if grid_num_key == "initial_char_grid_position" and self.output_positions:
                grid_num = self.output_positions[0]
                log.debug(f"使用output_positions的第一个值 {grid_num} 作为initial_char_grid_position")
            elif grid_num_key == "waste_fluid_grid_position":
                # 从配置中获取废液位置
                grid_num = self.configurations.get(grid_num_key, 1)  # 默认为1
                log.debug(f"使用waste_fluid_grid_position: {grid_num}")
            else:
                # 尝试从configurations获取值
                grid_val = self.configurations.get(grid_num_key)
                if grid_val is not None:
                    try:
                        grid_num = int(float(str(grid_val)))
                    except ValueError:
                        log.error(f"配置键 '{grid_num_key}' 的值 '{grid_val}' 无法转换为整数")
                        return False
                else:
                    log.error(f"配置中未找到键 '{grid_num_key}'")
                    return False
        else:
            log.error("未提供网格号或网格号键")
            return False
            
        description_suffix = self._resolve_template(step_params.get('description_suffix', ''), context)
        description = f"网格 {grid_num}{description_suffix}"

        log.info(f"打印机移动: {description}")
        if not self.printer.move_to_grid_position(grid_num): # 假设 PrinterControl.move_to_grid_position 返回 bool
            log.error(f"打印机移动到 {description} 失败 (命令发送层面)。")
            return False

        wait_time = self.default_wait_times.get('after_printer_move', 2.0)
        log.info(f"移动命令已发送，等待 {wait_time} 秒稳定时间...")
        time.sleep(wait_time)
        
        # 获取移动后的实际位置并缓存
        current_pos = self.printer.get_current_position()
        if current_pos:
            # 假设网格移动主要关心XY，Z轴由打印机逻辑或后续步骤调整
            self.grid_positions_cache[grid_num] = (current_pos[0], current_pos[1], current_pos[2])
            log.debug(f"网格 {grid_num} 坐标已缓存: (X:{current_pos[0]:.2f}, Y:{current_pos[1]:.2f}, Z:{current_pos[2]:.2f})")
        else:
            log.warning(f"移动到网格 {grid_num} 后无法获取当前位置以缓存。")

        # 验证位置，PrinterControl.move_to_grid_position 内部可能已经有验证
        # 此处的验证依赖于缓存或对打印机网格逻辑的了解
        if self._verify_printer_position(grid_position_num=grid_num):
            log.info(f"打印机成功移动到 {description}.")
            return True
        else:
            log.error(f"打印机移动到 {description} 后位置验证失败。")
            return False

    def _safe_printer_home(self, step_params: dict, context: dict):
        """执行打印机归位"""
        log.info("打印机执行归位...")
        if not self.printer.home(): # 假设 PrinterControl.home 返回 bool
            log.error("打印机归位失败 (命令发送层面)。")
            return False

        wait_time = self.default_wait_times.get('after_printer_home', self.default_wait_times.get('after_printer_move', 10.0))
        log.info(f"归位命令已发送，等待 {wait_time} 秒稳定时间...")
        time.sleep(wait_time)

        # 归位后的Z轴位置可能不是0，取决于你的打印机配置
        # 0.46 是 experiment_easy.py 中的值，这里作为示例
        expected_z_after_home = float(self.configurations.get("home_z_expected", 0.46))
        if self._verify_printer_position(expected_x=0, expected_y=0, expected_z=expected_z_after_home):
            log.info("打印机归位成功.")
            self.grid_positions_cache.clear() # 归位后清除网格缓存
            return True
        else:
            # 归位验证失败通常不是致命的，打印一个警告
            log.warning(f"打印机归位后位置验证未完全通过 (Z={expected_z_after_home} vs actual). 可能仍可继续。")
            self.grid_positions_cache.clear()
            return True # 或者 False，取决于严格程度

    def _control_pump_operation(self, step_params: dict, context: dict):
        """
        控制蠕动泵操作 (吸取或排出液体)
        
        方向约定（根据实际硬件行为）:
        - direction=0: 移出液体，从电解池排出到废液区/取样区 (排出模式)
        - direction=1: 泵入液体，从储液瓶泵送电解液到电解池 (吸取模式)
        
        参数:
            step_params: 包含以下可能的键:
                - action: 'dispense'(排出)或'aspirate'(吸取)
                - volume_ml: 液体体积(ml)
                - volume_ml_key: 配置中液体体积的键名
                - direction: 显式指定的方向(0或1)，覆盖由action推断的方向
                - speed_rpm: 泵转速(RPM)
                - speed_rpm_key: 配置中泵转速的键名
            context: 上下文字典，用于模板解析
            
        返回:
            bool: 操作成功为True，失败为False
        """
        # 获取并检查动作类型
        action = step_params.get('action', 'dispense')  # dispense(默认)或aspirate
        if action not in ('dispense', 'aspirate'):
            log.error(f"无效的泵操作动作类型: {action}")
            return False
        
        # 获取液体体积
        # 处理volume_ml参数
        if 'volume_ml' in step_params:
            # 直接提供了体积
            try:
                volume_ml = float(step_params['volume_ml'])
            except ValueError:
                log.error(f"无法将volume_ml '{step_params['volume_ml']}' 转换为浮点数")
                return False
        elif 'volume_ml_key' in step_params:
            # 通过配置键获取体积
            volume_key = step_params['volume_ml_key']
            
            # 从配置中获取体积值
            volume_val = self.configurations.get(volume_key)
            if volume_val is None:
                log.error(f"配置中未找到键 '{volume_key}'")
                return False
                
            try:
                volume_ml = float(volume_val)
            except ValueError:
                log.error(f"无法将配置键 '{volume_key}' 的值 '{volume_val}' 转换为浮点数")
                return False
        else:
            log.error("未提供volume_ml或volume_ml_key")
            return False
        
        # 获取速度 (如果提供)
        if 'speed_rpm' in step_params:
            try:
                speed_rpm = float(step_params['speed_rpm'])
            except ValueError:
                log.error(f"无法将speed_rpm '{step_params['speed_rpm']}' 转换为浮点数")
                return False
        elif 'speed_rpm_key' in step_params:
            speed_key = step_params['speed_rpm_key']
            speed_val = self.configurations.get(speed_key)
            
            if speed_val is not None:
                try:
                    speed_rpm = float(speed_val)
                except ValueError:
                    log.error(f"无法将配置键 '{speed_key}' 的值 '{speed_val}' 转换为浮点数")
                    return False
            else:
                log.debug(f"配置中未找到速度键 '{speed_key}'，将使用自动速度模式")
                speed_rpm = None
        else:
            log.debug("未提供speed_rpm或speed_rpm_key，将使用自动速度模式")
            speed_rpm = None

        # 获取泵参数 (串口, 单元ID)
        # 这里使用全局泵配置，可以增加对step_params中pump_params的支持
        pump_params = self.config.get('pump_klipper_params', {})
        port = pump_params.get('P')
        unit_id = pump_params.get('U')

        if port is None or unit_id is None:
            log.error(f"泵参数配置不完整: {pump_params}")
            return False

        # 设置方向参数: 对应硬件实际行为
        # D=1: 泵入液体，从储液瓶泵送电解液到电解池
        # D=0: 移出液体，从电解池排出到废液区/取样区
        direction = 0 if action == "dispense" else 1
        
        # 当 step_params 中显式提供 direction 时，优先使用
        if 'direction' in step_params:
            try:
                explicit_direction = int(step_params['direction'])
                # 使用显式指定的方向，覆盖自动推断的方向
                direction = explicit_direction
                log.info(f"使用显式指定的泵方向: {direction} (0=移出/1=泵入)")
            except ValueError:
                log.error(f"无法将direction '{step_params['direction']}' 转换为整数")
                return False
        
        # 格式化日志消息
        direction_desc = "泵入" if direction == 1 else "移出"
        log.info(f"泵操作: {direction_desc} {volume_ml} mL 液体" + 
                 (f" (速度: {speed_rpm} RPM)" if speed_rpm else " (自动速度)"))

        # 执行泵操作
        try:            
            kw = {'P': port, 'U': unit_id, 'D': direction}

            # 根据是否有速度参数选择不同的方法
            if speed_rpm is not None:
                response = self.pump_proxy.dispense_speed(volume_ml, speed_rpm, **kw)
            else:
                response = self.pump_proxy.dispense_auto(volume_ml, **kw)

            # 检查响应
            if isinstance(response, dict) and response.get("result") == "ok":
                # 更精确地估算泵送时间
                # 假设泵有一个基本速率，例如每毫升约需2秒
                # 较大体积的液体（如清洗）可以稍微优化等待时间
                base_time_per_ml = 2.0
                if volume_ml > 10.0:  # 大体积液体
                    base_time_per_ml = 1.5
                elif volume_ml < 2.0:  # 小体积液体可能需要更多时间
                    base_time_per_ml = 2.5
                
                # 如果提供了速度，也可以考虑其影响
                speed_factor = 1.0
                if speed_rpm is not None:
                    # 假设标准速度大约是60 RPM，据此调整
                    standard_speed = 60.0
                    speed_factor = standard_speed / speed_rpm
                    # 限制速度因子的范围，避免极端值
                    speed_factor = max(0.5, min(speed_factor, 2.0))
                
                # 计算估计时间，加上基本启动时间
                est_time = base_time_per_ml * volume_ml * speed_factor + 2.0
                # 确保至少有配置的最小等待时间
                est_time = max(est_time, self.default_wait_times.get('after_pump', 5.0))
                
                log.info(f"泵命令已发送，预计需要 {est_time:.1f} 秒完成...")
                
                # 等待泵操作完成
                wait_msg = f"等待泵完成{direction_desc}液体"
                self._wait_and_log({"message": wait_msg, "seconds": est_time}, context)
                
                log.info(f"完成{direction_desc} {volume_ml} mL 液体")
                return True
            else:
                log.error(f"泵操作失败。响应: {response}")
                return False
                
        except Exception as e:
            log.error(f"泵操作通信错误或执行错误: {e}", exc_info=True)
            return False

    def _set_valve_state(self, step_params: dict, context: dict):
        """
        设置电磁阀状态
        
        阀门状态约定（根据实际硬件行为）:
        - open_to_reservoir=true时，valve_state="ON"：打开阀门到储液瓶通路（适用于泵入液体模式，D=1）
        - open_to_reservoir=false时，valve_state="OFF"：打开阀门到废液区/取样区通路（适用于移出液体模式，D=0）
        """
        open_to_reservoir = bool(step_params['open_to_reservoir'])
        
        # 处理relay_id参数
        if 'relay_id' in step_params:
            # 直接提供了relay_id
            try:
                relay_id = int(step_params['relay_id'])
            except ValueError:
                log.error(f"无法将relay_id '{step_params['relay_id']}' 转换为整数")
                return False
        elif 'relay_id_key' in step_params:
            # 需要从配置中获取relay_id
            relay_id_key = step_params['relay_id_key']
            
            # 特殊处理valve_klipper_relay_id关键字
            if relay_id_key == 'valve_klipper_relay_id':
                relay_id = self.config.get('valve_klipper_relay_id')
                if relay_id is None:
                    log.error("配置中未找到valve_klipper_relay_id")
                    return False
            # 特殊处理内联模板标记
            elif relay_id_key.startswith('{{') and relay_id_key.endswith('}}'):
                varname = relay_id_key[2:-2].strip()
                # 检查上下文中的变量
                if varname in context:
                    relay_id = context[varname]
                else:
                    # 尝试作为配置键解析
                    relay_id = self.configurations.get(varname)
                    
                if relay_id is None:
                    log.error(f"从上下文或配置中无法获取继电器ID变量 '{varname}'")
                    return False
            else:
                # 直接从配置获取值
                relay_id = self.configurations.get(relay_id_key)
                if relay_id is None:
                    log.error(f"配置中未找到继电器ID键 '{relay_id_key}'")
                    return False
                    
            try:
                relay_id = int(relay_id)
            except ValueError:
                log.error(f"无法将继电器ID值 '{relay_id}' 转换为整数")
                return False
        else:
            # 使用默认值
            relay_id = self.config.get('valve_klipper_relay_id')
            if relay_id is None:
                log.error("未提供relay_id或relay_id_key，且配置中没有默认的valve_klipper_relay_id")
                return False
                
        # 阀门控制状态，与open_to_reservoir状态保持一致
        # 使阀门状态与泵方向一致:
        # - 当泵入液体时(D=1)，阀门应开启(ON)，允许从储液瓶流入
        # - 当移出液体时(D=0)，阀门应关闭(OFF)，导向废液区/取样区
        valve_state = "ON" if open_to_reservoir else "OFF"
        
        # 显示更精确的日志信息
        if open_to_reservoir:
            flow_desc = "储液瓶通路 (泵入模式，对应D=1)"
            flow_detail = "允许液体从储液瓶流向系统"
        else:
            flow_desc = "废液/取样通路 (移出模式，对应D=0)"
            flow_detail = "引导液体流向废液区或取样区"
            
        # 增强阀门状态日志记录，更新描述以匹配实际硬件行为
        log.info(f"电磁阀: 切换到 {flow_desc} (继电器ID: {relay_id}, 状态: {valve_state})")
        log.info(f"流体方向: {flow_detail}")
        
        # 发送继电器命令
        try:
            if valve_state == "ON":
                response = self.relay_proxy.on(relay_id)
            else:
                response = self.relay_proxy.off(relay_id)

            # 验证操作成功
            if isinstance(response, dict) and response.get("result") == "ok":
                log.info(f"电磁阀成功切换到 {flow_desc}.")
                
                # 等待阀门切换完成
                wait_time = self.default_wait_times.get('after_relay', 1.5)
                log.info(f"等待阀门切换完成 ({flow_desc}) 等待 {wait_time} 秒...")
                time.sleep(wait_time)
                
                return True
            else:
                log.error(f"电磁阀切换失败: {response}")
                return False
        except Exception as e:
            log.error(f"电磁阀通信错误或执行错误: {e}")
            return False

    def _execute_chi_measurement(self, step_config: dict, context: dict):
        """执行单个CHI电化学测试"""
        chi_method_name = step_config['chi_method']
        # 解析chi_params中的模板
        parsed_chi_params = self._parse_params(step_config.get('chi_params', {}), context)
        
        # 文件名处理，确保在project_path下
        file_name_template = parsed_chi_params.get('fileName', f"{self.project_name}_{chi_method_name}")
        # fileName 应该只是文件名，不含路径，chi.Setup会处理路径
        # 如果fileName模板中包含了 {{project_name}} 等，它们已经被解析了
        parsed_chi_params['fileName'] = os.path.basename(file_name_template)

        log.info(f"执行CHI测试: {chi_method_name}, 参数: {parsed_chi_params}")

        # 获取CHI技术类 - 直接使用导入的类，而不是从globals()获取
        if chi_method_name == "CV":
            chi_class = CV
        elif chi_method_name == "LSV":
            chi_class = LSV
        elif chi_method_name == "EIS":
            chi_class = EIS
        elif chi_method_name == "IT":
            chi_class = IT
        elif chi_method_name == "OCP":
            chi_class = OCP 
        elif chi_method_name == "CA":
            chi_class = CA
        else:
            log.error(f"未知的CHI方法: {chi_method_name}")
            return False
        
        try:
            # 实例化CHI技术对象
            # **parsed_chi_params 会将字典解包为关键字参数
            chi_experiment = chi_class(**parsed_chi_params)
            
            # 执行前置动作
            if 'actions_before' in step_config:
                log.info(f"  执行 {chi_method_name} 的前置动作...")
                for sub_step_config in step_config['actions_before']:
                    if not self._dispatch_step(sub_step_config, context):
                        log.error(f"  {chi_method_name} 的前置动作失败，中止当前CHI测试。")
                        return False
            
            # 等待稳定
            stabilization_time = self.default_wait_times.get('chi_stabilization', 0)
            if stabilization_time > 0:
                 self._wait_and_log({"message": "CHI测量前稳定", "seconds": stabilization_time}, context)

            # 运行CHI实验 (单个)
            chi_run_sequence([chi_experiment]) # run_sequence期望一个列表
            log.info(f"CHI测试 {chi_method_name} 完成。原始数据文件: {parsed_chi_params['fileName']}.txt") # control_chi会自动加.txt

            # 执行后置动作
            if 'actions_after' in step_config:
                log.info(f"  执行 {chi_method_name} 的后置动作...")
                for sub_step_config in step_config['actions_after']:
                    # 为process_chi_data步骤传递原始文件名（不含路径）
                    if sub_step_config.get("type") == "process_chi_data" and \
                       sub_step_config.get("params",{}).get("source_file_name_in_chi_params") == "{{chi_params.fileName}}.txt": # 假设模板是这样的
                        # 更新上下文或直接修改sub_step_config的参数以包含实际文件名
                        # 这里简化：假设process_chi_data知道如何从chi_params中获取文件名
                        pass

                    if not self._dispatch_step(sub_step_config, context):
                        log.error(f"  {chi_method_name} 的后置动作失败。")
                        # 后置动作失败可能不一定需要中止整个CHI步骤，取决于设计
                        # return False 
            return True
        except Exception as e:
            log.error(f"执行CHI测试 {chi_method_name} 失败: {e}", exc_info=True)
            return False

    def _execute_chi_sequence(self, step_config: dict, context: dict):
        """执行一系列CHI电化学测试"""
        chi_tests_config = step_config.get('chi_tests', [])
        if not chi_tests_config:
            log.warning("CHI序列步骤中未定义任何测试。")
            return True

        log.info(f"开始执行CHI测试序列 (共 {len(chi_tests_config)} 个测试)...")
        
        chi_experiment_objects = []
        test_details_for_processing = []

        for i, test_cfg in enumerate(chi_tests_config):
            method_name = test_cfg['method']
            parsed_params = self._parse_params(test_cfg.get('params', {}), context)
            
            # 文件名处理
            file_name_template = parsed_params.get('fileName', f"{self.project_name}_{method_name}_{i}")
            parsed_params['fileName'] = os.path.basename(file_name_template)

            log.debug(f"  序列测试 {i+1}: {method_name}, 参数: {parsed_params}")

            # 获取CHI技术类 - 直接使用导入的类，而不是从globals()获取
            if method_name == "CV":
                chi_class = CV
            elif method_name == "LSV":
                chi_class = LSV
            elif method_name == "EIS":
                chi_class = EIS
            elif method_name == "IT":
                chi_class = IT
            elif method_name == "OCP":
                chi_class = OCP 
            elif method_name == "CA":
                chi_class = CA
            else:
                log.error(f"  序列中未知的CHI方法: {method_name}")
                return False # 中止整个序列

            try:
                chi_experiment_objects.append(chi_class(**parsed_params))
                test_details_for_processing.append({
                    "method": method_name,
                    "original_file_name_template": parsed_params['fileName'] # 保存用于后续数据处理步骤查找文件
                })
            except Exception as e:
                log.error(f"  序列中实例化CHI测试 {method_name} 失败: {e}", exc_info=True)
                return False
        
        # 执行前置动作 (序列级别)
        if 'actions_before' in step_config:
            log.info(f"  执行CHI序列的前置动作...")
            for sub_step_config in step_config['actions_before']:
                if not self._dispatch_step(sub_step_config, context):
                    log.error(f"  CHI序列的前置动作失败，中止序列。")
                    return False
        
        stabilization_time = self.default_wait_times.get('chi_stabilization', 0)
        if stabilization_time > 0:
                self._wait_and_log({"message": "CHI序列测量前稳定", "seconds": stabilization_time}, context)

        # 运行整个CHI序列
        try:
            chi_run_sequence(chi_experiment_objects)
            log.info("CHI测试序列全部完成。")
            # 临时将测试详情放入上下文，供后续 process_chi_data 步骤使用（如果它们在序列的actions_after中）
            context['_last_chi_sequence_details'] = test_details_for_processing
        except Exception as e:
            log.error(f"执行CHI测试序列时发生错误: {e}", exc_info=True)
            return False

        # 执行后置动作 (序列级别)
        if 'actions_after' in step_config:
            log.info(f"  执行CHI序列的后置动作...")
            for sub_step_config in step_config['actions_after']:
                if not self._dispatch_step(sub_step_config, context):
                    log.error(f"  CHI序列的后置动作失败。")
                    # return False
        
        if '_last_chi_sequence_details' in context: # 清理临时上下文
            del context['_last_chi_sequence_details']
            
        return True

    def _parse_electrochemical_file(self, file_path: str) -> pd.DataFrame:
        """解析电化学文件 (与之前版本一致)"""
        log.debug(f"尝试解析电化学文件: {file_path}")
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            log.warning(f"电化学文件不存在或为空: {file_path}")
            return pd.DataFrame()
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            data_start = -1
            header_line_type = None # 'potential_current' or 'time_current'

            for i, line in enumerate(lines):
                line_lower = line.lower().strip()
                if 'potential/v' in line_lower and 'current/a' in line_lower:
                    data_start = i + 1
                    header_line_type = 'potential_current'
                    break
                elif 'time/sec' in line_lower and 'current/a' in line_lower: # CHI的i-t曲线通常是Time/sec
                    data_start = i + 1
                    header_line_type = 'time_current'
                    break
            
            if data_start == -1:
                log.warning(f"在文件中未找到可识别的数据头: {file_path}")
                return pd.DataFrame()

            data_rows = []
            for line_num, line_content in enumerate(lines[data_start:]):
                clean_line = line_content.strip()
                if not clean_line: continue # 跳过空行
                
                # 尝试用逗号分割，如果不行再尝试用制表符或多个空格
                parts = [p.strip() for p in clean_line.split(',') if p.strip()]
                if len(parts) < 2: # 尝试制表符
                    parts = [p.strip() for p in clean_line.split('\t') if p.strip()]
                if len(parts) < 2: # 尝试多个空格
                    parts = [p.strip() for p in clean_line.split() if p.strip()]

                if len(parts) >= 2:
                    try:
                        # 取前两列作为数据
                        data_rows.append([float(parts[0]), float(parts[1])])
                    except ValueError:
                        log.debug(f"跳过无法解析为数字的行 {line_num + data_start} in {file_path}: '{line_content}'")
            
            if not data_rows:
                log.warning(f"未从文件中解析到有效数据行: {file_path}")
                return pd.DataFrame()

            if header_line_type == 'time_current':
                df = pd.DataFrame(data_rows, columns=['Time', 'Current'])
            elif header_line_type == 'potential_current':
                df = pd.DataFrame(data_rows, columns=['Potential', 'Current'])
            else: # 不应该发生，但作为回退
                df = pd.DataFrame() 
            
            log.debug(f"成功解析文件 {file_path}, 共 {len(df)} 行数据。列: {df.columns.tolist()}")
            return df
        except Exception as e:
            log.error(f"解析电化学文件 {file_path} 失败: {e}", exc_info=True)
            return pd.DataFrame()

    def _calculate_charge(self, it_data: pd.DataFrame) -> float:
        """计算IT曲线的电荷量 (与之前版本一致)"""
        if not isinstance(it_data, pd.DataFrame) or it_data.empty or \
           'Time' not in it_data.columns or 'Current' not in it_data.columns:
            log.warning("IT数据无效或缺少必要列 ('Time', 'Current')，无法计算电荷。")
            return 0.0
        if len(it_data) < 2:
            log.warning("IT数据点不足 (<2)，无法计算电荷。")
            return 0.0
        try:
            # 确保数据按时间排序
            it_data_sorted = it_data.sort_values('Time').reset_index(drop=True)
            # 使用梯形法则计算积分（电荷）
            charge = abs(np.trapz(it_data_sorted['Current'], it_data_sorted['Time']))
            log.debug(f"计算得到电荷: {charge:.6f} C")
            return charge
        except Exception as e:
            log.error(f"计算电荷时发生错误: {e}", exc_info=True)
            return 0.0

    def _process_chi_data(self, step_params: dict, context: dict):
        """通用CHI数据处理步骤"""
        data_type = step_params['data_type'].upper() # CV, LSV, IT, CV_CDL
        # 文件名可能在chi_params中，或者直接在step_params中提供
        # 这里的 source_file_name_in_chi_params 指的是CHI原始文件名，不含路径
        raw_file_name_template = step_params.get('source_file_name_in_chi_params')
        if not raw_file_name_template:
            log.error(f"处理{data_type}数据：未提供 source_file_name_in_chi_params")
            return False
        
        # 解析文件名模板
        # 注意：如果这个process_chi_data是在一个chi_sequence的actions_after中，
        # 那么context可能需要包含该序列中每个测试的实际文件名。
        # 简化：假设文件名模板能直接从当前context解析，或者它是一个固定值。
        # 对于chi_sequence后的处理，可能需要迭代context['_last_chi_sequence_details']
        # 这里我们先假设文件名是直接可解析的，或者对于单个chi_measurement它引用了chi_params.fileName
        
        # 尝试从上下文中获取解析后的文件名（如果它是由chi_measurement步骤动态生成的）
        # 例如，如果chi_params.fileName是 "{{project_name}}_CV.txt"，那么解析后会是 "MyProj_CV.txt"
        # 我们需要这个解析后的基本文件名。
        
        # 复杂性：fileName在chi_params中是模板，在执行_execute_chi_measurement时被解析。
        # process_chi_data需要知道那个最终被使用的不带路径的文件名。
        # 方案1: _execute_chi_measurement将最终文件名放入context。
        # 方案2: process_chi_data重新解析fileName模板（如果它是基于相同context的）。
        # 方案3: source_file_name_in_chi_params 直接就是那个模板，process_chi_data解析它。

        # 使用方案3的思路：
        actual_raw_file_name = self._resolve_template(raw_file_name_template, context)
        # control_chi会自动添加.txt，所以这里也确保它
        if not actual_raw_file_name.lower().endswith(".txt"):
            actual_raw_file_name += ".txt"
            
        chi_file_path = os.path.join(self.project_path, actual_raw_file_name)
        log.info(f"处理 {data_type} 数据文件: {chi_file_path}")

        # 如果文件不存在，尝试在当前目录查找而不是项目目录
        # CHI软件有时会将文件保存在当前目录而不是指定的项目目录
        if not os.path.exists(chi_file_path):
            current_dir_path = os.path.join(os.getcwd(), actual_raw_file_name)
            if os.path.exists(current_dir_path):
                log.info(f"在当前目录找到 {data_type} 文件: {current_dir_path}")
                
                # 将文件复制到项目目录
                try:
                    import shutil
                    shutil.copy2(current_dir_path, chi_file_path)
                    log.info(f"已将文件复制到项目目录: {chi_file_path}")
                except Exception as e:
                    log.error(f"复制文件到项目目录失败: {e}")
                    chi_file_path = current_dir_path  # 如果复制失败，使用当前目录的文件路径
            else:
                log.error(f"{data_type} 文件不存在: {chi_file_path} 和 {current_dir_path}")
            # 在Excel中记录文件缺失
            if self.reporter and data_type == "IT":
                voltage = float(context.get('current_voltage', 0))
                output_pos = str(context.get('current_output_position', 'N/A'))
                loop_idx = int(context.get('loop_index', -1))
                self.reporter.record_it_result(voltage, "文件缺失", output_pos, loop_idx, None)
            return False # 标记此步骤失败

        data_df = self._parse_electrochemical_file(chi_file_path)
        if data_df.empty:
            log.warning(f"{data_type} 数据解析为空或失败。")
            if self.reporter and data_type == "IT":
                voltage = float(context.get('current_voltage', 0))
                output_pos = str(context.get('current_output_position', 'N/A'))
                loop_idx = int(context.get('loop_index', -1))
                self.reporter.record_it_result(voltage, "数据为空", output_pos, loop_idx, None)
            return True # 解析为空不一定算失败，但没有图表

        plot_path = None
        plot_filename_base = os.path.splitext(actual_raw_file_name)[0] # 去掉.txt
        plot_file_path = os.path.join(self.project_path, f"{plot_filename_base}_plot.png")

        try:
            plt.figure(figsize=(8, 5))
            if data_type == "CV" or data_type == "CV_CDL" or data_type == "LSV":
                if 'Potential' not in data_df.columns or 'Current' not in data_df.columns:
                    log.error(f"{data_type} 数据缺少 Potential 或 Current 列。")
                    plt.close()
                    return True # 数据列不对，无法绘图
                plt.plot(data_df['Potential'], data_df['Current'], 'b-', linewidth=1.5)
                plt.xlabel('Potential (V)')
            elif data_type == "IT":
                if 'Time' not in data_df.columns or 'Current' not in data_df.columns:
                    log.error(f"{data_type} 数据缺少 Time 或 Current 列。")
                    plt.close()
                    return True # 数据列不对，无法绘图
                plt.plot(data_df['Time'], data_df['Current'], 'b-', linewidth=1.5)
                plt.xlabel('Time (s)')
            else:
                log.warning(f"未知数据类型 {data_type} 的绘图逻辑。")
                plt.close()
                return True # 无法绘图

            plt.ylabel('Current (A)')
            title_suffix = f" at {context['current_voltage']:.1f}V" if data_type == "IT" and 'current_voltage' in context else ""
            plt.title(f'{data_type.replace("_", " ")}{title_suffix}')
            plt.grid(True)
            plt.tight_layout()
            plt.savefig(plot_file_path, dpi=300)
            plt.close()
            plot_path = plot_file_path # 标记图表已生成
            log.info(f"{data_type} 图已保存: {plot_file_path}")
        except Exception as e:
            log.error(f"生成 {data_type} 图失败: {e}", exc_info=True)
            plot_path = None

        # --- 调用ExcelReporter记录 ---
        if not self.reporter:
            log.warning("ExcelReporter未初始化，跳过Excel记录。")
            return True # 即使报告失败，数据处理本身可能算成功

        if data_type == "CV":
            # 使用record_main_plot方法记录CV结果
            self.reporter.record_main_plot(
                tag_name="CV", 
                png_image_path=plot_path,
                project_anchor_key="cv_plot_anchor", 
                central_anchor_key="central_cv_plot_anchor"
            )
        elif data_type == "CV_CDL":
            # 使用record_main_plot方法记录CV_CDL结果
            self.reporter.record_main_plot(
                tag_name="CV_CDL", 
                png_image_path=plot_path,
                project_anchor_key="cv_cdl_plot_anchor", 
                central_anchor_key="central_cv_cdl_plot_anchor"
            )
        elif data_type == "LSV":
            # 使用record_main_plot方法记录LSV结果
            self.reporter.record_main_plot(
                tag_name="LSV", 
                png_image_path=plot_path,
                project_anchor_key="lsv_plot_anchor", 
                central_anchor_key="central_lsv_plot_anchor"
            )
        elif data_type == "IT":
            voltage = float(context.get('current_voltage', 0))
            output_pos_str = str(context.get('current_output_position', 'N/A'))
            loop_idx = int(context.get('loop_index', -1))
            charge = self._calculate_charge(data_df)
            status_for_excel = f"{charge:.6f}" if charge > 0 else "计算电荷失败"
            
            self.reporter.record_it_result(
                voltage=voltage,
                charge_or_status=status_for_excel,
                output_pos=output_pos_str,
                loop_index=loop_idx,
                it_plot_path=plot_path
            )
            # 收集IT图信息用于最终的图库
            if plot_path:
                self.it_plot_info_list.append({
                    'voltage': voltage,
                    'path': plot_path,
                    'index': loop_idx
                })
        else:
            log.info(f"数据类型 {data_type} 没有特定的Excel记录逻辑。")
            
        return True


    def _execute_voltage_loop(self, step_config: dict, context: dict):
        """执行电压循环步骤"""
        voltage_source_cfg = step_config['voltage_source']
        output_positions_source_cfg = step_config.get('output_positions_source', {})
        loop_sequence_cfg = step_config['loop_sequence']

        # --- 1. 生成电压序列 ---
        voltages_to_loop = []
        vs_type = voltage_source_cfg.get('type', 'config_key') # 默认为config_key
        if vs_type == 'range':
            start_v = float(voltage_source_cfg['start'])
            end_v = float(voltage_source_cfg['end'])
            step_v = float(voltage_source_cfg['step'])
            # arange 对于浮点数步进可能不精确，用linspace更稳妥
            num_points = int(round(abs(end_v - start_v) / abs(step_v))) + 1 if step_v != 0 else 1
            voltages_to_loop = np.linspace(start_v, end_v, num_points).round(2).tolist() # 保留两位小数
        elif vs_type == 'list_literal':
            voltages_to_loop = [float(v) for v in voltage_source_cfg['values']]
        elif vs_type == 'config_key':
            # 如果key是 "voltage_range"，则使用顶层配置的voltage_range并按0.1步进生成
            # 如果key是 "voltages_calculated"，则使用初始化时计算好的self.voltages
            key_name = voltage_source_cfg.get('key')
            if key_name == "voltage_range": # 特殊处理，与顶层voltage_range行为一致
                vr_cfg = self.config['voltage_range']
                if vr_cfg[0] < vr_cfg[1]:
                    v_arr = np.round(np.arange(vr_cfg[0], vr_cfg[1] + 0.1, 0.1), 2)
                else:
                    start, end = vr_cfg[0], vr_cfg[1]
                    num_points = int(round(abs(end - start) / 0.1)) + 1 if start != end else 1
                    v_arr = np.round(np.linspace(start, end, num_points), 2)
                voltages_to_loop = v_arr.tolist()
            else: # 否则，从configurations中获取预计算的列表
                voltages_to_loop = self._resolve_template(f"{{{{config.{key_name}}}}}", context)
                if not isinstance(voltages_to_loop, list):
                    log.error(f"Voltage loop: configurations中的 '{key_name}' 不是一个列表。")
                    return False
        else:
            log.error(f"Voltage loop: 未知的voltage_source类型 '{vs_type}'")
            return False
        
        if not voltages_to_loop:
            log.warning("Voltage loop: 生成的电压序列为空，跳过循环。")
            return True
        log.info(f"Voltage loop: 将对以下电压进行迭代: {voltages_to_loop}")

        # --- 2. 准备输出位置序列 ---
        output_positions_for_loop = []
        ops_type = output_positions_source_cfg.get('type', 'config_key') # 默认为config_key
        if ops_type == 'sequential_from_config_key':
            first_pos_key = output_positions_source_cfg['first_pos_key']
            first_pos = int(self._resolve_template(f"{{{{config.{first_pos_key}}}}}", context))
            output_positions_for_loop = list(range(first_pos, first_pos + len(voltages_to_loop)))
        elif ops_type == 'list_from_config_key':
            list_key = output_positions_source_cfg['list_key']
            output_positions_for_loop = self._resolve_template(f"{{{{config.{list_key}}}}}", context)
        elif ops_type == 'list_literal':
            output_positions_for_loop = [int(p) for p in output_positions_source_cfg['values']]
        elif ops_type == 'fixed_value':
            fixed_val = int(self._resolve_template(output_positions_source_cfg['value'], context))
            output_positions_for_loop = [fixed_val] * len(voltages_to_loop)
        elif ops_type == 'config_key': # 直接使用顶层计算的 output_positions
            key_name = output_positions_source_cfg.get('key')
            if key_name == "output_positions_list": # 特殊处理
                 output_positions_for_loop = self.output_positions # 使用初始化时确定的列表
            else:
                output_positions_for_loop = self._resolve_template(f"{{{{config.{key_name}}}}}", context)

        if not output_positions_for_loop or len(output_positions_for_loop) != len(voltages_to_loop):
            if len(output_positions_for_loop) == 1 and ops_type != 'fixed_value': # 如果只提供了一个，则假设所有电压都用这个位置
                log.warning(f"Voltage loop: 输出位置列表长度与电压点数不匹配，但只提供了一个位置。将对所有电压使用位置 {output_positions_for_loop[0]}.")
                output_positions_for_loop = [output_positions_for_loop[0]] * len(voltages_to_loop)
            elif ops_type == 'fixed_value' and output_positions_for_loop: # fixed_value 已处理
                pass
            else:
                log.error(f"Voltage loop: 输出位置列表长度 ({len(output_positions_for_loop)}) 与电压点数 ({len(voltages_to_loop)}) 不匹配。")
                return False
        log.info(f"Voltage loop: 对应的输出位置序列: {output_positions_for_loop}")

        # --- 3. 执行循环 ---
        for i, voltage in enumerate(voltages_to_loop):
            current_output_pos = output_positions_for_loop[i]
            
            # 创建/更新循环上下文
            loop_context = context.copy() # 继承父上下文
            loop_context['current_voltage'] = voltage
            loop_context['current_voltage_file_str'] = (f"neg{int(abs(voltage * 10))}" if voltage < 0 else f"{int(voltage * 10)}")
            loop_context['current_output_position'] = current_output_pos
            loop_context['loop_index'] = i

            log.info(f"[Voltage Loop {i+1}/{len(voltages_to_loop)}] 电压: {voltage:.2f}V, 输出位置: {current_output_pos}")

            for sub_step_config in loop_sequence_cfg:
                if not self._dispatch_step(sub_step_config, loop_context):
                    log.error(f"Voltage loop 在 电压 {voltage:.2f}V (索引 {i}) 时子步骤失败。中止循环。")
                    return False # 子步骤失败，中止整个循环
            log.info(f"[Voltage Loop {i+1}/{len(voltages_to_loop)}] 电压: {voltage:.2f}V 处理完成。")
        
        log.info("Voltage loop 全部完成。")
        return True

    def _execute_sequence_step(self, step_config: dict, context: dict):
        """执行一个子序列步骤（宏或者内联动作）"""
        sub_sequence_name = step_config.get("name_in_sub_sequences")
        inline_actions = step_config.get("actions")
        
        actions_to_execute = []
        if sub_sequence_name:
            if sub_sequence_name not in self.config.get("sub_sequences", {}):
                log.error(f"子序列 '{sub_sequence_name}' 未在配置中定义。")
                return False
            sub_seq_def = self.config["sub_sequences"][sub_sequence_name]
            log.info(f"执行子序列: {sub_sequence_name} ({sub_seq_def.get('description', '')})")
            actions_to_execute = sub_seq_def.get("actions", [])
        elif inline_actions:
            log.info(f"执行内联动作序列 (共 {len(inline_actions)} 个动作)")
            actions_to_execute = inline_actions
        else:
            log.warning("序列步骤既未指定子序列名称也未包含内联动作。")
            return True # 空序列算成功

        # 如果子序列需要特定的上下文变量，而这些变量在调用时没有（例如dispense_sample_and_clean_cell中的current_output_position）
        # 可以在调用sequence步骤时，通过params传入，然后在子序列的actions中用模板引用
        # 或者，在sequence步骤配置中添加一个 context_override 字段
        # "context_override": {"current_output_position": "{{config.initial_char_position}}"}
        # 然后在分发子动作前，将这些覆盖值加入到context中
        
        # 创建一个新的上下文副本，用于此序列，可以被覆盖
        sequence_context = context.copy()
        context_overrides = self._parse_params(step_config.get("context_override", {}), context) # 解析覆盖值中的模板
        if context_overrides:
            log.debug(f"  应用上下文覆盖到子序列: {context_overrides}")
            sequence_context.update(context_overrides)

        for sub_action_config in actions_to_execute:
            if not self._dispatch_step(sub_action_config, sequence_context): # 使用序列特定的上下文
                log.error(f"子序列/内联序列中的步骤失败。中止当前序列。")
                return False
        
        log.info(f"子序列/内联序列执行完毕。")
        return True


    def _dispatch_step(self, step_config: dict, context: dict) -> bool:
        """
        根据步骤类型分发任务到相应的执行方法。
        返回 True 表示成功，False 表示失败。
        """
        step_id = step_config.get('id', '未命名步骤')
        step_type = step_config.get('type')
        description = self._resolve_template(step_config.get('description', ''), context)

        log.info(f"--- [开始步骤: {step_id}] {description} (类型: {step_type}) ---")

        # 1. 检查是否启用
        if not step_config.get('enabled', True):
            log.info(f"步骤 {step_id} 已禁用，跳过。")
            return True

        # 2. 检查条件跳过标志
        skip_flag_true_key = step_config.get('skip_if_flag_true')
        if skip_flag_true_key and self.experiment_flags.get(skip_flag_true_key, False):
            log.info(f"步骤 {step_id} 因标志 '{skip_flag_true_key}' 为True而跳过。")
            return True
        
        skip_flag_false_key = step_config.get('skip_if_flag_false')
        if skip_flag_false_key and not self.experiment_flags.get(skip_flag_false_key, True): # 标志默认为True以避免意外跳过
            log.info(f"步骤 {step_id} 因标志 '{skip_flag_false_key}' 为False而跳过。")
            return True

        # 3. 解析通用参数 (params) 和特定参数 (如 chi_params)
        #   注意：模板解析应该在每个具体执行方法内部进行，因为它们可能需要不同的上下文或对解析结果有不同处理
        #   或者，在这里进行一次通用解析，然后具体方法再按需处理
        #   为了简化，我们让具体执行方法自己处理其需要的参数的模板解析
        #   更新：改为在这里解析params，然后传递给具体方法
        
        parsed_params = self._parse_params(step_config.get('params', {}), context)
        # 对于chi_measurement, chi_params的解析在_execute_chi_measurement内部进行，因为它更复杂

        # 4. 根据类型分发
        success = False
        if step_type == "printer_home":
            success = self._safe_printer_home(parsed_params, context)
        elif step_type == "move_printer_xyz":
            success = self._safe_printer_move_to_xyz(parsed_params, context)
        elif step_type == "move_printer_grid":
            success = self._safe_printer_move_to_grid(parsed_params, context)
        elif step_type == "set_valve":
            success = self._set_valve_state(parsed_params, context)
        elif step_type == "pump_liquid":
            success = self._control_pump_operation(parsed_params, context)
        elif step_type == "chi_measurement":
            success = self._execute_chi_measurement(step_config, context) # chi_measurement需要原始step_config
        elif step_type == "chi_sequence":
            success = self._execute_chi_sequence(step_config, context) # chi_sequence也需要原始step_config
        elif step_type == "process_chi_data":
            success = self._process_chi_data(parsed_params, context)
        elif step_type == "voltage_loop":
            success = self._execute_voltage_loop(step_config, context) # voltage_loop需要原始step_config
        elif step_type == "sequence":
            success = self._execute_sequence_step(step_config, context) # sequence_step需要原始step_config
        elif step_type == "wait":
            success = self._wait_and_log(parsed_params, context)
        elif step_type == "log_message":
            success = self._log_message(parsed_params, context)
        # elif step_type == "stop_all_chi_processes":
        #     success = self._stop_all_chi()
        else:
            log.error(f"未知的步骤类型: {step_type} (步骤ID: {step_id})")
            success = False # 未知类型视为失败

        if success:
            log.info(f"--- [完成步骤: {step_id}] ---")
        else:
            log.error(f"--- [失败步骤: {step_id}] ---")
        return success

    def run_full_experiment(self):
        """
        从JSON配置执行完整的实验流程。
        """
        log.info(f"\n\n[EXPERIMENT START] === 项目: {self.project_name} (配置: {self.config_file_path}) ===")
        
        # 打印一些关键配置信息
        log.info(f"Moonraker地址: {self.moonraker_base_url}")
        log.info(f"电压范围 (配置): {self.config['voltage_range']}")
        log.info(f"计算后电压序列: {self.voltages.tolist()}")
        log.info(f"计算后输出位置: {self.output_positions}")
        log.info(f"Klipper泵参数: {self.config.get('pump_klipper_params')}")
        log.info(f"Klipper阀门继电器ID: {self.config.get('valve_klipper_relay_id')}")

        initial_context = {
            "project_name": self.project_name,
            "base_path": self.base_path,
            "project_path": self.project_path,
            # 可以加入其他需要在模板中全局可用的上下文变量
        }
        # 将configurations中的内容也加入到初始上下文中，方便模板直接引用
        # 但要注意不要覆盖已有的键，或者通过 {{config.xxx}} 引用
        # initial_context.update(self.configurations) # 这样会导致 current_voltage 等被覆盖

        overall_success = True
        try:
            experiment_sequence_cfg = self.config.get('experiment_sequence', [])
            if not experiment_sequence_cfg:
                log.warning("实验序列为空，无操作执行。")
            else:
                for step_config in experiment_sequence_cfg:
                    if not self._dispatch_step(step_config, initial_context.copy()): # 传递上下文副本
                        log.critical(f"步骤 {step_config.get('id', '未定义ID')} 执行失败，实验中止。")
                        overall_success = False
                        break # 中止后续步骤
            
            if overall_success:
                log.info(f"[EXPERIMENT FLOW SUCCESS] === 项目: {self.project_name} 所有已启用步骤成功完成。 ===")
            else:
                log.error(f"[EXPERIMENT FLOW FAILED] === 项目: {self.project_name} 实验流程中途失败。 ===")

        except KeyboardInterrupt:
            log.warning("[EXPERIMENT INTERRUPTED] 用户通过 Ctrl+C 中断实验！")
            overall_success = False
        except Exception as e:
            log.critical(f"[EXPERIMENT FAILED UNHANDLED] 实验流程中发生未捕获的严重错误: {e}", exc_info=True)
            overall_success = False
        finally:
            # --- 最终报告生成 (无论成功与否，尝试生成报告) ---
            if self.reporter:
                try:
                    log.info("[REPORT] 开始生成最终Excel报告...")
                    # 添加IT图库到项目和中央Excel
                    if self.it_plot_info_list:
                        try:
                            # 使用add_it_plots_gallery方法添加IT图库
                            self.reporter.add_it_plots_gallery(
                                self.it_plot_info_list, 
                                target_workbook="project", 
                                anchor_key="it_plots_start_anchor"
                            )
                            self.reporter.add_it_plots_gallery(
                                self.it_plot_info_list,
                                target_workbook="central",
                                anchor_key="central_it_plots_start_anchor"
                            )
                            log.info("[REPORT] 已添加IT图库到项目和中央Excel")
                        except Exception as e:
                            log.warning(f"[REPORT] 添加IT图库失败: {e}")

                    # 添加实验概要信息
                    summary_params = {
                        "项目名称": self.project_name,
                        "Moonraker地址": self.moonraker_base_url,
                        "泵参数": str(self.config.get('pump_klipper_params')),
                        "阀门继电器ID": str(self.config.get('valve_klipper_relay_id')),
                        "配置电压范围": str(self.config.get('voltage_range')),
                        "最终输出位置": str(self.output_positions)
                    }
                    
                    try:
                        # 使用add_summary_info方法添加实验概要信息
                        self.reporter.add_summary_info(additional_info=summary_params)
                        log.info("[REPORT] 已添加实验概要信息")
                    except Exception as e:
                        log.warning(f"[REPORT] 添加实验概要失败: {e}")
                    
                    # 保存Excel文件
                    try:
                        self.reporter.save_all_workbooks()
                        log.info("[REPORT] Excel报告保存完毕")
                    except Exception as save_error:
                        log.warning(f"[REPORT] 保存Excel报告失败: {save_error}")

                    log.info("[REPORT] Excel报告生成完毕。")
                except Exception as report_err:
                    log.error(f"[REPORT] 生成最终报告时发生错误: {report_err}", exc_info=True)
            else:
                log.warning("[REPORT] ExcelReporter 未初始化，无法生成最终报告。")

            # --- 最终清理 (通常是归位和关闭CHI) ---
            # 这一步也可以通过JSON序列的最后步骤来实现，更灵活
            # 如果JSON中没有定义，这里可以做一个默认的
            log.info("[CLEANUP] 开始执行最终清理操作...")
            self._perform_final_cleanup() # 默认的清理方法

            log.info(f"[EXPERIMENT END] === 项目: {self.project_name} 执行结束。整体成功: {overall_success} ===")
            
            # 打印最终文件路径
            log.info("------------------------------------")
            if self.reporter:
                log.info(f"项目结果文件: {self.excel_project_path}")
                log.info(f"中央汇总文件: {self.excel_central_path}")
            log.info(f"项目数据文件夹: {self.project_path}")
            log.info("------------------------------------")
        return overall_success

    def _perform_final_cleanup(self):
        """执行默认的最终清理操作，除非JSON序列中已包含"""
        # 检查JSON序列是否已经包含归位等操作
        has_final_home = any(step.get("type") == "printer_home" and step.get("id", "").startswith("FINAL_") for step in self.config.get("experiment_sequence",[]))
        # has_final_chi_stop = any(...)
        
        if not has_final_home:
            log.info("  执行默认最终打印机归位...")
            try:
                self._safe_printer_home({}, {}) # 空参数和上下文
            except Exception as e:
                log.warning(f"  默认最终归位操作失败: {e}")
        
        # 停止所有活动的CHI进程 (如果需要)
        # if not has_final_chi_stop:
        # log.info("  尝试停止所有活动的CHI进程...")
        # try:
        #     chi_stop_all()
        # except Exception as e:
        #     log.warning(f"  尝试停止CHI进程时出错: {e}")
        
        log.info("默认最终清理操作完成。")

    def _voltage_loop(self, step_config: dict, context: dict):
        """
        执行电压循环测试

        参数:
            step_config: {
                'voltage_list_key': 配置中的key，指向一个电压序列，未提供时使用全局电压序列
                'output_positions_key': 配置中的key，指向一个输出位置序列，未提供时使用全局输出位置
                'method': 'IT' 目前只支持IT
                'test_params': 测试参数对象，特定于method
                'skip_voltage_indices': [可选] 要跳过的电压索引列表
                # 还可以有其他移动命令和CHI参数
            }
            context: 上下文字典
            
        返回:
            bool: 操作成功为True，失败为False
        """
        method = step_config.get('method', 'IT')
        if method != 'IT':
            log.error(f"目前只支持IT方法进行电压循环，提供了未知的方法: {method}")
            return False
            
        # 检查是否有需要跳过的索引
        skip_indices = step_config.get('skip_voltage_indices', [])
        log.info(f"跳过的电压索引: {skip_indices}")
            
        # 获取电压列表
        voltage_list_key = step_config.get('voltage_list_key')
        if voltage_list_key:
            voltage_list_value = self.configurations.get(voltage_list_key)
            if not voltage_list_value:
                log.error(f"找不到配置键 '{voltage_list_key}'")
                return False
            # 如果是字符串，尝试转换为列表
            if isinstance(voltage_list_value, str):
                try:
                    voltage_list = json.loads(voltage_list_value)
                except json.JSONDecodeError:
                    log.error(f"无法将电压列表字符串 '{voltage_list_value}' 解析为列表")
                    return False
            else:
                voltage_list = voltage_list_value
        else:
            # 使用全局计算的电压序列
            voltage_list = self.voltages.tolist() if self.voltages is not None else []
            
        if not voltage_list:
            log.error("电压列表为空，无法执行电压循环")
            return False
            
        log.info(f"电压循环将使用以下电压: {voltage_list}")
        
        # 获取输出位置列表
        output_positions_key = step_config.get('output_positions_key')
        if output_positions_key:
            positions_list_value = self.configurations.get(output_positions_key)
            if not positions_list_value:
                log.error(f"找不到配置键 '{output_positions_key}'")
                return False
            # 如果是字符串，尝试转换为列表
            if isinstance(positions_list_value, str):
                try:
                    output_positions = json.loads(positions_list_value)
                except json.JSONDecodeError:
                    log.error(f"无法将位置列表字符串 '{positions_list_value}' 解析为列表")
                    return False
            else:
                output_positions = positions_list_value
        else:
            # 使用全局计算的输出位置
            output_positions = self.output_positions
            
        # 确保位置列表长度与电压列表一致
        if len(output_positions) < len(voltage_list):
            log.warning(f"输出位置列表({len(output_positions)})短于电压列表({len(voltage_list)})，将使用循环填充")
            # 循环填充位置列表
            original_len = len(output_positions)
            while len(output_positions) < len(voltage_list):
                idx = len(output_positions) % original_len  # 循环索引
                output_positions.append(output_positions[idx])
        
        log.info(f"电压循环将使用以下输出位置: {output_positions}")
        
        # 提取IT测试参数
        chi_params = step_config.get('test_params', {})
        log.info(f"将使用以下基本参数进行所有IT测试: {chi_params}")

        # 遍历电压列表执行测试
        overall_success = True
        for idx, voltage in enumerate(voltage_list):
            # 跳过指定的索引
            if idx in skip_indices:
                log.info(f"跳过索引 {idx} (电压 {voltage}V)")
                continue
                
            # 创建每个测试的上下文
            loop_context = context.copy()
            loop_context['current_voltage'] = voltage
            loop_context['current_output_position'] = output_positions[idx]
            loop_context['loop_index'] = idx
            
            # 为每个电压设置文件名
            # 将电压值转为符合文件命名规则的字符串
            num_abs_scaled = int(round(abs(voltage) * 10))
            voltage_tag = f"{'neg' if voltage < 0 else ''}{num_abs_scaled}V"
            
            # 组合IT测试基本参数和当前电压的特定设置
            this_test_params = chi_params.copy()
            this_test_params['ei'] = voltage # 设置IT测试的持续电压
            
            # 建立文件名，确保每个电压测试有唯一文件名
            base_file_name = f"{self.project_name}_IT_{voltage_tag}"
            this_test_params['fileName'] = base_file_name
            
            # 执行电位器移动到指定位置
            success = self._move_to_position({
                "position": output_positions[idx],
                "message": f"移动到位置 {output_positions[idx]} 进行 IT@{voltage}V 测试"
            }, loop_context)
            
            if not success:
                log.error(f"为电压 {voltage}V 移动到位置 {output_positions[idx]} 失败，跳过该测试")
                overall_success = False
                continue
                
            # 执行IT测试
            chi_config = {
                "chi_method": "IT",
                "chi_params": this_test_params
            }
            
            log.info(f"开始执行 IT@{voltage}V 测试 (位置: {output_positions[idx]}, 文件名: {base_file_name})")
            
            test_success = self._execute_chi_measurement(chi_config, loop_context)
            if not test_success:
                log.error(f"电压 {voltage}V 的IT测试失败")
                overall_success = False
                continue
            
            # 处理IT数据
            process_success = self._process_chi_data({
                "data_type": "IT",
                "source_file_name_in_chi_params": "fileName",
                "source_file_path": ""  # 空字符串表示使用默认路径
            }, loop_context)
            
            if not process_success:
                log.warning(f"电压 {voltage}V 的IT数据处理失败，但将继续下一个测试")
                # 这不应该导致整个循环失败，所以不设置overall_success = False
                
            # 每个测试后短暂暂停
            time.sleep(1.0)
            
        return overall_success


# --- 主程序入口 ---
if __name__ == "__main__":
    # 配置基础日志记录器
    logging.basicConfig(
        level=logging.DEBUG, # 默认级别，会被配置文件中的log_level覆盖控制器本身的logger
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(), # 输出到控制台
            logging.FileHandler("experiment_controller.log", mode='w') # 输出到文件，每次覆盖
        ]
    )

    # 配置文件路径 (可以作为命令行参数传入)
    # config_path = "experiment_config.json" # 假设在同一目录
    # 更健壮的方式：
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "experiment_config.json")


    if not os.path.exists(config_path):
        log.critical(f"错误: 配置文件 '{config_path}' 未找到。请创建它或提供正确的路径。")
        exit(1)

    try:
        controller = ExperimentController(config_file_path=config_path)
        controller.run_full_experiment()
    except ConnectionError:
        log.critical("无法连接到必要的硬件或服务。请检查配置和设备状态。")
    except ValueError as ve:
        log.critical(f"配置参数错误: {ve}。请检查JSON配置文件。")
    except RuntimeError as rte: # 例如ExcelReporter初始化强制失败
        log.critical(f"运行时关键错误: {rte}")
    except Exception as main_exception:
        log.critical(f"主程序发生未处理的严重错误: {main_exception}", exc_info=True)
    finally:
        log.info("===== 实验控制程序结束 =====")
        # 移除键盘监听 (如果PrinterControl中使用了)
        try:
            if hasattr(controller, 'printer') and controller.printer:
                # 假设PrinterControl有unhook方法或在__del__中处理
                # controller.printer.unhook_keyboard_listener()
                pass
            # import keyboard # 如果是在这里全局设置的
            # keyboard.unhook_all()
            # log.info("已尝试移除键盘监听。")
        except Exception:
            pass