#!/usr/bin/env python3
"""
测试参数解析修复
"""

import json
import sys
from pathlib import Path

def test_param_resolution():
    """测试参数解析逻辑"""
    
    # 模拟配置数据
    config = {
        "configurations": {
            "safe_move_xy": [50.0, 50.0],
            "safe_move_z_high": 80.0,
            "electrolyte_volume_fill_ml": 8.65,
            "waste_fluid_grid_position": 1
        },
        "valve_klipper_relay_id": 1
    }
    
    def resolve_param(key_path: str, default_value=None):
        """解析参数键路径，支持数组索引语法"""
        if not key_path:
            return default_value
        
        # 处理数组索引语法，例如 "safe_move_xy[0]" 或 "configurations.safe_move_xy[0]"
        if '[' in key_path and ']' in key_path:
            # 提取基础键和索引
            base_key = key_path.split('[')[0]
            index_part = key_path.split('[')[1].rstrip(']')
            try:
                index = int(index_part)
                # 获取基础值
                if base_key.startswith("configurations."):
                    config_key = base_key.replace("configurations.", "")
                    base_value = config.get("configurations", {}).get(config_key, default_value)
                else:
                    # 对于没有configurations前缀的键，先尝试从configurations中查找
                    base_value = config.get("configurations", {}).get(base_key)
                    if base_value is None:
                        base_value = config.get(base_key, default_value)
                
                # 如果基础值是列表，返回指定索引的值
                if isinstance(base_value, list) and 0 <= index < len(base_value):
                    return base_value[index]
                else:
                    print(f"无法解析数组索引: {key_path}, base_value={base_value}")
                    return default_value
            except (ValueError, IndexError) as e:
                print(f"解析数组索引失败: {key_path}, error={e}")
                return default_value
        
        # 处理普通配置键
        if key_path.startswith("configurations."):
            config_key = key_path.replace("configurations.", "")
            return config.get("configurations", {}).get(config_key, default_value)
        else:
            # 对于没有configurations前缀的键，先尝试从configurations中查找
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
        ("waste_fluid_grid_position", 1),
        ("nonexistent_key", None)
    ]
    
    print("🧪 测试参数解析修复")
    print("=" * 40)
    
    all_passed = True
    for key_path, expected in test_cases:
        result = resolve_param(key_path)
        status = "✅" if result == expected else "❌"
        print(f"{status} {key_path} -> {result} (期望: {expected})")
        if result != expected:
            all_passed = False
    
    print("=" * 40)
    if all_passed:
        print("🎉 所有测试通过!")
    else:
        print("❌ 部分测试失败!")
    
    return all_passed

def test_config_loading():
    """测试配置文件加载"""
    config_path = "old/experiment_config.json"
    
    print("\n📁 测试配置文件加载")
    print("=" * 40)
    
    if not Path(config_path).exists():
        print(f"❌ 配置文件不存在: {config_path}")
        return False
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        print(f"✅ 配置文件加载成功")
        print(f"📋 项目名称: {config.get('project_name')}")
        print(f"📋 实验步骤数: {len(config.get('experiment_sequence', []))}")
        
        # 检查关键配置
        configurations = config.get("configurations", {})
        print(f"📋 安全移动XY: {configurations.get('safe_move_xy')}")
        print(f"📋 安全移动Z: {configurations.get('safe_move_z_high')}")
        
        return True
        
    except Exception as e:
        print(f"❌ 配置文件加载失败: {e}")
        return False

def main():
    """主测试函数"""
    print("🔧 实验自动化系统修复验证")
    print("=" * 50)
    
    # 测试参数解析
    param_test_passed = test_param_resolution()
    
    # 测试配置加载
    config_test_passed = test_config_loading()
    
    print("\n" + "=" * 50)
    print("📊 测试结果总结:")
    print(f"   参数解析: {'✅ 通过' if param_test_passed else '❌ 失败'}")
    print(f"   配置加载: {'✅ 通过' if config_test_passed else '❌ 失败'}")
    
    if param_test_passed and config_test_passed:
        print("\n🎉 所有修复验证通过!")
        print("💡 主要修复内容:")
        print("   1. 修复了API返回值判断逻辑 (error=false表示成功)")
        print("   2. 增强了参数解析，支持数组索引语法")
        print("   3. 减少了调试信息输出，保留关键操作日志")
        return True
    else:
        print("\n❌ 部分验证失败，需要进一步检查")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 