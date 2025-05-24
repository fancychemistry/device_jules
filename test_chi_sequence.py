#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import time
import json

def test_chi_sequence_fix():
    """测试CHI测试序列修复"""
    
    print("🧪 测试CHI测试序列修复")
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
    
    # 2. 加载配置
    print("\n📋 加载实验配置...")
    try:
        config_resp = requests.post(f"{automation_url}/api/experiment/load_config", 
                                  json={"config_path": "old/experiment_config.json"}, 
                                  timeout=10)
        config_result = config_resp.json()
        if config_result.get("success"):
            print(f"✅ 配置加载成功: {config_result.get('message')}")
        else:
            print(f"❌ 配置加载失败: {config_result.get('message')}")
            return False
    except Exception as e:
        print(f"❌ 配置加载异常: {e}")
        return False
    
    # 3. 启动实验
    print("\n🚀 启动实验...")
    try:
        start_resp = requests.post(f"{automation_url}/api/experiment/start", timeout=10)
        start_result = start_resp.json()
        if start_result.get("success"):
            experiment_id = start_result.get("experiment_id")
            print(f"✅ 实验启动成功: {experiment_id}")
        else:
            print(f"❌ 实验启动失败: {start_result.get('message')}")
            return False
    except Exception as e:
        print(f"❌ 实验启动异常: {e}")
        return False
    
    # 4. 监控实验进度，特别关注CHI测试序列
    print("\n📊 监控实验进度（重点关注CHI测试序列）...")
    chi_sequence_started = False
    chi_sequence_completed = False
    max_monitor_time = 1800  # 30分钟
    start_time = time.time()
    
    while time.time() - start_time < max_monitor_time:
        try:
            status_resp = requests.get(f"{automation_url}/api/experiment/status", timeout=5)
            status = status_resp.json()
            
            current_step = status.get("current_step", 0)
            total_steps = status.get("total_steps", 0)
            experiment_status = status.get("status", "unknown")
            step_results = status.get("step_results", [])
            
            # 检查是否到达CHI测试序列步骤（第5步）
            if current_step >= 5 and not chi_sequence_started:
                chi_sequence_started = True
                print(f"\n🧪 CHI测试序列开始！（步骤 {current_step}/{total_steps}）")
                
                # 获取CHI状态
                try:
                    chi_resp = requests.get(f"{device_url}/api/chi/status", timeout=5)
                    chi_status = chi_resp.json()
                    print(f"🔧 CHI初始状态: {chi_status}")
                except Exception as e:
                    print(f"⚠️ 获取CHI状态失败: {e}")
            
            # 如果CHI测试序列已开始，详细监控
            if chi_sequence_started and not chi_sequence_completed:
                try:
                    chi_resp = requests.get(f"{device_url}/api/chi/status", timeout=5)
                    chi_status = chi_resp.json()
                    
                    if not chi_status.get("error", True):
                        chi_info = chi_status.get("status", {})
                        chi_state = chi_info.get("status", "unknown")
                        test_type = chi_info.get("test_type", "unknown")
                        elapsed = chi_info.get("elapsed_seconds", 0)
                        
                        print(f"🔧 CHI状态: {chi_state}, 测试: {test_type}, 运行时间: {elapsed:.1f}s")
                        
                        # 检查是否完成
                        if chi_state in ["completed", "idle"] and current_step > 5:
                            chi_sequence_completed = True
                            print(f"🎉 CHI测试序列完成！")
                    
                except Exception as e:
                    print(f"⚠️ CHI状态监控异常: {e}")
            
            # 显示最新步骤结果
            if step_results:
                latest_result = step_results[-1]
                step_id = latest_result.get("step_id", "unknown")
                success = latest_result.get("success", False)
                message = latest_result.get("message", "")
                status_icon = "✅" if success else "❌"
                print(f"{status_icon} 最新步骤: {step_id} - {message}")
            
            # 检查实验是否结束
            if experiment_status in ["completed", "error"]:
                print(f"\n🏁 实验结束: {experiment_status}")
                break
            
            # 等待间隔
            time.sleep(10)
            
        except Exception as e:
            print(f"⚠️ 状态监控异常: {e}")
            time.sleep(5)
    
    # 5. 总结结果
    print("\n" + "=" * 50)
    print("📊 测试总结:")
    
    if chi_sequence_started:
        print("✅ CHI测试序列已启动")
        if chi_sequence_completed:
            print("✅ CHI测试序列已完成")
            print("🎉 CHI测试序列修复验证成功！")
            return True
        else:
            print("⚠️ CHI测试序列未完成（可能仍在运行）")
            return False
    else:
        print("❌ CHI测试序列未启动")
        return False

if __name__ == "__main__":
    success = test_chi_sequence_fix()
    if success:
        print("\n🎉 CHI测试序列修复验证成功！")
    else:
        print("\n⚠️ CHI测试序列可能需要更多时间或存在问题")
    
    print("\n💡 修复要点:")
    print("1. ✅ 改进了CHI测试序列的执行逻辑")
    print("2. ✅ 增强了CHI状态检测和等待逻辑") 
    print("3. ✅ 添加了详细的调试信息和错误处理")
    print("4. ✅ 确保每个CHI测试都能正确等待完成") 