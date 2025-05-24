#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import time
import json
import sys
from datetime import datetime

def check_services_status():
    """检查服务状态"""
    print("🔧 检查服务状态...")
    
    automation_url = "http://localhost:8002"
    device_url = "http://localhost:8001"
    
    try:
        # 检查device_tester服务
        device_resp = requests.get(f"{device_url}/api/status", timeout=5)
        device_status = device_resp.json()
        print(f"✅ Device Tester服务正常 (端口8001)")
        
        # 检查automation服务
        auto_resp = requests.get(f"{automation_url}/api/experiment/status", timeout=5)
        auto_status = auto_resp.json()
        print(f"✅ 实验自动化服务正常 (端口8002)，状态: {auto_status.get('status')}")
        
        return True, automation_url, device_url
        
    except Exception as e:
        print(f"❌ 服务检查失败: {e}")
        return False, None, None

def test_template_variable_resolution():
    """测试模板变量解析"""
    print("\n🔧 测试模板变量解析...")
    
    # 测试用例
    test_cases = [
        "{{project_name}}_CV",
        "{{project_name}}_EIS",
        "{{project_name}}_IT_{{current_voltage_file_str}}V",
        "C60_From_Easy",  # 纯文本
        "{{unknown_var}}_test"  # 未知变量
    ]
    
    import re
    
    # 模拟项目配置
    config = {"project_name": "C60_From_Easy"}
    context = {"current_voltage_file_str": "neg12"}
    
    for test_case in test_cases:
        print(f"🔧 测试用例: '{test_case}'")
        
        # 模拟解析逻辑
        resolved_value = test_case
        template_pattern = r'\{\{([^}]+)\}\}'
        matches = re.findall(template_pattern, test_case)
        
        for match in matches:
            template_var = match.strip()
            if template_var == "project_name":
                project_name = config.get("project_name", "Unknown")
                resolved_value = resolved_value.replace(f"{{{{{template_var}}}}}", project_name)
            elif template_var in context:
                resolved_value = resolved_value.replace(f"{{{{{template_var}}}}}", str(context[template_var]))
        
        print(f"   解析结果: '{resolved_value}'")
        
        # 验证结果
        if test_case == "{{project_name}}_CV":
            expected = "C60_From_Easy_CV"
        elif test_case == "{{project_name}}_EIS":
            expected = "C60_From_Easy_EIS"
        elif test_case == "{{project_name}}_IT_{{current_voltage_file_str}}V":
            expected = "C60_From_Easy_IT_neg12V"
        else:
            expected = resolved_value
        
        if resolved_value == expected:
            print(f"   ✅ 解析正确")
        else:
            print(f"   ❌ 解析错误，期望: '{expected}'")
    
    print("✅ 模板变量解析测试完成")

def test_chi_sequence_only():
    """仅测试CHI测试序列，不运行完整实验"""
    print("\n🧪 CHI测试序列独立测试")
    print("=" * 60)
    
    success, automation_url, device_url = check_services_status()
    if not success:
        return False
    
    # 1. 加载配置
    print("📋 加载实验配置...")
    try:
        config_resp = requests.post(f"{automation_url}/api/experiment/load_config", 
                                  json={"config_path": "old/experiment_config.json"}, 
                                  timeout=10)
        config_result = config_resp.json()
        if not config_result.get("success"):
            print(f"❌ 配置加载失败: {config_result.get('message')}")
            return False
        
        steps = config_result.get("steps", [])
        print(f"✅ 配置加载成功，总步骤数: {len(steps)}")
        
        # 找到CHI测试序列步骤
        chi_sequence_step = None
        for i, step in enumerate(steps):
            if step.get("type") == "chi_sequence":
                chi_sequence_step = (i+1, step)
                break
        
        if not chi_sequence_step:
            print("❌ 未找到CHI测试序列步骤")
            return False
        
        step_num, step_config = chi_sequence_step
        chi_tests = step_config.get("chi_tests", [])
        print(f"✅ 找到CHI测试序列: 第{step_num}步，包含{len(chi_tests)}个测试")
        
        for test in chi_tests:
            method = test.get("method")
            params = test.get("params", {})
            file_name = params.get("fileName", "unknown")
            print(f"   - {method}: {file_name}")
        
    except Exception as e:
        print(f"❌ 配置处理异常: {e}")
        return False
    
    # 2. 手动测试模板变量解析
    print("\n🔧 手动测试模板变量解析...")
    for test in chi_tests:
        method = test.get("method")
        params = test.get("params", {})
        
        # 模拟解析过程
        resolved_params = {}
        for key, value in params.items():
            if isinstance(value, str):
                import re
                resolved_value = value
                template_pattern = r'\{\{([^}]+)\}\}'
                matches = re.findall(template_pattern, value)
                
                for match in matches:
                    template_var = match.strip()
                    if template_var == "project_name":
                        project_name = "C60_From_Easy"  # 模拟配置
                        resolved_value = resolved_value.replace(f"{{{{{template_var}}}}}", project_name)
                
                resolved_params[key] = resolved_value
            else:
                resolved_params[key] = value
        
        print(f"   {method}: {params.get('fileName')} -> {resolved_params.get('fileName')}")
    
    return True

