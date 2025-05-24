import asyncio
from backend.services.adapters.chi_adapter import CHIAdapter
from backend.pubsub import Broadcaster

async def test_chi_initialize():
    """测试CHI初始化"""
    print("🧪 测试CHI适配器初始化...")
    
    try:
        # 创建广播器
        broadcaster = Broadcaster()
        print("✅ Broadcaster创建成功")
        
        # 创建CHI适配器
        chi_adapter = CHIAdapter(
            broadcaster=broadcaster,
            results_base_dir="./experiment_results",
            chi_path="C:/CHI760E/chi760e/chi760e.exe"
        )
        print("✅ CHIAdapter创建成功")
        
        # 测试初始化
        result = await chi_adapter.initialize()
        print(f"🔧 初始化结果: {result}")
        
        if result:
            print("✅ CHI初始化成功")
            
            # 获取状态
            status = await chi_adapter.get_status()
            print(f"📊 CHI状态: {status}")
        else:
            print("❌ CHI初始化失败")
            print(f"错误信息: {chi_adapter._last_error}")
            
    except Exception as e:
        print(f"❌ 测试CHI初始化时发生异常: {e}")
        import traceback
        traceback.print_exc()

def main():
    print("=" * 50)
    print("🧪 CHI适配器初始化测试")
    print("=" * 50)
    
    asyncio.run(test_chi_initialize())
    
    print("=" * 50)

if __name__ == "__main__":
    main() 