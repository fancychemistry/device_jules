#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import json

def test_chi_filename():
    """测试CHI文件命名功能"""
    automation_url = "http://localhost:8002"
    
    try:
        # 1. 先加载配置
        print("📋 加载配置...")
        config_resp = requests.post(f"{automation_url}/api/experiment/load_config", 
                                  json={
                                      "config_path": "old/experiment_config.json",
                                      "project_name": "TestCHI_Naming"
                                  }, 
                                  timeout=10)
        config_result = config_resp.json()
        
        if config_result.get("success"):
            print(f"✅ 配置加载成功，项目名称: {config_result.get('project_name')}")
        else:
            print(f"❌ 配置加载失败: {config_result.get('message')}")
            return False
        
        # 2. 测试CHI文件命名
        print("🧪 测试CHI文件命名...")
        chi_resp = requests.post(f"{automation_url}/api/experiment/test_chi_filename", timeout=5)
        chi_result = chi_resp.json()
        
        if chi_result.get("success"):
            print(f"✅ CHI文件命名测试成功")
            print(f"📋 项目名称: {chi_result.get('project_name')}")
            print(f"📄 测试文件名: {chi_result.get('test_filename')}")
            print(f"📁 CHI工作目录: {chi_result.get('chi_working_directory')}")
            print(f"💡 消息: {chi_result.get('message')}")
        else:
            print(f"❌ CHI文件命名测试失败: {chi_result.get('message')}")
            return False
            
        # 3. 测试状态API
        print("📊 获取实验状态...")
        status_resp = requests.get(f"{automation_url}/api/experiment/status", timeout=5)
        status = status_resp.json()
        
        print(f"📋 项目名称: {status.get('project_name')}")
        print(f"📁 项目文件夹: {status.get('project_folder')}")
        print(f"📝 日志条数: {len(status.get('experiment_logs', []))}")
        
        # 显示最新日志
        logs = status.get('experiment_logs', [])
        if logs:
            print("📝 最新日志:")
            for log in logs[-3:]:
                print(f"   [{log.get('timestamp')}] [{log.get('level')}] {log.get('message')}")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        return False

if __name__ == "__main__":
    print("🔧 CHI文件命名功能测试")
    print("=" * 50)
    success = test_chi_filename()
    if success:
        print("\n🎉 CHI文件命名测试通过！")
    else:
        print("\n❌ CHI文件命名测试失败！") 