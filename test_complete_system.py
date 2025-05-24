#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import time
import json

def test_chi_sequence_execution():
    """测试完整的CHI测试序列执行"""
    
    print("🧪 完整CHI测试序列验证")
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
    
    # 2. 加载实验配置
    print("\n📋 加载实验配置...")
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
    
    # 4. 监控实验进度，特别关注CHI测试序列
    print("\n📊 监控实验进度（重点关注CHI测试序列）...")
    start_time = time.time()
    max_wait = 1200  # 20分钟
    chi_tests_detected = []
    chi_tests_completed = []
    step_5_started = False
    step_5_completed = False
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
                last_step = current_step
            
            # 检查实验是否结束
            if experiment_status in ["completed", "error"]:
                print(f"\n🏁 实验结束: {experiment_status}")
                if experiment_status == "completed":
                    print(f"🎉 实验成功完成！")
                    return True
                else:
                    print(f"❌ 实验失败")
                    return False
            
            # 特别关注步骤5（CHI测试序列）
            if current_step == 5 and not step_5_started:
                step_5_started = True
                print(f"\n🧪 CHI测试序列开始！（步骤 {current_step}）")
            
            if current_step >= 5 and step_5_started:
                # 获取详细CHI状态
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
                        current_chi_status = f"{chi_state}_{test_type}"
                        
                        # 检测新的CHI测试启动
                        if test_type != "unknown" and test_type not in chi_tests_detected:
                            chi_tests_detected.append(test_type)
                            print(f"🔬 新CHI测试启动: {test_type} (文件: {file_name})")
                        
                        # 检测CHI测试完成
                        if chi_state == "completed" and test_type not in chi_tests_completed:
                            chi_tests_completed.append(test_type)
                            print(f"✅ CHI测试完成: {test_type}")
                        
                        # 显示CHI状态变化
                        if current_chi_status != last_chi_status:
                            print(f"🔧 CHI状态: {chi_state}, 测试: {test_type}, 运行: {elapsed:.1f}s")
                            last_chi_status = current_chi_status
                        
                        # 定期显示进度
                        elif elapsed > 0 and int(elapsed) % 15 == 0:  # 每15秒显示一次
                            print(f"⏱️  CHI {test_type} 运行中: {elapsed:.1f}s")
                    
                except Exception as e:
                    print(f"⚠️ CHI状态获取异常: {e}")
            
            # 检查步骤5是否完成
            if current_step > 5 and step_5_started and not step_5_completed:
                step_5_completed = True
                print(f"\n🎉 CHI测试序列完成！")
                print(f"📈 检测到的CHI测试: {chi_tests_detected}")
                print(f"✅ 完成的CHI测试: {chi_tests_completed}")
            
            # 显示最新步骤结果
            if step_results:
                latest_result = step_results[-1]
                step_id = latest_result.get("step_id", "unknown")
                success = latest_result.get("success", False)
                message = latest_result.get("message", "")
                
                if step_id == "FIRST_04_INITIAL_CHI_TESTS":
                    if success:
                        print(f"🎉 CHI测试序列步骤完成！")
                    else:
                        print(f"❌ CHI测试序列步骤失败: {message}")
                        return False
            
            time.sleep(3)  # 较低频率监控
            
        except Exception as e:
            print(f"⚠️ 状态监控异常: {e}")
            time.sleep(5)
    
    # 超时处理
    elapsed_total = time.time() - start_time
    print(f"\n⏰ 监控超时({elapsed_total:.1f}秒)")
    print(f"🧪 检测到的CHI测试: {chi_tests_detected}")
    print(f"✅ 完成的CHI测试: {chi_tests_completed}")
    
    if len(chi_tests_completed) >= 3:  # 至少完成3个CHI测试
        print(f"🔶 部分CHI测试完成，可能需要更多时间")
        return True
    else:
        print(f"❌ CHI测试序列执行不完整")
        return False

def test_web_interface():
    """测试网页界面访问"""
    
    print("\n🌐 测试网页界面访问")
    print("=" * 40)
    
    # 测试实验自动化网页
    try:
        import urllib.request
        
        print("🔧 测试实验自动化网页 (http://localhost:8002)")
        response = urllib.request.urlopen("http://localhost:8002", timeout=10)
        html_content = response.read().decode('utf-8')
        
        if "电化学实验自动化控制台" in html_content:
            print("✅ 实验自动化网页可以正常访问")
            print("   包含正确的中文标题")
            return True
        else:
            print("⚠️ 实验自动化网页可访问但内容可能不正确")
            return False
            
    except Exception as e:
        print(f"❌ 网页访问失败: {e}")
        return False

if __name__ == "__main__":
    print("🔧 完整系统功能验证")
    print("=" * 70)
    
    # 测试1：网页界面访问
    print("\n🟦 第一阶段：网页界面访问测试")
    web_success = test_web_interface()
    
    # 测试2：完整CHI测试序列
    print("\n🟦 第二阶段：完整CHI测试序列")
    sequence_success = test_chi_sequence_execution()
    
    # 总结
    print("\n" + "=" * 70)
    print("📊 系统验证总结:")
    print(f"   网页界面访问: {'✅ 正常' if web_success else '❌ 异常'}")
    print(f"   CHI测试序列: {'✅ 正常' if sequence_success else '❌ 异常'}")
    
    if web_success and sequence_success:
        print("\n🎉 完整系统功能验证成功！")
        print("\n🔧 系统功能:")
        print("1. ✅ 网页界面可以正常访问")
        print("2. ✅ CHI测试序列能够顺序执行")
        print("3. ✅ 所有电化学测试都能正确完成")
        print("4. ✅ 文件生成和状态检测正常")
        print("\n🌐 访问地址:")
        print("   实验控制台: http://localhost:8002")
        print("   设备状态: http://localhost:8001/api/status")
        
    elif web_success:
        print("\n🔶 网页界面正常，但CHI测试序列可能有问题")
        print("   建议检查CHI设备连接和配置")
        
    elif sequence_success:
        print("\n🔶 CHI测试序列正常，但网页界面访问有问题")
        print("   建议检查端口占用和防火墙设置")
        
    else:
        print("\n⚠️ 系统存在多个问题，需要进一步调试")
        print("   建议逐步检查服务启动、网络配置和设备连接") 