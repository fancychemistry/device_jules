import requests
import json

def test_grid_api():
    try:
        # 测试打印机网格移动API
        url = "http://localhost:8001/api/printer/grid"
        payload = {"position": 2}
        
        print(f"🧪 测试API: {url}")
        print(f"📋 请求数据: {payload}")
        
        response = requests.post(url, json=payload, timeout=10)
        
        print(f"📊 响应状态码: {response.status_code}")
        print(f"📄 响应内容: {response.text}")
        
        if response.status_code == 500:
            print("❌ 确认出现HTTP 500错误 - 可能是printer_adapter未定义")
        elif response.status_code == 200:
            print("✅ API调用成功")
        else:
            print(f"⚠️ 其他状态码: {response.status_code}")
            
    except requests.exceptions.ConnectionError:
        print("❌ 连接失败 - device_tester.py可能未运行")
    except Exception as e:
        print(f"❌ 测试失败: {e}")

if __name__ == "__main__":
    test_grid_api() 