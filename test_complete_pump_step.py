import requests
import time
import json

def test_complete_pump_step():
    """测试完整的第4步（泵送电解液）"""
    print("🧪 测试完整的第4步（泵送电解液）...")
    
    base_url_automation = "http://localhost:8002"
    base_url_device = "http://localhost:8001"
    
    # 1. 初始化设备
    print("🔧 初始化设备...")
    try:
        response = requests.post(f"{base_url_device}/api/printer/initialize")
        print(f"🖨️ 打印机初始化: {response.json()}")
        
        response = requests.post(f"{base_url_device}/api/pump/initialize")
        print(f"💧 泵初始化: {response.json()}")
        
        response = requests.post(f"{base_url_device}/api/relay/initialize")
        print(f"🔌 继电器初始化: {response.json()}")
        
        time.sleep(2)
    except Exception as e:
        print(f"❌ 设备初始化失败: {e}")
        return False
    
    # 2. 加载配置
    print("📋 加载实验配置...")
    try:
        response = requests.post(f"{base_url_automation}/api/experiment/load_config",
                               json={"config_path": "old/experiment_config.json"})
        result = response.json()
        print(f"📋 配置加载: {result['success']} - {result['message']}")
        if not result['success']:
            return False
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")
        return False
    
    # 3. 开始实验
    print("🚀 开始实验...")
    try:
        response = requests.post(f"{base_url_automation}/api/experiment/start")
        result = response.json()
        print(f"🚀 实验开始: {result}")
        if not result['success']:
            return False
        
        experiment_id = result['experiment_id']
    except Exception as e:
        print(f"❌ 实验启动失败: {e}")
        return False
    
    # 4. 监控实验进度，等待第4步完成
    print("📊 监控实验进度，等待第4步完成...")
    max_wait_time = 600  # 最多等待10分钟
    start_time = time.time()
    last_step = 0
    step_4_completed = False
    
    while time.time() - start_time < max_wait_time:
        try:
            response = requests.get(f"{base_url_automation}/api/experiment/status")
            status = response.json()
            
            current_step = status['current_step']
            experiment_status = status['status']
            
            # 显示进度变化
            if current_step != last_step:
                print(f"📊 实验状态: {experiment_status} - 步骤 {current_step}/{status['total_steps']}")
                last_step = current_step
            
            # 检查第4步是否完成
            if len(status['step_results']) >= 4:
                step_4_result = status['step_results'][3]  # 第4步（索引3）
                if step_4_result['step_id'] == 'FIRST_03_PUMP_ELECTROLYTE':
                    step_4_completed = True
                    print("✅ 第4步（泵送电解液）已完成！")
                    
                    # 停止实验
                    requests.post(f"{base_url_automation}/api/experiment/stop")
                    
                    # 显示步骤结果
                    print("\n📋 步骤执行结果:")
                    for i, step_result in enumerate(status['step_results']):
                        success_icon = "✅" if step_result['success'] else "❌"
                        print(f"  {success_icon} 步骤 {i+1}: {step_result['step_id']} - {step_result['message']}")
                    
                    return step_4_result['success']
            
            if experiment_status in ['error', 'completed', 'stopped']:
                print(f"🏁 实验结束: {experiment_status}")
                
                # 显示步骤结果
                print("\n📋 步骤执行结果:")
                for i, step_result in enumerate(status['step_results']):
                    success_icon = "✅" if step_result['success'] else "❌"
                    print(f"  {success_icon} 步骤 {i+1}: {step_result['step_id']} - {step_result['message']}")
                
                if experiment_status == 'error':
                    print("❌ 实验出现错误")
                    return False
                else:
                    return step_4_completed
            
            time.sleep(3)  # 增加检查间隔
            
        except Exception as e:
            print(f"⚠️ 获取状态失败: {e}")
            time.sleep(3)
    
    print("⏰ 实验监控超时")
    return False

def main():
    print("=" * 60)
    print("🧪 第4步（泵送电解液）完整测试")
    print("=" * 60)
    
    success = test_complete_pump_step()
    
    print("\n" + "="*60)
    if success:
        print("🎉 第4步（泵送电解液）测试成功！")
    else:
        print("❌ 第4步（泵送电解液）测试失败")
    print("="*60)

if __name__ == "__main__":
    main() 