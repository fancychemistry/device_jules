import requests
import time
import json

def test_first_4_steps():
    """测试前4个步骤"""
    print("🧪 测试前4个实验步骤...")
    
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
    
    # 4. 监控实验进度
    print("📊 监控实验进度...")
    max_wait_time = 300  # 最多等待5分钟
    start_time = time.time()
    last_step = 0
    
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
            
            # 检查是否完成前4步或出错
            if current_step >= 4:
                print("✅ 前4个步骤已完成！")
                
                # 停止实验
                requests.post(f"{base_url_automation}/api/experiment/stop")
                
                # 显示步骤结果
                print("\n📋 步骤执行结果:")
                for i, step_result in enumerate(status['step_results']):
                    success_icon = "✅" if step_result['success'] else "❌"
                    print(f"  {success_icon} 步骤 {i+1}: {step_result['step_id']} - {step_result['message']}")
                
                return True
            
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
                    return True
            
            time.sleep(2)
            
        except Exception as e:
            print(f"⚠️ 获取状态失败: {e}")
            time.sleep(2)
    
    print("⏰ 实验监控超时")
    return False

def main():
    print("=" * 60)
    print("🧪 前4步骤专项测试")
    print("=" * 60)
    
    success = test_first_4_steps()
    
    print("\n" + "="*60)
    if success:
        print("🎉 前4步骤测试成功！")
    else:
        print("❌ 前4步骤测试失败")
    print("="*60)

if __name__ == "__main__":
    main() 