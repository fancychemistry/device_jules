import asyncio
import httpx
import sys
import time

async def test_device_tester():
    """测试device_tester的基本功能"""
    
    # 设备测试器URL
    url = "http://localhost:8001"
    
    print("开始测试device_tester...")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. 测试状态API
            print("1. 测试状态API...")
            try:
                response = await client.get(f"{url}/api/status")
                if response.status_code == 200:
                    status = response.json()
                    print(f"  ✅ 状态获取成功: {status}")
                else:
                    print(f"  ❌ 状态获取失败: {response.status_code}")
                    return False
            except Exception as e:
                print(f"  ❌ 状态API调用失败: {e}")
                return False
            
            # 2. 测试打印机初始化
            print("2. 测试打印机初始化...")
            try:
                response = await client.post(f"{url}/api/printer/initialize")
                if response.status_code == 200:
                    result = response.json()
                    if not result.get("error", True):
                        print(f"  ✅ 打印机初始化成功: {result.get('message')}")
                    else:
                        print(f"  ⚠️ 打印机初始化返回错误: {result.get('message')}")
                else:
                    print(f"  ❌ 打印机初始化失败: {response.status_code}")
            except Exception as e:
                print(f"  ❌ 打印机初始化调用失败: {e}")
            
            # 3. 测试泵初始化
            print("3. 测试泵初始化...")
            try:
                response = await client.post(f"{url}/api/pump/initialize")
                if response.status_code == 200:
                    result = response.json()
                    if not result.get("error", True):
                        print(f"  ✅ 泵初始化成功: {result.get('message')}")
                    else:
                        print(f"  ⚠️ 泵初始化返回错误: {result.get('message')}")
                else:
                    print(f"  ❌ 泵初始化失败: {response.status_code}")
            except Exception as e:
                print(f"  ❌ 泵初始化调用失败: {e}")
            
            # 4. 测试继电器初始化
            print("4. 测试继电器初始化...")
            try:
                response = await client.post(f"{url}/api/relay/initialize")
                if response.status_code == 200:
                    result = response.json()
                    if not result.get("error", True):
                        print(f"  ✅ 继电器初始化成功: {result.get('message')}")
                    else:
                        print(f"  ⚠️ 继电器初始化返回错误: {result.get('message')}")
                else:
                    print(f"  ❌ 继电器初始化失败: {response.status_code}")
            except Exception as e:
                print(f"  ❌ 继电器初始化调用失败: {e}")
            
            # 5. 测试CHI初始化
            print("5. 测试CHI初始化...")
            try:
                response = await client.post(f"{url}/api/chi/initialize")
                if response.status_code == 200:
                    result = response.json()
                    if not result.get("error", True):
                        print(f"  ✅ CHI初始化成功: {result.get('message')}")
                    else:
                        print(f"  ⚠️ CHI初始化返回错误: {result.get('message')}")
                else:
                    print(f"  ❌ CHI初始化失败: {response.status_code}")
            except Exception as e:
                print(f"  ❌ CHI初始化调用失败: {e}")
            
            # 6. 再次检查最终状态
            print("6. 检查最终状态...")
            try:
                response = await client.get(f"{url}/api/status")
                if response.status_code == 200:
                    status = response.json()
                    print(f"  ✅ 最终状态: {status}")
                    
                    # 统计初始化成功的设备数量
                    initialized_count = sum([
                        status.get("printer", {}).get("initialized", False),
                        status.get("pump", {}).get("initialized", False),
                        status.get("relay", {}).get("initialized", False),
                        status.get("chi", {}).get("initialized", False)
                    ])
                    
                    print(f"  📊 {initialized_count}/4 个设备初始化成功")
                    return initialized_count >= 2  # 至少有2个设备成功即认为测试通过
                    
            except Exception as e:
                print(f"  ❌ 最终状态检查失败: {e}")
                return False
    
    except Exception as e:
        print(f"❌ 测试过程中发生异常: {e}")
        return False

def main():
    """主函数"""
    print("DeviceTester功能测试")
    print("=" * 50)
    
    # 检查device_tester是否正在运行
    print("检查device_tester是否运行...")
    try:
        import requests
        response = requests.get("http://localhost:8001/api/status", timeout=5)
        if response.status_code != 200:
            print("❌ device_tester未运行，请先启动: python device_tester.py")
            return False
        print("✅ device_tester正在运行")
    except Exception as e:
        print(f"❌ device_tester未运行或无法连接: {e}")
        print("请先启动: python device_tester.py")
        return False
    
    # 运行异步测试
    result = asyncio.run(test_device_tester())
    
    print("=" * 50)
    if result:
        print("✅ 测试通过！device_tester基本功能正常")
        return True
    else:
        print("❌ 测试失败！device_tester存在问题")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 