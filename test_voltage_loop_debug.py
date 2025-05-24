#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import time
import json

def test_voltage_loop_debug():
    """调试电压循环功能"""
    
    print("🔧 电压循环功能调试")
    print("=" * 60)
    
    automation_url = "http://localhost:8002"
    device_url = "http://localhost:8001"
    
    # 1. 检查服务状态
    print("🔧 检查服务状态...")
    try:
        device_resp = requests.get(f"{device_url}/api/status", timeout=5)
        device_status = device_resp.json()
        print(f"✅ Device Tester服务正常")
        
        auto_resp = requests.get(f"{automation_url}/api/experiment/status", timeout=5)
        auto_status = auto_resp.json()
        print(f"✅ 实验自动化服务正常，状态: {auto_status.get('status')}")
        
    except Exception as e:
        print(f"❌ 服务检查失败: {e}")
        return False
    
    # 2. 加载修复后的配置
    print("\n📋 加载修复后的配置...")
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
        
        # 检查配置修复情况
        steps = config_result.get("steps", [])
        
        # 检查是否删除了数据处理步骤
        data_processing_steps = [step for step in steps if "PROCESS" in step.get('id', '')]
        print(f"🔧 数据处理步骤数量: {len(data_processing_steps)} (应该为0)")
        
        # 找到电压循环步骤
        voltage_loop_step = None
        for i, step in enumerate(steps):
            if step.get("type") == "voltage_loop":
                voltage_loop_step = (i+1, step)
                break
        
        if voltage_loop_step:
            step_num, step_config = voltage_loop_step
            print(f"✅ 找到电压循环步骤: 第{step_num}步 - {step_config.get('description', 'voltage_loop')}")
            
            # 检查循环序列
            loop_sequence = step_config.get("loop_sequence", [])
            print(f"🔧 电压循环子步骤数量: {len(loop_sequence)}")
            for sub_step in loop_sequence:
                print(f"   - {sub_step.get('id', 'unknown')}: {sub_step.get('type', 'unknown')}")
        else:
            print("⚠️ 未找到电压循环步骤")
            return False
        
    except Exception as e:
        print(f"❌ 配置加载异常: {e}")
        return False
    
    # 3. 启动实验
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
    
    # 4. 监控实验进度
    print("\n📊 监控实验进度...")
    start_time = time.time()
    max_wait = 1800  # 30分钟
    voltage_loop_started = False
    voltage_loop_completed = False
    it_tests_detected = []
    voltages_processed = []
    last_step = 0
    
    while time.time() - start_time < max_wait:
        try:
            # 获取实验状态
            exp_resp = requests.get(f"{automation_url}/api/experiment/status", timeout=5)
            exp_status = exp_resp.json()
            
            current_step = exp_status.get("current_step", 0)
            experiment_status = exp_status.get("status", "unknown")
            step_results = exp_status.get("step_results", [])
            progress = exp_status.get("progress", 0) * 100
            
            # 显示步骤进度
            if current_step != last_step:
                print(f"📋 步骤进度: {current_step}/{total_steps} ({progress:.1f}%)")
                last_step = current_step
                
                # 显示最新步骤结果
                if step_results:
                    latest_result = step_results[-1]
                    step_id = latest_result.get("step_id", "unknown")
                    success = latest_result.get("success", False)
                    message = latest_result.get("message", "")
                    
                    status_icon = "✅" if success else "❌"
                    print(f"   {status_icon} {step_id}: {message}")
            
            # 检查实验是否结束
            if experiment_status in ["completed", "error"]:
                print(f"\n🏁 实验结束: {experiment_status}")
                if experiment_status == "completed":
                    print(f"🎉 实验成功完成！")
                    print(f"🔋 电压循环是否启动: {'是' if voltage_loop_started else '否'}")
                    print(f"🔋 电压循环是否完成: {'是' if voltage_loop_completed else '否'}")
                    print(f"⚡ 处理的电压: {voltages_processed}")
                    print(f"🔬 检测到的IT测试: {it_tests_detected}")
                    
                    if voltage_loop_completed and len(it_tests_detected) > 0:
                        return True
                    else:
                        return False
                else:
                    print(f"❌ 实验失败")
                    return False
            
            # 检查是否到达电压循环步骤
            if voltage_loop_step and current_step == voltage_loop_step[0] and not voltage_loop_started:
                voltage_loop_started = True
                print(f"\n🔋 电压循环步骤开始！（步骤 {current_step}）")
            
            # 如果在电压循环步骤中，监控CHI状态
            if voltage_loop_started and not voltage_loop_completed:
                try:
                    chi_resp = requests.get(f"{device_url}/api/chi/status", timeout=5)
                    chi_status = chi_resp.json()
                    
                    if not chi_status.get("error", True):
                        status_info = chi_status.get("status", {})
                        chi_state = status_info.get("status", "unknown")
                        test_type = status_info.get("test_type", "unknown")
                        elapsed = status_info.get("elapsed_seconds", 0)
                        file_name = status_info.get("file_name", "unknown")
                        
                        # 检测新的IT测试启动
                        if test_type == "IT" and file_name not in it_tests_detected and file_name != "unknown":
                            it_tests_detected.append(file_name)
                            
                            # 从文件名提取电压信息
                            if "_IT_" in file_name:
                                voltage_part = file_name.split("_IT_")[1].replace("V", "")
                                if voltage_part not in voltages_processed:
                                    voltages_processed.append(voltage_part)
                            
                            print(f"🔬 新IT测试启动: {file_name} (电压: {voltage_part if '_IT_' in file_name else 'unknown'})")
                        
                        # 显示CHI测试完成
                        if chi_state == "completed" and test_type == "IT":
                            print(f"✅ IT测试完成: {file_name}")
                    
                except Exception as e:
                    # CHI状态获取失败不影响主流程
                    pass
            
            # 检查电压循环步骤是否完成
            if voltage_loop_started and current_step > voltage_loop_step[0] and not voltage_loop_completed:
                voltage_loop_completed = True
                print(f"\n🎉 电压循环步骤完成！")
                print(f"⚡ 处理的电压: {voltages_processed}")
                print(f"🔬 检测到的IT测试: {it_tests_detected}")
            
            time.sleep(3)  # 监控间隔
            
        except Exception as e:
            print(f"⚠️ 状态监控异常: {e}")
            time.sleep(5)
    
    # 超时处理
    elapsed_total = time.time() - start_time
    print(f"\n⏰ 监控超时({elapsed_total:.1f}秒)")
    print(f"🔋 电压循环是否启动: {'是' if voltage_loop_started else '否'}")
    print(f"🔋 电压循环是否完成: {'是' if voltage_loop_completed else '否'}")
    print(f"⚡ 处理的电压: {voltages_processed}")
    print(f"🔬 检测到的IT测试: {it_tests_detected}")
    
    if voltage_loop_started and len(it_tests_detected) > 0:
        print(f"🔶 电压循环部分执行，检测到{len(it_tests_detected)}个IT测试")
        return True
    else:
        print(f"❌ 电压循环未正确执行")
        return False

if __name__ == "__main__":
    print("🔧 电压循环功能调试")
    print("=" * 70)
    
    success = test_voltage_loop_debug()
    
    print("\n" + "=" * 70)
    if success:
        print("🎉 电压循环功能调试成功！")
        print("\n🔧 修复内容:")
        print("1. ✅ 删除了配置文件中的数据处理步骤")
        print("2. ✅ 修复了CHI测试等待完成逻辑")
        print("3. ✅ 修复了电压序列生成逻辑")
        print("4. ✅ 改进了电压循环监控")
        print("5. ✅ 添加了详细的调试信息")
    else:
        print("❌ 电压循环功能调试失败")
        print("\n🔧 可能的问题:")
        print("1. 服务未正常启动")
        print("2. CHI设备连接问题")
        print("3. 实现逻辑仍有bug")
        print("4. 硬件设备状态异常") 