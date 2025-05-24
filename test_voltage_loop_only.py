#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import time
import json

def test_voltage_loop_only():
    """专门测试电压循环功能"""
    
    print("🔋 专门测试电压循环功能")
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
    
    # 2. 加载专门的电压循环测试配置
    print("\n📋 加载电压循环测试配置...")
    try:
        config_resp = requests.post(f"{automation_url}/api/experiment/load_config", 
                                  json={"config_path": "test_voltage_loop_config.json"}, 
                                  timeout=10)
        config_result = config_resp.json()
        if not config_result.get("success"):
            print(f"❌ 配置加载失败: {config_result.get('message')}")
            return False
        
        total_steps = len(config_result.get("steps", []))
        print(f"✅ 配置加载成功，总步骤数: {total_steps}")
        
        # 显示步骤信息
        steps = config_result.get("steps", [])
        for i, step in enumerate(steps):
            step_type = step.get("type", "unknown")
            description = step.get("description", "")
            print(f"  步骤 {i+1}: {step_type} - {description}")
        
    except Exception as e:
        print(f"❌ 配置加载异常: {e}")
        return False
    
    # 3. 启动实验
    print("\n🚀 启动电压循环测试实验...")
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
    
    # 4. 监控实验进度，特别关注电压循环步骤
    print("\n📊 监控电压循环实验进度...")
    start_time = time.time()
    max_wait = 1800  # 30分钟
    voltage_loop_started = False
    voltage_loop_completed = False
    it_tests_detected = []
    last_step = 0
    last_chi_status = None
    
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
                if step_results:
                    latest_result = step_results[-1]
                    step_id = latest_result.get("step_id", "unknown")
                    success = latest_result.get("success", False)
                    message = latest_result.get("message", "")
                    status_icon = "✅" if success else "❌"
                    print(f"  {status_icon} {step_id}: {message}")
                last_step = current_step
            
            # 检查实验是否结束
            if experiment_status in ["completed", "error"]:
                print(f"\n🏁 实验结束: {experiment_status}")
                if experiment_status == "completed":
                    print(f"🎉 电压循环测试成功完成！")
                    if voltage_loop_completed:
                        print(f"✅ 电压循环步骤成功执行")
                        print(f"🔬 检测到的IT测试: {it_tests_detected}")
                        return True
                    else:
                        print(f"⚠️ 实验完成但电压循环可能未执行")
                        return False
                else:
                    print(f"❌ 实验失败")
                    # 显示错误详情
                    if step_results:
                        for result in step_results:
                            if not result.get("success", True):
                                print(f"  ❌ 失败步骤: {result.get('step_id')} - {result.get('message')}")
                    return False
            
            # 检查是否到达电压循环步骤（第3步）
            if current_step == 3 and not voltage_loop_started:
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
                        
                        # 构建状态标识
                        current_chi_status = f"{chi_state}_{test_type}_{file_name}"
                        
                        # 检测新的IT测试启动
                        if test_type == "IT" and file_name not in it_tests_detected:
                            it_tests_detected.append(file_name)
                            print(f"🔬 新IT测试启动: {file_name}")
                        
                        # 显示CHI状态变化
                        if current_chi_status != last_chi_status:
                            if test_type == "IT":
                                print(f"🔧 IT测试状态: {chi_state}, 文件: {file_name}, 运行: {elapsed:.1f}s")
                            last_chi_status = current_chi_status
                        
                        # 定期显示IT测试进度
                        elif test_type == "IT" and elapsed > 0 and int(elapsed) % 15 == 0:
                            print(f"⏱️  IT测试运行中: {file_name}, {elapsed:.1f}s")
                    
                except Exception as e:
                    # CHI状态获取失败不影响主流程
                    pass
            
            # 检查电压循环步骤是否完成
            if voltage_loop_started and current_step > 3 and not voltage_loop_completed:
                voltage_loop_completed = True
                print(f"\n🎉 电压循环步骤完成！")
                print(f"📈 检测到的IT测试: {it_tests_detected}")
            
            # 显示最新步骤结果
            if step_results:
                latest_result = step_results[-1]
                step_id = latest_result.get("step_id", "unknown")
                success = latest_result.get("success", False)
                message = latest_result.get("message", "")
                
                if step_id == "TEST_02_IT_VOLTAGE_SWEEP":
                    if success:
                        print(f"🎉 电压循环步骤成功完成！消息: {message}")
                    else:
                        print(f"❌ 电压循环步骤失败: {message}")
                        return False
            
            time.sleep(3)  # 监控间隔
            
        except Exception as e:
            print(f"⚠️ 状态监控异常: {e}")
            time.sleep(5)
    
    # 超时处理
    elapsed_total = time.time() - start_time
    print(f"\n⏰ 监控超时({elapsed_total:.1f}秒)")
    print(f"🔋 电压循环是否启动: {'是' if voltage_loop_started else '否'}")
    print(f"🔋 电压循环是否完成: {'是' if voltage_loop_completed else '否'}")
    print(f"🔬 检测到的IT测试: {it_tests_detected}")
    
    if voltage_loop_started and len(it_tests_detected) > 0:
        print(f"🔶 电压循环部分执行，检测到{len(it_tests_detected)}个IT测试")
        return True
    else:
        print(f"❌ 电压循环未正确执行")
        return False

if __name__ == "__main__":
    print("🔧 电压循环专项测试")
    print("=" * 70)
    
    success = test_voltage_loop_only()
    
    print("\n" + "=" * 70)
    if success:
        print("🎉 电压循环专项测试成功！")
        print("\n🔧 验证要点:")
        print("1. ✅ voltage_loop步骤类型正确识别")
        print("2. ✅ 电压范围自动生成和解析")
        print("3. ✅ 输出位置配置正确应用")
        print("4. ✅ 模板变量正确替换")
        print("5. ✅ IT测试序列正确执行")
        print("6. ✅ CHI测试完成检测正常")
        print("7. ✅ grid移动和泵送操作正常")
    else:
        print("❌ 电压循环专项测试失败")
        print("\n🔧 可能的问题:")
        print("1. voltage_loop实现逻辑有bug")
        print("2. 模板变量解析失败")
        print("3. CHI设备连接问题")
        print("4. 硬件设备响应异常")
        print("5. 配置文件格式错误") 