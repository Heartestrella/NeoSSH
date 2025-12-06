import paramiko
import re
import time
import json
from typing import Dict, Optional, Callable
import threading


class Monitor:
    """通过 paramiko SSHClient 获取系统资源信息的监控类"""

    def __init__(self, channel: Optional[paramiko.Channel] = None, ssh_client: Optional[paramiko.SSHClient] = None):
        """
        初始化 Monitor 类

        Args:
            channel: paramiko.Channel 对象（保留兼容性，但优先使用 ssh_client）
            ssh_client: paramiko.SSHClient 对象，用于执行 SSH 命令（推荐使用，更快）
        """
        self.ssh_channel = channel
        self.ssh_client = ssh_client
        self._lock = threading.Lock()
        self._last_result = None
        self._last_result_time = 0
        self._result_cache_duration = 0.5  # 缓存结果 0.5 秒，避免频繁调用

    def _execute_command_fast(self, command: str, timeout: float = 2.0) -> str:
        """
        使用 exec_command 快速执行命令（非阻塞，推荐使用）

        Args:
            command: 要执行的命令
            timeout: 超时时间（秒）

        Returns:
            命令输出的字符串
        """
        if self.ssh_client:
            try:
                stdin, stdout, stderr = self.ssh_client.exec_command(
                    command, timeout=timeout)
                output = stdout.read().decode('utf-8', errors='ignore')
                return output.strip()
            except Exception as e:
                raise Exception(f"执行命令失败: {e}")
        elif self.ssh_channel and not self.ssh_channel.closed:
            # 降级到 channel 方式（较慢）
            return self._execute_command_slow(command, timeout)
        else:
            raise Exception("SSH 连接未设置或已关闭")

    def _execute_command_slow(self, command: str, timeout: float = 3.0) -> str:
        """
        通过 channel 执行命令（较慢，仅作为备用方案）

        Args:
            command: 要执行的命令
            timeout: 超时时间（秒）

        Returns:
            命令输出的字符串
        """
        if not self.ssh_channel or self.ssh_channel.closed:
            raise Exception("SSH channel 未设置或已关闭")

        try:
            # 快速清空缓冲区（非阻塞）
            if self.ssh_channel.recv_ready():
                self.ssh_channel.recv(4096)

            # 发送命令
            full_command = f"{command}\n"
            self.ssh_channel.send(full_command.encode('utf-8'))

            # 减少等待时间
            time.sleep(0.1)

            output = b""
            start_time = time.time()

            # 快速读取输出
            while time.time() - start_time < timeout:
                if self.ssh_channel.recv_ready():
                    chunk = self.ssh_channel.recv(4096)
                    output += chunk
                    time.sleep(0.05)  # 减少等待时间
                else:
                    if len(output) > 0:
                        time.sleep(0.1)  # 减少等待时间
                        if not self.ssh_channel.recv_ready():
                            break
                    else:
                        time.sleep(0.05)

            # 继续读取剩余数据
            while self.ssh_channel.recv_ready():
                chunk = self.ssh_channel.recv(4096)
                output += chunk

            result = output.decode('utf-8', errors='ignore')
            # 清理 ANSI 转义码
            result = re.sub(r'\x1b\[[0-9;]*m', '', result)
            result = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', result)
            result = re.sub(r'\r\n', '\n', result)

            # 移除命令本身和提示符
            lines = result.split('\n')
            filtered_lines = []
            for line in lines:
                if (line.strip() and
                    command not in line and
                    not re.match(r'^.*[\$#]\s*$', line.strip()) and
                        not re.match(r'^\[.*\]\s*$', line.strip())):
                    filtered_lines.append(line)

            return '\n'.join(filtered_lines).strip()

        except Exception as e:
            raise Exception(f"执行命令失败: {e}")

    def get_system_metrics(self) -> Dict:
        """

        Returns:
            - type: "info" (用于标识数据类型)
            - cpu_percent: CPU 使用百分比
            - mem_percent: 内存使用百分比
            - mem_used: 内存使用量（MB，整数）
            - load: 负载平均值数组 [1分钟, 5分钟, 15分钟]
            - uptime_seconds: 系统运行时间（秒，整数）
        """
        current_time = time.time()
        if (self._last_result and
                current_time - self._last_result_time < self._result_cache_duration):
            return self._last_result

        try:
            command = """cpu_info=$(grep 'cpu ' /proc/stat | awk '{usage=($2+$4)*100/($2+$3+$4+$5)} END {print usage}') && \
mem_info=$(free | grep Mem) && \
mem_percent=$(echo "$mem_info" | awk '{printf "%.1f", $3/$2 * 100.0}') && \
mem_used_mb=$(echo "$mem_info" | awk '{printf "%d", $3/1024}') && \
load_1min=$(awk '{printf "%.2f", $1}' /proc/loadavg) && \
load_5min=$(awk '{printf "%.2f", $2}' /proc/loadavg) && \
load_15min=$(awk '{printf "%.2f", $3}' /proc/loadavg) && \
uptime_sec=$(awk '{print int($1)}' /proc/uptime) && \
echo "CPU:$cpu_info" && \
echo "MEM_PERCENT:$mem_percent" && \
echo "MEM_USED_MB:$mem_used_mb" && \
echo "LOAD_1MIN:$load_1min" && \
echo "LOAD_5MIN:$load_5min" && \
echo "LOAD_15MIN:$load_15min" && \
echo "UPTIME:$uptime_sec"
"""

            output = self._execute_command_fast(command, timeout=1.5)

            # 解析输出
            cpu_percent = 0.0
            mem_percent = 0.0
            mem_used = 0
            load_1min = 0.0
            load_5min = 0.0
            load_15min = 0.0
            uptime_seconds = 0

            for line in output.split('\n'):
                line = line.strip()
                if ':' in line:
                    key, value = line.split(':', 1)
                    try:
                        if key == 'CPU':
                            cpu_percent = float(value)
                        elif key == 'MEM_PERCENT':
                            mem_percent = float(value)
                        elif key == 'MEM_USED_MB':
                            mem_used = int(float(value))
                        elif key == 'LOAD_1MIN':
                            load_1min = float(value)
                        elif key == 'LOAD_5MIN':
                            load_5min = float(value)
                        elif key == 'LOAD_15MIN':
                            load_15min = float(value)
                        elif key == 'UPTIME':
                            uptime_seconds = int(float(value))
                    except ValueError:
                        continue

            # 返回符合 _set_usage 函数期望的格式
            result = {
                'type': 'info',  # 标识数据类型
                'cpu_percent': round(cpu_percent, 1),
                'mem_percent': round(mem_percent, 1),
                'mem_used': mem_used,  # 整数，单位 MB
                'load': [load_1min, load_5min, load_15min],  # 负载数组
                'uptime_seconds': uptime_seconds  # 整数，单位秒
            }

            # 缓存结果
            self._last_result = result
            self._last_result_time = time.time()
            return result

        except Exception as e:
            # 如果出错，返回默认值
            result = {
                'type': 'info',
                'cpu_percent': 0.0,
                'mem_percent': 0.0,
                'mem_used': 0,
                'load': [0.0, 0.0, 0.0],
                'uptime_seconds': 0
            }
            self._last_result = result
            self._last_result_time = time.time()
            return result

    def get_combined_metrics_async(self, callback: Optional[Callable[[Dict], None]] = None):
        """
        异步获取系统指标（用于兼容现有代码）
        注意：由于 exec_command 本身很快，这里实际上可以同步调用

        Args:
            callback: 回调函数，接收指标字典作为参数
        """
        def _async_get():
            try:
                metrics = self.get_system_metrics()
                if callback:
                    callback(metrics)
            except Exception as e:
                if callback:
                    callback({
                        'type': 'info',
                        'cpu_percent': 0.0,
                        'mem_percent': 0.0,
                        'mem_used': 0,
                        'load': [0.0, 0.0, 0.0],
                        'uptime_seconds': 0,
                        'error': str(e)
                    })

        thread = threading.Thread(target=_async_get, daemon=True)
        thread.start()

    def get_sysinfo_details(self) -> Dict:
        """
        通过把完整 bash 脚本以 stdin 方式传给远端 bash 执行，避免命令行转义问题。
        返回解析后的字典，失败返回空 dict。带有简单 DEBUG 输出。
        """
        try:
            script = r'''#!/bin/bash
sys=$(uname -s)
kernel=$(uname -r)
arch=$(uname -m)
hostn=$(hostname)
cpu_model=$(awk -F: '/model name/ {gsub(/^[ \t]+/,"",$2); print $2; exit}' /proc/cpuinfo || echo)
cores=$(nproc 2>/dev/null || echo 0)
cpu_freq=$(awk -F: '/cpu MHz/ {printf("%.0f",$2); exit}' /proc/cpuinfo 2>/dev/null || echo)
if [ -n "$cpu_freq" ]; then cpu_freq="${cpu_freq}MHz"; fi
cpu_cache=$(awk -F: '/cache size/ {gsub(/^[ \t]+/,"",$2); print $2; exit}' /proc/cpuinfo || echo)
mem_kb=$(awk '/MemTotal/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo)
mem_mb=0
if [ -n "$mem_kb" ]; then mem_mb=$((mem_kb/1024)); fi
ip=$(hostname -I 2>/dev/null | awk '{print $1}' || echo)

# 输出 key:value 每行，便于本地解析
printf "system:%s\nkernel:%s\narch:%s\nhostname:%s\ncpu_model:%s\ncpu_cores:%s\ncpu_freq:%s\ncpu_cache:%s\nmem_total:%sMB\nip:%s\n" \
    "$sys" "$kernel" "$arch" "$hostn" "$cpu_model" "$cores" "$cpu_freq" "$cpu_cache" "$mem_mb" "$ip"
'''
            print(
                "DEBUG: get_sysinfo_details: using stdin-bash script (length {})".format(len(script)))

            output = ""

            # 优先使用 ssh_client.exec_command 并通过 stdin 传脚本（避免 shell 转义问题）
            if getattr(self, "ssh_client", None):
                try:
                    print("DEBUG: exec_command 'bash -s' via ssh_client")
                    stdin, stdout, stderr = self.ssh_client.exec_command(
                        'bash -s', timeout=8)
                    try:
                        stdin.write(script)
                        # Ensure remote bash sees EOF
                        try:
                            stdin.channel.shutdown_write()
                        except Exception:
                            try:
                                stdin.close()
                            except Exception:
                                pass
                    except Exception:
                        pass
                    out = stdout.read().decode('utf-8', errors='ignore')
                    err = stderr.read().decode('utf-8', errors='ignore')
                    print("DEBUG: exec_command stdout preview:", out[:1000])
                    if err:
                        print("DEBUG: exec_command stderr preview:",
                              err[:1000])
                    output = out.strip() or ""
                except Exception as e:
                    print("DEBUG: exec_command exception:", repr(e))
                    output = ""

            # 回退到慢速 channel 执行（如果存在 long-lived shell channel）
            if not output and getattr(self, "ssh_channel", None) and not getattr(self.ssh_channel, "closed", False):
                try:
                    print("DEBUG: falling back to _execute_command_slow")
                    # _execute_command_slow 实现应能接受 full script; 它内部会处理发送与读取
                    output = self._execute_command_slow(
                        script, timeout=8.0) or ""
                    print("DEBUG: channel output preview:", output[:1000])
                except Exception as e:
                    print("DEBUG: _execute_command_slow exception:", repr(e))
                    output = ""

            print("DEBUG: raw sysinfo output (len={}): {}".format(
                len(output), (output[:1000] + "...") if len(output) > 1000 else output))

            if not output:
                return {}

            # 解析 key:value 行到字典
            info: Dict[str, str] = {}
            for line in output.splitlines():
                line = line.strip()
                if not line:
                    continue
                if ':' in line:
                    k, v = line.split(':', 1)
                    info[k.strip()] = v.strip()

            if not info:
                return {}

            # 规范化/类型转换
            result: Dict = {}
            result['system'] = info.get('system', '')
            result['kernel'] = info.get('kernel', '')
            result['arch'] = info.get('arch', '')
            result['hostname'] = info.get('hostname', '')
            result['cpu_model'] = info.get('cpu_model', '')
            try:
                result['cpu_cores'] = int(info.get('cpu_cores', '0') or 0)
            except Exception:
                result['cpu_cores'] = 0
            result['cpu_freq'] = info.get('cpu_freq', '')
            result['cpu_cache'] = info.get('cpu_cache', '')
            result['mem_total'] = info.get('mem_total', '')
            result['ip'] = info.get('ip', '')
            return result
        except Exception as e:
            print("DEBUG: get_sysinfo_details top-level exception:", repr(e))
            return {}

    def get_top_processes(self, top_n: int = 5) -> Dict:
        """
        获取 CPU 占用最高的前 N 个进程信息（不包括 kworker 和 rcu_ 内核线程）。
        返回包含 type 和进程列表的字典，直接可供 _set_usage 使用。
        失败返回空字典。

        Args:
            top_n: 返回进程数，默认 5

        Returns:
            字典格式：
            {
                "type": "info",
                "top_processes": [
                    {"pid": 1234, "name": "python3", "cpu": 15.5, "mem_mb": 123.45},
                    {"pid": 5678, "name": "nginx", "cpu": 8.2, "mem_mb": 45.67},
                    ...
                ]
            }
        """
        try:
            # 使用 key:value 行输出格式，避免 JSON 转义问题（参考 get_sysinfo_details 方案）
            script = r'''#!/bin/bash
TOP_N={top_n}
ps -eo pid,comm,%cpu,rss --sort=-%cpu | awk -v top_n="$TOP_N" '
NR>1 && $2 !~ /^kworker/ && $2 !~ /^rcu_/ {{

    count++
    if (count <= top_n) {{
        mem_mb = $4 / 1024
        printf "pid:%s|name:%s|cpu:%s|mem_mb:%.2f\n", $1, $2, $3, mem_mb
    }}
}}
'
'''.format(top_n=top_n)

            print("DEBUG: get_top_processes: executing script (top_n={})".format(top_n))

            output = ""

            # 优先使用 ssh_client.exec_command + stdin 方式
            if getattr(self, "ssh_client", None):
                try:
                    print("DEBUG: exec_command 'bash -s' via ssh_client for processes")
                    stdin, stdout, stderr = self.ssh_client.exec_command(
                        'bash -s', timeout=10)
                    try:
                        stdin.write(script.encode('utf-8'))
                        stdin.channel.shutdown_write()
                    except Exception as e:
                        print("DEBUG: stdin write exception:", repr(e))

                    out = stdout.read().decode('utf-8', errors='ignore')
                    err = stderr.read().decode('utf-8', errors='ignore')
                    print(
                        "DEBUG: processes exec_command stdout preview:", out[:1000])
                    if err:
                        print(
                            "DEBUG: processes exec_command stderr preview:", err[:500])
                    output = out.strip() or ""
                except Exception as e:
                    print("DEBUG: processes exec_command exception:", repr(e))
                    output = ""

            # 回退到 channel 方式
            if not output and getattr(self, "ssh_channel", None) and not getattr(self.ssh_channel, "closed", False):
                try:
                    print("DEBUG: falling back to _execute_command_slow for processes")
                    output = self._execute_command_slow(
                        script, timeout=10.0) or ""
                    print("DEBUG: processes channel output preview:",
                          output[:1000])
                except Exception as e:
                    print("DEBUG: processes _execute_command_slow exception:", repr(e))
                    output = ""

            print("DEBUG: raw processes output (len={}): {}".format(
                len(output), (output[:1000] + "...") if len(output) > 1000 else output))

            if not output:
                return {"type": "info", "top_processes": []}

            # 解析 key:value 行到进程列表（参考 get_sysinfo_details 方案）
            processes_list = []
            for line in output.splitlines():
                line = line.strip()
                if not line:
                    continue
                # 解析 pid:XXX|name:YYY|cpu:ZZZ|mem_mb:WWW 格式
                process_dict = {}
                for pair in line.split('|'):
                    if ':' in pair:
                        k, v = pair.split(':', 1)
                        process_dict[k.strip()] = v.strip()

                # 类型转换
                if 'pid' in process_dict and 'name' in process_dict:
                    try:
                        process_dict['pid'] = int(process_dict['pid'])
                    except Exception:
                        pass
                    try:
                        process_dict['cpu'] = float(process_dict.get('cpu', 0))
                    except Exception:
                        process_dict['cpu'] = 0.0
                    try:
                        process_dict['mem_mb'] = float(
                            process_dict.get('mem_mb', 0))
                    except Exception:
                        process_dict['mem_mb'] = 0.0

                    processes_list.append(process_dict)

            print("DEBUG: parsed {} processes".format(len(processes_list)))

            return {
                "type": "info",
                "top_processes": processes_list
            }

        except Exception as e:
            print("DEBUG: get_top_processes top-level exception:", repr(e))
            return {"type": "info", "top_processes": []}
