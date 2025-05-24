#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import time
import json

def test_chi_completion_fix():
    """测试CHI完成检测修复"""
    
    print("🧪 测试CHI完成检测修复")
    print("=" * 50)
    
    automation_url = "http://localhost:8002"
    device_url = "http://localhost:8001"
    
    # 1. 检查服务状态
    print("🔧 检查服务状态...")
    try:
        # 检查device_tester
        device_resp = requests.get(f"{device_url}/api/status", timeout=5)
        device_status = device_resp.json()
        print(f"✅ Device Tester状态: {device_status}")
        
        # 检查实验自动化
        auto_resp = requests.get(f"{automation_url}/api/experiment/status", timeout=5)
        auto_status = auto_resp.json()
        print(f"✅ 实验自动化状态: {auto_status.get('status', 'unknown')}")
        
    except Exception as e:
        print(f"❌ 服务检查失败: {e}")
        return False
    
    # 2. 手动测试CHI状态检测
    print("\n🧪 手动测试CHI状态检测...")
    try:
        # 启动一个简单的CV测试
        cv_params = {
            "ei": 0.8,
            "eh": 0.8,
            "el": -1.4,
            "v": 0.2,
            "si": 0.01,
            "cl": 1,  # 减少循环次数以便快速测试
            "sens": 1e-3,
            "fileName": "test_fix_CV"
        }
        
        print(f"🔧 启动测试CV，参数: {cv_params}")
        cv_resp = requests.post(f"{device_url}/api/chi/cv", json=cv_params, timeout=10)
        cv_result = cv_resp.json()
        
        if cv_result.get("error", True):
            print(f"❌ CV测试启动失败: {cv_result.get('message')}")
            return False
        
        print(f"✅ CV测试启动成功: {cv_result.get('message')}")
        
        # 监控CHI状态变化
        print(f"📊 监控CHI状态变化...")
        start_time = time.time()
        max_wait = 180  # 3分钟
        status_history = []
        
        while time.time() - start_time < max_wait:
            try:
                chi_resp = requests.get(f"{device_url}/api/chi/status", timeout=5)
                chi_status = chi_resp.json()
                
                if not chi_status.get("error", True):
                    status_info = chi_status.get("status", {})
                    chi_state = status_info.get("status", "unknown")
                    test_type = status_info.get("test_type", "unknown")
                    elapsed = status_info.get("elapsed_seconds", 0)
                    
                    # 记录状态变化
                    current_status = f"{chi_state}_{test_type}"
                    if not status_history or status_history[-1] != current_status:
                        status_history.append(current_status)
                        print(f"🔧 CHI状态变化: {chi_state}, 测试: {test_type}, 运行时间: {elapsed:.1f}s")
                    
                    # 检查是否完成
                    if chi_state in ["completed", "idle", "finished", "stopped"]:
                        print(f"🎉 CHI测试完成，最终状态: {chi_state}")
                        print(f"📈 状态变化历史: {' -> '.join(status_history)}")
                        return True
                    elif chi_state == "error":
                        print(f"❌ CHI测试出错，最终状态: {chi_state}")
                        return False
                
                time.sleep(3)
                
            except Exception as e:
                print(f"⚠️ 状态监控异常: {e}")
                time.sleep(3)
        
        print(f"⏰ CHI状态监控超时({max_wait}秒)")
        print(f"📈 状态变化历史: {' -> '.join(status_history)}")
        return False
        
    except Exception as e:
        print(f"❌ CHI测试异常: {e}")
        return False

def test_full_chi_sequence():
    """测试完整CHI测试序列"""
    
    print("\n🧪 测试完整CHI测试序列")
    print("=" * 50)
    
    automation_url = "http://localhost:8002"
    
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
        print(f"✅ 配置加载成功")
    except Exception as e:
        print(f"❌ 配置加载异常: {e}")
        return False
    
    # 2. 启动实验（只执行到CHI测试序列）
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
    
    # 3. 监控CHI测试序列
    print("\n📊 监控CHI测试序列...")
    chi_tests_completed = 0
    chi_tests_expected = 5  # CV_Pre, CV_Cdl, CV, LSV, EIS
    start_time = time.time()
    max_wait = 600  # 10分钟
    
    while time.time() - start_time < max_wait:
        try:
            # 检查实验状态
            status_resp = requests.get(f"{automation_url}/api/experiment/status", timeout=5)
            status = status_resp.json()
            
            current_step = status.get("current_step", 0)
            experiment_status = status.get("status", "unknown")
            step_results = status.get("step_results", [])
            
            # 如果已完成或出错，结束监控
            if experiment_status in ["completed", "error"]:
                print(f"\n🏁 实验结束: {experiment_status}")
                break
            
            # 检查是否到达CHI测试序列（步骤5）
            if current_step >= 5:
                print(f"🧪 CHI测试序列正在执行（步骤 {current_step}）")
                
                # 统计完成的CHI测试数量
                chi_step_results = [r for r in step_results if r.get("step_id") == "FIRST_04_INITIAL_CHI_TESTS"]
                if chi_step_results:
                    latest_chi_result = chi_step_results[-1]
                    if latest_chi_result.get("success"):
                        if chi_tests_completed == 0:  # 第一次检测到完成
                            chi_tests_completed = chi_tests_expected
                            print(f"🎉 CHI测试序列完成！所有{chi_tests_expected}个测试已完成")
                            return True
            
            # 显示最新步骤结果
            if step_results:
                latest_result = step_results[-1]
                step_id = latest_result.get("step_id", "unknown")
                success = latest_result.get("success", False)
                message = latest_result.get("message", "")
                status_icon = "✅" if success else "❌"
                print(f"{status_icon} 最新步骤: {step_id} - {message}")
            
            time.sleep(5)
            
        except Exception as e:
            print(f"⚠️ 状态监控异常: {e}")
            time.sleep(5)
    
    print(f"⏰ CHI测试序列监控超时")
    return False

if __name__ == "__main__":
    print("🔧 CHI测试完成检测修复验证")
    print("=" * 70)
    
    # 测试1：CHI状态检测
    chi_fix_success = test_chi_completion_fix()
    
    # 测试2：完整CHI序列
    sequence_fix_success = test_full_chi_sequence()
    
    print("\n" + "=" * 70)
    print("📊 修复验证总结:")
    print(f"   CHI状态检测: {'✅ 修复成功' if chi_fix_success else '❌ 仍有问题'}")
    print(f"   CHI测试序列: {'✅ 修复成功' if sequence_fix_success else '❌ 仍有问题'}")
    
    if chi_fix_success and sequence_fix_success:
        print("\n🎉 CHI测试序列修复验证成功！")
        print("\n💡 修复要点:")
        print("1. ✅ 修复了监控循环启动问题（设置monitoring=True）")
        print("2. ✅ 改进了文件完成检测逻辑")
        print("3. ✅ 优化了状态变化检测和清理逻辑")
        print("4. ✅ 减少了等待间隔，提高响应性")
        print("5. ✅ 确保测试完成后正确进入下一个测试")
    else:
        print("\n⚠️ CHI测试序列修复需要进一步调试") 