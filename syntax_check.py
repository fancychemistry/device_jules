import ast
import sys
import traceback

def check_syntax(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            source = f.read()
        
        # 尝试解析语法
        ast.parse(source)
        print(f"✅ {filename} 语法正确")
        return True
    except SyntaxError as e:
        print(f"❌ {filename} 语法错误:")
        print(f"   行 {e.lineno}: {e.text.strip() if e.text else ''}")
        print(f"   错误: {e.msg}")
        print(f"   位置: {e.offset}")
        return False
    except Exception as e:
        print(f"❌ {filename} 检查失败: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    check_syntax("device_tester.py") 