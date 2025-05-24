C60_From_Easy 电化学实验自动化流程分析
项目概述
这是一个名为 "C60_From_Easy" 的电化学实验自动化配置文件，用于控制一个集成了3D打印机、泵系统、继电器阀门和CHI电化学工作站的自动化实验平台。
系统硬件配置
核心设备
3D打印机: 通过Moonraker API控制 (http://192.168.51.168:7125)
泵系统: 串口设备 /dev/ttyEKU081_ttyCH9344USB0
继电器阀门: ID为1的继电器控制
CHI电化学工作站: CHI760E型号，路径 C:\CHI760E\chi760e\chi760e.exe

关键参数设置

电压扫描范围: -1.2V 到 -1.3V
液体体积配置:
电解液填充: 8.65 mL
初始清洗: 15.0 mL
IT预排液: 2.0 mL
IT取样: 3.5 mL
IT最终清洗: 10.0 mL

完整实验流程
阶段一：系统初始化 (步骤 1-3)

1. INIT_00_HOME_PRINTER - 打印机归位
目的: 将3D打印机所有轴归零到原点位置
类型: printer_home
状态: 启用
2. FIRST_01_MOVE_TO_SAFE_POINT - 移动到安全点
目的: 将打印头移动到安全位置，避免碰撞
类型: move_printer_xyz
目标位置: (50.0, 50.0, 80.0)
条件: 可通过 skip_first_sequence 标志跳过
3. FIRST_02_MOVE_TO_INITIAL_POS - 移动到初始表征位置
目的: 移动到第一个样品位置进行初始电化学表征
类型: move_printer_grid
目标: 网格位置由 output_positions[0] 确定
条件: 可通过 skip_first_sequence 标志跳过
阶段二：初始电化学表征 (步骤 4-6)
4. FIRST_03_PUMP_ELECTROLYTE - 泵送电解液
目的: 向电解池中注入新鲜电解液
类型: sequence (复合动作)
详细步骤:
打开阀门连接储液罐 (open_to_reservoir: true)
泵送8.65 mL电解液 (direction: 1 表示正向泵送)
关闭阀门断开储液罐 (open_to_reservoir: false)
5. FIRST_04_INITIAL_CHI_TESTS - 初始电化学测试序列
目的: 执行完整的电化学表征测试
类型: chi_sequence
包含测试:
a) CV_Pre (预循环伏安)
初始电位: 0.8V, 高电位: 0.8V, 低电位: -1.4V
扫描速率: 0.2 V/s, 步长: 0.01V, 循环数: 2
灵敏度: 1e-3 A/V
b) CV_Cdl (双电层电容循环伏安)
参数同CV_Pre，用于测量双电层电容
c) CV (主循环伏安)
初始电位: 0V, 高电位: 0V, 低电位: -2.2V
扫描速率: 0.2 V/s, 步长: 0.01V, 循环数: 2
灵敏度: 1e-1 A/V
d) LSV (线性扫描伏安)
初始电位: 0V, 终止电位: -2.2V
扫描速率: 0.2 V/s, 步长: 0.01V
灵敏度: 1e-1 A/V
e) EIS (电化学阻抗谱)
直流电位: -1V
频率范围: 10 Hz - 100,000 Hz
交流幅度: 0.01V, 灵敏度: 1e-3 A/V
6. FIRST_05_PROCESS_INITIAL_DATA - 处理初始数据
目的: 处理和分析初始电化学测试数据
类型: sequence
处理内容:
CV数据处理和绘图 (锚点: E2, H2)
CV_CDL数据处理和绘图 (锚点: J2, L2)
LSV数据处理和绘图 (锚点: E16, P2)
阶段三：初始清洗 (步骤 7)
7. FIRST_06_INITIAL_CLEANING - 初始阶段清洗
目的: 清洗电解池，为后续IT测试做准备
类型: sequence
清洗步骤:
移动到废液位置 (网格位置1)
确保阀门关闭 (open_to_reservoir: false)
反向泵送15.0 mL进行清洗 (direction: 0)
阶段四：多电压IT扫描循环 (步骤 8)
8. SUBSEQUENT_07_IT_VOLTAGE_SWEEP - 核心实验循环
目的: 在不同电压下进行IT (计时电流法) 测试并收集样品
类型: voltage_loop
电压范围: -1.2V 到 -1.3V
输出位置: 由 output_positions_list 配置确定
每个电压循环包含4个子步骤:
a) IT_LOOP_PUMP_FRESH_ELECTROLYTE - 泵送新鲜电解液
打开阀门连接储液罐
泵送8.65 mL新鲜电解液
关闭阀门
b) IT_LOOP_MEASUREMENT - IT测量
方法: IT (计时电流法)
电位: 当前循环电压 ({{current_voltage}})
采样间隔: 0.1s, 测试时间: 5s
灵敏度: 1e-1 A/V
文件名: C60_From_Easy_IT_{电压}V
c) IT_LOOP_PROCESS_DATA - 数据处理
处理IT测试数据
记录当前电压、输出位置、循环索引
生成图表 (锚点: E30, H20)
d) IT_LOOP_SAMPLE_AND_CLEAN - 取样和清洗
预排液: 移动到废液位置，排出2.0 mL
取样: 移动到指定输出位置，分配3.5 mL样品
清洗: 返回废液位置，清洗10.0 mL
阶段五：实验结束 (步骤 9)
9. FINAL_08_CLEANUP_AND_HOME - 最终清理和归位
目的: 确保系统安全状态并归位
类型: sequence
步骤:
确保阀门关闭 (open_to_reservoir: false)
打印机归位到原点
实验逻辑特点
1. 条件执行
通过 skip_first_sequence 标志可以跳过初始表征阶段
适用于需要重复IT测试但跳过初始设置的场景
2. 模板变量系统
使用 {{project_name}}, {{current_voltage}} 等模板变量
实现动态文件命名和参数传递
3. 安全机制
多层安全移动策略 (先Z轴上升，再XY移动，最后Z轴下降)
每步操作后的等待时间确保系统稳定
4. 数据管理
自动文件命名和组织
Excel报告的预定义锚点位置
实时数据处理和可视化
实验输出
数据文件
CV, CV_Cdl, LSV, EIS的原始数据文件
每个电压的IT测试数据
处理后的图表和分析结果
Excel报告
项目级别和中心级别的双重图表布局
CV, CV_CDL, LSV图表的固定位置
IT测试结果的画廊式展示
这个配置文件设计了一个高度自动化的电化学实验流程，能够系统性地表征样品的电化学性质，并在不同电压条件下收集反应产物进行进一步分析。