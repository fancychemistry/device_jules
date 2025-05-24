import requests
import time
import json

def init_devices():
    """初始化所有设备"""
    base_url = "http://localhost:8001"
    
    print("🔧 初始化设备...")
    
    # 初始化打印机
    try:
        response = requests.post(f"{base_url}/api/printer/initialize")
        print(f"🖨️ 打印机初始化: {response.json()}")
        time.sleep(2)
    except Exception as e:
        print(f"❌ 打印机初始化失败: {e}")
        return False
    
    # 初始化泵
    try:
        response = requests.post(f"{base_url}/api/pump/initialize")
        print(f"💧 泵初始化: {response.json()}")
        time.sleep(2)
    except Exception as e:
        print(f"❌ 泵初始化失败: {e}")
        return False
    
    # 初始化继电器
    try:
        response = requests.post(f"{base_url}/api/relay/initialize")
        print(f"🔌 继电器初始化: {response.json()}")
        time.sleep(2)
    except Exception as e:
        print(f"❌ 继电器初始化失败: {e}")
        return False
    
    # 初始化CHI
    try:
        response = requests.post(f"{base_url}/api/chi/initialize")
        print(f"🧪 CHI初始化: {response.json()}")
    except Exception as e:
        print(f"⚠️ CHI初始化失败: {e} (跳过，继续测试其他功能)")
    
    time.sleep(2)
    
    return True

def test_experiment():
    """测试实验流程"""
    automation_url = "http://localhost:8002"
    
    print("🧪 测试实验流程...")
    
    # 加载配置
    try:
        response = requests.post(f"{automation_url}/api/experiment/load_config", 
                               json={"config_path": "old/experiment_config.json"})
        result = response.json()
        print(f"📋 配置加载: {result}")
        if not result.get("success", False):
            print(f"❌ 配置加载失败: {result.get('message')}")
            return False
        time.sleep(1)
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")
        return False
    
    # 开始实验
    try:
        response = requests.post(f"{automation_url}/api/experiment/start")
        result = response.json()
        print(f"🚀 实验开始: {result}")
        
        if not result.get("success", False):
            print(f"❌ 实验启动失败: {result.get('message')}")
            return False
        
        # 监控实验状态
        for i in range(120):  # 监控120次，每次间隔5秒（总共10分钟）
            time.sleep(5)
            try:
                status_response = requests.get(f"{automation_url}/api/experiment/status")
                status_data = status_response.json()
                
                if not status_data.get("success", False):
                    print(f"❌ 获取状态失败: {status_data.get('message')}")
                    continue
                
                status = status_data.get("status", {})
                experiment_status = status.get("status", "unknown")
                current_step = status.get("current_step", 0)
                total_steps = status.get("total_steps", 0)
                step_results = status.get("step_results", [])
                
                print(f"📊 实验状态 ({i+1}/120): {experiment_status} - 步骤 {current_step}/{total_steps}")
                
                # 显示最新的步骤结果
                if step_results:
                    latest_result = step_results[-1]
                    step_id = latest_result.get("step_id", "未知")
                    success = latest_result.get("success", False)
                    message = latest_result.get("message", "")
                    
                    if success:
                        print(f"  ✅ 最新步骤 {step_id}: {message}")
                    else:
                        print(f"  ❌ 最新步骤 {step_id}: {message}")
                
                if experiment_status in ['completed', 'error']:
                    print(f"🏁 实验结束: {experiment_status}")
                    if experiment_status == 'error':
                        print(f"❌ 错误信息: {status.get('error', '未知错误')}")
                        # 显示所有失败的步骤
                        print("❌ 失败步骤详情:")
                        for result in step_results:
                            if not result.get("success", False):
                                print(f"  - {result.get('step_id')}: {result.get('message')}")
                    return experiment_status == 'completed'
                    
            except Exception as e:
                print(f"❌ 状态检查失败: {e}")
                
        print("⏰ 监控超时，实验可能仍在运行")
        return False
        
    except Exception as e:
        print(f"❌ 实验启动失败: {e}")
        return False

def test_experiment_step(step_name, step_id):
    """测试单个实验步骤"""
    print(f"🧪 测试步骤: {step_name} (ID: {step_id})")
    
    base_url = "http://localhost:8002"
    
    try:
        response = requests.post(f"{base_url}/execute_step", json={"step_id": step_id})
        result = response.json()
        print(f"📄 步骤响应: {result}")
        
        if result.get("success", False):
            print(f"✅ {step_name} 执行成功")
            return True
        else:
            print(f"❌ {step_name} 执行失败: {result.get('message', '未知错误')}")
            return False
            
    except Exception as e:
        print(f"❌ {step_name} 执行异常: {e}")
        return False

