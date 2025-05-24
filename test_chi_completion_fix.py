#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import time
import json

def test_single_chi_test():
    """测试单个CHI测试的完成检测"""
    
    print("🧪 测试单个CHI测试完成检测")
    print("=" * 50)
    
    device_url = "http://localhost:8001"
    
    # 1. 启动一个CV测试
    cv_params = {
        "ei": 0.8,
        "eh": 0.8,
        "el": -1.4,
        "v": 0.2,
        "si": 0.01,
        "cl": 1,  # 只有1个循环，快速测试
        "sens": 1e-3,
        "fileName": "test_completion_fix"
    }
    
    print(f"🔧 启动CV测试...")
    try:
        cv_resp = requests.post(f"{device_url}/api/chi/cv", json=cv_params, timeout=10)
        cv_result = cv_resp.json()
        
        if cv_result.get("error", True):
            print(f"❌ CV测试启动失败: {cv_result.get('message')}")
            return False
        
        print(f"✅ CV测试启动成功: {cv_result.get('message')}")
        print(f"📁 文件名: {cv_params['fileName']}")
        
    except Exception as e:
        print(f"❌ CV测试启动异常: {e}")
        return False
    
    # 2. 详细监控CHI状态变化和文件生成
    print(f"\n📊 开始详细监控...")
    start_time = time.time()
    max_wait = 300  # 5分钟
    status_history = []
    last_elapsed = 0
    
    while time.time() - start_time < max_wait:
        try:
            # 获取CHI状态
            chi_resp = requests.get(f"{device_url}/api/chi/status", timeout=5)
            chi_status = chi_resp.json()
            
            if not chi_status.get("error", True):
                status_info = chi_status.get("status", {})
                chi_state = status_info.get("status", "unknown")
                test_type = status_info.get("test_type", "unknown")
                elapsed = status_info.get("elapsed_seconds", 0)
                file_name = status_info.get("file_name", "unknown")
                
                # 记录状态变化
                current_status = f"{chi_state}_{test_type}"
                if not status_history or status_history[-1] != current_status:
                    status_history.append(current_status)
                    print(f"🔄 CHI状态变化: {chi_state}, 测试: {test_type}, 文件: {file_name}")
                
                # 显示进度
                if elapsed > last_elapsed + 5 or elapsed == 0:  # 每5秒显示一次或首次
                    print(f"⏱️  运行时间: {elapsed:.1f}s")
                    last_elapsed = elapsed
                
                # 检查是否完成
                if chi_state in ["completed", "idle", "finished", "stopped"]:
                    elapsed_total = time.time() - start_time
                    print(f"\n🎉 CHI测试完成！")
                    print(f"   最终状态: {chi_state}")
                    print(f"   总监控时间: {elapsed_total:.1f}秒")
                    print(f"   状态变化历史: {' -> '.join(status_history)}")
                    return True
                elif chi_state == "error":
                    print(f"\n❌ CHI测试出错，状态: {chi_state}")
                    return False
            else:
                print(f"⚠️ 获取CHI状态失败: {chi_status.get('message')}")
            
            time.sleep(2)  # 高频监控
            
        except Exception as e:
            print(f"⚠️ 监控异常: {e}")
            time.sleep(3)
    
    print(f"\n⏰ 监控超时({max_wait}秒)")
    print(f"📈 状态变化历史: {' -> '.join(status_history)}")
    return False