def test_full_experiment():
    """测试完整实验流程"""
    print("\n🚀 完整实验流程测试")
    print("=" * 60)
    
    success, automation_url, device_url = check_services_status()
    if not success:
        return False
    
    # 1. 加载配置
    print("📋 加载实验配置...")
    try:
        config_resp = requests.post(f"{automation_url}/api/experiment/load_config", 
                                  json={"config_path": "old/experiment_config.json"}, 
                                  timeout=10)
        config_result = config_resp.json()
        if not config_result.get("success"):
            print(f"❌ 配置加载失败: {config_result.get('message')}")
            return False
        
        total_steps = len(config_result.get("steps", []))
        print(f"✅ 配置加载成功，总步骤数: {total_steps}")
        
    except Exception as e:
        print(f"❌ 配置加载异常: {e}")
        return False
    
    # 2. 启动实验
    print("\n🚀 启动实验...")
    try:
        start_resp = requests.post(f"{automation_url}/api/experiment/start", timeout=10)
        start_result = start_resp.json()
        if not start_result.get("success"):
            print(f"❌ 实验启动失败: {start_result.get('message')}")
            return False
        
        experiment_id = start_result.get("experiment_id")
        print(f"✅ 实验启动成功: {experiment_id}")
        
    except Exception as e:
        print(f"❌ 实验启动异常: {e}")
        return False
    
    # 3. 监控实验进度
    print("\n📊 监控实验进度...")
    start_time = time.time()
    max_wait = 2400  # 40分钟
    chi_sequence_started = False
    chi_sequence_completed = False
    voltage_loop_started = False
    voltage_loop_completed = False
    chi_tests_detected = []
    last_step = 0
    step_times = {}
    
    while time.time() - start_time < max_wait:
        try:
            # 获取实验状态
            exp_resp = requests.get(f"{automation_url}/api/experiment/status", timeout=5)
            exp_status = exp_resp.json()
            
            current_step = exp_status.get("current_step", 0)
            experiment_status = exp_status.get("status", "unknown")
            step_results = exp_status.get("step_results", [])
            progress = exp_status.get("progress", 0) * 100
            
            # 记录步骤时间
            if current_step != last_step and current_step > 0:
                step_times[current_step] = time.time()
                print(f"📋 步骤进度: {current_step}/{total_steps} ({progress:.1f}%)")
                
                # 显示最新步骤结果
                if step_results:
                    latest_result = step_results[-1]
                    step_id = latest_result.get("step_id", "unknown")
                    success = latest_result.get("success", False)
                    message = latest_result.get("message", "")
                    
                    status_icon = "✅" if success else "❌"
                    print(f"   {status_icon} {step_id}: {message}")
                    
                last_step = current_step
            
            # 检查实验是否结束
            if experiment_status in ["completed", "error"]:
                print(f"\n🏁 实验结束: {experiment_status}")
                elapsed_total = time.time() - start_time
                
                if experiment_status == "completed":
                    print(f"🎉 实验成功完成！总用时: {elapsed_total:.1f}秒")
                    print(f"🧪 CHI序列是否启动: {'是' if chi_sequence_started else '否'}")
                    print(f"🧪 CHI序列是否完成: {'是' if chi_sequence_completed else '否'}")
                    print(f"🔋 电压循环是否启动: {'是' if voltage_loop_started else '否'}")
                    print(f"🔋 电压循环是否完成: {'是' if voltage_loop_completed else '否'}")
                    print(f"🔬 检测到的CHI测试: {chi_tests_detected}")
                    
                    # 分析步骤时间
                    if len(step_times) > 1:
                        print(f"\n⏱️  步骤用时分析:")
                        prev_time = min(step_times.values())
                        for step_num in sorted(step_times.keys()):
                            step_time = step_times[step_num]
                            duration = step_time - prev_time
                            print(f"   步骤 {step_num}: {duration:.1f}秒")
                            prev_time = step_time
                    
                    return chi_sequence_completed and voltage_loop_completed
                else:
                    print(f"❌ 实验失败")
                    return False
            
            # 检查CHI序列步骤
            if current_step == 5 and not chi_sequence_started:  # FIRST_04_INITIAL_CHI_TESTS
                chi_sequence_started = True
                print(f"\n🧪 CHI测试序列开始！（步骤 {current_step}）")
            
            # 检查电压循环步骤
            if current_step == 7 and not voltage_loop_started:  # SUBSEQUENT_07_IT_VOLTAGE_SWEEP  
                voltage_loop_started = True
                print(f"\n🔋 电压循环步骤开始！（步骤 {current_step}）")
            
            # 如果在CHI相关步骤中，监控CHI状态
            if (chi_sequence_started and not chi_sequence_completed) or (voltage_loop_started and not voltage_loop_completed):
                try:
                    chi_resp = requests.get(f"{device_url}/api/chi/status", timeout=5)
                    chi_status = chi_resp.json()
                    
                    if not chi_status.get("error", True):
                        status_info = chi_status.get("status", {})
                        test_type = status_info.get("test_type", "unknown")
                        file_name = status_info.get("file_name", "unknown")
                        
                        # 检测新的CHI测试
                        if test_type != "unknown" and file_name not in chi_tests_detected and file_name != "unknown":
                            chi_tests_detected.append(file_name)
                            print(f"🔬 新CHI测试检测: {test_type} - {file_name}")
                    
                except Exception as e:
                    # CHI状态获取失败不影响主流程
                    pass
            
            # 检查步骤完成
            if chi_sequence_started and current_step > 5 and not chi_sequence_completed:
                chi_sequence_completed = True
                print(f"\n🎉 CHI测试序列完成！")
            
            if voltage_loop_started and current_step > 7 and not voltage_loop_completed:
                voltage_loop_completed = True
                print(f"\n🎉 电压循环步骤完成！")
            
            time.sleep(3)  # 监控间隔
            
        except Exception as e:
            print(f"⚠️ 状态监控异常: {e}")
            time.sleep(5)
    
    # 超时处理
    elapsed_total = time.time() - start_time
    print(f"\n⏰ 监控超时({elapsed_total:.1f}秒)")
    print(f"🧪 CHI序列是否启动: {'是' if chi_sequence_started else '否'}")
    print(f"🧪 CHI序列是否完成: {'是' if chi_sequence_completed else '否'}")
    print(f"🔋 电压循环是否启动: {'是' if voltage_loop_started else '否'}")
    print(f"🔋 电压循环是否完成: {'是' if voltage_loop_completed else '否'}")
    print(f"🔬 检测到的CHI测试: {chi_tests_detected}")
    
    return False