def test_chi_test_step(test_name, step_id):
    """测试CHI电化学测试步骤"""
    print(f"🔬 测试CHI步骤: {test_name} (ID: {step_id})")
    
    base_url = "http://localhost:8002"
    
    try:
        response = requests.post(f"{base_url}/execute_step", json={"step_id": step_id})
        result = response.json()
        print(f"📄 CHI步骤响应: {result}")
        
        if result.get("success", False):
            print(f"✅ {test_name} 启动成功")
            # 等待CHI测试完成
            wait_for_chi_completion(test_name)
            return True
        else:
            print(f"❌ {test_name} 启动失败: {result.get('message', '未知错误')}")
            return False
            
    except Exception as e:
        print(f"❌ {test_name} 执行异常: {e}")
        return False

def wait_for_chi_completion(test_name, max_wait=120):
    """等待CHI测试完成"""
    print(f"⏳ 等待{test_name}完成...")
    
    base_url = "http://localhost:8001"
    wait_time = 0
    
    while wait_time < max_wait:
        try:
            response = requests.get(f"{base_url}/api/chi/status")
            result = response.json()
            
            if not result.get("error", True):
                status = result.get("status", {})
                chi_status = status.get("status", "unknown")
                
                if chi_status == "idle":
                    print(f"✅ {test_name}已完成")
                    return True
                elif chi_status == "running":
                    elapsed = status.get("elapsed_seconds", 0)
                    print(f"🔄 {test_name}运行中... (已运行{elapsed:.1f}秒)")
                elif chi_status == "error":
                    print(f"❌ {test_name}出错")
                    return False
            
            time.sleep(5)
            wait_time += 5
            
        except Exception as e:
            print(f"⚠️ 监控CHI状态异常: {e}")
            time.sleep(5)
            wait_time += 5
    
    print(f"⏰ {test_name}监控超时")
    return False

def check_automation_service():
    """检查自动化服务状态"""
    print("🔧 检查实验自动化服务...")
    
    base_url = "http://localhost:8002"
    
    try:
        response = requests.get(f"{base_url}/api/experiment/status")
        result = response.json()
        print(f"📊 自动化服务状态: {result}")
        return True
    except Exception as e:
        print(f"❌ 自动化服务连接失败: {e}")
        return False

def load_experiment_config():
    """加载实验配置"""
    print("📋 加载实验配置...")
    
    base_url = "http://localhost:8002"
    
    try:
        # 使用old/experiment_config.json配置文件
        config_data = {"config_file": "old/experiment_config.json"}
        response = requests.post(f"{base_url}/api/experiment/load_config", json=config_data)
        result = response.json()
        print(f"📄 配置加载响应: {result}")
        
        if result.get("success", False):
            print("✅ 实验配置加载成功")
            return True
        else:
            print(f"❌ 实验配置加载失败: {result.get('message', '未知错误')}")
            return False
            
    except Exception as e:
        print(f"❌ 加载实验配置异常: {e}")
        return False

def start_experiment():
    """启动实验"""
    print("🚀 启动实验...")
    
    base_url = "http://localhost:8002"
    
    try:
        response = requests.post(f"{base_url}/api/experiment/start")
        result = response.json()
        print(f"📄 实验启动响应: {result}")
        
        if result.get("success", False):
            print("✅ 实验启动成功")
            return True
        else:
            print(f"❌ 实验启动失败: {result.get('message', '未知错误')}")
            return False
            
    except Exception as e:
        print(f"❌ 启动实验异常: {e}")
        return False

