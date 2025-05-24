#!/usr/bin/env python3
"""
调试API响应格式
"""

import asyncio
import httpx
import json

async def test_api_responses():
    """测试device_tester的API响应格式"""
    
    print("🔧 测试 device_tester API 响应格式")
    print("=" * 50)
    
    device_tester_url = "http://localhost:8001"
    
    # 测试打印机归位API
    print("\n📍 测试打印机归位API...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(f"{device_tester_url}/api/printer/home")
            
            print(f"HTTP状态码: {response.status_code}")
            print(f"响应头: {dict(response.headers)}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"响应内容: {json.dumps(result, indent=2, ensure_ascii=False)}")
                
                # 测试我们的逻辑
                success = not result.get("error", True)
                message = result.get("message", "")
                print(f"解析结果: success={success}, message='{message}'")
                
                if success:
                    print("✅ 根据我们的逻辑，这应该是成功的")
                else:
                    print("❌ 根据我们的逻辑，这应该是失败的")
            else:
                print(f"❌ HTTP请求失败: {response.status_code}")
                try:
                    error_content = response.text
                    print(f"错误内容: {error_content}")
                except:
                    print("无法读取错误内容")
                    
    except Exception as e:
        print(f"❌ API调用异常: {e}")
    
    # 测试状态API
    print("\n📊 测试系统状态API...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{device_tester_url}/api/status")
            
            print(f"HTTP状态码: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"状态响应: {json.dumps(result, indent=2, ensure_ascii=False)}")
            else:
                print(f"❌ 状态查询失败: {response.status_code}")
                
    except Exception as e:
        print(f"❌ 状态查询异常: {e}")

if __name__ == "__main__":
    asyncio.run(test_api_responses()) 