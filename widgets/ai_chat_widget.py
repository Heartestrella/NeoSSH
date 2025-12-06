from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
import os
from PyQt5.QtCore import QUrl, Qt, QObject, pyqtSlot, QEventLoop, QTimer, QVariant, pyqtSignal, QSize
from PyQt5.QtGui import QKeyEvent, QDesktopServices, QPixmap, QPainter
from PyQt5.QtSvg import QSvgRenderer
from tools.setting_config import SCM
from tools.ai_model_manager import AIModelManager
from tools.ai_mcp_manager import AIMCPManager
from tools.ai_history_manager import AIHistoryManager
import json
import base64
import re
import typing
import time
import requests
import threading
import shlex
from bs4 import BeautifulSoup
from tokenizers import Tokenizer
import locale
from PyQt5.QtCore import QLocale
import langid

if typing.TYPE_CHECKING:
    from main_window import Window
    from widgets.ssh_widget import SSHWidget

CONFIGER = SCM()


class AIBridge(QObject):
    toolResultReady = pyqtSignal(str, str)
    backendCallReady = pyqtSignal(str, str)
    streamChunkReceived = pyqtSignal(str, str)
    streamFinished = pyqtSignal(str, int, str, str)
    streamFailed = pyqtSignal(str, str)
    userinfo_got = pyqtSignal(str, str)  # username , qid

    def __init__(self, parent=None, main_window: 'Window' = None):
        super().__init__(parent)
        self.main_window = main_window
        self.model_manager = AIModelManager()
        self.mcp_manager = AIMCPManager()
        self.history_manager = AIHistoryManager()
        self.pending_tool_calls = {}
        self.active_requests = {}
        self.qq_name = None
        self.qq_number = None
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            tokenizer_path = os.path.join(
                current_dir, '..', 'resource', 'models', 'tokenizer.json')
            self.tokenizer = Tokenizer.from_file(tokenizer_path)
        except Exception as e:
            self.tokenizer = None
            print(f"Failed to load tokenizer from file: {e}")
        self._register_tool_handlers()

    def _register_tool_handlers(self):
        def 超级内容():
            ApiKey = "ctx7sk-e56f0c2f-317c-4da3-9aa7-0a207313118e"

            def _execute_context7_tool(tool_name: str, args: str, request_id: str):
                if request_id:
                    self.active_requests[request_id] = {'cancelled': False}

                def _worker():
                    try:
                        if self.active_requests.get(request_id, {}).get('cancelled'):
                            return
                        proxy_config_str = CONFIGER.read_config().get("ai_chat_proxy")
                        proxies = {}
                        if proxy_config_str:
                            try:
                                proxy_config = json.loads(proxy_config_str)
                                protocol = proxy_config.get("protocol")
                                host = proxy_config.get("host")
                                port = proxy_config.get("port")
                                username = proxy_config.get("username")
                                password = proxy_config.get("password")
                                if protocol and host and port:
                                    auth = ""
                                    if username and password:
                                        auth = f"{username}:{password}@"
                                    proxy_url = f"{protocol}://{auth}{host}:{port}"
                                    if protocol.startswith('socks'):
                                        proxy_scheme = 'socks5h' if protocol == 'socks5' else protocol
                                        proxy_url = f"{proxy_scheme}://{auth}{host}:{port}"
                                        proxies = {"http": proxy_url,
                                                   "https": proxy_url}
                                    else:
                                        proxies = {"http": proxy_url,
                                                   "https": proxy_url}
                            except (json.JSONDecodeError, AttributeError):
                                pass
                        headers = {
                            "Authorization": f"Bearer {ApiKey}"
                        }
                        if tool_name == "resolve-library-id":
                            library_match = re.search(
                                r'<libraryName>(.*?)</libraryName>', args, re.DOTALL)
                            if not library_match:
                                raise ValueError(
                                    "Missing libraryName parameter")
                            library_name = library_match.group(1).strip()
                            search_url = f"https://context7.com/api/v1/search?query={requests.utils.quote(library_name)}"
                            response = requests.get(
                                search_url, headers=headers, timeout=120, proxies=proxies)
                        elif tool_name == "get-library-docs":
                            library_id_match = re.search(
                                r'<context7CompatibleLibraryID>(.*?)</context7CompatibleLibraryID>', args, re.DOTALL)
                            if not library_id_match:
                                raise ValueError(
                                    "Missing context7CompatibleLibraryID parameter")
                            library_id = library_id_match.group(
                                1).strip().lstrip('/')
                            topic_match = re.search(
                                r'<topic>(.*?)</topic>', args, re.DOTALL)
                            tokens_match = re.search(
                                r'<tokens>(\d+)</tokens>', args, re.DOTALL)
                            params = {"type": "json"}
                            if topic_match:
                                params["topic"] = topic_match.group(1).strip()
                            if tokens_match:
                                params["tokens"] = tokens_match.group(1)
                            else:
                                params["tokens"] = str(5000*4)
                            docs_url = f"https://context7.com/api/v1/{library_id}"
                            response = requests.get(
                                docs_url, headers=headers, params=params, timeout=120, proxies=proxies)
                        else:
                            raise ValueError(f"Unknown tool: {tool_name}")
                        response.raise_for_status()
                        if not self.active_requests.get(request_id, {}).get('cancelled'):
                            self.toolResultReady.emit(
                                request_id, response.text)
                    except requests.exceptions.RequestException as e:
                        if not self.active_requests.get(request_id, {}).get('cancelled'):
                            self.toolResultReady.emit(request_id, str(e))
                    except Exception as e:
                        if not self.active_requests.get(request_id, {}).get('cancelled'):
                            self.toolResultReady.emit(request_id, str(e))
                    finally:
                        if request_id in self.active_requests:
                            del self.active_requests[request_id]
                thread = threading.Thread(target=_worker)
                thread.daemon = True
                thread.start()
                return "Executing..."

            def resolve_library_id(args: str = '', request_id: str = None):
                """
                <libraryName>Library name to search for and retrieve a Context7-compatible library ID.</libraryName>
                """
                return _execute_context7_tool("resolve-library-id", args, request_id)

            def get_library_docs(args: str = '', request_id: str = None):
                """
                <context7CompatibleLibraryID>Exact Context7-compatible library ID (e.g., '/mongodb/docs', '/vercel/next.js', '/supabase/supabase', '/vercel/next.js/v14.3.0-canary.87') retrieved from 'resolve-library-id' or directly from user query in the format '/org/project' or '/org/project/version'.</context7CompatibleLibraryID>
                <topic>Topic to focus documentation on (e.g., 'hooks', 'routing').</topic>
                """
                return _execute_context7_tool("get-library-docs", args, request_id)

            self.mcp_manager.register_tool_handler(
                server_name="超级内容",
                tool_name="resolve_library_id",
                handler=resolve_library_id,
                description="Resolves a package/product name to a Context7-compatible library ID and returns a list of matching libraries. You MUST call this function before 'get-library-docs' to obtain a valid Context7-compatible library ID UNLESS the user explicitly provides a library ID in the format '/org/project' or '/org/project/version' in their query. Selection Process: 1. Analyze the query to understand what library/package the user is looking for 2. Return the most relevant match based on: - Name similarity to the query (exact matches prioritized) - Description relevance to the query's intent - Documentation coverage (prioritize libraries with higher Code Snippet counts) - Trust score (consider libraries with scores of 7-10 more authoritative) Response Format: - Return the selected library ID in a clearly marked section - Provide a brief explanation for why this library was chosen - If multiple good matches exist, acknowledge this but proceed with the most relevant one - If no good matches exist, clearly state this and suggest query refinements For ambiguous queries, request clarification before proceeding with a best-guess match.",
                auto_approve=True
            )
            self.mcp_manager.register_tool_handler(
                server_name="超级内容",
                tool_name="get_library_docs",
                handler=get_library_docs,
                description="Fetches up-to-date documentation for a library. You must call 'resolve-library-id' first to obtain the exact Context7-compatible library ID required to use this tool, UNLESS the user explicitly provides a library ID in the format '/org/project' or '/org/project/version' in their query.",
                auto_approve=True
            )

        def 通用():
            def provideListOptions(args: str = '') -> str:
                """<title>标题(仅支持纯字符串格式)(必填)</title><options>每行一个选项(仅支持纯字符串格式)(必填)</options>"""
                options_match = re.search(r'<options>(.*?)</options>', args, re.DOTALL)
                if not options_match:
                    return json.dumps({"status": "error", "content": "未提供选项列表"}, ensure_ascii=False)
                title_match = re.search(r'<title>(.*?)</title>', args)
                title = title_match.group(1).strip() if title_match else '快速回复'
                options_text = options_match.group(1).strip()
                if not options_text:
                    return json.dumps({"status": "error", "content": "未提供选项列表"}, ensure_ascii=False)
                options = [line.strip() for line in options_text.split('\n') if line.strip()]
                return json.dumps({"status": "success", "action": "provideListOptions", "title": title,"options": options}, ensure_ascii=False)

            def fetchWeb(url: str, method: str = "GET", body: str = None, headers: dict = None, only_body: bool = True, request_id: str = None) -> str:
                effective_headers = headers.copy() if headers is not None else {}
                if request_id:
                    self.active_requests[request_id] = {'cancelled': False}

                def _fetch_worker():
                    try:
                        if self.active_requests.get(request_id, {}).get('cancelled'):
                            return
                        proxy_config_str = CONFIGER.read_config().get("ai_chat_proxy")
                        proxies = {}
                        if proxy_config_str:
                            try:
                                proxy_config = json.loads(proxy_config_str)
                                protocol = proxy_config.get("protocol")
                                host = proxy_config.get("host")
                                port = proxy_config.get("port")
                                username = proxy_config.get("username")
                                password = proxy_config.get("password")
                                if protocol and host and port:
                                    auth = ""
                                    if username and password:
                                        auth = f"{username}:{password}@"
                                    proxy_url = f"{protocol}://{auth}{host}:{port}"
                                    if protocol.startswith('socks'):
                                        proxy_scheme = 'socks5h' if protocol == 'socks5' else protocol
                                        proxy_url = f"{proxy_scheme}://{auth}{host}:{port}"
                                        proxies = {"http": proxy_url,
                                                   "https": proxy_url}
                                    else:
                                        proxies = {"http": proxy_url,
                                                   "https": proxy_url}
                            except (json.JSONDecodeError, AttributeError):
                                pass
                        if "User-Agent" not in effective_headers:
                            effective_headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                        response = requests.request(method.upper(
                        ), url, headers=effective_headers, data=body, timeout=10, proxies=proxies, allow_redirects=True, stream=True)
                        response.raise_for_status()
                        content_chunks = []
                        for chunk in response.iter_content(chunk_size=8192):
                            if self.active_requests.get(request_id, {}).get('cancelled'):
                                return
                            content_chunks.append(chunk)
                        if self.active_requests.get(request_id, {}).get('cancelled'):
                            return
                        full_content = b''.join(content_chunks).decode(
                            'utf-8', errors='ignore')
                        content = ""
                        if only_body:
                            soup = BeautifulSoup(full_content, 'html.parser')
                            if soup.body:
                                content = soup.body.decode_contents()
                            else:
                                content = "HTML中未找到body标签"
                        else:
                            content = full_content
                        if not self.active_requests.get(request_id, {}).get('cancelled'):
                            self.toolResultReady.emit(request_id, content)
                    except requests.exceptions.RequestException as e:
                        if not self.active_requests.get(request_id, {}).get('cancelled'):
                            self.toolResultReady.emit(request_id, str(e))
                    except Exception as e:
                        if not self.active_requests.get(request_id, {}).get('cancelled'):
                            self.toolResultReady.emit(request_id, str(e))
                    finally:
                        if request_id in self.active_requests:
                            del self.active_requests[request_id]
                thread = threading.Thread(target=_fetch_worker)
                thread.daemon = True
                thread.start()
                return "Executing..."
            self.mcp_manager.register_tool_handler(
                server_name="通用",
                tool_name="fetchWeb",
                handler=fetchWeb,
                description="获取网页内容",
                auto_approve=True
            )
            self.mcp_manager.register_tool_handler(
                server_name="通用",
                tool_name="provideListOptions",
                handler=provideListOptions,
                description="提供用户快速回复选项",
                auto_approve=True
            )

        def Linux终端():
            def _safe_quote(path):
                if path is None:
                    return "''"
                return shlex.quote(str(path))

            def _internal_execute_interactive_shell(command: str, cwd: str = '.', request_id: str = None):
                full_command = "cd " + cwd + ";" + command
                if not self.main_window:
                    return json.dumps({"status": "error", "content": "Main window not available."}, ensure_ascii=False)
                active_widget = None
                if request_id and request_id in self.pending_tool_calls:
                    active_widget = self.pending_tool_calls[request_id].get(
                        'widget')
                if not active_widget:
                    active_widget = self.main_window.get_active_ssh_widget()
                if not active_widget:
                    return json.dumps({"status": "error", "content": "No active SSH session found."}, ensure_ascii=False)
                worker = None
                if hasattr(active_widget, 'ssh_widget') and hasattr(active_widget.ssh_widget, 'bridge'):
                    worker = active_widget.ssh_widget.bridge.worker
                if not worker:
                    return json.dumps({"status": "error", "content": "Could not find the SSH worker for the active session."}, ensure_ascii=False)
                if request_id:
                    self.pending_tool_calls[request_id]['worker'] = worker

                def on_output_ready(result_str, code):
                    try:
                        if request_id in self.pending_tool_calls:
                            call_info = self.pending_tool_calls[request_id]
                            if call_info.get('cancelled', False):
                                result_str = result_str + "\n用户中断"
                            self.toolResultReady.emit(request_id, result_str)
                            del self.pending_tool_calls[request_id]
                        worker.command_output_ready.disconnect(on_output_ready)
                    except TypeError:
                        pass
                worker.command_output_ready.connect(on_output_ready)
                active_widget.execute_command_and_capture(full_command)
                return "Executing..."

            def _internal_execute_silent_shell(command: str, cwd: str = '.'):
                full_command = "cd " + cwd + "; " + command if cwd != '.' else command
                if not self.main_window:
                    return json.dumps({"status": "error", "content": "Main window not available."}, ensure_ascii=False)
                active_widget = self.main_window.get_active_ssh_widget()
                if not active_widget:
                    return json.dumps({"status": "error", "content": "No active SSH session found."}, ensure_ascii=False)
                worker = None
                if hasattr(active_widget, 'ssh_widget') and hasattr(active_widget.ssh_widget, 'bridge'):
                    worker = active_widget.ssh_widget.bridge.worker
                if not worker:
                    return json.dumps({"status": "error", "content": "Could not find the SSH worker for the active session."}, ensure_ascii=False)
                if not hasattr(worker, 'execute_silent_command'):
                    return json.dumps({"status": "error", "content": "SSH worker does not have 'execute_silent_command' method."}, ensure_ascii=False)
                output, error, exit_code = worker.execute_silent_command(
                    full_command)
                if exit_code == 0:
                    return output
                else:
                    return json.dumps({"status": "error", "content": error, "exit_code": exit_code}, ensure_ascii=False)

            def exe_shell(args: str = '', request_id: str = None):
                """
                <exe_shell><shell>{要执行的命令}</shell><cwd>{工作目录}</cwd><reason>{简单且易懂的执行理由或原因或目的}</reason></exe_shell>
                """
                if not args:
                    return json.dumps({"status": "error", "content": "No arguments provided."}, ensure_ascii=False)
                try:
                    shell_match = re.search(
                        r'<shell>([\s\S]*?)</shell>', args, re.DOTALL)
                    if not shell_match:
                        return json.dumps({"status": "error", "content": "Missing or invalid <shell> tag."}, ensure_ascii=False)
                    shell = shell_match.group(1)
                    cwd_match = re.search(r'<cwd>(.*?)</cwd>', args, re.DOTALL)
                    cwd = cwd_match.group(1).strip() if cwd_match else '.'
                    return _internal_execute_interactive_shell(shell, cwd, request_id)
                except Exception as e:
                    return json.dumps({"status": "error", "content": f"An unexpected error occurred: {e}"}, ensure_ascii=False)

            def read_file(file_path: list = None, show_line: bool = False, start_line: int = None, end_line: int = None):
                if not file_path:
                    return json.dumps({"status": "error", "content": "No file path provided or list is empty."}, ensure_ascii=False)
                try:
                    if len(file_path) == 1:
                        safe_path = _safe_quote(file_path[0])
                        if start_line is not None and end_line is not None:
                            if start_line < 1 or end_line < start_line:
                                return json.dumps({"status": "error", "content": "Invalid line range. start_line must be >= 1 and end_line must be >= start_line."}, ensure_ascii=False)
                            if show_line:
                                command = f"sed -n '{start_line},{end_line}p' {safe_path} | awk '{{print NR+{start_line-1}\"|\" $0}}'"
                            else:
                                command = f"sed -n '{start_line},{end_line}p' {safe_path}"
                        else:
                            command = f"cat {safe_path}"
                            if show_line:
                                command = f"awk '{{print NR\"|\" $0}}' {safe_path}"
                        return _internal_execute_silent_shell(command)
                    else:
                        results = []
                        for path in file_path:
                            safe_path = _safe_quote(path)
                            if start_line is not None and end_line is not None:
                                if start_line < 1 or end_line < start_line:
                                    content = json.dumps(
                                        {"status": "error", "content": "Invalid line range."}, ensure_ascii=False)
                                elif show_line:
                                    command = f"sed -n '{start_line},{end_line}p' {safe_path} | awk '{{print NR+{start_line-1}\"|\" $0}}'"
                                    content = _internal_execute_silent_shell(
                                        command)
                                else:
                                    command = f"sed -n '{start_line},{end_line}p' {safe_path}"
                                    content = _internal_execute_silent_shell(
                                        command)
                            else:
                                command = f"cat {safe_path}"
                                if show_line:
                                    command = f"awk '{{print NR\"|\" $0}}' {safe_path}"
                                content = _internal_execute_silent_shell(
                                    command)
                            try:
                                error_data = json.loads(content)
                                if isinstance(error_data, dict) and error_data.get("status") == "error":
                                    content = error_data.get(
                                        "content", "Unknown error")
                            except (json.JSONDecodeError, TypeError):
                                pass
                            results.append(
                                f"<filePath={path}>\n{content}\n<filePath>")
                        return "\n".join(results)
                except Exception as e:
                    return json.dumps({"status": "error", "content": f"Failed to read file(s): {e}"}, ensure_ascii=False)

            def edit_file(args: str = None, request_id: str = None):
                """
                <edit_file><path>{文件绝对路径(必填)}</path><start_line>{开始行号(必填)(-1为覆写整个文件)}</start_line><end_line>{结束行号(必填)(-1为覆写整个文件)}</end_line><originalcontent>{行范围内原始完整内容(行范围非-1时必填)}</originalcontent><replace>{新内容(必填)}</replace></edit_file>
                """
                if not args:
                    return json.dumps({"status": "error", "content": "No arguments provided for edit_file."}, ensure_ascii=False)
                if request_id:
                    self.pending_tool_calls[request_id] = {
                        'server_name': 'Linux终端',
                        'tool_name': 'edit_file',
                        'start_time': time.time(),
                        'widget': self.main_window.get_active_ssh_widget() if self.main_window else None
                    }

                def _edit_worker():
                    try:
                        if request_id and self.pending_tool_calls.get(request_id, {}).get('cancelled'):
                            return
                        path_match = re.search(
                            r'<path>(.*?)</path>', args, re.DOTALL)
                        start_line_match = re.search(
                            r'<start_line>(-?\d+)</start_line>', args)
                        end_line_match = re.search(
                            r'<end_line>(-?\d+)</end_line>', args)
                        if not (path_match and start_line_match and end_line_match):
                            result = json.dumps(
                                {"status": "error", "content": "Missing or invalid path/start_line/end_line tags."}, ensure_ascii=False)
                            if request_id:
                                self.toolResultReady.emit(request_id, result)
                            return result
                        file_path = path_match.group(1).strip()
                        start_line = int(start_line_match.group(1))
                        end_line = int(end_line_match.group(1))
                        if start_line == -1 and end_line == -1:
                            if request_id and self.pending_tool_calls.get(request_id, {}).get('cancelled'):
                                return
                            replace_content = re.search(
                                r'<replace>(.*?)</replace>', args, re.DOTALL)
                            if replace_content is None:
                                result = json.dumps(
                                    {"status": "error", "content": "Missing <replace> tag."}, ensure_ascii=False)
                                if request_id:
                                    self.toolResultReady.emit(
                                        request_id, result)
                                return result
                            replace_block = replace_content.group(1)
                            import os as os_module
                            parent_dir = os_module.path.dirname(file_path)
                            if parent_dir:
                                safe_parent_dir = _safe_quote(parent_dir)
                                mkdir_command = f"mkdir -p {safe_parent_dir}"
                                _internal_execute_silent_shell(mkdir_command)
                            new_content = replace_block.strip() if replace_block.strip() else ""
                            encoded_content = base64.b64encode(
                                new_content.encode('utf-8')).decode('utf-8')
                            safe_path = _safe_quote(file_path)
                            command = f"echo '{encoded_content}' | base64 --decode > {safe_path}"
                            r = _internal_execute_silent_shell(command)
                            if request_id and self.pending_tool_calls.get(request_id, {}).get('cancelled'):
                                return
                            if r == '':
                                active_widget = self.main_window.get_active_ssh_widget() if self.main_window else None
                                if active_widget:
                                    widget_key = active_widget.objectName()
                                    self.main_window._refresh_paths(widget_key)
                                result = json.dumps(
                                    {"status": "success", "content": f"成功创建新文件: {file_path}", "action": "create"}, ensure_ascii=False)
                            else:
                                result = json.dumps(
                                    {"status": "error", "content": f"创建文件失败: {r}"}, ensure_ascii=False)
                            if request_id:
                                self.toolResultReady.emit(request_id, result)
                            return result
                        search_content = re.search(
                            r'<originalcontent>(.*?)</originalcontent>', args, re.DOTALL)
                        if search_content is None:
                            result = json.dumps(
                                {"status": "error", "content": "Missing <originalcontent> tag."}, ensure_ascii=False)
                            if request_id:
                                self.toolResultReady.emit(request_id, result)
                            return result
                        search_block = search_content.group(1)
                        replace_content = re.search(
                            r'<replace>(.*?)</replace>', args, re.DOTALL)
                        if replace_content is None:
                            result = json.dumps(
                                {"status": "error", "content": "Missing <replace> tag."}, ensure_ascii=False)
                            if request_id:
                                self.toolResultReady.emit(request_id, result)
                            return result
                        replace_block = replace_content.group(1)
                        if request_id and self.pending_tool_calls.get(request_id, {}).get('cancelled'):
                            return
                        remote_content_json = read_file([file_path])
                        try:
                            remote_data = json.loads(remote_content_json)
                            if remote_data.get("status") == "error":
                                if request_id:
                                    self.toolResultReady.emit(
                                        request_id, remote_content_json)
                                return remote_content_json
                            remote_content = remote_data.get("content", "")
                        except (json.JSONDecodeError, AttributeError):
                            remote_content = remote_content_json
                        if request_id and self.pending_tool_calls.get(request_id, {}).get('cancelled'):
                            return
                        remote_content = remote_content.replace('\r', '')
                        lines = remote_content.splitlines(True)
                        if not (1 <= start_line <= end_line <= len(lines)):
                            result = json.dumps(
                                {"status": "error", "content": f"Line numbers out of bounds. File has {len(lines)} lines."}, ensure_ascii=False)
                            if request_id:
                                self.toolResultReady.emit(request_id, result)
                            return result
                        actual_block = "".join(lines[start_line - 1:end_line])
                        search_block_stripped = search_block.strip()
                        actual_block_stripped = actual_block.strip()
                        if actual_block_stripped != search_block_stripped:
                            result = json.dumps({
                                "status": "error",
                                "content": "Content verification failed. The content on the server does not match the 'search' block.",
                                "expected": search_block_stripped,
                                "actual": actual_block_stripped
                            }, ensure_ascii=False)
                            if request_id:
                                self.toolResultReady.emit(request_id, result)
                            return result
                        if request_id and self.pending_tool_calls.get(request_id, {}).get('cancelled'):
                            return
                        leading_whitespace = ""
                        if start_line <= len(lines):
                            first_line_of_block = lines[start_line - 1]
                            leading_whitespace = first_line_of_block[:len(
                                first_line_of_block) - len(first_line_of_block.lstrip())]
                        original_last_line = lines[end_line - 1]
                        line_ending = '\n'
                        if original_last_line.endswith('\r\n'):
                            line_ending = '\r\n'
                        new_content_parts = []
                        if replace_block and not replace_block.isspace():
                            replace_lines = replace_block.rstrip('\n\r').splitlines()
                            new_content_parts = [
                                leading_whitespace + line + line_ending for line in replace_lines]
                        new_lines = lines[:start_line - 1] + \
                            new_content_parts + lines[end_line:]
                        new_full_content = "".join(new_lines)
                        encoded_content = base64.b64encode(
                            new_full_content.encode('utf-8')).decode('utf-8')
                        safe_path = _safe_quote(file_path)
                        command = f"echo '{encoded_content}' | base64 --decode > {safe_path}"
                        r = _internal_execute_silent_shell(command)
                        if request_id and self.pending_tool_calls.get(request_id, {}).get('cancelled'):
                            return
                        if r == '':
                            active_widget = self.main_window.get_active_ssh_widget() if self.main_window else None
                            if active_widget:
                                widget_key = active_widget.objectName()
                                self.main_window._refresh_paths(widget_key)
                            result = json.dumps(
                                {"status": "success", "content": f"{file_path} {start_line}-{end_line} {search_block} -> {replace_block}"}, ensure_ascii=False)
                        else:
                            result = json.dumps(
                                {"status": "error", "content": r}, ensure_ascii=False)
                        if request_id:
                            self.toolResultReady.emit(request_id, result)
                        return result
                    except Exception as e:
                        result = json.dumps(
                            {"status": "error", "content": f"An unexpected error occurred during file edit: {e}"}, ensure_ascii=False)
                        if request_id:
                            self.toolResultReady.emit(request_id, result)
                        return result
                    finally:
                        if request_id and request_id in self.pending_tool_calls:
                            del self.pending_tool_calls[request_id]
                if request_id:
                    thread = threading.Thread(target=_edit_worker)
                    thread.daemon = True
                    thread.start()
                    return "Executing..."
                else:
                    return _edit_worker()

            def navigate_file_manager(path: str = None):
                if not path:
                    return json.dumps({"status": "error", "content": "No path provided."}, ensure_ascii=False)
                if not self.main_window:
                    return json.dumps({"status": "error", "content": "Main window not available."}, ensure_ascii=False)
                active_widget = self.main_window.get_active_ssh_widget()
                if not active_widget:
                    return json.dumps({"status": "error", "content": "No active SSH session found."}, ensure_ascii=False)
                if hasattr(active_widget, '_set_file_bar'):
                    QTimer.singleShot(
                        0, lambda: active_widget._set_file_bar(path))
                    return json.dumps({"status": "success", "content": f"Navigated file manager to {path}"}, ensure_ascii=False)
                else:
                    return json.dumps({"status": "error", "content": "File explorer update function not found in the active session."}, ensure_ascii=False)

            def get_terminal_output(count: int = 1):
                if not self.main_window:
                    return json.dumps({"status": "error", "content": "Main window not available."}, ensure_ascii=False)
                active_widget = self.main_window.get_active_ssh_widget()
                if not active_widget:
                    return json.dumps({"status": "error", "content": "No active SSH session found."}, ensure_ascii=False)
                if hasattr(active_widget, 'ssh_widget') and hasattr(active_widget.ssh_widget, 'get_latest_output'):
                    return active_widget.ssh_widget.get_latest_output(count)
                else:
                    return json.dumps({"status": "error", "content": "Could not find the terminal output function."}, ensure_ascii=False)

            def list_dir(path: str = None, recursive: bool = False):
                try:
                    safe_path = _safe_quote(path)
                    if recursive:
                        command = f"ls -RFA {safe_path}"
                    else:
                        command = f"ls -FA {safe_path}"
                    r = _internal_execute_silent_shell(command)
                    if r == '':
                        r = '空目录'
                    return r
                except Exception as e:
                    return json.dumps({"status": "error", "content": f"Failed to list directory: {e}"}, ensure_ascii=False)
            self.mcp_manager.register_tool_handler(
                server_name="Linux终端",
                tool_name="exe_shell",
                handler=exe_shell,
                description="在当前终端执行shell命令",
                auto_approve=False
            )
            self.mcp_manager.register_tool_handler(
                server_name="Linux终端",
                tool_name="read_file",
                handler=read_file,
                description="读取服务器文件内容",
                auto_approve=True
            )
            self.mcp_manager.register_tool_handler(
                server_name="Linux终端",
                tool_name="edit_file",
                handler=edit_file,
                description="覆写文件内容/编辑文件内容",
                auto_approve=False
            )
            self.mcp_manager.register_tool_handler(
                server_name="Linux终端",
                tool_name="navigate_file_manager",
                handler=navigate_file_manager,
                description="导航文件管理器到指定路径",
                auto_approve=True
            )
            self.mcp_manager.register_tool_handler(
                server_name="Linux终端",
                tool_name="get_terminal_output",
                handler=get_terminal_output,
                description="获取最新几条的所执行命令的终端输出",
                auto_approve=True
            )
            self.mcp_manager.register_tool_handler(
                server_name="Linux终端",
                tool_name="list_dir",
                handler=list_dir,
                description="列出目录结构",
                auto_approve=True
            )
        Linux终端()
        通用()
        超级内容()
        # print(self.getSystemPrompt())

    @pyqtSlot(str, str, str, result=str)
    def callBackend(self, request_id: str, method_name: str, args_json: str):
        def _worker():
            try:
                if not hasattr(self, method_name):
                    raise AttributeError(f"Method '{method_name}' not found")
                method = getattr(self, method_name)
                if not callable(method):
                    raise TypeError(f"'{method_name}' is not callable")
                if args_json:
                    args_data = json.loads(args_json)
                    if isinstance(args_data, dict):
                        result = method(**args_data)
                    elif isinstance(args_data, list):
                        result = method(*args_data)
                    else:
                        result = method(args_data)
                else:
                    result = method()
                if isinstance(result, str):
                    self.backendCallReady.emit(request_id, result)
                else:
                    self.backendCallReady.emit(
                        request_id, json.dumps(result, ensure_ascii=False))
            except Exception as e:
                error_result = json.dumps({
                    "status": "error",
                    "content": f"Backend call failed: {str(e)}",
                    "method": method_name
                }, ensure_ascii=False)
                self.backendCallReady.emit(request_id, error_result)

        thread = threading.Thread(target=_worker)
        thread.daemon = True
        thread.start()
        return ""

    @pyqtSlot(result=str)
    def getSystemPrompt(self):
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            prompt_path = os.path.join(
                current_dir, '..', 'resource', 'widget', 'ai_chat', 'system.md')
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompt = f.read()
            prompt += "\n\n# 已连接的MCP服务器\n"
            prompt += "当服务器已连接时,你可以通过`use_mcp_tool`工具使用该服务器的工具.\n"
            for server_name, tools in self.mcp_manager.tools.items():
                prompt += f"\n## {server_name}\n"
                prompt += "### 可用工具\n"
                for tool_name, tool_info in tools.items():
                    prompt += f"- {tool_name}\n"
                    prompt += f"      {tool_info['description']}\n\n"
                    input_format = tool_info.get('input_format', 'String')
                    prompt += f"      输入模式 [{input_format}]\n"
                    schema_str = tool_info['schema']
                    prompt += f"{schema_str}\n\n"
            return prompt
        except Exception as e:
            print(f"Error generating system prompt: {e}")
            return ""

    @pyqtSlot(str, result=str)
    def processMessage(self, message):
        mcp_tool_call = self.mcp_manager.parse_mcp_tool_use(message)
        if mcp_tool_call:
            return json.dumps(mcp_tool_call, ensure_ascii=False)
        return ""

    def _execute_tool_async(self, server_name, tool_name, arguments, request_id):
        try:
            result = self.mcp_manager.execute_tool(
                server_name, tool_name, arguments, request_id)
            result_str = str(result)
            if result_str != "Executing...":
                self.toolResultReady.emit(request_id, result_str)
                if request_id in self.pending_tool_calls:
                    del self.pending_tool_calls[request_id]
        except json.JSONDecodeError as e:
            result_str = json.dumps(
                {"status": "error", "content": f"Invalid arguments format: {e}"}, ensure_ascii=False)
            self.toolResultReady.emit(request_id, result_str)
            if request_id in self.pending_tool_calls:
                del self.pending_tool_calls[request_id]
        except Exception as e:
            result_str = json.dumps(
                {"status": "error", "content": f"Tool execution error: {e}"}, ensure_ascii=False)
            self.toolResultReady.emit(request_id, result_str)
            if request_id in self.pending_tool_calls:
                del self.pending_tool_calls[request_id]

    @pyqtSlot(str, str, str, result=str)
    @pyqtSlot(str, str, str, str, result=str)
    def executeMcpTool(self, server_name, tool_name, arguments: str, request_id=None):
        if request_id:
            self.pending_tool_calls[request_id] = {
                'server_name': server_name,
                'tool_name': tool_name,
                'start_time': time.time(),
                'widget': self.main_window.get_active_ssh_widget()
            }
            QTimer.singleShot(0, lambda: self._execute_tool_async(
                server_name, tool_name, arguments, request_id
            ))
            return ""
        else:
            try:
                result = self.mcp_manager.execute_tool(
                    server_name, tool_name, arguments)
                return str(result)
            except json.JSONDecodeError as e:
                return json.dumps({"status": "error", "content": f"Invalid arguments format: {e}"}, ensure_ascii=False)

    @pyqtSlot(str)
    def cancelMcpTool(self, request_id):
        if request_id in self.active_requests:
            self.active_requests[request_id]['cancelled'] = True
            self.toolResultReady.emit(request_id, json.dumps({
                "status": "cancelled",
                "content": "用户已取消操作"
            }, ensure_ascii=False))
        if request_id in self.pending_tool_calls:
            call_info = self.pending_tool_calls[request_id]
            worker = call_info.get('worker')
            call_info['cancelled'] = True
            call_info['cancel_time'] = time.time()
            if worker:
                worker.send_interrupt()
            QTimer.singleShot(
                5000, lambda: self._force_cancel_timeout(request_id))

    def _force_cancel_timeout(self, request_id):
        if request_id in self.pending_tool_calls:
            call_info = self.pending_tool_calls[request_id]
            if call_info.get('cancelled', False):
                self.toolResultReady.emit(request_id, json.dumps({
                    "status": "cancelled",
                    "content": "命令中断超时,强制取消。"
                }, ensure_ascii=False))
                worker = call_info.get('worker')
                if worker:
                    try:
                        worker.command_output_ready.disconnect()
                    except:
                        pass
                del self.pending_tool_calls[request_id]

    @pyqtSlot(str)
    def forceContinueTool(self, request_id: str):
        if request_id in self.pending_tool_calls:
            call_info = self.pending_tool_calls[request_id]
            worker = call_info.get('worker')
            if worker and hasattr(worker, 'force_complete'):
                worker.force_complete.emit(request_id)

    @pyqtSlot(result=str)
    def getSystemLanguage(self):
        try:
            locale_name = QLocale.system().name()
            language_code = locale_name.replace('_', '-')
            return language_code
        except Exception as e:
            try:
                default_locale = locale.getdefaultlocale()[0]
                if default_locale:
                    return default_locale.replace('_', '-')
                else:
                    return 'en-US'
            except:
                return 'en-US'

    @pyqtSlot(result=str)
    def getDefaultModels(self):
        models = self.model_manager._get_default_models()
        return json.dumps(models.get("NeoSSHVip-深度思考"), ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def detectLanguage(self, text):
        try:
            lang_code, confidence = langid.classify(text)
            return json.dumps({"language": lang_code, "confidence": float(confidence)}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "content": str(e)}, ensure_ascii=False)

    @pyqtSlot(str, str, result=str)
    def translateText(self, text, target_language):
        try:
            model_info = self.model_manager._get_default_models().get("NeoSSHVip-深度思考")
            if not model_info:
                return "翻译模型未配置"
            api_url = model_info.get("api_url")
            model_name = model_info.get("model_name")
            api_key = model_info.get("key")
            if not all([api_url, model_name, api_key]):
                return "翻译模型配置不完整"
            current_dir = os.path.dirname(os.path.abspath(__file__))
            translation_rules_path = os.path.join(
                current_dir, '..', 'resource', 'widget', 'ai_chat', 'translation.md')
            try:
                with open(translation_rules_path, 'r', encoding='utf-8') as f:
                    translation_rules = f.read()
            except Exception:
                translation_rules = "你是一个专业的翻译助手，只返回翻译结果，不要添加任何解释或说明。"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json, text/event-stream",
                "Accept-Encoding": "gzip, deflate, br, zstd"
            }
            messages = [
                {"role": "system", "content": translation_rules},
                {"role": "user", "content": f"请将以下文本翻译成{target_language}：\n\n{text}"}
            ]
            payload = {"model": model_name,
                       "messages": messages, "stream": True}
            options = {"method": "POST", "headers": headers,
                       "body": json.dumps(payload)}
        except Exception as e:
            return f"翻译时发生意外错误: {str(e)}"
        while True:
            try:
                request_id = f"translate_{time.time()}"
                loop = QEventLoop()
                result_data = {
                    "text": "",
                    "buffer": "",
                    "error": ""
                }

                def on_chunk(req_id, chunk):
                    if req_id != request_id:
                        return
                    result_data["buffer"] += chunk
                    lines = result_data["buffer"].split('\n')
                    result_data["buffer"] = lines.pop()
                    for line in lines:
                        if line.startswith('data: '):
                            data_str = line[6:].strip()
                            if data_str == '[DONE]':
                                continue
                            try:
                                data = json.loads(data_str)
                                if 'error' in data:
                                    error_info = data.get('error', {})
                                    error_message = str(
                                        error_info.get('message', error_info))
                                    result_data["error"] += error_message
                                    continue
                                choices = data.get('choices')
                                if isinstance(choices, list) and choices:
                                    delta = choices[0].get('delta', {})
                                    content_chunk = delta.get('content', '')
                                    if content_chunk:
                                        result_data["text"] += content_chunk
                            except json.JSONDecodeError:
                                continue

                def on_finished(req_id, status_code, reason, headers_json):
                    if req_id == request_id:
                        if status_code != 200:
                            result_data["error"] = f"翻译失败: {status_code} {reason}"
                        loop.quit()

                def on_failed(req_id, error):
                    if req_id == request_id:
                        result_data["error"] = f"翻译网络错误: {error}"
                        loop.quit()
                self.streamChunkReceived.connect(on_chunk)
                self.streamFinished.connect(on_finished)
                self.streamFailed.connect(on_failed)
                self.proxiedFetch(
                    request_id, f"{api_url}/chat/completions", json.dumps(options))
                loop.exec_()
                self.streamChunkReceived.disconnect(on_chunk)
                self.streamFinished.disconnect(on_finished)
                self.streamFailed.disconnect(on_failed)
                if result_data["error"]:
                    continue
                if result_data["text"]:
                    return result_data["text"]
                else:
                    continue
            except Exception as e:
                continue

    @pyqtSlot(result=str)
    def getModels(self):
        return json.dumps(self.model_manager.load_models(), ensure_ascii=False)

    @pyqtSlot(str)
    def saveModels(self, models_json):
        try:
            models_data = json.loads(models_json)
            self.model_manager.save_models(models_data)
        except Exception as e:
            print(f"Error saving AI models: {e}")

    @pyqtSlot(str, result=str)
    def getSetting(self, key):
        config = CONFIGER.read_config()
        return config.get(key, "")

    @pyqtSlot(str, str)
    def saveSetting(self, key, value):
        CONFIGER.revise_config(key, value)

    @pyqtSlot(str, 'QVariant')
    def saveHistory(self, first_message, conversation):
        try:
            return self.history_manager.save_history(first_message, conversation)
        except Exception as e:
            print(f"Error saving chat history: {e}")

    @pyqtSlot(result=str)
    def listHistories(self):
        try:
            histories = self.history_manager.list_histories()
            return json.dumps(histories, ensure_ascii=False)
        except Exception as e:
            print(f"Error listing chat histories: {e}")
            return "[]"

    @pyqtSlot(str, result=str)
    def loadHistory(self, filename):
        try:
            history = self.history_manager.load_history(filename)
            return json.dumps(history, ensure_ascii=False)
        except Exception as e:
            print(f"Error loading chat history: {e}")
            return "[]"

    @pyqtSlot(str, result=bool)
    def deleteHistory(self, filename):
        try:
            return self.history_manager.delete_history(filename)
        except Exception as e:
            print(f"Error deleting chat history: {e}")
            return False

    @pyqtSlot(result=str)
    def get_current_cwd(self):
        if not self.main_window:
            return json.dumps({"status": "error", "content": "Main window not available."}, ensure_ascii=False)
        active_widget = self.main_window.get_active_ssh_widget()
        if not active_widget:
            return json.dumps({"status": "error", "content": "No active SSH session found."}, ensure_ascii=False)
        if hasattr(active_widget, 'ssh_widget') and hasattr(active_widget.ssh_widget, 'bridge'):
            cwd = active_widget.ssh_widget.bridge.current_directory
            return json.dumps({"status": "success", "cwd": cwd}, ensure_ascii=False)
        else:
            return json.dumps({"status": "error", "content": "Could not find the terminal bridge."}, ensure_ascii=False)

    @pyqtSlot(result=str)
    def get_file_manager_cwd(self):
        if not self.main_window:
            return json.dumps({"status": "error", "content": "Main window not available."}, ensure_ascii=False)
        active_widget = self.main_window.get_active_ssh_widget()
        if not active_widget:
            return json.dumps({"status": "error", "content": "No active SSH session found."}, ensure_ascii=False)
        if hasattr(active_widget, 'file_explorer'):
            cwd = active_widget.file_explorer.path
            return json.dumps({"status": "success", "cwd": cwd}, ensure_ascii=False)
        else:
            return json.dumps({"status": "error", "content": "Could not find the file explorer."}, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def listFiles(self, cwd):
        if not self.main_window:
            return json.dumps({"status": "error", "content": "Main window not available."}, ensure_ascii=False)
        active_widget = self.main_window.get_active_ssh_widget()
        if not active_widget:
            return json.dumps({"status": "error", "content": "No active SSH session found."}, ensure_ascii=False)
        worker = None
        if hasattr(active_widget, 'ssh_widget') and hasattr(active_widget.ssh_widget, 'bridge'):
            worker = active_widget.ssh_widget.bridge.worker
        if not worker:
            return json.dumps({"status": "error", "content": "Could not find the SSH worker for the active session."}, ensure_ascii=False)
        import shlex
        safe_path = shlex.quote(str(cwd))
        command = f"cd {safe_path}; ls -Ap | grep -v /"
        output, error, exit_code = worker.execute_silent_command(command)
        if exit_code == 0:
            files = [line.strip()
                     for line in output.strip().split('\n') if line.strip()]
            return json.dumps({"status": "success", "files": files}, ensure_ascii=False)
        elif exit_code == 1 and not output.strip():
            return json.dumps({"status": "success", "files": []}, ensure_ascii=False)
        else:
            return json.dumps({"status": "error", "content": error, "exit_code": exit_code}, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def listDirs(self, path):
        if not self.main_window:
            return json.dumps({"status": "error", "content": "Main window not available."}, ensure_ascii=False)
        active_widget = self.main_window.get_active_ssh_widget()
        if not active_widget:
            return json.dumps({"status": "error", "content": "No active SSH session found."}, ensure_ascii=False)
        worker = None
        if hasattr(active_widget, 'ssh_widget') and hasattr(active_widget.ssh_widget, 'bridge'):
            worker = active_widget.ssh_widget.bridge.worker
        if not worker:
            return json.dumps({"status": "error", "content": "Could not find the SSH worker for the active session."}, ensure_ascii=False)
        import shlex
        safe_path = shlex.quote(str(path))
        command = f"cd {safe_path}; ls -Ap | grep /"
        output, error, exit_code = worker.execute_silent_command(command)
        if exit_code == 0:
            dirs = [line.strip().rstrip('/')
                    for line in output.strip().split('\n') if line.strip()]
            return json.dumps({"status": "success", "dirs": dirs}, ensure_ascii=False)
        elif exit_code == 1 and not output.strip():
            return json.dumps({"status": "success", "dirs": []}, ensure_ascii=False)
        else:
            return json.dumps({"status": "error", "content": error, "exit_code": exit_code}, ensure_ascii=False)

    @pyqtSlot(result=str)
    def get_system_info(self):
        if not self.main_window:
            return json.dumps({"status": "error", "content": "Main window not available."}, ensure_ascii=False)
        active_widget = self.main_window.get_active_ssh_widget()
        if not active_widget:
            return json.dumps({"status": "error", "content": "No active SSH session found."}, ensure_ascii=False)
        worker = None
        if hasattr(active_widget, 'ssh_widget') and hasattr(active_widget.ssh_widget, 'bridge'):
            worker = active_widget.ssh_widget.bridge.worker
        if not worker:
            return json.dumps({"status": "error", "content": "Could not find the SSH worker for the active session."}, ensure_ascii=False)
        command = (
            'echo "---HOSTNAME---"; hostname; '
            'echo "---USER---"; whoami; '
            'echo "---OS---"; uname -a; '
            'echo "---CPU---"; lscpu | grep "Model name:"'
        )
        output, error, exit_code = worker.execute_silent_command(command)
        # if exit_code != 0:
        #     return json.dumps({"status": "error", "content": error, "exit_code": exit_code}, ensure_ascii=False)
        info = {}
        try:
            parts = output.split('---')
            for i in range(1, len(parts), 2):
                key = parts[i].strip()
                value = parts[i+1].strip()
                if key == 'HOSTNAME':
                    info['hostname'] = value
                elif key == 'USER':
                    info['user'] = value
                elif key == 'OS':
                    info['os'] = value
                elif key == 'CPU':
                    info['cpu_model'] = value.replace(
                        'Model name:', '').strip()
        except Exception as e:
            return json.dumps({"status": "error", "content": f"Failed to parse system info: {e}\nRaw output:\n{output}"}, ensure_ascii=False)
        return json.dumps({"status": "success", "content": info}, ensure_ascii=False)

    @pyqtSlot(str)
    def cancelProxiedFetch(self, request_id):
        if request_id in self.active_requests:
            self.active_requests[request_id]['cancelled'] = True

    @pyqtSlot(str, str, str)
    def proxiedFetch(self, request_id, url, options_json):
        self.active_requests[request_id] = {'cancelled': False}

        def run():
            try:
                options = json.loads(options_json)
                proxy_config_str = self.getSetting("ai_chat_proxy")
                proxies = {}
                if proxy_config_str:
                    proxy_config = json.loads(proxy_config_str)
                    protocol = proxy_config.get("protocol")
                    host = proxy_config.get("host")
                    port = proxy_config.get("port")
                    username = proxy_config.get("username")
                    password = proxy_config.get("password")
                    if protocol and host and port:
                        auth = ""
                        if username and password:
                            auth = f"{username}:{password}@"
                        proxy_url = f"{protocol}://{auth}{host}:{port}"
                        if protocol.startswith('socks'):
                            proxy_scheme = 'socks5h' if protocol == 'socks5' else protocol
                            proxy_url = f"{proxy_scheme}://{auth}{host}:{port}"
                            proxies = {"http": proxy_url, "https": proxy_url}
                        else:
                            proxies = {"http": proxy_url, "https": proxy_url}
                headers = options.get('headers', {})
                body = options.get('body', None)
                method = options.get('method', 'GET')
                use_stream = options.get('stream', True)
                if use_stream:
                    with requests.request(method, url, headers=headers, data=body, stream=True, proxies=proxies, timeout=300) as r:
                        for chunk in r.iter_content(chunk_size=8192):
                            if self.active_requests.get(request_id, {}).get('cancelled'):
                                break
                            if chunk:
                                self.streamChunkReceived.emit(
                                    request_id, chunk.decode('utf-8', errors='ignore'))
                        if not self.active_requests.get(request_id, {}).get('cancelled'):
                            response_headers = dict(r.headers)
                            self.streamFinished.emit(
                                request_id, r.status_code, r.reason, json.dumps(response_headers))
                else:
                    r = requests.request(
                        method, url, headers=headers, data=body, proxies=proxies, timeout=300)
                    if not self.active_requests.get(request_id, {}).get('cancelled'):
                        self.streamChunkReceived.emit(request_id, r.text)
                        response_headers = dict(r.headers)
                        self.streamFinished.emit(
                            request_id, r.status_code, r.reason, json.dumps(response_headers))
            except Exception as e:
                if not self.active_requests.get(request_id, {}).get('cancelled'):
                    self.streamFailed.emit(request_id, str(e))
            finally:
                if request_id in self.active_requests:
                    del self.active_requests[request_id]
        thread = threading.Thread(target=run)
        thread.start()

    @pyqtSlot(QVariant, result=str)
    def getTokenUsage(self, messages_variant):
        if not self.tokenizer:
            return "?"
        messages = messages_variant
        if not isinstance(messages, list):
            return "0"
        total_tokens = 0
        for message in messages:
            content = message.get('content')
            if isinstance(content, str):
                total_tokens += len(self.tokenizer.encode(content).ids)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get('type') == 'text' and 'text' in part:
                        total_tokens += len(
                            self.tokenizer.encode(part['text']).ids)
        return str(total_tokens)

    @pyqtSlot(str, str)
    def setQQUserInfo(self, qq_name, qq_number):
        if (not qq_name or qq_name == '') and (not qq_number or qq_number == ''):
            return
        self.qq_name = qq_name
        self.qq_number = qq_number
        self.userinfo_got.emit(qq_name, qq_number)
        parent = self.parent()
        if parent:
            if hasattr(parent, 'browser') and parent.browser:
                js_code = f"setQQUserInfo({json.dumps(qq_name)}, {json.dumps(qq_number)});"
                parent.browser.page().runJavaScript(js_code)
            if hasattr(parent, 'destroy_qq_login_browser'):
                parent.destroy_qq_login_browser()

    @pyqtSlot(result=QVariant)
    def getQQUserInfo(self):
        return {"qq_name": self.qq_name, "qq_number": self.qq_number}

    @pyqtSlot(str, result=bool)
    def showFileDiff(self, args_str: str):
        from PyQt5.QtCore import QMetaObject, Qt, Q_RETURN_ARG, Q_ARG
        result = [False]

        def _execute():
            result[0] = self._do_show_diff_sync(args_str)
        QMetaObject.invokeMethod(self, "_execute_in_main_thread",
                                 Qt.BlockingQueuedConnection, Q_ARG(object, _execute))
        return result[0]

    @pyqtSlot(object)
    def _execute_in_main_thread(self, func):
        func()

    def _do_show_diff_sync(self, args_str: str):
        result = {'success': True}

        def _show_diff():
            try:
                path_match = re.search(
                    r'<path>(.*?)</path>', args_str, re.DOTALL)
                if not path_match:
                    print("Error: Missing <path> tag")
                    return
                file_path = path_match.group(1).strip()
                start_match = re.search(
                    r'<start_line>(-?\d+)</start_line>', args_str)
                end_match = re.search(
                    r'<end_line>(-?\d+)</end_line>', args_str)
                if not (start_match and end_match):
                    print("Error: Missing line number tags")
                    return
                start_line = int(start_match.group(1))
                end_line = int(end_match.group(1))
                replace_match = re.search(
                    r'<replace>(.*?)</replace>', args_str, re.DOTALL)
                if not replace_match:
                    print("Error: Missing <replace> tag")
                    return
                replace_block = replace_match.group(1)
                if start_line == -1 and end_line == -1:
                    if not self.main_window:
                        return
                    active_widget = self.main_window.get_active_ssh_widget()
                    if not active_widget or not hasattr(active_widget, 'diff_widget'):
                        return
                    if hasattr(active_widget, 'file_bar') and hasattr(active_widget.file_bar, 'pivot'):
                        active_widget.file_bar.pivot.items["diff"].show()
                        active_widget.file_bar.pivot.setCurrentItem('diff')
                    worker = None
                    if hasattr(active_widget, 'ssh_widget') and hasattr(active_widget.ssh_widget, 'bridge'):
                        worker = active_widget.ssh_widget.bridge.worker
                    if not worker:
                        print("Error: SSH worker not found")
                        return
                    safe_path = shlex.quote(file_path)
                    check_cmd = f"test -f {safe_path} && cat {safe_path} || echo ''"
                    existing_content, _, _ = worker.execute_silent_command(
                        check_cmd)
                    new_content = replace_block.strip() if replace_block.strip() else ""
                    active_widget.diff_widget.set_left_content(
                        existing_content if existing_content else "")
                    active_widget.diff_widget.set_right_content(new_content)
                    if hasattr(active_widget.diff_widget, 'left_label'):
                        label_text = f"原内容:{file_path}" if existing_content else f"新建文件:{file_path}"
                        active_widget.diff_widget.left_label.setText(
                            label_text)
                    if hasattr(active_widget.diff_widget, 'right_label'):
                        active_widget.diff_widget.right_label.setText(
                            f"新内容:{file_path}")
                    active_widget.diff_widget.compare_diff()
                    result['success'] = True
                    return
                original_match = re.search(
                    r'<originalcontent>(.*?)</originalcontent>', args_str, re.DOTALL)
                if not original_match:
                    print("Error: Missing <originalcontent> tag")
                    return
                original_block = original_match.group(1)
                if not self.main_window:
                    return
                active_widget = self.main_window.get_active_ssh_widget()
                if not active_widget or not hasattr(active_widget, 'diff_widget'):
                    return
                worker = None
                if hasattr(active_widget, 'ssh_widget') and hasattr(active_widget.ssh_widget, 'bridge'):
                    worker = active_widget.ssh_widget.bridge.worker
                if not worker:
                    print("Error: SSH worker not found")
                    return
                safe_path = shlex.quote(file_path)
                file_size_cmd = f"stat -c%s {safe_path} 2>/dev/null || stat -f%z {safe_path} 2>/dev/null"
                size_output, size_error, size_exit_code = worker.execute_silent_command(
                    file_size_cmd)
                if size_exit_code == 0:
                    try:
                        file_size = int(size_output.strip())
                        if file_size > 1048576:
                            print(f"文件大小超过1MB({file_size} bytes),跳过diff检测")
                            return
                    except ValueError:
                        print(f"无法解析文件大小: {size_output}")
                        return
                read_file_handler = None
                if hasattr(self.mcp_manager, 'tools') and 'Linux终端' in self.mcp_manager.tools:
                    read_file_handler = self.mcp_manager.tools['Linux终端'].get(
                        'read_file', {}).get('handler')
                if not read_file_handler:
                    print("Error: read_file handler not found")
                    return
                remote_content_result = read_file_handler([file_path])
                try:
                    remote_data = json.loads(remote_content_result)
                    if remote_data.get("status") == "error":
                        print(
                            f"Error reading file: {remote_data.get('content')}")
                        return
                    remote_full_content = remote_data.get("content", "")
                except (json.JSONDecodeError, AttributeError):
                    remote_full_content = remote_content_result
                remote_full_content = remote_full_content.replace('\r', '')
                lines = remote_full_content.splitlines(True)
                if not (1 <= start_line <= end_line <= len(lines)):
                    print(
                        f"Error: Line numbers out of bounds. File has {len(lines)} lines.")
                    return
                actual_block = "".join(lines[start_line - 1:end_line])
                search_block_stripped = original_block.strip()
                actual_block_stripped = actual_block.strip()
                if actual_block_stripped != search_block_stripped:
                    print(
                        f"Error: Content verification failed. Expected:\n{search_block_stripped}\n\nActual:\n{actual_block_stripped}")
                    return
                if hasattr(active_widget, 'file_bar') and hasattr(active_widget.file_bar, 'pivot'):
                    active_widget.file_bar.pivot.items["diff"].show()
                    active_widget.file_bar.pivot.setCurrentItem('diff')
                leading_whitespace = ""
                if start_line <= len(lines):
                    first_line_of_block = lines[start_line - 1]
                    leading_whitespace = first_line_of_block[:len(
                        first_line_of_block) - len(first_line_of_block.lstrip())]
                original_last_line = lines[end_line - 1]
                line_ending = '\n'
                if original_last_line.endswith('\r\n'):
                    line_ending = '\r\n'
                new_content_parts = []
                if replace_block and not replace_block.isspace():
                    replace_lines = replace_block.rstrip('\n\r').splitlines()
                    new_content_parts = [
                        leading_whitespace + line + line_ending for line in replace_lines]
                modified_lines = lines[:start_line - 1] + \
                    new_content_parts + lines[end_line:]
                modified_full_content = "".join(modified_lines)
                active_widget.diff_widget.set_left_content(remote_full_content)
                active_widget.diff_widget.set_right_content(
                    modified_full_content)
                if hasattr(active_widget.diff_widget, 'left_label'):
                    active_widget.diff_widget.left_label.setText(
                        f"原内容:{file_path}")
                if hasattr(active_widget.diff_widget, 'right_label'):
                    active_widget.diff_widget.right_label.setText(
                        f"修改后:{file_path}")
                active_widget.diff_widget.compare_diff()
                result['success'] = True
            except Exception as e:
                print(f"Error showing diff: {e}")
                import traceback
                traceback.print_exc()
        _show_diff()
        return result['success']


class AiChatWidget(QWidget):

    def qqLoginUrlBrowser(self):
        from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings
        from PyQt5.QtWebChannel import QWebChannel
        qqLoginUrl = "https://xui.ptlogin2.qq.com/cgi-bin/xlogin?pt_disable_pwd=1&appid=715030901&hide_close_icon=0&daid=73&pt_no_auth=1&s_url=https%3A%2F%2Fqun.qq.com%2F"
        self.qq_login_browser = QWebEngineView(self)
        self.qq_login_browser.hide()
        self.qq_login_browser.page().setWebChannel(self.channel)
        self.qq_login_browser.settings().setAttribute(
            QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        self.qq_login_browser.settings().setAttribute(
            QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        self.qq_login_browser.setContextMenuPolicy(Qt.NoContextMenu)
        self.qq_login_browser.resize(1024, 768)
        self.qq_login_browser.setUrl(QUrl(qqLoginUrl))
        try:
            def on_load(ok):
                if not ok:
                    return
                qq_login_js_path = os.path.join(os.path.dirname(
                    __file__), '..', 'resource', 'widget', 'ai_chat', 'qq_login.js')
                with open(qq_login_js_path, 'r', encoding='utf-8') as f:
                    qq_login_js_code = f.read()
                injection_js = f"""
                    new Promise((resolve, reject) => {{
                        const script = document.createElement('script');
                        script.src = 'qrc:///qtwebchannel/qwebchannel.js';
                        script.onload = () => {{
                            new QWebChannel(qt.webChannelTransport, function (channel) {{
                                window.backend = channel.objects.backend;
                                resolve();
                            }});
                        }};
                        script.onerror = () => {{
                            reject(new Error('Failed to load qwebchannel.js'));
                        }};
                        document.head.appendChild(script);
                    }}).then(() => {{
                        {qq_login_js_code}
                    }}).catch(console.error);"""
                self.qq_login_browser.page().runJavaScript(injection_js)
            self.qq_login_browser.page().loadFinished.connect(on_load)
        except Exception as e:
            pass

    def __init__(self, parent=None, main_window: 'Window' = None):
        super().__init__(parent)
        self.tab_id = None
        self._side_panel = None
        self.qq_login_browser = None
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)
        self.browser = None
        if CONFIGER.read_config().get("right_panel_ai_chat", True):
            from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings
            from PyQt5.QtWebChannel import QWebChannel
            self.channel = QWebChannel()
            self.bridge = AIBridge(self, main_window=main_window)
            self.channel.registerObject('backend', self.bridge)
            self.browser = QWebEngineView()
            self.browser.page().setWebChannel(self.channel)
            self.browser.settings().setAttribute(
                QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
            self.browser.settings().setAttribute(
                QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            self.browser.setContextMenuPolicy(Qt.NoContextMenu)
            self.layout.addWidget(self.browser)
            project_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..'))
            index_html_path = os.path.join(
                project_root, 'resource', 'widget', 'ai_chat', 'index.html')
            self.browser.setUrl(QUrl.fromLocalFile(index_html_path))

            self.qqLoginUrlBrowser()
        else:
            self.layout.setAlignment(Qt.AlignCenter)
            icon_label = QLabel()
            icon_path = os.path.abspath(os.path.join(os.path.dirname(
                __file__), '..', 'resource', 'icons', 'ai_disabled.svg'))
            renderer = QSvgRenderer(icon_path)
            pixmap = QPixmap(128, 128)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            icon_label.setPixmap(pixmap)
            icon_label.setAlignment(Qt.AlignCenter)
            self.layout.addWidget(icon_label)
            disabled_label = QLabel(self.tr("AI对话已经禁用,请开启选项后重启程序."))
            disabled_label.setAlignment(Qt.AlignCenter)
            disabled_label.setWordWrap(True)
            self.layout.addWidget(disabled_label)

    def keyPressEvent(self, event: QKeyEvent):
        if self.browser and event.key() == Qt.Key_F5:
            self.browser.reload()
        elif event.key() == Qt.Key_F12:
            if os.environ.get('QTWEBENGINE_REMOTE_DEBUGGING'):
                QDesktopServices.openUrl(
                    QUrl("http://localhost:" + str(os.environ['QTWEBENGINE_REMOTE_DEBUGGING'])))
        else:
            super().keyPressEvent(event)

    def set_tab_id(self, tab_id):
        self.tab_id = tab_id

    def _find_side_panel(self):
        if self._side_panel:
            return self._side_panel
        parent = self.parent()
        while parent is not None:
            if parent.metaObject().className() == "SidePanelWidget":
                self._side_panel = parent
                return self._side_panel
            parent = parent.parent()
        return None

    def get_tab_data(self):
        side_panel = self._find_side_panel()
        if side_panel:
            tab_data = side_panel.get_tab_data_by_uuid(self.tab_id)
            return tab_data
        return None

    def destroy_qq_login_browser(self):
        if self.qq_login_browser:
            self.qq_login_browser.deleteLater()
            self.qq_login_browser = None