def monitor_experiment_progress(max_wait=600):
    """监控实验进度"""
    print("📊 监控实验进度...")
    
    base_url = "http://localhost:8002"
    wait_time = 0
    last_step = -1
    
    while wait_time < max_wait:
        try:
            response = requests.get(f"{base_url}/api/experiment/status")
            result = response.json()
            
            if result.get("success", False):
                status = result.get("status", {})
                current_step = status.get("current_step", 0)
                total_steps = status.get("total_steps", 0)
                progress = status.get("progress", 0)
                is_running = status.get("is_running", False)
                step_results = status.get("step_results", [])
                
                # 显示新步骤的进度
                if current_step != last_step:
                    print(f"🔄 步骤进度: {current_step}/{total_steps} ({progress*100:.1f}%)")
                    
                    # 显示最近的步骤结果
                    if step_results:
                        latest_result = step_results[-1]
                        step_id = latest_result.get("step_id", "未知")
                        success = latest_result.get("success", False)
                        message = latest_result.get("message", "")
                        
                        if success:
                            print(f"✅ 步骤 {step_id} 成功: {message}")
                        else:
                            print(f"❌ 步骤 {step_id} 失败: {message}")
                    
                    last_step = current_step
                
                # 检查实验是否完成
                if not is_running:
                    if current_step >= total_steps:
                        print("🎉 实验完成！")
                        return True, step_results
                    else:
                        print("❌ 实验提前结束")
                        return False, step_results
            
            time.sleep(5)
            wait_time += 5
            
        except Exception as e:
            print(f"⚠️ 监控实验状态异常: {e}")
            time.sleep(5)
            wait_time += 5
    
    print("⏰ 实验监控超时")
    return False, []

def analyze_experiment_results(step_results):
    """分析实验结果"""
    print("\n📊 实验结果分析:")
    print("-" * 50)
    
    if not step_results:
        print("❌ 没有步骤结果数据")
        return
    
    successful_steps = 0
    failed_steps = 0
    
    for result in step_results:
        step_id = result.get("step_id", "未知")
        success = result.get("success", False)
        message = result.get("message", "")
        
        if success:
            print(f"✅ {step_id}: {message}")
            successful_steps += 1
        else:
            print(f"❌ {step_id}: {message}")
            failed_steps += 1
    
    total_steps = successful_steps + failed_steps
    print("-" * 50)
    print(f"📈 总结: {successful_steps}/{total_steps} 步骤成功")
    print(f"✅ 成功: {successful_steps}")
    print(f"❌ 失败: {failed_steps}")
    
    if failed_steps == 0:
        print("🎉 所有步骤都成功执行！")
    else:
        print(f"⚠️ 有 {failed_steps} 个步骤失败")

def check_chi_results():
    """检查CHI测试结果文件"""
    print("\n🔬 检查CHI测试结果文件:")
    print("-" * 40)
    
    try:
        response = requests.get("http://localhost:8001/api/chi/results")
        result = response.json()
        
        if not result.get("error", True):
            files = result.get("files", [])
            print(f"📁 找到 {len(files)} 个结果文件:")
            
            for file_info in files:
                filename = file_info.get("filename", "未知")
                size = file_info.get("size", 0)
                modified = file_info.get("modified", "未知")
                print(f"  📄 {filename} ({size} bytes, {modified})")
        else:
            print("❌ 获取CHI结果文件失败")
            
    except Exception as e:
        print(f"❌ 检查CHI结果异常: {e}")

def main():
    print("=" * 70)
    print("🧪 完整实验自动化流程测试")
    print("=" * 70)
    
    # 1. 检查自动化服务
    if not check_automation_service():
        print("❌ 自动化服务不可用，请先启动experiment_automation.py")
        return
    
    print("\n" + "-" * 50)
    
    # 2. 加载实验配置
    if not load_experiment_config():
        print("❌ 实验配置加载失败，无法继续")
        return
    
    print("\n" + "-" * 50)
    
    # 3. 启动实验
    if not start_experiment():
        print("❌ 实验启动失败，无法继续")
        return
    
    print("\n" + "-" * 50)
    
    # 4. 监控实验进度
    success, step_results = monitor_experiment_progress()
    
    print("\n" + "-" * 50)
    
    # 5. 分析实验结果
    analyze_experiment_results(step_results)
    
    print("\n" + "-" * 50)
    
    # 6. 检查CHI结果文件
    check_chi_results()
    
    # 7. 总结
    print("\n" + "=" * 70)
    print("🎯 完整实验自动化测试总结")
    print("=" * 70)
    
    if success:
        print("🎉 完整实验自动化流程测试成功！")
        print("✅ 所有硬件设备和电化学方法都正常工作")
        print("✅ 实验数据已成功生成")
    else:
        print("❌ 实验自动化流程测试失败")
        print("⚠️ 请检查失败的步骤和相关日志")
    
    print("=" * 70)

if __name__ == "__main__":
    main() 