def test_chi_sequence():
    """测试CHI测试序列"""
    
    print("\n🧪 测试CHI测试序列完成检测")
    print("=" * 50)
    
    automation_url = "http://localhost:8002"
    device_url = "http://localhost:8001"
    
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
    
    # 3. 监控CHI测试序列进度
    print("\n📊 监控CHI测试序列进度...")
    start_time = time.time()
    max_wait = 900  # 15分钟
    chi_tests_seen = set()
    chi_tests_completed = 0
    
    while time.time() - start_time < max_wait:
        try:
            # 检查实验状态
            exp_resp = requests.get(f"{automation_url}/api/experiment/status", timeout=5)
            exp_status = exp_resp.json()
            
            current_step = exp_status.get("current_step", 0)
            experiment_status = exp_status.get("status", "unknown")
            step_results = exp_status.get("step_results", [])
            
            # 显示当前步骤
            if current_step > 0:
                print(f"📋 当前步骤: {current_step}, 实验状态: {experiment_status}")
            
            # 检查是否到达CHI测试序列（步骤5）
            if current_step >= 5:
                # 获取详细CHI状态
                try:
                    chi_resp = requests.get(f"{device_url}/api/chi/status", timeout=5)
                    chi_status = chi_resp.json()
                    
                    if not chi_status.get("error", True):
                        status_info = chi_status.get("status", {})
                        chi_state = status_info.get("status", "unknown")
                        test_type = status_info.get("test_type", "unknown")
                        elapsed = status_info.get("elapsed_seconds", 0)
                        
                        # 追踪不同的CHI测试
                        if test_type != "unknown":
                            if test_type not in chi_tests_seen:
                                chi_tests_seen.add(test_type)
                                print(f"🧪 新CHI测试开始: {test_type}")
                            
                            if chi_state == "completed":
                                chi_tests_completed += 1
                                print(f"✅ CHI测试 {test_type} 完成")
                            
                        print(f"🔧 CHI: {chi_state}, 测试: {test_type}, 运行: {elapsed:.1f}s")
                
                except Exception as e:
                    print(f"⚠️ CHI状态获取异常: {e}")
            
            # 检查实验是否结束
            if experiment_status in ["completed", "error"]:
                print(f"\n🏁 实验结束: {experiment_status}")
                break
            
            # 显示最新步骤结果
            if step_results:
                latest_result = step_results[-1]
                step_id = latest_result.get("step_id", "unknown")
                success = latest_result.get("success", False)
                message = latest_result.get("message", "")
                
                if step_id == "FIRST_04_INITIAL_CHI_TESTS":
                    if success:
                        print(f"🎉 CHI测试序列完成！")
                        return True
                    else:
                        print(f"❌ CHI测试序列失败: {message}")
                        return False
            
            time.sleep(5)
            
        except Exception as e:
            print(f"⚠️ 状态监控异常: {e}")
            time.sleep(5)
    
    print(f"⏰ CHI测试序列监控超时")
    print(f"🧪 检测到的CHI测试: {list(chi_tests_seen)}")
    print(f"✅ 完成的CHI测试: {chi_tests_completed}")
    return False

if __name__ == "__main__":
    print("🔧 CHI测试完成检测修复验证")
    print("=" * 70)
    
    # 测试1：单个CHI测试
    print("\n🟦 第一阶段：单个CHI测试")
    single_test_success = test_single_chi_test()
    
    # 给系统一些时间清理
    if single_test_success:
        print("\n⏳ 等待5秒，让系统清理...")
        time.sleep(5)
    
    # 测试2：CHI测试序列
    print("\n🟦 第二阶段：CHI测试序列")
    sequence_test_success = test_chi_sequence()
    
    # 总结
    print("\n" + "=" * 70)
    print("📊 修复验证总结:")
    print(f"   单个CHI测试完成检测: {'✅ 成功' if single_test_success else '❌ 失败'}")
    print(f"   CHI测试序列完成检测: {'✅ 成功' if sequence_test_success else '❌ 失败'}")
    
    if single_test_success and sequence_test_success:
        print("\n🎉 CHI测试完成检测修复验证成功！")
        print("\n🔧 修复内容:")
        print("1. ✅ 所有CHI测试方法都设置了monitoring=True")
        print("2. ✅ 所有CHI测试方法都启动了监控循环")
        print("3. ✅ 改进了文件完成检测逻辑")
        print("4. ✅ 增加了文件修改时间检测")
        print("5. ✅ 优化了监控日志输出")
        
    elif single_test_success:
        print("\n🔶 单个CHI测试检测已修复，但测试序列仍有问题")
        print("   建议检查实验自动化中的CHI序列执行逻辑")
        
    else:
        print("\n⚠️ CHI测试完成检测仍有问题")
        print("   建议检查device_tester.py日志获取详细信息") 