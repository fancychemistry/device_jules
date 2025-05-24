#!/usr/bin/env python3
"""
修复chi_adapter.py的缩进问题
"""

def fix_chi_adapter():
    """修复chi_adapter.py的缩进问题"""
    
    file_path = 'backend/services/adapters/chi_adapter.py'
    
    try:
        # 读取文件
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        print(f"文件总行数: {len(lines)}")
        
        # 检查第936行附近的问题
        problem_lines = []
        for i in range(930, min(945, len(lines))):
            line = lines[i]
            print(f"Line {i+1}: {repr(line)}")
            
            # 检查缩进问题
            if line.strip() and not line.startswith(' ') and not line.startswith('\t'):
                if i > 0 and lines[i-1].strip().endswith(':'):
                    problem_lines.append(i)
                    print(f"  ⚠️ 可能的缩进问题")
        
        if problem_lines:
            print(f"\n发现可能的缩进问题在行: {[i+1 for i in problem_lines]}")
            
            # 尝试修复
            for line_idx in problem_lines:
                if line_idx < len(lines):
                    original_line = lines[line_idx]
                    # 如果行不是以空格开头，添加适当的缩进
                    if original_line.strip() and not original_line.startswith(' '):
                        # 查找前一行的缩进级别
                        prev_line = lines[line_idx - 1] if line_idx > 0 else ""
                        if prev_line.strip().endswith(':'):
                            # 前一行以冒号结尾，当前行应该缩进
                            indent = len(prev_line) - len(prev_line.lstrip()) + 4
                            lines[line_idx] = ' ' * indent + original_line.lstrip()
                            print(f"修复行 {line_idx+1}: 添加 {indent} 个空格缩进")
            
            # 写回文件
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            
            print(f"\n✅ 已修复缩进问题并保存文件")
            return True
        else:
            print("\n✅ 未发现明显的缩进问题")
            return True
            
    except Exception as e:
        print(f"❌ 修复过程中出错: {e}")
        return False

def test_syntax():
    """测试语法是否正确"""
    try:
        with open('backend/services/adapters/chi_adapter.py', 'r', encoding='utf-8') as f:
            code = f.read()
        
        compile(code, 'backend/services/adapters/chi_adapter.py', 'exec')
        print("✅ 语法检查通过")
        return True
    except SyntaxError as e:
        print(f"❌ 语法错误:")
        print(f"    行 {e.lineno}: {e.text}")
        print(f"    错误: {e.msg}")
        return False
    except Exception as e:
        print(f"❌ 检查语法时出错: {e}")
        return False

if __name__ == "__main__":
    print("修复CHI适配器缩进问题")
    print("=" * 40)
    
    print("\n1. 检查和修复缩进...")
    fix_result = fix_chi_adapter()
    
    print("\n2. 测试语法...")
    syntax_result = test_syntax()
    
    print("\n" + "=" * 40)
    if fix_result and syntax_result:
        print("✅ 修复完成！")
    else:
        print("❌ 修复失败！") 