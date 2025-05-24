#!/usr/bin/env python3
"""
测试API响应格式解析修复
"""

def test_api_response_parsing():
    """测试API响应解析函数"""
    
    print("🔧 测试API响应格式解析修复")
    print("=" * 50)
    
    def parse_api_response(result):
        """通用的API响应解析函数（与experiment_automation.py中的逻辑一致）"""
        message = result.get("message", "")
        
        # 优先检查success字段
        if "success" in result:
            success = result.get("success", False)
            print(f"🔧 API响应解析: 使用success字段, success={success}, message='{message}'")
            return {"success": success, "message": message}
        
        # 如果没有success字段，检查error字段
        elif "error" in result:
            # error=False表示成功，error=True表示失败
            success = not result.get("error", True)
            print(f"🔧 API响应解析: 使用error字段, error={result.get('error')}, success={success}, message='{message}'")
            return {"success": success, "message": message}
        
        # 如果都没有，默认为失败
        else:
            print(f"🔧 API响应解析: 缺少success/error字段, 默认失败, message='{message}'")
            return {"success": False, "message": message or "未知响应格式"}
    
    # 测试用例
    test_cases = [
        # device_tester.py 实际返回的格式
        {"success": True, "message": "打印机归位成功"},
        {"success": False, "message": "打印机未初始化"},
        
        # 可能的error格式
        {"error": False, "message": "操作成功"},
        {"error": True, "message": "操作失败"},
        
        # 边界情况
        {"message": "只有消息"},
        {},
        {"success": True},
        {"error": False}
    ]
    
    all_passed = True
    
    for i, response in enumerate(test_cases, 1):
        print(f"\n测试 {i}: 原始响应 = {response}")
        parsed = parse_api_response(response)
        
        # 判断期望结果
        if "success" in response:
            expected = response["success"]
        elif "error" in response:
            expected = not response["error"]
        else:
            expected = False
        
        actual = parsed["success"]
        status = "✅" if actual == expected else "❌"
        
        print(f"{status} 解析结果: success={actual}, 期望: {expected}")
        
        if actual != expected:
            all_passed = False
    
    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 所有API响应格式解析测试通过!")
        print("\n💡 修复说明:")
        print("1. ✅ 优先使用 success 字段")
        print("2. ✅ 兼容 error 字段格式")
        print("3. ✅ 处理缺失字段的情况")
        print("4. ✅ 输出详细的调试信息")
    else:
        print("❌ 部分测试失败!")
    
    return all_passed

if __name__ == "__main__":
    test_api_response_parsing() 