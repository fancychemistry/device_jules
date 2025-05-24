#!/usr/bin/env python3
"""
Device Tester 调试脚本
用于诊断device_tester.py的启动问题
"""

import sys
import os
import traceback
import importlib.util

def check_imports():
    """检查所有必要的导入"""
    print("🔍 检查导入...")
    
    required_modules = [
        'fastapi',
        'uvicorn', 
        'httpx',
        'asyncio',
        'logging',
        'pathlib',
        'json',
        'pydantic'
    ]
    
    missing_modules = []
    for module in required_modules:
        try:
            __import__(module)
            print(f"  ✅ {module}")
        except ImportError as e:
            print(f"  ❌ {module}: {e}")
            missing_modules.append(module)
    
    if missing_modules:
        print(f"\n❌ 缺少模块: {missing_modules}")
        return False
    
    print("✅ 所有基础模块导入成功")
    return True

def check_custom_imports():
    """检查自定义模块导入"""
    print("\n🔍 检查自定义模块...")
    
    custom_modules = [
        ('backend.pubsub', 'Broadcaster'),
        ('backend.services.adapters.printer_adapter', 'PrinterAdapter'),
        ('backend.services.adapters.pump_adapter', 'PumpAdapter'),
        ('backend.services.adapters.relay_adapter', 'RelayAdapter'),
        ('backend.services.adapters.chi_adapter', 'CHIAdapter')
    ]
    
    failed_imports = []
    for module_path, class_name in custom_modules:
        try:
            module = __import__(module_path, fromlist=[class_name])
            getattr(module, class_name)
            print(f"  ✅ {module_path}.{class_name}")
        except Exception as e:
            print(f"  ❌ {module_path}.{class_name}: {e}")
            failed_imports.append((module_path, class_name, str(e)))
    
    if failed_imports:
        print(f"\n❌ 自定义模块导入失败:")
        for module_path, class_name, error in failed_imports:
            print(f"    {module_path}.{class_name}: {error}")
        return False
    
    print("✅ 所有自定义模块导入成功")
    return True

def check_file_structure():
    """检查文件结构"""
    print("\n🔍 检查文件结构...")
    
    required_files = [
        'device_tester.py',
        'backend/pubsub.py',
        'backend/services/adapters/printer_adapter.py',
        'backend/services/adapters/pump_adapter.py',
        'backend/services/adapters/relay_adapter.py',
        'backend/services/adapters/chi_adapter.py'
    ]
    
    missing_files = []
    for file_path in required_files:
        if os.path.exists(file_path):
            print(f"  ✅ {file_path}")
        else:
            print(f"  ❌ {file_path}")
            missing_files.append(file_path)
    
    if missing_files:
        print(f"\n❌ 缺少文件: {missing_files}")
        return False
    
    print("✅ 所有必要文件存在")
    return True

def test_device_tester_syntax():
    """测试device_tester.py的语法"""
    print("\n🔍 检查device_tester.py语法...")
    
    try:
        with open('device_tester.py', 'r', encoding='utf-8') as f:
            code = f.read()
        
        compile(code, 'device_tester.py', 'exec')
        print("✅ device_tester.py语法正确")
        return True
    except SyntaxError as e:
        print(f"❌ device_tester.py语法错误:")
        print(f"    行 {e.lineno}: {e.text}")
        print(f"    错误: {e.msg}")
        return False
    except Exception as e:
        print(f"❌ 检查语法时出错: {e}")
        return False

def test_minimal_import():
    """测试最小化导入device_tester"""
    print("\n🔍 测试导入device_tester模块...")
    
    try:
        # 添加当前目录到Python路径
        if '.' not in sys.path:
            sys.path.insert(0, '.')
        
        # 尝试导入device_tester模块
        spec = importlib.util.spec_from_file_location("device_tester", "device_tester.py")
        device_tester = importlib.util.module_from_spec(spec)
        
        print("  正在执行模块...")
        spec.loader.exec_module(device_tester)
        
        print("✅ device_tester模块导入成功")
        return True
    except Exception as e:
        print(f"❌ 导入device_tester模块失败:")
        print(f"    错误: {e}")
        print(f"    详细信息:")
        traceback.print_exc()
        return False

def check_port_availability():
    """检查端口8001是否可用"""
    print("\n🔍 检查端口8001...")
    
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('localhost', 8001))
        sock.close()
        
        if result == 0:
            print("❌ 端口8001已被占用")
            return False
        else:
            print("✅ 端口8001可用")
            return True
    except Exception as e:
        print(f"❌ 检查端口时出错: {e}")
        return False

def main():
    """主函数"""
    print("Device Tester 调试诊断")
    print("=" * 50)
    
    # 检查步骤
    checks = [
        ("基础模块导入", check_imports),
        ("文件结构", check_file_structure),
        ("自定义模块导入", check_custom_imports),
        ("语法检查", test_device_tester_syntax),
        ("端口可用性", check_port_availability),
        ("模块导入测试", test_minimal_import)
    ]
    
    results = []
    for name, check_func in checks:
        print(f"\n{'='*20} {name} {'='*20}")
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ {name}检查时出现异常: {e}")
            traceback.print_exc()
            results.append((name, False))
    
    # 总结
    print("\n" + "="*50)
    print("📊 诊断结果总结:")
    print("="*50)
    
    passed = 0
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {name}: {status}")
        if result:
            passed += 1
    
    print(f"\n总计: {passed}/{len(results)} 项检查通过")
    
    if passed == len(results):
        print("\n🎉 所有检查通过！device_tester应该可以正常启动")
        print("建议运行: python device_tester.py")
    else:
        print(f"\n⚠️ 有 {len(results) - passed} 项检查失败")
        print("请根据上述错误信息修复问题后重试")
    
    return passed == len(results)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 