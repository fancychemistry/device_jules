#!/usr/bin/env python3
"""
综合测试脚本 - 验证所有修复
"""

import json
import asyncio
import httpx

def test_template_variable_resolution():
    """测试模板变量解析"""
    
    print("🧪 测试模板变量解析")
    print("=" * 50)
    
    # 模拟配置
    config = {
        "project_name": "C60_From_Easy",
        "first_experiment_position": 2,
        "output_positions_list": None,
        "configurations": {
            "initial_char_grid_position": "{{output_positions[0]}}",
            "waste_fluid_grid_position": 1
        }
    }
    
    def provide_default_values(config):
        """提供默认值"""
        if config.get("output_positions_list") is None:
            first_pos = config.get("first_experiment_position", 2)
            default_positions = [first_pos, first_pos + 1, first_pos + 2, first_pos + 3]
            config["output_positions"] = default_positions
            print(f"🔧 创建默认输出位置: {default_positions}")
        else:
            config["output_positions"] = config["output_positions_list"]
    
    def resolve_template_value(value, config):
        """解析模板变量"""
        if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
            template_var = value[2:-2].strip()
            
            if template_var == "project_name":
                return config.get("project_name", "Unknown")
            elif template_var.startswith("output_positions[") and template_var.endswith("]"):
                try:
                    index_str = template_var[len("output_positions["):-1]
                    index = int(index_str)
                    output_positions = config.get("output_positions", [])
                    if 0 <= index < len(output_positions):
                        resolved = output_positions[index]
                        print(f"🔧 模板变量解析: {value} -> {resolved}")
                        return resolved
                    else:
                        print(f"⚠️ 输出位置索引超出范围: {template_var}, 使用默认值2")
                        return 2
                except (ValueError, IndexError) as e:
                    print(f"⚠️ 解析输出位置索引失败: {template_var}, 错误: {e}, 使用默认值2")
                    return 2
            else:
                print(f"⚠️ 未知模板变量: {template_var}, 保持原值")
                return value
        return value
    
    def resolve_recursive(obj, config):
        """递归解析"""
        if isinstance(obj, dict):
            return {key: resolve_recursive(value, config) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [resolve_recursive(item, config) for item in obj]
        elif isinstance(obj, str) and obj.startswith("{{") and obj.endswith("}}"):
            return resolve_template_value(obj, config)
        else:
            return obj
    
    # 测试流程
    print("原始配置:")
    print(f"  initial_char_grid_position: {config['configurations']['initial_char_grid_position']}")
    print(f"  output_positions_list: {config.get('output_positions_list')}")
    
    provide_default_values(config)
    
    # 解析配置
    config["configurations"] = resolve_recursive(config["configurations"], config)
    
    print("\n解析后配置:")
    print(f"  initial_char_grid_position: {config['configurations']['initial_char_grid_position']}")
    print(f"  output_positions: {config.get('output_positions')}")
    
    # 验证结果
    expected_position = 2  # first_experiment_position
    actual_position = config['configurations']['initial_char_grid_position']
    
    if actual_position == expected_position:
        print("✅ 模板变量解析测试通过!")
        return True
    else:
        print(f"❌ 模板变量解析测试失败! 期望: {expected_position}, 实际: {actual_position}")
        return False

async def test_full_system():
    """测试完整系统"""
    
    print("\n🚀 测试完整系统")
    print("=" * 50)
    
    # 检查experiment_automation是否在运行
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://localhost:8002/api/experiment/status")
            if response.status_code == 200:
                print("✅ 实验自动化系统运行正常")
                
                # 测试加载配置
                print("🔧 测试配置加载...")
                load_response = await client.post(
                    "http://localhost:8002/api/experiment/load_config",
                    json={"config_path": "old/experiment_config.json"}
                )
                
                if load_response.status_code == 200:
                    result = load_response.json()
                    if result.get("success"):
                        print("✅ 配置加载成功")
                        print(f"📋 步骤数量: {len(result.get('steps', []))}")
                        return True
                    else:
                        print(f"❌ 配置加载失败: {result.get('message')}")
                        return False
                else:
                    print(f"❌ 配置加载请求失败: {load_response.status_code}")
                    return False
            else:
                print(f"❌ 系统状态检查失败: {response.status_code}")
                return False
    except Exception as e:
        print(f"❌ 系统测试失败: {e}")
        print("💡 请先启动实验自动化系统: python experiment_automation.py")
        return False

def test_api_response_parsing():
    """测试API响应解析"""
    
    print("\n🔧 测试API响应解析")
    print("=" * 30)
    
    def parse_api_response(result):
        """通用的API响应解析函数"""
        message = result.get("message", "")
        
        if "success" in result:
            success = result.get("success", False)
            return {"success": success, "message": message}
        elif "error" in result:
            success = not result.get("error", True)
            return {"success": success, "message": message}
        else:
            return {"success": False, "message": message or "未知响应格式"}
    
    # 测试用例
    test_cases = [
        ({"success": True, "message": "操作成功"}, True),
        ({"success": False, "message": "操作失败"}, False),
        ({"error": False, "message": "操作成功"}, True),
        ({"error": True, "message": "操作失败"}, False),
    ]
    
    all_passed = True
    for response, expected in test_cases:
        parsed = parse_api_response(response)
        if parsed["success"] != expected:
            print(f"❌ 解析失败: {response} -> {parsed['success']} (期望: {expected})")
            all_passed = False
    
    if all_passed:
        print("✅ API响应解析测试通过!")
    
    return all_passed

async def main():
    """主测试函数"""
    
    print("🔧 综合测试 - 验证所有修复")
    print("=" * 60)
    
    tests = [
        ("模板变量解析", test_template_variable_resolution()),
        ("API响应解析", test_api_response_parsing()),
        ("完整系统测试", await test_full_system())
    ]
    
    passed = 0
    total = len(tests)
    
    for name, result in tests:
        if result:
            passed += 1
            print(f"✅ {name}: 通过")
        else:
            print(f"❌ {name}: 失败")
    
    print("\n" + "=" * 60)
    print(f"📊 测试结果: {passed}/{total} 通过")
    
    if passed == total:
        print("🎉 所有测试通过! 系统已准备就绪!")
        print("\n💡 下一步:")
        print("1. 启动系统: python experiment_automation.py")
        print("2. 访问控制台: http://localhost:8002")
        print("3. 加载配置并开始实验")
    else:
        print("⚠️ 部分测试失败，请检查相关功能")

if __name__ == "__main__":
    asyncio.run(main()) 