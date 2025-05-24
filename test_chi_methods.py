import requests
import time
import json

def test_chi_initialization():
    """测试CHI初始化"""
    print("🧪 测试CHI初始化...")
    
    base_url = "http://localhost:8001"
    
    try:
        response = requests.post(f"{base_url}/api/chi/initialize")
        result = response.json()
        print(f"📄 CHI初始化响应: {result}")
        
        if result.get("error", True):
            print(f"❌ CHI初始化失败: {result.get('message')}")
            return False
        else:
            print("✅ CHI初始化成功")
            return True
            
    except Exception as e:
        print(f"❌ CHI初始化异常: {e}")
        return False

def test_chi_status():
    """测试CHI状态"""
    print("🔧 检查CHI状态...")
    
    base_url = "http://localhost:8001"
    
    try:
        response = requests.get(f"{base_url}/api/chi/status")
        result = response.json()
        print(f"📊 CHI状态: {result}")
        return True
    except Exception as e:
        print(f"❌ 获取CHI状态失败: {e}")
        return False

def test_cv_method():
    """测试循环伏安法(CV)"""
    print("🔬 测试循环伏安法(CV)...")
    
    base_url = "http://localhost:8001"
    
    # CV测试参数
    cv_params = {
        "ei": -0.5,      # 初始电位 (V)
        "eh": 0.5,       # 高电位 (V)
        "el": -0.5,      # 低电位 (V)
        "v": 0.1,        # 扫描速率 (V/s)
        "si": 0.001,     # 采样间隔 (V)
        "cl": 2,         # 循环次数
        "sens": 1e-5,    # 灵敏度 (A/V)
        "qt": 2.0,       # 静置时间 (s)
        "pn": "p",       # 初始扫描方向
        "file_name": "test_cv",
        "autosens": False
    }
    
    try:
        response = requests.post(f"{base_url}/api/chi/cv", json=cv_params)
        result = response.json()
        print(f"📄 CV测试响应: {result}")
        
        if result.get("error", True):
            print(f"❌ CV测试失败: {result.get('message')}")
            return False
        else:
            print("✅ CV测试已启动")
            return True
            
    except Exception as e:
        print(f"❌ CV测试异常: {e}")
        return False

def test_lsv_method():
    """测试线性扫描伏安法(LSV)"""
    print("🔬 测试线性扫描伏安法(LSV)...")
    
    base_url = "http://localhost:8001"
    
    # LSV测试参数
    lsv_params = {
        "initial_v": -0.5,    # 初始电位 (V)
        "final_v": 0.5,       # 最终电位 (V)
        "scan_rate": 0.1,     # 扫描速率 (V/s)
        "interval": 0.001,    # 采样间隔 (V)
        "sens": 1e-5,         # 灵敏度 (A/V)
        "file_name": "test_lsv"
    }
    
    try:
        response = requests.post(f"{base_url}/api/chi/lsv", json=lsv_params)
        result = response.json()
        print(f"📄 LSV测试响应: {result}")
        
        if result.get("error", True):
            print(f"❌ LSV测试失败: {result.get('message')}")
            return False
        else:
            print("✅ LSV测试已启动")
            return True
            
    except Exception as e:
        print(f"❌ LSV测试异常: {e}")
        return False

def test_eis_method():
    """测试电化学阻抗谱(EIS)"""
    print("🔬 测试电化学阻抗谱(EIS)...")
    
    base_url = "http://localhost:8001"
    
    # EIS测试参数
    eis_params = {
        "voltage": 0.0,         # 直流电位 (V)
        "freq_init": 100000,    # 起始频率 (Hz)
        "freq_final": 0.1,      # 结束频率 (Hz)
        "amplitude": 10,        # 交流振幅 (mV)
        "sens": 1e-5,           # 灵敏度 (A/V)
        "impautosens": True,    # 自动灵敏度
        "mode": "impsf",        # 测试模式
        "file_name": "test_eis"
    }
    
    try:
        response = requests.post(f"{base_url}/api/chi/eis", json=eis_params)
        result = response.json()
        print(f"📄 EIS测试响应: {result}")
        
        if result.get("error", True):
            print(f"❌ EIS测试失败: {result.get('message')}")
            return False
        else:
            print("✅ EIS测试已启动")
            return True
            
    except Exception as e:
        print(f"❌ EIS测试异常: {e}")
        return False

