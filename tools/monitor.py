import paramiko
import re
from typing import Dict, Optional, Callable
import time
import json
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
        # 用于保存上次的网卡字节数与时间戳，计算速率
        self._net_prev = {}

        # --- 新增：轮询器相关状态（单线程轮询所有回调） ---
        self._poll_lock = threading.Lock()
        # 每一项: {"callback": callable, "kind": str, "interval": float, "next": float}
        self._pollers = []
        self._poll_thread = None
        self._poll_thread_stop = threading.Event()
        # 轮询主循环精度（秒）
        self._poll_tick = 0.2

    def _execute_command_fast(self, command: str, timeout: float = 2.0) -> str:
        """
        使用 exec_command 快速执行命令（非阻塞，推荐使用）
        """
        if self.ssh_client:
            try:
                # 保证传给 paramiko 的 timeout 为数字或 None（避免外部误传函数等）
                try:
                    tval = float(timeout) if timeout is not None else None
                except Exception:
                    tval = None
                stdin, stdout, stderr = self.ssh_client.exec_command(
                    command, timeout=tval)
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
        """
        if not self.ssh_channel or self.ssh_channel.closed:
            raise Exception("SSH channel 未设置或已关闭")

        # 保证 timeout 为 float（防止外部传入非数值）
        try:
            timeout_val = float(timeout) if timeout is not None else 3.0
        except Exception:
            timeout_val = 3.0

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
            while time.time() - start_time < timeout_val:
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
            # print(
            #     "DEBUG: get_sysinfo_details: using stdin-bash script (length {})".format(len(script)))

            output = ""

            # 优先使用 ssh_client.exec_command 并通过 stdin 传脚本（避免 shell 转义问题）
            if getattr(self, "ssh_client", None):
                try:
                    # print("DEBUG: exec_command 'bash -s' via ssh_client")
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
                    # print("DEBUG: exec_command stdout preview:", out[:1000])
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
                    # print("DEBUG: falling back to _execute_command_slow")
                    # _execute_command_slow 实现应能接受 full script; 它内部会处理发送与读取
                    output = self._execute_command_slow(
                        script, timeout=8.0) or ""
                    # print("DEBUG: channel output preview:", output[:1000])
                except Exception as e:
                    print("DEBUG: _execute_command_slow exception:", repr(e))
                    output = ""

            # print("DEBUG: raw sysinfo output (len={}): {}".format(
            #     len(output), (output[:1000] + "...") if len(output) > 1000 else output))

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

            # print("DEBUG: get_top_processes: executing script (top_n={})".format(top_n))

            output = ""

            # 优先使用 ssh_client.exec_command + stdin 方式
            if getattr(self, "ssh_client", None):
                try:
                    # print("DEBUG: exec_command 'bash -s' via ssh_client for processes")
                    stdin, stdout, stderr = self.ssh_client.exec_command(
                        'bash -s', timeout=10)
                    try:
                        stdin.write(script.encode('utf-8'))
                        stdin.channel.shutdown_write()
                    except Exception as e:
                        print("DEBUG: stdin write exception:", repr(e))

                    out = stdout.read().decode('utf-8', errors='ignore')
                    err = stderr.read().decode('utf-8', errors='ignore')
                    # print(
                    #     "DEBUG: processes exec_command stdout preview:", out[:1000])
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
                    # print("DEBUG: falling back to _execute_command_slow for processes")
                    output = self._execute_command_slow(
                        script, timeout=10.0) or ""
                    # print("DEBUG: processes channel output preview:",
                    #       output[:1000])
                except Exception as e:
                    print("DEBUG: processes _execute_command_slow exception:", repr(e))
                    output = ""

            # print("DEBUG: raw processes output (len={}): {}".format(
            #     len(output), (output[:1000] + "...") if len(output) > 1000 else output))

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

            # print("DEBUG: parsed {} processes".format(len(processes_list)))

            return {
                "type": "info",
                "top_processes": processes_list
            }

        except Exception as e:
            print("DEBUG: get_top_processes top-level exception:", repr(e))
            return {"type": "info", "top_processes": []}

    def get_top_processes_async(self, top_n: int = 5, callback: Optional[Callable[[Dict], None]] = None):
        """
        异步获取 top processes，结果通过 callback(return_dict) 返回（非阻塞）。
        callback 接受一个 dict，格式与 get_top_processes 返回值一致。
        """
        def _worker():
            try:
                result = self.get_top_processes(top_n)
                if callback:
                    callback(result)
            except Exception as e:
                if callback:
                    callback(
                        {"type": "info", "top_processes": [], "error": str(e)})

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def get_net_usage(self, timeout: float = 5.0) -> Dict:
        """
        获取各网卡当前累计字节数，并基于上次读取计算 KB/s 速率。
        """
        try:
            # 强制保证 timeout 为数字，避免被误传其它对象
            try:
                timeout_val = float(timeout) if timeout is not None else 5.0
            except Exception:
                timeout_val = 5.0

            script = r'''#!/bin/bash
awk 'NR>2{gsub(/:/,"",$1); if($1!="lo") print $1 "|" $2 "|" $10}' /proc/net/dev
'''
            output = ""
            if getattr(self, "ssh_client", None):
                try:
                    stdin, stdout, stderr = self.ssh_client.exec_command(
                        'bash -s', timeout=timeout_val)
                    try:
                        stdin.write(script)
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
                    if err:
                        print("DEBUG: get_net_usage stderr:", err[:1000])
                    output = out.strip() or ""
                except Exception as e:
                    print("DEBUG: get_net_usage exec exception:", repr(e))
                    output = ""
            # 回退到慢速 channel
            if not output and getattr(self, "ssh_channel", None) and not getattr(self.ssh_channel, "closed", False):
                try:
                    output = self._execute_command_slow(
                        script, timeout=timeout_val) or ""
                except Exception as e:
                    print("DEBUG: get_net_usage channel exception:", repr(e))
                    output = ""

            if not output:
                return {"type": "info", "net_usage": []}

            now = time.time()
            net_list = []
            for line in output.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) < 3:
                    continue
                iface = parts[0]
                try:
                    rx = int(parts[1])
                except Exception:
                    rx = 0
                try:
                    tx = int(parts[2])
                except Exception:
                    tx = 0

                prev = self._net_prev.get(iface)
                rx_kbps = 0.0
                tx_kbps = 0.0
                if prev:
                    dt = now - prev.get("ts", now)
                    if dt > 0.05:
                        rx_kbps = max(
                            0.0, (rx - prev.get("rx", 0)) / dt / 1024.0)
                        tx_kbps = max(
                            0.0, (tx - prev.get("tx", 0)) / dt / 1024.0)
                # 更新缓存
                self._net_prev[iface] = {"rx": rx, "tx": tx, "ts": now}

                net_list.append({
                    "iface": iface,
                    "rx_kbps": round(rx_kbps, 2),
                    "tx_kbps": round(tx_kbps, 2),
                    "rx_bytes": rx,
                    "tx_bytes": tx
                })

            return {"type": "info", "net_usage": net_list}
        except Exception as e:
            print("DEBUG: get_net_usage top-level exception:", repr(e))
            return {"type": "info", "net_usage": []}

    def get_net_usage_async(self, timeout: int = 5, callback: Optional[Callable[[Dict], None]] = None):
        """
        异步获取网络使用情况（get_net_usage），结果通过 callback(dict) 回传（非阻塞）。
        timeout 可用于控制远端命令超时。
        """
        def _worker():
            try:
                res = self.get_net_usage(timeout=timeout)
                # print(res)
                if callback:
                    callback(res)
            except Exception as e:
                if callback:
                    callback({"type": "info", "net_usage": [], "error": str(e)})

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def get_connections(self, limit: int = 20, timeout: float = 5.0) -> Dict:
        """
        获取前若干网络连接及对应进程的流量（基于 /proc/<pid>/net/dev），返回：
        {
            "type": "info",
            "connections": [
                {
                    "pid": 123,
                    "name": "sshd",
                    "local_ip": "1.2.3.4",
                    "local_port": "22",
                    "remote_ip": "5.6.7.8",
                    "remote_port": "34567",
                    "connections": 3,
                    "upload_kbps": 0.12,
                    "download_kbps": 0.34,
                    "rx_bytes": 12345,
                    "tx_bytes": 67890
                }, ...
            ]
        }
        注意：第一次调用时 upload_kbps/download_kbps 可能为 0（无历史数据）。
        """
        try:
            try:
                timeout_val = float(timeout) if timeout is not None else 5.0
            except Exception:
                timeout_val = 5.0

            script = r'''#!/bin/bash
LIMIT={limit}
ss -tunp -H | head -n $LIMIT | while read -r line; do
    # 提取字段
    proto=$(echo "$line" | awk '{print $1}')
    state=$(echo "$line" | awk '{print $2}')
    local=$(echo "$line" | awk '{print $5}')
    remote=$(echo "$line" | awk '{print $6}')
    users=$(echo "$line" | awk '{for(i=7;i<=NF;i++) printf $i " "; print ""}')
    pid=$(echo "$users" | grep -o 'pid=[0-9]\+' | cut -d= -f2 | head -n1)
    pname=$(echo "$users" | grep -o '"[^"]\+"' | tr -d '"' | head -n1)
    [[ -z "$pid" ]] && continue
    [[ -z "$pname" ]] && pname="unknown"

    local_ip=$(echo "$local" | rev | cut -d: -f2- | rev)
    local_port=$(echo "$local" | rev | cut -d: -f1 | rev)
    remote_ip=$(echo "$remote" | rev | cut -d: -f2- | rev)
    remote_port=$(echo "$remote" | rev | cut -d: -f1 | rev)

    # 读取 /proc/<pid>/net/dev 汇总 rx/tx 字节
    proc_rx=0
    proc_tx=0
    if [[ -r /proc/$pid/net/dev ]]; then
        read rx_sum tx_sum < <(awk 'NR>2 {gsub(/:/,"",$1); rx+=$2; tx+=$10} END {print (rx+0),"",(tx+0)}' /proc/$pid/net/dev 2>/dev/null)
        proc_rx=${rx_sum:-0}
        proc_tx=${tx_sum:-0}
    fi

    conn_count=$(ss -tunp | grep "pid=$pid" | wc -l || echo 0)

    # 输出 key:value 用 | 分隔，便于本地解析
    printf "pid:%s|name:%s|local_ip:%s|local_port:%s|remote_ip:%s|remote_port:%s|connections:%s|rx_bytes:%s|tx_bytes:%s\n" \
        "$pid" "$pname" "$local_ip" "$local_port" "$remote_ip" "$remote_port" "$conn_count" "$proc_rx" "$proc_tx"
done
'''.replace('{limit}', str(int(limit)))

            output = ""
            if getattr(self, "ssh_client", None):
                try:
                    stdin, stdout, stderr = self.ssh_client.exec_command(
                        'bash -s', timeout=timeout_val)
                    try:
                        stdin.write(script.encode('utf-8'))
                        stdin.channel.shutdown_write()
                    except Exception as e:
                        print("DEBUG: stdin write exception:", repr(e))

                    out = stdout.read().decode('utf-8', errors='ignore')
                    err = stderr.read().decode('utf-8', errors='ignore')
                    # print(
                    #     "DEBUG: processes exec_command stdout preview:", out[:1000])
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
                    # print("DEBUG: falling back to _execute_command_slow for processes")
                    output = self._execute_command_slow(
                        script, timeout=10.0) or ""
                    # print("DEBUG: processes channel output preview:",
                    #       output[:1000])
                except Exception as e:
                    print("DEBUG: processes _execute_command_slow exception:", repr(e))
                    output = ""

            # print("DEBUG: raw processes output (len={}): {}".format(
            #     len(output), (output[:1000] + "...") if len(output) > 1000 else output))

            if not output:
                return {"type": "info", "connections": []}

            # --- 插入 now 变量和确保 _proc_prev 存在 ---
            now = time.time()
            if not hasattr(self, "_proc_prev"):
                self._proc_prev = {}

            # 解析 key:value 行到连接列表
            conns = []
            for line in output.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = {}
                for pair in line.split('|'):
                    if ':' in pair:
                        k, v = pair.split(':', 1)
                        parts[k.strip()] = v.strip()
                try:
                    pid = int(parts.get('pid', 0))
                except Exception:
                    continue
                name = parts.get('name', 'unknown')
                local_ip = parts.get('local_ip', '')
                local_port = parts.get('local_port', '')
                remote_ip = parts.get('remote_ip', '')
                remote_port = parts.get('remote_port', '')
                try:
                    rx_bytes = int(parts.get('rx_bytes', 0))
                except Exception:
                    rx_bytes = 0
                try:
                    tx_bytes = int(parts.get('tx_bytes', 0))
                except Exception:
                    tx_bytes = 0
                try:
                    conn_count = int(parts.get('connections', 0))
                except Exception:
                    conn_count = 0

                # 计算速率（KB/s），使用 self._proc_prev 缓存
                prev = getattr(self, "_proc_prev", {}).get(pid)
                dl_kbps = 0.0
                ul_kbps = 0.0
                if prev:
                    dt = now - prev.get("ts", now)
                    if dt > 0.05:
                        dl_kbps = max(
                            0.0, (rx_bytes - prev.get("rx", 0)) / dt / 1024.0)
                        ul_kbps = max(
                            0.0, (tx_bytes - prev.get("tx", 0)) / dt / 1024.0)
                # 更新 proc cache (与 net cache 共用命名空间 _proc_prev)
                if not hasattr(self, "_proc_prev"):
                    self._proc_prev = {}
                self._proc_prev[pid] = {
                    "rx": rx_bytes, "tx": tx_bytes, "ts": now}

                conns.append({
                    "pid": pid,
                    "name": name,
                    "local_ip": local_ip,
                    "local_port": local_port,
                    "remote_ip": remote_ip,
                    "remote_port": remote_port,
                    "connections": conn_count,
                    "upload_kbps": round(ul_kbps, 2),
                    "download_kbps": round(dl_kbps, 2),
                    "rx_bytes": rx_bytes,
                    "tx_bytes": tx_bytes
                })

            return {"type": "info", "connections": conns}

        except Exception as e:
            print("DEBUG: get_connections top-level exception:", repr(e))
            return {"type": "info", "connections": []}

    def get_connections_async(self, limit: int = 20, timeout: float = 5.0, callback: Optional[Callable[[Dict], None]] = None):
        """
        异步获取 connections，结果通过 callback(dict) 回传（非阻塞）。
        """
        def _worker():
            try:
                res = self.get_connections(limit=limit, timeout=timeout)
                print(res)
                if callback:
                    callback(res)
            except Exception as e:
                if callback:
                    callback(
                        {"type": "info", "connections": [], "error": str(e)})

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def get_disks(self, limit: int = 15, timeout: float = 5.0) -> Dict:
        """
        获取磁盘分区信息及基于 /proc/diskstats 的读写速率（KB/s，基于本地缓存计算）。
        返回 {"type":"info","disks":[{...}, ...]}
        所有数值字段都保证为 int/float，used_percent 返回浮点（0-100）。
        """
        try:
            try:
                timeout_val = float(timeout) if timeout is not None else 5.0
            except Exception:
                timeout_val = 5.0

            script = (r'''#!/bin/bash
LIMIT={limit}
df -k --output=source,size,used,avail,pcent,target | tail -n +2 | head -n $LIMIT | while read -r filesystem size used avail usep mount; do
    [[ "$filesystem" == "tmpfs" || "$filesystem" == "udev" ]] && continue
    device_type="physical"
    if [[ "$filesystem" == *"merged"* ]]; then
        device_type="docker_overlay"
    fi
    dev=$(basename "$filesystem")
    read_sectors=$(awk -v d="$dev" '$3==d {print $6}' /proc/diskstats 2>/dev/null)
    write_sectors=$(awk -v d="$dev" '$3==d {print $10}' /proc/diskstats 2>/dev/null)
    read_sectors=${read_sectors:-0}
    write_sectors=${write_sectors:-0}
    printf "device:%s|mount:%s|type:%s|size_kb:%s|used_kb:%s|avail_kb:%s|used_percent:%s|read_sectors:%s|write_sectors:%s\n" \
        "$filesystem" "$mount" "$device_type" "$size" "$used" "$avail" "$usep" "$read_sectors" "$write_sectors"
done
''').replace('{limit}', str(int(limit)))

            output = ""
            if getattr(self, "ssh_client", None):
                try:
                    stdin, stdout, stderr = self.ssh_client.exec_command(
                        'bash -s', timeout=timeout_val)
                    try:
                        stdin.write(script)
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
                    if err:
                        print("DEBUG: get_disks stderr:", err[:1000])
                    output = out.strip() or ""
                except Exception as e:
                    print("DEBUG: get_disks exec exception:", repr(e))
                    output = ""

            if not output and getattr(self, "ssh_channel", None) and not getattr(self.ssh_channel, "closed", False):
                try:
                    output = self._execute_command_slow(
                        script, timeout=timeout_val) or ""
                except Exception as e:
                    print("DEBUG: get_disks channel exception:", repr(e))
                    output = ""

            if not output:
                return {"type": "info", "disk_usage": []}

            now = time.time()
            disks = []
            if not hasattr(self, "_disk_prev"):
                self._disk_prev = {}

            for line in output.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = {}
                for pair in line.split('|'):
                    if ':' in pair:
                        k, v = pair.split(':', 1)
                        parts[k.strip()] = v.strip()

                device = parts.get('device', '')
                mount = parts.get('mount', '')
                dtype = parts.get('type', 'physical')

                # 数值字段转换，容错为 0
                def to_int(x):
                    try:
                        return int(x)
                    except Exception:
                        try:
                            return int(float(x))
                        except Exception:
                            return 0

                def to_float(x):
                    try:
                        return float(x)
                    except Exception:
                        try:
                            return float(x.replace('%', '').strip())
                        except Exception:
                            return 0.0

                size_kb = to_int(parts.get('size_kb', 0))
                used_kb = to_int(parts.get('used_kb', 0))
                avail_kb = to_int(parts.get('avail_kb', 0))
                used_percent_raw = parts.get('used_percent', '')
                # 去掉 % 并转换为浮点数（0-100）
                used_percent = to_float(used_percent_raw.strip().rstrip('%'))

                try:
                    read_sectors = int(parts.get('read_sectors', 0))
                except Exception:
                    read_sectors = 0
                try:
                    write_sectors = int(parts.get('write_sectors', 0))
                except Exception:
                    write_sectors = 0

                read_bytes = read_sectors * 512
                write_bytes = write_sectors * 512

                prev = self._disk_prev.get(device)
                read_kbps = 0.0
                write_kbps = 0.0
                if prev:
                    dt = now - prev.get("ts", now)
                    if dt > 0.05:
                        read_kbps = max(
                            0.0, (read_bytes - prev.get("read", 0)) / dt / 1024.0)
                        write_kbps = max(
                            0.0, (write_bytes - prev.get("write", 0)) / dt / 1024.0)

                # 更新缓存
                self._disk_prev[device] = {
                    "read": read_bytes, "write": write_bytes, "ts": now}

                disks.append({
                    "device": device,
                    "mount": mount,
                    "type": dtype,
                    "size_kb": size_kb,
                    "used_kb": used_kb,
                    "avail_kb": avail_kb,
                    "used_percent": round(used_percent, 2),
                    "read_kbps": round(read_kbps, 2),
                    "write_kbps": round(write_kbps, 2),
                    "read_bytes": read_bytes,
                    "write_bytes": write_bytes
                })

            return {"type": "info", "disk_usage": disks}

        except Exception as e:
            print("DEBUG: get_disks top-level exception:", repr(e))
            return {"type": "info", "disk_usage": []}

    def get_disks_async(self, limit: int = 15, timeout: float = 5.0, callback: Optional[Callable[[Dict], None]] = None):
        """
        异步获取磁盘信息（单次），结果通过 callback(dict) 回传（非阻塞）。
        建议在需要持续轮询时使用 register_poll(callback, kind='disks', interval=...) 注册到轮询器。
        """
        def _worker():
            try:
                res = self.get_disks(limit=limit, timeout=timeout)
                if callback:
                    callback(res)
            except Exception as e:
                if callback:
                    callback({"type": "info", "disks": [], "error": str(e)})

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def get_all_processes(self, limit: int = 50, timeout: float = 5.0) -> Dict:
        """
        获取前 limit 个进程的详细列表（user, pid, cpu, mem_mb, name, command）。
        使用纯 bash 解析，简单输出格式，本地解析 JSON。
        """
        try:
            try:
                timeout_val = float(timeout) if timeout is not None else 5.0
            except Exception:
                timeout_val = 5.0

            # 使用简单分隔符，本地解析
            script = (r'''#!/bin/bash
    LIMIT={limit}
    ps -eo user,pid,%cpu,rss,comm,cmd --no-headers --sort=-%cpu | head -n $LIMIT | awk 'NR>0 {{
        # 使用 ASCII 31 (Unit Separator) 作为字段分隔符，避免内容冲突
        cmd_clean = $0
        sub(/^[^[:space:]]+[[:space:]]+[0-9]+[[:space:]]+[0-9.]+[[:space:]]+[0-9]+[[:space:]]+[^[:space:]]+[[:space:]]+/, "", cmd_clean)
        user = $1
        pid = $2
        cpu = $3
        rss_kb = $4
        comm = $5
        cmd = cmd_clean
        
        # 计算内存 MB
        mem_mb = rss_kb / 1024
        
        # 使用 ASCII 31 (US) 分隔字段，ASCII 30 (RS) 分隔行
        printf "%s\x1f%s\x1f%s\x1f%.1f\x1f%s\x1f%s\x1e", user, pid, cpu, mem_mb, comm, cmd
    }}'
    ''').replace('{limit}', str(int(limit)))

            output = ""
            if getattr(self, "ssh_client", None):
                try:
                    stdin, stdout, stderr = self.ssh_client.exec_command(
                        'bash -s', timeout=timeout_val)
                    try:
                        stdin.write(script.encode('utf-8'))
                        stdin.channel.shutdown_write()
                    except Exception:
                        pass

                    out = stdout.read().decode('utf-8', errors='ignore')
                    err = stderr.read().decode('utf-8', errors='ignore')
                    output = out.strip() or ""
                except Exception as e:
                    print(f"DEBUG: get_all_processes exec exception: {e}")
                    output = ""

            if not output:
                return {"type": "info", "all_processes": []}

            # 解析输出：ASCII 30 (RS) 分隔行，ASCII 31 (US) 分隔字段
            processes = []
            for line in output.split('\x1e'):
                if not line.strip():
                    continue
                parts = line.split('\x1f')
                if len(parts) >= 6:
                    try:
                        proc = {
                            "user": parts[0],
                            "pid": int(parts[1]),
                            "cpu": float(parts[2]),
                            "mem_mb": float(parts[3]),
                            "name": parts[4],
                            "command": parts[5] if len(parts) > 5 else parts[4]
                        }
                        processes.append(proc)
                    except (ValueError, IndexError) as e:
                        continue

            return {"type": "info", "all_processes": processes}

        except Exception as e:
            print(f"DEBUG: get_all_processes top-level exception: {e}")
            return {"type": "info", "all_processes": []}

    def get_all_processes_async(self, limit: int = 50, timeout: float = 5.0, callback: Optional[Callable[[Dict], None]] = None):
        """
        异步获取 all_processes，使用单后台线程执行一次并通过 callback 返回结果。
        """
        def _worker():
            try:
                res = self.get_all_processes(limit=limit, timeout=timeout)
                if callback:
                    callback(res)
            except Exception as e:
                if callback:
                    callback(
                        {"type": "info", "all_processes": [], "error": str(e)})

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _fetch_for_kind(self, kind: str):
        """内部：根据 kind 调用对应的同步获取函数并返回 dict"""
        try:
            if kind in ("top", "top_processes"):
                return self.get_top_processes()
            if kind in ("net", "net_usage"):
                return self.get_net_usage()
            if kind in ("conn", "connections"):
                return self.get_connections()
            if kind in ("disks", "disk", "storage"):
                return self.get_disks()
            if kind in ("sysinfo",):
                return {"type": "sysinfo", **self.get_sysinfo_details()}
            if kind in ("all_processes", "allprocs", "processes", "all"):
                return self.get_all_processes()
            if kind in ("metrics", "system_metrics", "combined"):
                return self.get_system_metrics()
            # 默认返回空 info
            return {"type": "info"}
        except Exception as e:
            return {"type": "info", "error": str(e)}

    def _poll_loop(self):
        """后台线程：轮询注册的回调并按各自 interval 调用"""
        while not self._poll_thread_stop.is_set():
            now = time.time()
            # 复制一份以减少锁住时间
            with self._poll_lock:
                pollers_copy = list(self._pollers)
            for entry in pollers_copy:
                try:
                    if now >= entry.get("next", 0):
                        # 获取数据并调用回调（在同一线程中执行，避免线程爆炸）
                        res = self._fetch_for_kind(entry.get("kind", "info"))
                        try:
                            entry["callback"](res)
                        except Exception:
                            # 回调抛异常不影响其他任务
                            pass
                        # 更新下次执行时间
                        entry["next"] = now + \
                            max(0.01, float(entry.get("interval", 1.0)))
                except Exception:
                    # 单项出错忽略，继续轮询其他项
                    continue
            # 休眠较短时间，满足低延迟和低 CPU
            self._poll_thread_stop.wait(self._poll_tick)

    def _ensure_poller_running(self):
        """确保轮询线程在运行（无则启动）"""
        if self._poll_thread and self._poll_thread.is_alive():
            return
        # 清理停止标志并启动线程
        self._poll_thread_stop.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def stop_poller(self, join: bool = False):
        """停止轮询线程"""
        self._poll_thread_stop.set()
        if join and self._poll_thread:
            try:
                self._poll_thread.join(timeout=1.0)
            except Exception:
                pass
        self._poll_thread = None

    def register_poll(self, callback: Callable[[Dict], None], kind: str = "info", interval: float = 1.0, once: bool = False):
        """
        注册一个回调到轮询列表。
        - callback(res: dict) : 回调函数，将在轮询线程中被调用（请勿直接操作 GUI）。
        - kind: "top"|"net"|"conn"|"sysinfo"|"metrics"|"combined" 或同义词
        - interval: 秒，最小 0.01
        - once: 如果为 True，则只执行一次（在后台线程），不会加入持续轮询列表。
        """
        if not callable(callback):
            return

        if once:
            # 在独立线程中执行一次并返回（不加入 pollers）
            def _once_worker():
                try:
                    res = self._fetch_for_kind(kind)
                    try:
                        callback(res)
                    except Exception:
                        pass
                except Exception:
                    try:
                        callback(
                            {"type": "info", "error": "once fetch failed"})
                    except Exception:
                        pass

            t = threading.Thread(target=_once_worker, daemon=True)
            t.start()
            return

        try:
            interval = max(0.01, float(interval))
        except Exception:
            interval = 1.0
        entry = {"callback": callback, "kind": kind,
                 "interval": interval, "next": time.time()}
        with self._poll_lock:
            # 如果同一 callback 已存在，先移除旧的
            self._pollers = [p for p in self._pollers if p.get(
                "callback") != callback]
            self._pollers.append(entry)
        self._ensure_poller_running()

    def register_one_shot(self, callback: Callable[[Dict], None], kind: str = "info"):
        """
        便捷方法：只执行一次的注册（等同 register_poll(..., once=True)）。
        """
        self.register_poll(callback, kind=kind, interval=0.01, once=True)
