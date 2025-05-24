#!/usr/bin/env python3
"""
电化学实验自动化系统启动脚本
同时启动设备测试器和实验自动化控制台
"""

import subprocess
import sys
import time
import os
import signal
import threading
from pathlib import Path

class SystemLauncher:
    def __init__(self):
        self.device_tester_process = None
        self.experiment_automation_process = None
        self.running = True
    
    def start_device_tester(self):
        """启动设备测试器"""
        print("🔧 启动设备测试器...")
        try:
            self.device_tester_process = subprocess.Popen(
                [sys.executable, "device_tester.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # 监控输出
            threading.Thread(
                target=self.monitor_process_output,
                args=(self.device_tester_process, "DeviceTester"),
                daemon=True
            ).start()
            
            print("✅ 设备测试器启动中... (端口 8001)")
            return True
        except Exception as e:
            print(f"❌ 设备测试器启动失败: {e}")
            return False
    
    def start_experiment_automation(self):
        """启动实验自动化系统"""
        print("🧪 启动实验自动化控制台...")
        try:
            # 等待设备测试器完全启动
            time.sleep(5)
            
            self.experiment_automation_process = subprocess.Popen(
                [sys.executable, "experiment_automation.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # 监控输出
            threading.Thread(
                target=self.monitor_process_output,
                args=(self.experiment_automation_process, "ExperimentAutomation"),
                daemon=True
            ).start()
            
            print("✅ 实验自动化控制台启动中... (端口 8002)")
            return True
        except Exception as e:
            print(f"❌ 实验自动化控制台启动失败: {e}")
            return False
    
    def monitor_process_output(self, process, name):
        """监控进程输出"""
        try:
            while self.running and process.poll() is None:
                line = process.stdout.readline()
                if line:
                    print(f"[{name}] {line.strip()}")
        except Exception as e:
            print(f"[{name}] 输出监控错误: {e}")
    
    def check_dependencies(self):
        """检查依赖文件"""
        required_files = [
            "device_tester.py",
            "experiment_automation.py",
            "old/experiment_config.json"
        ]
        
        missing_files = []
        for file_path in required_files:
            if not Path(file_path).exists():
                missing_files.append(file_path)
        
        if missing_files:
            print("❌ 缺少必要文件:")
            for file_path in missing_files:
                print(f"   - {file_path}")
            return False
        
        print("✅ 依赖文件检查通过")
        return True
    
    def setup_signal_handlers(self):
        """设置信号处理器"""
        def signal_handler(signum, frame):
            print("\n🛑 接收到停止信号，正在关闭系统...")
            self.shutdown()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def shutdown(self):
        """关闭所有进程"""
        self.running = False
        
        if self.experiment_automation_process:
            print("🛑 关闭实验自动化控制台...")
            self.experiment_automation_process.terminate()
            try:
                self.experiment_automation_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.experiment_automation_process.kill()
        
        if self.device_tester_process:
            print("🛑 关闭设备测试器...")
            self.device_tester_process.terminate()
            try:
                self.device_tester_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.device_tester_process.kill()
        
        print("✅ 系统已关闭")
    
    def run(self):
        """运行系统"""
        print("🚀 电化学实验自动化系统启动器")
        print("=" * 50)
        
        # 检查依赖
        if not self.check_dependencies():
            return False
        
        # 设置信号处理器
        self.setup_signal_handlers()
        
        # 启动设备测试器
        if not self.start_device_tester():
            return False
        
        # 启动实验自动化系统
        if not self.start_experiment_automation():
            self.shutdown()
            return False
        
        print("\n" + "=" * 50)
        print("🎉 系统启动完成!")
        print("📱 设备测试器: http://localhost:8001")
        print("🧪 实验控制台: http://localhost:8002")
        print("=" * 50)
        print("按 Ctrl+C 停止系统")
        
        try:
            # 保持运行
            while self.running:
                # 检查进程状态
                if self.device_tester_process and self.device_tester_process.poll() is not None:
                    print("❌ 设备测试器意外退出")
                    break
                
                if self.experiment_automation_process and self.experiment_automation_process.poll() is not None:
                    print("❌ 实验自动化控制台意外退出")
                    break
                
                time.sleep(1)
        
        except KeyboardInterrupt:
            print("\n🛑 用户请求停止")
        
        finally:
            self.shutdown()
        
        return True

def main():
    """主函数"""
    # 检查Python版本
    if sys.version_info < (3, 7):
        print("❌ 需要 Python 3.7 或更高版本")
        return False
    
    # 检查必要的包
    required_packages = ['fastapi', 'uvicorn', 'httpx', 'requests']
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print("❌ 缺少必要的包:")
        for package in missing_packages:
            print(f"   - {package}")
        print("\n请运行: pip install fastapi uvicorn httpx requests")
        return False
    
    # 启动系统
    launcher = SystemLauncher()
    return launcher.run()

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 