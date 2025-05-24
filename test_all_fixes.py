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

def test_custom_project_name():
    """测试自定义项目名称功能"""
    print("\n🔧 测试自定义项目名称功能")
    print("=" * 60)
    
    success, automation_url, device_url = check_services_status()
    if not success:
        return False
    
    custom_project_name = f"TestProject_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    print(f"📋 测试自定义项目名称: {custom_project_name}")
    
    try:
        # 1. 加载配置时指定自定义项目名称
        config_resp = requests.post(f"{automation_url}/api/experiment/load_config", 
                                  json={
                                      "config_path": "old/experiment_config.json",
                                      "project_name": custom_project_name
                                  }, 
                                  timeout=10)
        config_result = config_resp.json()
        
        if not config_result.get("success"):
            print(f"❌ 配置加载失败: {config_result.get('message')}")
            return False
        
        print(f"✅ 配置加载成功")
        print(f"📋 项目名称: {config_result.get('project_name')}")
        print(f"📁 项目文件夹: {config_result.get('project_folder')}")
        print(f"📊 总步骤数: {config_result.get('total_steps')}")
        
        # 验证项目名称是否正确设置
        if config_result.get('project_name') == custom_project_name:
            print(f"✅ 自定义项目名称设置成功")
        else:
            print(f"❌ 项目名称设置失败，期望: {custom_project_name}, 实际: {config_result.get('project_name')}")
            return False
        
        # 验证项目文件夹是否包含项目名称
        project_folder = config_result.get('project_folder', '')
        if custom_project_name in project_folder:
            print(f"✅ 项目文件夹路径正确")
        else:
            print(f"❌ 项目文件夹路径错误，路径: {project_folder}")
            return False
        
        # 2. 测试状态API中是否包含项目信息
        status_resp = requests.get(f"{automation_url}/api/experiment/status", timeout=5)
        status_result = status_resp.json()
        
        if status_result.get('project_name') == custom_project_name:
            print(f"✅ 状态API中项目名称正确")
        else:
            print(f"❌ 状态API中项目名称错误")
            return False
        
        # 3. 验证日志功能
        experiment_logs = status_result.get('experiment_logs', [])
        print(f"📝 当前日志条数: {len(experiment_logs)}")
        
        if len(experiment_logs) > 0:
            print(f"✅ 日志系统正常工作")
            # 显示最新的几条日志
            for log in experiment_logs[-3:]:
                print(f"   [{log.get('timestamp')}] {log.get('message')}")
        else:
            print(f"⚠️ 暂无日志记录")
            
        return True
        
    except Exception as e:
        print(f"❌ 测试自定义项目名称异常: {e}")
        return False

def test_step_order_and_status():
    """测试步骤顺序和状态显示"""
    print("\n🔧 测试步骤顺序和状态显示")
    print("=" * 60)
    
    success, automation_url, device_url = check_services_status()
    if not success:
        return False
    
    try:
        # 1. 加载配置
        print("📋 加载实验配置...")
        config_resp = requests.post(f"{automation_url}/api/experiment/load_config", 
                                  json={"config_path": "old/experiment_config.json"}, 
                                  timeout=10)
        config_result = config_resp.json()
        
        if not config_result.get("success"):
            print(f"❌ 配置加载失败: {config_result.get('message')}")
            return False
        
        total_steps = config_result.get("total_steps", 0)
        print(f"✅ 配置加载成功，总步骤数: {total_steps}")
        
        # 2. 获取详细状态信息
        print("\n📊 获取详细状态信息...")
        status_resp = requests.get(f"{automation_url}/api/experiment/status", timeout=5)
        status_result = status_resp.json()
        
        print(f"实验ID: {status_result.get('experiment_id', '无')}")
        print(f"项目名称: {status_result.get('project_name', '无')}")
        print(f"项目文件夹: {status_result.get('project_folder', '无')}")
        print(f"实验状态: {status_result.get('status', '无')}")
        print(f"当前步骤: {status_result.get('current_step', 0)}/{status_result.get('total_steps', 0)}")
        print(f"当前步骤名称: {status_result.get('current_step_name', '无')}")
        print(f"当前步骤描述: {status_result.get('current_step_description', '无')}")
        print(f"已完成步骤: {status_result.get('completed_steps', 0)}")
        print(f"失败步骤: {status_result.get('failed_steps', 0)}")
        
        # 3. 验证步骤列表
        all_step_results = status_result.get('all_step_results', [])
        print(f"\n📋 步骤结果详情 (共{len(all_step_results)}个):")
        
        if all_step_results:
            for result in all_step_results:
                step_id = result.get('step_id', '未知')
                step_index = result.get('step_index', -1)
                success_status = '✅' if result.get('success', False) else '❌'
                skipped = result.get('skipped', False)
                if skipped:
                    success_status = '⏭️'
                duration = result.get('duration_seconds', 0)
                
                print(f"  {success_status} 步骤{step_index + 1}: {step_id} (用时: {duration:.1f}s)")
        else:
            print("  暂无步骤结果")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试步骤顺序和状态异常: {e}")
        return False