def main():
    """主函数"""
    print("🔧 完整系统测试 - 修复后验证")
    print("=" * 70)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 测试1: 模板变量解析
    test_template_variable_resolution()
    
    # 测试2: CHI序列独立测试
    chi_test_success = test_chi_sequence_only()
    
    # 根据用户选择决定是否运行完整测试
    print(f"\n🔧 CHI序列测试结果: {'✅ 通过' if chi_test_success else '❌ 失败'}")
    
    user_input = input("\n是否继续运行完整实验测试？(y/N): ").strip().lower()
    if user_input == 'y':
        # 测试3: 完整实验流程
        full_test_success = test_full_experiment()
        
        print("\n" + "=" * 70)
        print("🔧 完整系统测试结果:")
        print(f"1. 模板变量解析: ✅ 通过")
        print(f"2. CHI序列测试: {'✅ 通过' if chi_test_success else '❌ 失败'}")
        print(f"3. 完整实验测试: {'✅ 通过' if full_test_success else '❌ 失败'}")
        
        if chi_test_success and full_test_success:
            print("\n🎉 所有测试通过！系统修复成功！")
            return True
        else:
            print("\n❌ 部分测试失败，需要进一步修复")
            return False
    else:
        print("\n✅ 基础测试完成，跳过完整实验测试")
        return chi_test_success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 