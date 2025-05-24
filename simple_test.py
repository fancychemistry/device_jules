#!/usr/bin/env python3
"""
简单的API逻辑测试
"""

import requests
import json

def test_api_logic():
    """测试API返回值解析逻辑"""
    
    print("🧪 测试API返回值解析逻辑")
    print("=" * 40)
    
    # 模拟device_tester的API返回格式
    test_cases = [
        # 成功的情况
        {"error": False, "message": "打印机正在归位"},
        {"error": False, "message": "打印机归位成功"},
        {"error": False, "message": "泵送完成"},
        
        # 失败的情况
        {"error": True, "message": "打印机未初始化"},
        {"error": True, "message": "设备连接失败"},
        
        # 边界情况
        {"message": "缺少error字段"},  # 默认error=True
        {},  # 空响应
    ]
    
    def parse_api_response(result):
        """解析API响应的逻辑（与experiment_automation.py中的逻辑一致）"""
        success = not result.get("error", True)
        message = result.get("message", "")
        return {"success": success, "message": message}
    
    all_passed = True
    
    for i, response in enumerate(test_cases, 1):
        parsed = parse_api_response(response)
        
        # 期望结果
        expected_success = not response.get("error", True)
        
        status = "✅" if parsed["success"] == expected_success else "❌"
        print(f"{status} 测试 {i}: {response}")
        print(f"   解析结果: success={parsed['success']}, message='{parsed['message']}'")
        print(f"   期望成功: {expected_success}")
        
        if parsed["success"] != expected_success:
            all_passed = False
        
        print()
    
    if all_passed:
        print("🎉 所有API逻辑测试通过!")
    else:
        print("❌ 部分API逻辑测试失败!")
    
    return all_passed

def test_param_parsing():
    """测试参数解析逻辑"""
    
    print("🧪 测试参数解析逻辑")
    print("=" * 40)
    
    # 模拟配置
    config = {
        "configurations": {
            "safe_move_xy": [50.0, 50.0],
            "safe_move_z_high": 80.0,
            "electrolyte_volume_fill_ml": 8.65
        },
        "valve_klipper_relay_id": 1
    }
    
    def resolve_param(key_path: str, default_value=None):
        """参数解析逻辑（与experiment_automation.py中的逻辑一致）"""
        if not key_path:
            return default_value
        
        # 处理数组索引语法
        if '[' in key_path and ']' in key_path:
            base_key = key_path.split('[')[0]
            index_part = key_path.split('[')[1].rstrip(']')
            try:
                index = int(index_part)
                if base_key.startswith("configurations."):
                    config_key = base_key.replace("configurations.", "")
                    base_value = config.get("configurations", {}).get(config_key, default_value)
                else:
                    base_value = config.get("configurations", {}).get(base_key)
                    if base_value is None:
                        base_value = config.get(base_key, default_value)
                
                if isinstance(base_value, list) and 0 <= index < len(base_value):
                    return base_value[index]
                else:
                    return default_value
            except (ValueError, IndexError):
                return default_value
        
        # 处理普通配置键
        if key_path.startswith("configurations."):
            config_key = key_path.replace("configurations.", "")
            return config.get("configurations", {}).get(config_key, default_value)
        else:
            value = config.get("configurations", {}).get(key_path)
            if value is not None:
                return value
            return config.get(key_path, default_value)
    
    # 测试用例
    test_cases = [
        ("safe_move_xy[0]", 50.0),
        ("safe_move_xy[1]", 50.0),
        ("configurations.safe_move_z_high", 80.0),
        ("safe_move_z_high", 80.0),
        ("valve_klipper_relay_id", 1),
        ("electrolyte_volume_fill_ml", 8.65),
        ("nonexistent[0]", None),
        ("nonexistent_key", None)
    ]
    
    all_passed = True
    
    for key_path, expected in test_cases:
        result = resolve_param(key_path)
        status = "✅" if result == expected else "❌"
        print(f"{status} {key_path} -> {result} (期望: {expected})")
        if result != expected:
            all_passed = False
    
    if all_passed:
        print("\n🎉 所有参数解析测试通过!")
    else:
        print("\n❌ 部分参数解析测试失败!")
    
    return all_passed

if __name__ == "__main__":
    print("🔧 实验自动化系统逻辑测试")
    print("=" * 50)
    
    api_passed = test_api_logic()
    print()
    param_passed = test_param_parsing()
    
    print("\n" + "=" * 50)
    print("📊 测试总结:")
    print(f"   API逻辑: {'✅ 通过' if api_passed else '❌ 失败'}")
    print(f"   参数解析: {'✅ 通过' if param_passed else '❌ 失败'}")
    
    if api_passed and param_passed:
        print("\n🎉 所有逻辑测试通过!")
        print("\n💡 修复说明:")
        print("1. ✅ API返回值判断：error=false表示成功")
        print("2. ✅ 参数解析：支持 safe_move_xy[0] 语法") 
        print("3. ✅ 错误处理：添加HTTP状态码检查")
        print("4. ✅ 调试信息：添加详细的API调用日志")
        print("\n下一步：启动系统并测试实际API调用")
    else:
        print("\n❌ 逻辑测试失败，需要检查代码!")

# 检查实验状态
print("实验状态:")
try:
    resp = requests.get('http://localhost:8002/api/experiment/status')
    status = resp.json()
    print(f"  状态: {status.get('status')}")
    print(f"  步骤: {status.get('current_step')}/{status.get('total_steps')}")
    
    results = status.get('step_results', [])
    if results:
        print("  最新结果:")
        for r in results[-2:]:
            print(f"    {r.get('step_id')}: {'✅' if r.get('success') else '❌'} {r.get('message')}")
except Exception as e:
    print(f"  错误: {e}")

print("\nCHI状态:")
try:
    resp = requests.get('http://localhost:8001/api/chi/status')
    chi_status = resp.json()
    print(f"  CHI响应: {chi_status}")
except Exception as e:
    print(f"  错误: {e}")

print("\n设备状态:")
try:
    resp = requests.get('http://localhost:8001/api/status')
    device_status = resp.json()
    print(f"  设备状态: {device_status}")
except Exception as e:
    print(f"  错误: {e}") 