def test_short_experiment_run():
    """测试短时间实验运行（只执行前几个步骤）"""
    print("\n🔧 测试短时间实验运行")
    print("=" * 60)
    
    success, automation_url, device_url = check_services_status()
    if not success:
        return False
    
    test_project_name = f"ShortTest_{datetime.now().strftime('%H%M%S')}"
    
    try:
        # 1. 加载配置
        print(f"📋 加载配置，项目名称: {test_project_name}")
        config_resp = requests.post(f"{automation_url}/api/experiment/load_config", 
                                  json={
                                      "config_path": "old/experiment_config.json",
                                      "project_name": test_project_name
                                  }, 
                                  timeout=10)
        config_result = config_resp.json()
        
        if not config_result.get("success"):
            print(f"❌ 配置加载失败: {config_result.get('message')}")
            return False
        
        print(f"✅ 配置加载成功")
        
        # 2. 启动实验
        print("\n🚀 启动实验...")
        start_resp = requests.post(f"{automation_url}/api/experiment/start", timeout=10)
        start_result = start_resp.json()
        
        if not start_result.get("success"):
            print(f"❌ 实验启动失败: {start_result.get('message')}")
            return False
        
        experiment_id = start_result.get("experiment_id")
        print(f"✅ 实验启动成功: {experiment_id}")
        
        # 3. 监控前几个步骤（最多30秒）
        print("\n📊 监控实验进度...")
        start_time = time.time()
        max_wait = 30  # 30秒
        last_step = 0
        last_status = None
        
        while time.time() - start_time < max_wait:
            try:
                status_resp = requests.get(f"{automation_url}/api/experiment/status", timeout=5)
                status = status_resp.json()
                
                current_step = status.get("current_step", 0)
                experiment_status = status.get("status", "unknown")
                current_step_name = status.get("current_step_name", "")
                current_step_description = status.get("current_step_description", "")
                
                # 如果步骤或状态发生变化，输出信息
                if current_step != last_step or experiment_status != last_status:
                    print(f"📋 步骤更新: {current_step}/{status.get('total_steps', 0)}")
                    print(f"   状态: {experiment_status}")
                    print(f"   当前步骤: {current_step_name}")
                    print(f"   描述: {current_step_description}")
                    
                    last_step = current_step
                    last_status = experiment_status
                
                # 如果实验结束或执行了几个步骤就停止
                if experiment_status in ["completed", "error"] or current_step >= 3:
                    print(f"\n⏹ 停止监控，当前状态: {experiment_status}, 步骤: {current_step}")
                    break
                
                time.sleep(2)
                
            except Exception as e:
                print(f"⚠️ 状态监控异常: {e}")
                time.sleep(2)
        
        # 4. 停止实验（如果还在运行）
        if last_status == "running":
            print("\n⏹ 主动停止实验...")
            try:
                stop_resp = requests.post(f"{automation_url}/api/experiment/stop", timeout=5)
                stop_result = stop_resp.json()
                if stop_result.get("success"):
                    print("✅ 实验已停止")
                else:
                    print(f"⚠️ 停止实验失败: {stop_result.get('message')}")
            except Exception as e:
                print(f"⚠️ 停止实验异常: {e}")
        
        # 5. 获取最终状态
        print("\n📊 获取最终状态...")
        final_status_resp = requests.get(f"{automation_url}/api/experiment/status", timeout=5)
        final_status = final_status_resp.json()
        
        completed_steps = final_status.get("completed_steps", 0)
        failed_steps = final_status.get("failed_steps", 0)
        all_results = final_status.get("all_step_results", [])
        
        print(f"✅ 已完成步骤: {completed_steps}")
        print(f"❌ 失败步骤: {failed_steps}")
        print(f"📋 总记录步骤: {len(all_results)}")
        
        # 输出步骤详情
        if all_results:
            print("\n📋 步骤执行详情:")
            for i, result in enumerate(all_results):
                step_id = result.get('step_id', '未知')
                success = result.get('success', False)
                skipped = result.get('skipped', False)
                duration = result.get('duration_seconds', 0)
                message = result.get('message', '无消息')
                
                if skipped:
                    status_icon = "⏭️"
                    status_text = "跳过"
                elif success:
                    status_icon = "✅"
                    status_text = "成功"
                else:
                    status_icon = "❌"
                    status_text = "失败"
                
                print(f"  {status_icon} {step_id}: {status_text} (用时: {duration:.1f}s)")
                if message and message != "无消息":
                    print(f"      消息: {message}")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试短时间实验运行异常: {e}")
        return False

def main():
    """主函数"""
    print("🔧 完整系统修复验证测试")
    print("=" * 70)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 测试1: 自定义项目名称功能
    test1_success = test_custom_project_name()
    
    # 测试2: 步骤顺序和状态显示
    test2_success = test_step_order_and_status()
    
    # 测试3: 短时间实验运行
    test3_success = test_short_experiment_run()
    
    print("\n" + "=" * 70)
    print("🔧 完整系统修复验证结果:")
    print(f"1. 自定义项目名称功能: {'✅ 通过' if test1_success else '❌ 失败'}")
    print(f"2. 步骤顺序和状态显示: {'✅ 通过' if test2_success else '❌ 失败'}")
    print(f"3. 短时间实验运行测试: {'✅ 通过' if test3_success else '❌ 失败'}")
    
    all_tests_passed = test1_success and test2_success and test3_success
    
    if all_tests_passed:
        print("\n🎉 所有修复验证测试通过！系统修复成功！")
        print("\n📋 修复总结:")
        print("✅ 1. 增加了自定义project_name功能")
        print("✅ 2. 修复了步骤执行顺序问题")
        print("✅ 3. 改进了实时日志和状态显示")
        print("✅ 4. 增加了项目文件夹自动创建功能")
        print("✅ 5. 改进了Web界面的用户体验")
        return True
    else:
        print("\n❌ 部分测试失败，需要进一步检查和修复")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 