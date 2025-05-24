import requests
import time
import json

def test_valve_control():
    """测试阀门控制"""
    print("🔧 测试阀门控制...")
    
    base_url = "http://localhost:8001"
    
    # 测试打开阀门
    try:
        print("📋 测试打开阀门（连接储液罐）...")
        start_time = time.time()
        response = requests.post(f"{base_url}/api/relay/toggle", 
                               json={"relay_id": 1, "state": "on"}, 
                               timeout=60)
        elapsed = time.time() - start_time
        print(f"⏱️ 阀门打开用时: {elapsed:.2f}秒")
        print(f"📄 响应: {response.json()}")
        
        time.sleep(2)
        
        # 测试关闭阀门
        print("📋 测试关闭阀门（断开储液罐）...")
        start_time = time.time()
        response = requests.post(f"{base_url}/api/relay/toggle", 
                               json={"relay_id": 1, "state": "off"}, 
                               timeout=60)
        elapsed = time.time() - start_time
        print(f"⏱️ 阀门关闭用时: {elapsed:.2f}秒")
        print(f"📄 响应: {response.json()}")
        
        return True
        
    except Exception as e:
        print(f"❌ 阀门控制测试失败: {e}")
        return False

def test_pump_operation():
    """测试泵送操作"""
    print("🔧 测试泵送操作...")
    
    base_url = "http://localhost:8001"
    
    try:
        # 发起泵送请求
        volume_ul = 8650  # 8.65 mL = 8650 μL
        print(f"📋 开始泵送 {volume_ul} μL (8.65 mL)...")
        
        start_time = time.time()
        response = requests.post(f"{base_url}/api/pump/dispense_auto",
                               json={
                                   "pump_index": 0,
                                   "volume": volume_ul,
                                   "speed": "normal",
                                   "direction": 1
                               },
                               timeout=60)
        
        api_call_time = time.time() - start_time
        print(f"⏱️ 泵送API调用用时: {api_call_time:.2f}秒")
        print(f"📄 泵送响应: {response.json()}")
        
        if response.status_code != 200:
            print(f"❌ 泵送请求失败，HTTP状态码: {response.status_code}")
            return False
        
        result = response.json()
        if result.get("error", True):
            print(f"❌ 泵送请求错误: {result.get('message', '未知错误')}")
            return False
        
        # 监控泵送状态
        print("🔧 开始监控泵送状态...")
        monitor_start = time.time()
        last_progress = 0
        
        while time.time() - monitor_start < 300:  # 最多监控5分钟
            try:
                status_response = requests.get(f"{base_url}/api/pump/status", timeout=10)
                if status_response.status_code != 200:
                    print(f"⚠️ 获取状态失败: {status_response.status_code}")
                    time.sleep(2)
                    continue
                
                status_result = status_response.json()
                if status_result.get("error", True):
                    print(f"⚠️ 状态API错误: {status_result.get('message', '未知错误')}")
                    time.sleep(2)
                    continue
                
                status = status_result.get("status", {})
                running = status.get("running", False)
                progress = status.get("progress", 0)
                elapsed_time = status.get("elapsed_time_seconds", 0)
                total_duration = status.get("total_duration_seconds", 0)
                
                # 只在进度变化时显示
                if abs(progress - last_progress) > 0.05 or int(time.time()) % 10 == 0:
                    progress_percent = progress * 100
                    print(f"🔧 泵送进度: {progress_percent:.1f}% ({elapsed_time:.1f}s / {total_duration:.1f}s) - 运行中: {running}")
                    last_progress = progress
                
                if not running:
                    if progress >= 0.99:
                        monitor_elapsed = time.time() - monitor_start
                        print(f"✅ 泵送完成！最终进度: {progress*100:.1f}%, 监控用时: {monitor_elapsed:.1f}秒")
                        return True
                    else:
                        print(f"⚠️ 泵送提前停止，最终进度: {progress*100:.1f}%")
                        return False
                
                time.sleep(1)
                
            except Exception as status_error:
                print(f"⚠️ 监控状态异常: {status_error}")
                time.sleep(2)
        
        print("⏰ 泵送监控超时")
        return False
        
    except Exception as e:
        print(f"❌ 泵送操作测试失败: {e}")
        return False

def test_sequence():
    """测试完整的泵送序列"""
    print("🧪 测试完整的泵送序列（打开阀门 -> 泵送 -> 关闭阀门）...")
    
    # 1. 打开阀门
    if not test_valve_control():
        return False
    
    print("\n" + "="*50)
    
    # 2. 泵送
    if not test_pump_operation():
        return False
    
    print("\n" + "="*50)
    
    # 3. 再次关闭阀门确保安全
    print("🔧 最终关闭阀门确保安全...")
    try:
        response = requests.post("http://localhost:8001/api/relay/toggle", 
                               json={"relay_id": 1, "state": "off"}, 
                               timeout=60)
        print(f"📄 最终阀门响应: {response.json()}")
    except Exception as e:
        print(f"⚠️ 最终阀门关闭失败: {e}")
    
    return True

def main():
    print("=" * 60)
    print("🧪 泵送和阀门控制专项测试")
    print("=" * 60)
    
    # 初始化设备
    print("🔧 初始化设备...")
    base_url = "http://localhost:8001"
    
    try:
        # 初始化泵
        response = requests.post(f"{base_url}/api/pump/initialize")
        print(f"💧 泵初始化: {response.json()}")
        
        # 初始化继电器
        response = requests.post(f"{base_url}/api/relay/initialize")
        print(f"🔌 继电器初始化: {response.json()}")
        
        time.sleep(2)
        
    except Exception as e:
        print(f"❌ 设备初始化失败: {e}")
        return
    
    print("\n" + "="*60)
    
    # 执行测试
    success = test_sequence()
    
    print("\n" + "="*60)
    if success:
        print("🎉 泵送和阀门控制测试成功！")
    else:
        print("❌ 泵送和阀门控制测试失败")
    print("="*60)

if __name__ == "__main__":
    main() 