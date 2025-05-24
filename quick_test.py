#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import time
import json

def check_experiment_status():
    """检查实验状态"""
    try:
        response = requests.get('http://localhost:8002/api/experiment/status')
        status_data = response.json()
        
        experiment_id = status_data.get("experiment_id", "unknown")
        status = status_data.get("status", "unknown")
        current_step = status_data.get("current_step", 0)
        total_steps = status_data.get("total_steps", 0)
        progress = status_data.get("progress", 0) * 100
        step_results = status_data.get("step_results", [])
        
        print(f"实验ID: {experiment_id}")
        print(f"状态: {status}")
        print(f"进度: {current_step}/{total_steps} ({progress:.1f}%)")
        
        if step_results:
            print(f"最近完成的步骤:")
            for result in step_results[-3:]:  # 显示最近3个步骤
                step_id = result.get("step_id", "unknown")
                success = result.get("success", False)
                message = result.get("message", "")
                status_icon = "✅" if success else "❌"
                print(f"  {status_icon} {step_id}: {message}")
        
        return status
        
    except Exception as e:
        print(f"检查状态失败: {e}")
        return "error"

if __name__ == "__main__":
    print("🧪 实验状态监控")
    print("=" * 50)
    
    for i in range(30):  # 监控30次，每次间隔5秒
        print(f"\n📊 第 {i+1} 次检查:")
        status = check_experiment_status()
        
        if status in ["completed", "error"]:
            print(f"\n🏁 实验结束: {status}")
            break
        
        if i < 29:  # 不是最后一次检查
            print("等待5秒后再次检查...")
            time.sleep(5)
    
    print("\n" + "=" * 50)
    print("监控结束") 