#!/usr/bin/env python3
# -*- coding: utf-8 -*-

def remove_bom(filename):
    """移除文件开头的BOM字符"""
    try:
        # 读取文件内容（二进制模式）
        with open(filename, 'rb') as f:
            content = f.read()
        
        # 检查是否有BOM
        if content.startswith(b'\xef\xbb\xbf'):
            print(f"发现BOM字符，正在移除...")
            # 移除BOM并重新写入
            with open(filename, 'wb') as f:
                f.write(content[3:])  # 跳过前3个字节（BOM）
            print(f"✅ 已成功移除 {filename} 的BOM字符")
        else:
            print(f"ℹ️ {filename} 没有BOM字符")
            
    except Exception as e:
        print(f"❌ 处理文件失败: {e}")

if __name__ == "__main__":
    remove_bom("device_tester.py") 