def test_it_method():
    """测试计时电流法(IT)"""
    print("🔬 测试计时电流法(IT)...")
    
    base_url = "http://localhost:8001"
    
    # IT测试参数
    it_params = {
        "ei": 0.0,        # 恒定电位 (V)
        "st": 60.0,       # 总采样时间 (s)
        "si": 0.1,        # 采样间隔 (s)
        "sens": 1e-5,     # 灵敏度 (A/V)
        "file_name": "test_it"
    }
    
    try:
        response = requests.post(f"{base_url}/api/chi/it", json=it_params)
        result = response.json()
        print(f"📄 IT测试响应: {result}")
        
        if result.get("error", True):
            print(f"❌ IT测试失败: {result.get('message')}")
            return False
        else:
            print("✅ IT测试已启动")
            return True
            
    except Exception as e:
        print(f"❌ IT测试异常: {e}")
        return False

def test_ca_method():
    """测试计时安培法(CA)"""
    print("🔬 测试计时安培法(CA)...")
    
    base_url = "http://localhost:8001"
    
    # CA测试参数
    ca_params = {
        "ei": 0.0,        # 初始电位 (V)
        "eh": 0.5,        # 高电位 (V)
        "el": -0.5,       # 低电位 (V)
        "cl": 3,          # 阶跃数
        "pw": 5.0,        # 脉冲宽度 (s)
        "si": 0.1,        # 采样间隔 (s)
        "sens": 1e-5,     # 灵敏度 (A/V)
        "qt": 2.0,        # 静置时间 (s)
        "pn": "p",        # 初始极性
        "file_name": "test_ca",
        "autosens": False
    }
    
    try:
        response = requests.post(f"{base_url}/api/chi/ca", json=ca_params)
        result = response.json()
        print(f"📄 CA测试响应: {result}")
        
        if result.get("error", True):
            print(f"❌ CA测试失败: {result.get('message')}")
            return False
        else:
            print("✅ CA测试已启动")
            return True
            
    except Exception as e:
        print(f"❌ CA测试异常: {e}")
        return False

def test_ocp_method():
    """测试开路电位(OCP)"""
    print("🔬 测试开路电位(OCP)...")
    
    base_url = "http://localhost:8001"
    
    # OCP测试参数
    ocp_params = {
        "st": 30.0,       # 运行时间 (s)
        "si": 0.1,        # 采样间隔 (s)
        "eh": 2.0,        # 高电位限制 (V)
        "el": -2.0,       # 低电位限制 (V)
        "file_name": "test_ocp"
    }
    
    try:
        response = requests.post(f"{base_url}/api/chi/ocp", json=ocp_params)
        result = response.json()
        print(f"📄 OCP测试响应: {result}")
        
        if result.get("error", True):
            print(f"❌ OCP测试失败: {result.get('message')}")
            return False
        else:
            print("✅ OCP测试已启动")
            return True
            
    except Exception as e:
        print(f"❌ OCP测试异常: {e}")
        return False

def wait_for_test_completion(test_name, wait_time=10):
    """等待测试完成"""
    print(f"⏳ 等待{test_name}测试完成 ({wait_time}秒)...")
    time.sleep(wait_time)
    
    # 检查CHI状态
    try:
        response = requests.get("http://localhost:8001/api/chi/status")
        status = response.json()
        print(f"📊 当前CHI状态: {status}")
    except Exception as e:
        print(f"❌ 获取状态失败: {e}")

def main():
    print("=" * 60)
    print("🧪 CHI电化学方法全面测试")
    print("=" * 60)
    
    # 1. 初始化CHI
    if not test_chi_initialization():
        print("❌ CHI初始化失败，无法继续测试")
        return
    
    print("\n" + "-" * 40)
    
    # 2. 检查CHI状态
    test_chi_status()
    
    print("\n" + "-" * 40)
    
    # 3. 测试各种电化学方法
    methods_to_test = [
        ("CV (循环伏安法)", test_cv_method, 30),
        ("LSV (线性扫描伏安法)", test_lsv_method, 20),
        ("IT (计时电流法)", test_it_method, 15),
        ("CA (计时安培法)", test_ca_method, 25),
        ("OCP (开路电位)", test_ocp_method, 10),
        ("EIS (电化学阻抗谱)", test_eis_method, 60)
    ]
    
    successful_tests = 0
    total_tests = len(methods_to_test)
    
    for method_name, test_func, wait_time in methods_to_test:
        print(f"\n📋 测试 {method_name}...")
        
        if test_func():
            successful_tests += 1
            wait_for_test_completion(method_name, wait_time)
        else:
            print(f"❌ {method_name} 测试失败")
        
        print("-" * 40)
    
    # 4. 总结
    print(f"\n🎯 测试总结:")
    print(f"✅ 成功: {successful_tests}/{total_tests}")
    print(f"❌ 失败: {total_tests - successful_tests}/{total_tests}")
    
    if successful_tests == total_tests:
        print("🎉 所有电化学方法测试成功！")
    else:
        print("⚠️  部分电化学方法测试失败，请检查日志")
    
    print("=" * 60)

if __name__ == "__main__":
    main() 