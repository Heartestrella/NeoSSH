# remote_file_manage.py
from PyQt5.QtCore import pyqtSignal, QThread, QMutex, QWaitCondition, QThreadPool, QTimer, QEventLoop
from tools.transfer_worker import TransferWorker
from tools.setting_config import SCM
import paramiko
import traceback
import socks
from typing import Dict, List, Optional
import stat
import os
from typing import Tuple
from datetime import datetime
import shlex
from PyQt5.QtCore import Qt
from functools import partial
import time
from tools.session_manager import Session


class RemoteFileManager(QThread):
    """
    Remote file manager, responsible for building and maintaining remote file trees
    """
    permission_finished = pyqtSignal(
        str, int, bool, str)  # file_path, permission_num, success, error_msg
    # file_path, permission_num, success, error_msg
    permission_got = pyqtSignal(str, int, bool, str)
    kill_finished = pyqtSignal(int, bool, str)
    file_tree_updated = pyqtSignal(dict, str)  # file tree , path
    error_occurred = pyqtSignal(str)
    sftp_ready = pyqtSignal()
    upload_progress = pyqtSignal(str, int, int, int)
    download_progress = pyqtSignal(str, int, int, int)
    # File path, success, error message
    upload_finished = pyqtSignal(str, bool, str)
    # Path, success, error message
    delete_finished = pyqtSignal(str, bool, str)
    list_dir_finished = pyqtSignal(str, list)  # path, result
    # path, result (e.g. "directory"/"file"/False)
    path_check_result = pyqtSignal(str, object)
    # remote_path , local_path , status , error msg,open it
    download_finished = pyqtSignal(str, str, bool, str, bool)
    # source_path, target_path, status, error msg
    copy_finished = pyqtSignal(str, str, bool, str)
    # Original path, new path, success, error message
    rename_finished = pyqtSignal(str, str, bool, str)
    # path, info(dict), status(bool), error_msg(str)
    file_info_ready = pyqtSignal(str, dict, bool, str)
    # path , type
    file_type_ready = pyqtSignal(str, str)
    # path , status , error_msg
    mkdir_finished = pyqtSignal(str, bool, str)
    # path, success, error_message
    mkfile_finished = pyqtSignal(str, bool, str)
    # target_zip_path
    start_to_compression = pyqtSignal(str)
    # remote_path_path
    start_to_uncompression = pyqtSignal(str)
    compression_finished = pyqtSignal(str, str)

    def __init__(self, session_info, parent=None, child_key=None, jumpbox=None):
        super().__init__(parent)
        self.session_info = session_info
        self.host = session_info.host
        self.user = session_info.username
        self.password = session_info.password
        self.port = session_info.port
        self.auth_type = session_info.auth_type
        self.key_path = session_info.key_path
        self.jumpbox = jumpbox
        self.proxy_type = getattr(session_info, 'proxy_type', 'None')
        self.proxy_host = getattr(session_info, 'proxy_host', '')
        self.proxy_port = getattr(session_info, 'proxy_port', 0)
        self.proxy_username = getattr(session_info, 'proxy_username', '')
        self.proxy_password = getattr(session_info, 'proxy_password', '')
        # self.heart_timer = QTimer()
        # self.heart_timer.timeout.connect(self.keep_heartbeat)
        self.conn = None
        self.sftp = None
        self.upload_conn = None
        self.download_conn = None

        # File_tree
        self.file_tree: Dict = {}

        # UID/GID Caching
        self.uid_map: Dict[int, str] = {}
        self.gid_map: Dict[int, str] = {}

        # Thread Control
        self.mutex = QMutex()
        self.condition = QWaitCondition()
        self._is_running = True
        self._tasks = []

        # Thread pool for handling concurrent transfers
        self.thread_pool = QThreadPool()
        config = SCM().read_config()
        max_threads = config.get("max_concurrent_transfers", 4)
        self.thread_pool.setMaxThreadCount(max_threads)
        self.active_workers = {}  # To track active TransferWorker instances

    # ---------------------------
    # Main thread loop
    # ---------------------------
    def _create_socket(self):
        if self.proxy_type == 'None' or not self.proxy_host or not self.proxy_port:
            return None
        sock = socks.socksocket()
        sock.settimeout(15)
        proxy_type_map = {
            'HTTP': socks.HTTP,
            'SOCKS4': socks.SOCKS4,
            'SOCKS5': socks.SOCKS5
        }
        proxy_type = proxy_type_map.get(self.proxy_type)
        if not proxy_type:
            return None
        use_remote_dns = self.proxy_type in ['SOCKS4', 'SOCKS5']
        sock.set_proxy(
            proxy_type=proxy_type,
            addr=self.proxy_host,
            port=self.proxy_port,
            rdns=use_remote_dns,
            username=self.proxy_username if self.proxy_username else None,
            password=self.proxy_password if self.proxy_password else None
        )
        try:
            sock.connect((self.host, self.port))
            return sock
        except Exception as e:
            raise e

    def _create_ssh_connection(self):
        """Helper function to create and configure an SSH connection with jumpbox support."""
        conn = paramiko.SSHClient()
        conn.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        sock = self._create_socket()

        if isinstance(self.jumpbox, Session):
            jumpbox_conn = paramiko.SSHClient()
            jumpbox_conn.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            host = self.jumpbox.host
            user = self.jumpbox.username
            port = self.jumpbox.port
            password = self.jumpbox.password
            auth_type = self.jumpbox.auth_type
            key_path = self.jumpbox.key_path

            print(f"🔗 连接到跳板机: {user}@{host}:{port}")

            if auth_type == "password":
                jumpbox_conn.connect(
                    host, port, user, password,
                    timeout=30, banner_timeout=30, sock=sock
                )
            else:
                jumpbox_conn.connect(
                    host, port, user, key_filename=key_path,
                    timeout=30, banner_timeout=30, sock=sock
                )

            print("✅ 跳板机连接成功")

            print(f"🔄 创建到目标服务器 {self.host}:{self.port} 的隧道")
            jumpbox_transport = jumpbox_conn.get_transport()
            dest_addr = (self.host, self.port)
            jumpbox_channel = jumpbox_transport.open_channel(
                kind="direct-tcpip",
                dest_addr=dest_addr,
                src_addr=(host, port)
            )

            print("✅ 隧道创建成功")

            print(f"🔗 通过隧道连接到目标服务器: {self.user}@{self.host}:{self.port}")
            try:
                if self.auth_type == "password":
                    conn.connect(
                        self.host,
                        port=self.port,
                        username=self.user,
                        password=self.password,
                        timeout=30,
                        banner_timeout=30,
                        sock=jumpbox_channel
                    )
                else:
                    conn.connect(
                        self.host,
                        port=self.port,
                        username=self.user,
                        key_filename=self.key_path,
                        timeout=30,
                        banner_timeout=30,
                        sock=jumpbox_channel
                    )
                print("✅ 目标服务器连接成功")

            except Exception as e:
                self.error_occurred.emit(e)
                jumpbox_conn.close()
                raise e

            self.jumpbox_conn = jumpbox_conn

        else:
            print(f"🔗 直接连接到服务器: {self.user}@{self.host}:{self.port}")
            if self.auth_type == "password":
                conn.connect(
                    self.host,
                    port=self.port,
                    username=self.user,
                    password=self.password,
                    timeout=30,
                    banner_timeout=30,
                    sock=sock
                )
            else:
                conn.connect(
                    self.host,
                    port=self.port,
                    username=self.user,
                    key_filename=self.key_path,
                    timeout=30,
                    banner_timeout=30,
                    sock=sock
                )
            print("✅ 直接连接成功")

        transport = conn.get_transport()
        transport.set_keepalive(30)

        # self.heart_timer.start(5000)
        return conn

    def run(self):
        try:
            # Create all three connections at the start
            self.conn = self._create_ssh_connection()
            # self.upload_conn = self._create_ssh_connection()
            # self.download_conn = self._create_ssh_connection()

            self.sftp = self.conn.open_sftp()
            self.sftp_ready.emit()
            self._fetch_user_group_maps()
            while self._is_running:
                self.mutex.lock()
                if not self._tasks:
                    self.condition.wait(self.mutex)
                if self._tasks:
                    task = self._tasks.pop(0)
                    self.mutex.unlock()
                    try:
                        ttype = task.get('type')
                        if ttype == 'add_path':
                            self._add_path_to_tree(
                                task['path'], task["update_tree_sign"])
                        elif ttype == 'kill_process':
                            self._handle_kill_task(
                                task['pid'], task.get('callback'))
                        elif ttype == 'remove_path':
                            self._remove_path_from_tree(task['path'])
                        elif ttype == 'refresh':
                            self._refresh_paths_impl(task.get('paths'))
                        elif ttype == 'upload_file':
                            self._dispatch_transfer_task(
                                'upload',
                                task['local_path'],
                                task['remote_path'],
                                task['compression'],
                                task_id=task.get('task_id')
                            )
                        elif ttype == 'delete':
                            self._handle_delete_task(
                                task['path'],
                                task.get('callback')
                            )
                        elif ttype == "download_files":
                            self._dispatch_transfer_task(
                                'download',
                                None,  # local_path is not used for download tasks
                                task['path'],
                                task["compression"],
                                open_it=task["open_it"],
                                session_id=task.get("session_id")
                            )
                        elif ttype == 'list_dir':
                            # print(f"Handle:{[task['path']]}")
                            result = self.list_dir_detailed(task['path'])
                            # print(f"List dir : {result}")
                            self.list_dir_finished.emit(
                                task['path'], result or [])
                        elif ttype == 'check_path':
                            path_to_check = task['path']
                            try:
                                res = self.check_path_type(
                                    path_to_check)
                            except Exception as e:
                                res = False
                            self.path_check_result.emit(path_to_check, res)
                        elif ttype == 'copy_to':
                            self._handle_copy_task(
                                task['source_path'],
                                task['target_path'],
                                task.get('cut', False)
                            )
                        elif ttype == 'set_permissions':
                            self._handle_permission_task(
                                task['file_path'],
                                task['permission_num']
                            )
                        elif ttype == 'get_permissions':
                            self._handle_get_permission_task(task['file_path'])

                        elif ttype == 'rename':
                            self._handle_rename_task(
                                task['path'],
                                task['new_name'],
                                task.get('callback')
                            )
                        elif ttype == 'file_info':
                            path, info_dict, status, error_msg = self._get_file_info(
                                task['path'])
                            self.file_info_ready.emit(
                                path, info_dict, status, error_msg)
                        elif ttype == 'file_type':
                            self.classify_file_type_using_file(task['path'])
                        elif ttype == 'mkdir':
                            self._handle_mkdir_task(
                                task['path'], task.get('callback'))
                        elif ttype == "mkfile":
                            self._handle_mkfile_task(
                                task["path"], task.get('callback')
                            )
                        else:
                            print(f"Unknown task type: {ttype}")
                    except Exception as e:
                        tb = traceback.format_exc()
                        self.error_occurred.emit(
                            f"Error while executing task: {e}\n{tb}")
                else:
                    self.mutex.unlock()

        except Exception as e:
            tb = traceback.format_exc()
            self.error_occurred.emit(f"Remote File Manager Error: {e}\n{tb}")
        finally:
            self._cleanup()

    # ---------------------------
    # Thread Control & Cleanup
    # ---------------------------
    def stop(self):
        self._is_running = False
        self.condition.wakeAll()
        self.wait()

    def _cleanup(self):
        try:
            if self.sftp:
                self.sftp.close()
        except Exception:
            pass
        try:
            if self.conn:
                self.conn.close()
            # if self.upload_conn:
            #     self.upload_conn.close()
            # if self.download_conn:
            #     self.download_conn.close()
        except Exception:
            pass

    # ---------------------------
    # Transfer Worker Management
    # ---------------------------
        # try:
        #     signals = [
        #         'file_tree_updated', 'error_occurred', 'sftp_ready', 'upload_progress',
        #         'upload_finished', 'delete_finished', 'list_dir_finished', 'path_check_result',
        #         'download_finished', 'copy_finished', 'rename_finished', 'file_info_ready',
        #         'file_type_ready', 'mkdir_finished', 'start_to_compression', 'start_to_uncompression'
        #     ]
        #     for sig_name in signals:
        #         sig = getattr(self, sig_name, None)
        #         if sig:
        #             try:
        #                 sig.disconnect()
        #             except Exception:
        #                 pass
        # except Exception:
        #     pass
        try:
            if self.isRunning():
                self.quit()
                # self.wait(2000)
        except Exception:
            pass

    def _dispatch_transfer_task(self, action, local_path, remote_path, compression, open_it=False, task_id=None, session_id=None):
        """Creates and starts TransferWorker(s) for uploads or downloads."""
        if action == 'upload':
            self._dispatch_upload_task(
                local_path, remote_path, compression, open_it, task_id=task_id)
        elif action == 'download':
            self._dispatch_download_task(
                remote_path, compression, open_it, session_id=session_id)

    def _dispatch_upload_task(self, local_path, remote_path, compression, open_it, task_id=None):
        """Handles dispatching of upload tasks, expanding directories if necessary."""
        # If compression is on and we have a list of paths, treat it as a single batch job.
        if compression and isinstance(local_path, list):
            # self._create_and_start_worker(
            #     'upload', self.upload_conn, local_path, remote_path, compression, open_it, task_id=task_id)
            self._create_and_start_worker(
                'upload', self.conn, local_path, remote_path, compression, open_it, task_id=task_id)
            return

        # Fallback to original logic for single items or non-compressed lists.
        paths_to_process = local_path if isinstance(
            local_path, list) else [local_path]

        for path_item in paths_to_process:
            is_dir = os.path.isdir(path_item)

            if is_dir and not compression:
                # Expand directory into a list of files for individual upload
                all_files = self._list_local_files_recursive(path_item)
                for file_path in all_files:
                    # For each file, we pass the original directory as 'context'
                    # self._create_and_start_worker(
                    #     'upload', self.upload_conn, file_path, remote_path, compression, open_it, upload_context=path_item)
                    self._create_and_start_worker(
                        'upload', self.conn, file_path, remote_path, compression, open_it, upload_context=path_item)
            else:
                # It's a single file, a list of files, or a compressed directory
                # self._create_and_start_worker(
                #     'upload', self.upload_conn, path_item, remote_path, compression, open_it)
                self._create_and_start_worker(
                    'upload', self.conn, path_item, remote_path, compression, open_it)

    def _dispatch_download_task(self, remote_path, compression, open_it, session_id=None):
        """Handles dispatching of download tasks, expanding directories if necessary."""
        paths_to_process = remote_path if isinstance(
            remote_path, list) else [remote_path]
        print(f"paths_to_process : {paths_to_process}")
        if compression:
            # compression all files to a tar
            # self._create_and_start_worker(
            #     'download', self.download_conn, None, paths_to_process, compression, open_it, session_id=session_id)
            self._create_and_start_worker(
                'download', self.conn, None, paths_to_process, compression, open_it, session_id=session_id)
        else:
            for path_item in paths_to_process:
                print(f"非压缩下载 {path_item}")
                is_dir = self.check_path_type(path_item) == "directory"

                if is_dir:
                    # Expand directory into a list of files for individual download
                    all_files, dirs_to_create = self._list_remote_files_recursive(
                        path_item)
                    for file_path in all_files:
                        # For each file, we pass the original directory as 'context'
                        print(f"添加 {file_path} 到任务")
                        # self._create_and_start_worker(
                        #     'download', self.download_conn, None, file_path, compression, open_it, download_context=path_item, session_id=session_id)
                        self._create_and_start_worker(
                            'download', self.conn, None, file_path, compression, open_it, download_context=path_item, session_id=session_id)
                else:
                    # It's a single file, a list of files, or a compressed directory
                    # self._create_and_start_worker(
                    #     'download', self.download_conn, None, path_item, compression, open_it, session_id=session_id)
                    self._create_and_start_worker(
                        'download', self.conn, None, path_item, compression, open_it, session_id=session_id)

    def _list_remote_files_recursive(self, remote_path):
        """Recursively lists all files in a remote directory. Returns a tuple of (file_paths, dir_paths)."""
        file_paths = []
        dir_paths = [remote_path]

        items_to_scan = [remote_path]

        while items_to_scan:
            current_path = items_to_scan.pop(0)
            try:
                for attr in self.sftp.listdir_attr(current_path):
                    full_path = f"{current_path.rstrip('/')}/{attr.filename}"
                    if stat.S_ISDIR(attr.st_mode):
                        dir_paths.append(full_path)
                        items_to_scan.append(full_path)
                    else:
                        file_paths.append(full_path)
            except Exception as e:
                print(f"Error listing remote directory {current_path}: {e}")

        return file_paths, dir_paths

    def _list_local_files_recursive(self, local_path):
        """Recursively lists all files in a local directory."""
        file_paths = []
        for root, _, files in os.walk(local_path):
            for file in files:
                file_paths.append(os.path.join(root, file))
        return file_paths

    def _create_and_start_worker(self, action, connection, local_path, remote_path, compression, open_it=False, download_context=None, upload_context=None, task_id=None, session_id=None):
        """Helper to create, connect signals, and start a single TransferWorker."""
        worker = TransferWorker(
            connection,
            action,
            local_path,
            remote_path,
            compression,
            download_context,
            upload_context,
            task_id,
            session_id
        )

        # Store open_it parameter in worker for download callback
        if action == 'download':
            worker._open_it = open_it

        if action == 'upload':
            worker.signals.finished.connect(self.upload_finished)
            # Refresh the parent directory of the remote path upon successful upload.
            worker.signals.finished.connect(
                lambda path, success, msg: self.refresh_paths(
                    [os.path.dirname(remote_path.rstrip('/'))]) if success and remote_path else None
            )
            worker.signals.progress.connect(self.upload_progress)
            worker.signals.start_to_compression.connect(
                self.start_to_compression)
            worker.signals.start_to_uncompression.connect(
                self.start_to_uncompression)
            worker.signals.compression_finished.connect(
                self.compression_finished)

        elif action == 'download':
            # Create callback function for download completion
            def emit_download_finished(identifier, success, msg):
                """Emit download finished signal with proper parameters"""
                self.download_finished.emit(
                    identifier,
                    msg if success else "",
                    success,
                    "" if success else msg,
                    worker._open_it
                )
            worker._download_callback = emit_download_finished
            worker.signals.progress.connect(
                self.download_progress, Qt.QueuedConnection)
            worker.signals.compression_finished.connect(
                self.compression_finished)
            worker.signals.start_to_compression.connect(
                self.start_to_compression)
            worker.signals.start_to_uncompression.connect(
                self.start_to_uncompression)

        self.thread_pool.start(worker)

        # Track the worker
        if task_id:
            identifier = task_id
        else:
            identifier = str(
                local_path if action == 'upload' else remote_path)
        self.active_workers[identifier] = worker

    # ---------------------------
    # Public task API
    # ---------------------------

    def cancel_transfer(self, identifier: str):
        """Cancels an active transfer task."""
        worker = self.active_workers.pop(identifier, None)
        print(worker)
        if worker:
            print('stop loading')
            worker.stop()

    def mkdir(self, path: str, callback=None):
        self.mutex.lock()
        self._tasks.append({
            'type': 'mkdir',
            'path': path,
            "callback": callback,
        })
        self.condition.wakeAll()
        self.mutex.unlock()

    def mkfile(self, path: str, callback=None):
        self.mutex.lock()
        self._tasks.append({
            'type': 'mkfile',
            'path': path,
            "callback": callback,
        })
        self.condition.wakeAll()
        self.mutex.unlock()

    def get_file_type(self, path: str):
        self.mutex.lock()
        self._tasks.append({'type': 'file_type', 'path': path})
        self.condition.wakeAll()
        self.mutex.unlock()

    def get_file_info(self, path: str):
        """
        The result is sent via the file_info_ready signal.
        """
        self.mutex.lock()
        self._tasks.append({'type': 'file_info', 'path': path})
        self.condition.wakeAll()
        self.mutex.unlock()

    def set_permissions(self, file_path: str, permission_num: int):
        """
        Asynchronously sets permissions for a remote file or directory using chmod numeric mode.

        This method queues a permission setting task to be executed in the background.
        When the operation is complete, the `permission_finished` signal is emitted.

        Args:
            file_path (str): The path of the file or directory to set permissions for.
            permission_num (int): The chmod numeric permission value (e.g., 755, 644).

        Signals:
            permission_finished (str, int, bool, str): Emitted upon completion with parameters:
                - file_path (str): The file path.
                - permission_num (int): The requested permission value.
                - success (bool): True if the operation succeeded, False otherwise.
                - error_msg (str): Error message if the operation failed, empty string otherwise.
        """
        self.mutex.lock()
        self._tasks.append({
            'type': 'set_permissions',
            'file_path': file_path,
            'permission_num': permission_num
        })
        self.condition.wakeAll()
        self.mutex.unlock()

    def get_permissions(self, file_path: str):
        """
        Asynchronously gets permissions for a remote file or directory.

        Args:
            file_path (str): The path of the file or directory to get permissions for.

        Signals:
            permission_got (str, int, bool, str): Emitted upon completion with parameters:
                - file_path (str): The file path.
                - permission_num (int): The current permission value in numeric format.
                - success (bool): True if the operation succeeded, False otherwise.
                - error_msg (str): Error message if the operation failed, empty string otherwise.
        """
        self.mutex.lock()
        self._tasks.append({
            'type': 'get_permissions',
            'file_path': file_path
        })
        self.condition.wakeAll()
        self.mutex.unlock()

    def copy_to(self, source_path: str, target_path: str, cut: bool = False):
        """
    Asynchronously copies or moves a remote file or directory.

    This method queues a copy or move task to be executed in the background.
    When the operation is complete, the `copy_finished` signal is emitted.

    Args:
        source_path (str): The source path of the file or directory to copy/move.
        target_path (str): The destination path where the file or directory will be copied/moved.
        cut (bool, optional): If True, moves the file or directory (deletes the source after copying).
                              If False, copies the file or directory without deleting the source.
                              Defaults to False.

    Signals:
        copy_finished (str, str, bool, str): Emitted upon completion with parameters:
            - source_path (str): The original source path.
            - target_path (str): The target path.
            - success (bool): True if the operation succeeded, False otherwise.
            - error_msg (str): Error message if the operation failed, empty string otherwise.
        """
        self.mutex.lock()
        self._tasks.append({
            'type': 'copy_to',
            'source_path': source_path,
            'target_path': target_path,
            'cut': cut
        })
        self.condition.wakeAll()
        self.mutex.unlock()

    def kill_process(self, pid: int, callback=None):
        """
        Asynchronously kills a remote process by PID.

        This method queues a kill task to be executed in the background.
        Upon completion, the `kill_finished` signal is emitted.

        Args:
            pid (int): The PID of the process to kill.
            callback (callable, optional): A function to be called when the kill
                is complete. The callback receives two arguments:
                - success (bool): True if kill succeeded, False otherwise.
                - error_msg (str): Error message if kill failed, empty string otherwise.

        Signals:
            kill_finished (int, bool, str): Emitted upon completion with parameters:
                - pid (int): The PID that was killed.
                - success (bool): True if kill succeeded, False otherwise.
                - error_msg (str): Error message if kill failed, empty string otherwise.
        """
        self.mutex.lock()
        self._tasks.append({
            'type': 'kill_process',
            'pid': pid,
            'callback': callback
        })
        self.condition.wakeAll()
        self.mutex.unlock()

    def delete_path(self, path, callback=None):
        """
        Asynchronously deletes a remote file or directory.

        This method queues a delete task to be executed in the background.
        Upon completion, the `delete_finished` signal is emitted.

        Args:
            path (str): The remote path of the file or directory to delete.
            callback (callable, optional): A function to be called when the deletion
                is complete. The callback receives two arguments:
                - success (bool): True if deletion succeeded, False otherwise.
                - error_msg (str): Error message if deletion failed, empty string otherwise.

        Signals:
            delete_finished (str, bool, str): Emitted upon completion with parameters:
                - path (str): The path that was deleted.
                - success (bool): True if deletion succeeded, False otherwise.
                - error_msg (str): Error message if deletion failed, empty string otherwise.
        """

        self.mutex.lock()
        self._tasks.append({
            'type': 'delete',
            'path': path,
            'callback': callback
        })
        self.condition.wakeAll()
        self.mutex.unlock()

    def add_path(self, path: str, update_tree_sign=True):
        self.mutex.lock()
        self._tasks.append({'type': 'add_path', 'path': path,
                           "update_tree_sign": update_tree_sign})
        self.condition.wakeAll()
        self.mutex.unlock()

    def remove_path(self, path: str):
        self.mutex.lock()
        self._tasks.append({'type': 'remove_path', 'path': path})
        self.condition.wakeAll()
        self.mutex.unlock()

    def refresh_paths(self, paths: Optional[List[str]] = None):
        """Refresh the specified path or all directories if paths is None"""
        self.mutex.lock()
        self._tasks.append({'type': 'refresh', 'paths': paths})
        self.condition.wakeAll()
        self.mutex.unlock()

    def check_path_async(self, path: str):
        self.mutex.lock()
        self._tasks.append({'type': 'check_path', 'path': path})
        self.condition.wakeAll()
        self.mutex.unlock()

    def list_dir_async(self, path: str):
        """List a directory"""
        self.mutex.lock()
        if any(t.get('type') == 'list_dir' and t.get('path') == path for t in self._tasks):
            self.mutex.unlock()
            return
        self._tasks.append({'type': 'list_dir', 'path': path})
        self.condition.wakeAll()
        self.mutex.unlock()

    def download_path_async(self, path: str, open_it: bool = False, compression=False, session_id: str = None):
        self.mutex.lock()
        self._tasks.append(
            {'type': 'download_files', 'path': path, "open_it": open_it, "compression": compression, "session_id": session_id})
        self.condition.wakeAll()
        self.mutex.unlock()

    def rename(self, path: str, new_name: str, callback=None):
        """
        Asynchronously renames a remote file or directory.

        This method queues a rename task to be executed in the background.
        Upon completion, the `rename_finished` signal is emitted.

        Args:
            path (str): The remote path of the file or directory to rename.
            new_name (str): The new name for the file or directory.
            callback (callable, optional): A function to be called when the rename
                is complete. The callback receives two arguments:
                - success (bool): True if rename succeeded, False otherwise.
                - error_msg (str): Error message if rename failed, empty string otherwise.

        Signals:
            rename_finished (str, str, bool, str): Emitted upon completion with parameters:
                - original_path (str): The original path.
                - new_path (str): The new path after renaming.
                - success (bool): True if rename succeeded, False otherwise.
                - error_msg (str): Error message if rename failed, empty string otherwise.
        """

        self.mutex.lock()
        self._tasks.append({
            'type': 'rename',
            'path': path,
            'new_name': new_name,
            'callback': callback
        })
        self.condition.wakeAll()
        self.mutex.unlock()

    def upload_file(self, local_path, remote_path: str, compression: bool, callback=None, task_id=None):
        """
        Uploads a local file to the remote server asynchronously.

        This method queues an upload task to be executed in the background.
        Upon completion, the `upload_finished` signal is emitted.

        Args:
            local_path (str or list): Path to the local file to upload.
            remote_path (str): Target path on the remote server.
            callback (callable, optional): Function to call when upload is complete.
                Receives two arguments:
                - success (bool): True if upload succeeded, False otherwise.
                - error_msg (str): Error message if upload failed, empty string otherwise.

        Signals:
            upload_finished (str, bool, str): Emitted upon completion with parameters:
                - local_path (str): The local file path.
                - success (bool): True if upload succeeded, False otherwise.
                - error_msg (str): Error message if upload failed, empty string otherwise.
        """

        self.mutex.lock()
        self._tasks.append({
            'type': 'upload_file',
            'local_path': local_path,
            'remote_path': remote_path,
            'compression': compression,
            'callback': callback,
            'task_id': task_id
        })
        self.condition.wakeAll()
        self.mutex.unlock()

    def classify_file_type_using_file(self, path: str) -> str:
        """
        Use remote `file` command to detect a simplified file type and emit the result.

        Returns one of:
        - "image/video"
        - "text"
        - "executable"
        - "unknown"

        Emits: file_type_ready(path, type)
        """
        # safety: ensure conn exists
        if self.conn is None:
            self.file_type_ready.emit(path, "unknown")
            return "unknown"

        # quote path for shell safety
        safe_path = shlex.quote(path)

        try:
            # 1) Try MIME type first (follow symlink with -L)
            cmd_mime = f"file -b --mime-type -L {safe_path}"
            stdin, stdout, stderr = self.conn.exec_command(cmd_mime)
            exit_status = stdout.channel.recv_exit_status()
            mime_out = stdout.read().decode('utf-8', errors='ignore').strip().lower()
            _err = stderr.read().decode('utf-8', errors='ignore').strip()

            if exit_status == 0 and mime_out:
                # image/video by MIME
                if mime_out.startswith("image") or mime_out.startswith("video"):
                    self.file_type_ready.emit(path, "image/video")
                    return "image/video"

                # text-like MIME (text/* or some application types that are textual)
                if (mime_out.startswith("text")
                    or mime_out in {"application/json", "application/xml", "application/javascript"}
                        or mime_out.endswith("+xml") or mime_out.endswith("+json")):
                    self.file_type_ready.emit(path, "text")
                    return "text"

                # common executable-related MIME strings
                if ("executable" in mime_out
                    or "x-executable" in mime_out
                    or mime_out.startswith("application/x-sharedlib")
                    or "x-mach-binary" in mime_out
                    or "pe" in mime_out  # covers various PE-like mimes
                    ):
                    self.file_type_ready.emit(path, "executable")
                    return "executable"

            # 2) Fallback: use human-readable `file -b -L` output
            cmd_hr = f"file -b -L {safe_path}"
            stdin, stdout, stderr = self.conn.exec_command(cmd_hr)
            exit_status2 = stdout.channel.recv_exit_status()
            hr_out = stdout.read().decode('utf-8', errors='ignore').lower()
            _err2 = stderr.read().decode('utf-8', errors='ignore').strip()

            if exit_status2 == 0 and hr_out:
                # executable indicators
                if ("executable" in hr_out
                    or "elf" in hr_out
                    or "pe32" in hr_out
                    or "ms-dos" in hr_out
                        or "mach-o" in hr_out):
                    self.file_type_ready.emit(path, "executable")
                    return "executable"

                # image/video indicators
                if ("png" in hr_out or "jpeg" in hr_out or "jpg" in hr_out
                    or "gif" in hr_out or "bitmap" in hr_out
                    or "svg" in hr_out or "png image" in hr_out
                        or "video" in hr_out or "matroska" in hr_out or "mp4" in hr_out):
                    self.file_type_ready.emit(path, "image/video")
                    return "image/video"

                # text indicators
                if ("text" in hr_out or "ascii" in hr_out or "utf-8" in hr_out
                        or "script" in hr_out or "json" in hr_out or "xml" in hr_out):
                    self.file_type_ready.emit(path, "text")
                    return "text"

            # 3) 最后兜底：检查执行权限（远端 stat via sftp）
            try:
                attr = self.sftp.lstat(path)
                if bool(attr.st_mode & stat.S_IXUSR):
                    self.file_type_ready.emit(path, "executable")
                    return "executable"
            except Exception:
                # ignore stat errors here
                pass

            # default
            self.file_type_ready.emit(path, "unknown")
            return "unknown"

        except Exception as e:
            print(f"Failed to run remote file command for {path}: {e}")
            self.file_type_ready.emit(path, "unknown")
            return "unknown"

    def _handle_mkdir_task(self, path: str, callback=None):
        """
        Asynchronously create a remote directory (mkdir -p behavior) via SFTP.

        Emits:
            mkdir_finished(path, status, error_msg)
        """
        if self.sftp is None:
            error_msg = "SFTP connection not ready"
            print(f"❌ Mkdir failed - {error_msg}: {path}")
            self.mkdir_finished.emit(path, False, error_msg)
            if callback:
                callback(False, error_msg)
            return

        try:
            # Recursively create directories like 'mkdir -p'
            parts = path.strip("/").split("/")
            current_path = ""
            for part in parts:
                current_path += f"/{part}"
                try:
                    self.sftp.stat(current_path)
                except FileNotFoundError:
                    try:
                        self.sftp.mkdir(current_path)
                        print(f"✅ Created directory: {current_path}")
                    except Exception as mkdir_exc:
                        error_msg = f"Failed to create directory {current_path}: {mkdir_exc}"
                        print(f"❌ Mkdir failed - {error_msg}")
                        self.mkdir_finished.emit(path, False, error_msg)
                        if callback:
                            callback(False, error_msg)
                        return

            # Success
            self.mkdir_finished.emit(path, True, "")
            if callback:
                callback(True, "")

        except Exception as e:
            error_msg = f"Error during mkdir: {str(e)}"
            print(f"❌ Mkdir failed - {error_msg}")
            import traceback
            traceback.print_exc()
            self.mkdir_finished.emit(path, False, error_msg)
            if callback:
                callback(False, error_msg)

    def _handle_mkfile_task(self, path: str, callback=None):
        """
        Asynchronously create a remote file (touch behavior) via SFTP.

        Emits:
            mkfile_finished(path, status, error_msg)
        """
        if self.sftp is None:
            error_msg = "SFTP connection not ready"
            print(f"❌ Mkfile failed - {error_msg}: {path}")
            self.mkfile_finished.emit(path, False, error_msg)
            if callback:
                callback(False, error_msg)
            return

        try:
            # Check if parent directory exists, create if necessary
            parent_dir = os.path.dirname(path)
            if parent_dir and parent_dir != "/":
                # Recursively create parent directories like 'mkdir -p'
                parts = parent_dir.strip("/").split("/")
                current_path = ""
                for part in parts:
                    current_path += f"/{part}"
                    try:
                        self.sftp.stat(current_path)
                    except FileNotFoundError:
                        try:
                            self.sftp.mkdir(current_path)
                            print(
                                f"✅ Created parent directory: {current_path}")
                        except Exception as mkdir_exc:
                            error_msg = f"Failed to create parent directory {current_path}: {mkdir_exc}"
                            print(f"❌ Mkfile failed - {error_msg}")
                            self.mkfile_finished.emit(path, False, error_msg)
                            if callback:
                                callback(False, error_msg)
                            return

            # Create the file
            try:
                # Check if file already exists
                try:
                    self.sftp.stat(path)
                    # File exists, we can either overwrite or return error
                    # Here we choose to overwrite empty file
                    print(f"⚠️ File already exists, overwriting: {path}")
                except FileNotFoundError:
                    pass  # File doesn't exist, proceed to create

                # Create empty file by opening in write mode and closing immediately
                with self.sftp.open(path, 'w') as f:
                    f.write('')  # Write empty content
                print(f"✅ Created file: {path}")

                # Success
                self.mkfile_finished.emit(path, True, "")
                if callback:
                    callback(True, "")

            except Exception as file_exc:
                error_msg = f"Failed to create file {path}: {file_exc}"
                print(f"❌ Mkfile failed - {error_msg}")
                self.mkfile_finished.emit(path, False, error_msg)
                if callback:
                    callback(False, error_msg)
                return

        except Exception as e:
            error_msg = f"Error during mkfile: {str(e)}"
            print(f"❌ Mkfile failed - {error_msg}")
            import traceback
            traceback.print_exc()
            self.mkfile_finished.emit(path, False, error_msg)
            if callback:
                callback(False, error_msg)

    def _ensure_remote_directory_exists(self, remote_dir: str) -> Tuple[bool, str]:
        """
        确保远程目录存在，如果不存在则创建
        """
        try:
            # 尝试列出目录，如果不存在会抛出异常
            self.sftp.listdir(remote_dir)
            return True, ""
        except IOError:
            try:
                # 递归创建目录
                parts = remote_dir.strip('/').split('/')
                current_path = ''
                for part in parts:
                    current_path = current_path + '/' + part if current_path else '/' + part
                    try:
                        self.sftp.listdir(current_path)
                    except IOError:
                        self.sftp.mkdir(current_path)
                return True, ""
            except Exception as e:
                print(f"创建远程目录失败: {remote_dir}, 错误: {e}")
                return False, e
    # ---------------------------
    # 内部文件树操作
    # ---------------------------

    def _get_file_info(self, path: str):
        """
        获取文件/目录信息，跨平台兼容
        """
        if self.sftp is None:
            return None, "", False, "SFTP 未就绪"

        try:
            attr = self.sftp.lstat(path)

            # 权限 rwxr-xr-x 格式
            perm = stat.filemode(attr.st_mode)

            # 用户和组（跨平台）
            owner, group = self._get_owner_group(attr.st_uid, attr.st_gid)

            # 是否可执行
            is_executable = bool(attr.st_mode & stat.S_IXUSR)

            # 最后修改时间
            mtime = datetime.fromtimestamp(
                attr.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

            # 是否符号链接
            is_symlink = stat.S_ISLNK(attr.st_mode)
            symlink_target = None
            if is_symlink:
                try:
                    symlink_target = self.sftp.readlink(path)
                except Exception:
                    symlink_target = "<unresolved>"

            info = {
                "path": path,
                "filename": os.path.basename(path.rstrip('/')),
                "size": self._human_readable_size(attr.st_size),
                "owner": owner,
                "group": group,
                "permissions": perm,
                "is_executable": is_executable,
                "last_modified": mtime,
                "is_directory": stat.S_ISDIR(attr.st_mode),
                "is_symlink": is_symlink,
                "symlink_target": symlink_target
            }

            return path, info, True, ""

        except Exception as e:
            return path, {}, False, f"获取文件信息失败: {e}"

    def _handle_rename_task(self, path: str, new_name: str, callback=None):
        """
        处理重命名任务（内部实现）
        """
        if self.sftp is None:
            error_msg = "SFTP 连接未就绪"
            print(f"❌ 重命名失败 - {error_msg}: {path} -> {new_name}")
            self.rename_finished.emit(path, new_name, False, error_msg)
            if callback:
                callback(False, error_msg)
            return

        try:
            # 检查源路径是否存在
            try:
                self.sftp.stat(path)
            except IOError:
                error_msg = f"源路径不存在: {path}"
                print(f"❌ 重命名失败 - {error_msg}")
                self.rename_finished.emit(path, new_name, False, error_msg)
                if callback:
                    callback(False, error_msg)
                return

            # 构建新路径
            parent_dir = os.path.dirname(path.rstrip('/'))
            new_path = f"{parent_dir}/{new_name}" if parent_dir != '/' else f"/{new_name}"

            print(f"🔁 开始重命名: {path} -> {new_path}")

            # 执行重命名
            self.sftp.rename(path, new_path)

            print(f"✅ 重命名成功: {path} -> {new_path}")
            self.rename_finished.emit(path, new_path, True, "")

            # 刷新父目录
            if parent_dir:
                print(f"🔄 刷新父目录: {parent_dir}")
                self.refresh_paths([parent_dir])

            if callback:
                callback(True, "")

        except Exception as e:
            error_msg = f"重命名过程错误: {str(e)}"
            print(f"❌ 重命名失败 - {error_msg}")
            import traceback
            traceback.print_exc()
            self.rename_finished.emit(path, new_name, False, error_msg)
            if callback:
                callback(False, error_msg)

    def _handle_copy_task(self, source_path: str, target_path: str, cut: bool = False):
        """
        内部处理复制/移动任务
        """
        if self.conn is None:
            error_msg = "SSH 连接未就绪"
            print(f"❌ 复制失败: {source_path} -> {target_path}, {error_msg}")
            self.copy_finished.emit(source_path, target_path, False, error_msg)
            return

        try:
            # 检查源路径
            path_type = self.check_path_type(source_path)
            if not path_type:
                error_msg = f"源路径不存在: {source_path}"
                print(f"❌ 复制失败: {error_msg}")
                self.copy_finished.emit(
                    source_path, target_path, False, error_msg)
                return

            print(f"📁 源路径类型: {path_type}")

            # 确保目标目录存在
            remote_dir = os.path.dirname(target_path.rstrip('/'))
            dir_status, error = self._ensure_remote_directory_exists(
                remote_dir)
            if remote_dir and not dir_status:
                error_msg = f"无法创建目标目录: {remote_dir}\n{error}"
                print(f"❌ 复制失败: {error_msg}")
                self.copy_finished.emit(
                    source_path, target_path, False, error_msg)
                return

            # 执行复制或移动
            cmd = f'cp -r "{source_path}" "{target_path}"'
            if cut:
                cmd = f'mv "{source_path}" "{target_path}"'

            print(f"🔧 执行命令: {cmd}")
            stdin, stdout, stderr = self.conn.exec_command(cmd)
            exit_status = stdout.channel.recv_exit_status()
            error_output = stderr.read().decode('utf-8').strip()

            if exit_status == 0:
                print(f"✅ 复制成功: {source_path} -> {target_path}")
                self.copy_finished.emit(source_path, target_path, True, "")

                # 刷新源和目标父目录
                parent_dirs = list(
                    {os.path.dirname(source_path), os.path.dirname(target_path)})
                self.refresh_paths(parent_dirs)

            else:
                error_msg = error_output if error_output else "未知错误"
                print(f"❌ 复制失败: {error_msg}")
                self.copy_finished.emit(
                    source_path, target_path, False, error_msg)

        except Exception as e:
            error_msg = f"复制过程错误: {str(e)}"
            print(f"❌ 复制失败: {error_msg}")
            import traceback
            traceback.print_exc()
            self.copy_finished.emit(source_path, target_path, False, error_msg)

    def _add_path_to_tree(self, path: str, update_tree_sign: bool = True):
        parts = [p for p in path.strip("/").split("/") if p]
        if "" not in self.file_tree:
            self.file_tree[""] = {}
        current = self.file_tree[""]

        # 列出根目录
        try:
            self._get_directory_contents("/", current)
        except Exception as e:
            print(f"列出根目录时出错: {e}")

        # 逐级添加
        full_path_parts = []
        for part in parts:
            full_path_parts.append(part)
            full_path = "/" + "/".join(full_path_parts)
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            try:
                self._get_directory_contents(full_path, current[part])
            except Exception as e:
                print(f"列出目录 {full_path} 时出错: {e}")
            current = current[part]
        if update_tree_sign:
            self.file_tree_updated.emit(self.file_tree, path)

    def _remove_path_from_tree(self, path: str):
        parts = path.strip('/').split('/')
        current = self.file_tree.get('', {})
        for part in parts[:-1]:
            if part in current:
                current = current[part]
            else:
                return
        if parts and parts[-1] in current:
            del current[parts[-1]]
        self.file_tree_updated.emit(self.file_tree, path)

    def _get_directory_contents(self, path: str, node: Dict):
        try:
            for attr in self.sftp.listdir_attr(path):
                name = attr.filename
                full_path = f"{path.rstrip('/')}/{name}"
                if stat.S_ISLNK(attr.st_mode):
                    try:
                        target = self.sftp.stat(full_path)
                        if stat.S_ISDIR(target.st_mode):
                            node[name] = node.get(name, {})
                        else:
                            node[name] = "is_file"
                    except Exception:
                        node[name] = "is_symlink_broken"
                elif stat.S_ISDIR(attr.st_mode):
                    node[name] = node.get(name, {})
                else:
                    node[name] = "is_file"
        except Exception as e:
            self.error_occurred.emit(f"Error\n{e}")
            print(f"获取目录内容时出错: {e}")

    # ---------------------------
    # 刷新功能
    # ---------------------------
    def _refresh_paths_impl(self, paths: Optional[List[str]] = None):
        """线程内部刷新目录"""
        if self.sftp is None:
            print("_refresh_paths_impl: sftp 未就绪")
            return

        # 构建刷新列表
        if paths is None:
            to_refresh = []

            def walk_existing(node: Dict, cur_path: str):
                if not isinstance(node, dict):
                    return
                pathstr = '/' if cur_path == '' else cur_path
                to_refresh.append(pathstr)
                # 只遍历已有非空子目录
                for name, child in node.items():
                    if isinstance(child, dict) and child:  # 只有非空字典才继续
                        child_path = (cur_path.rstrip('/') + '/' +
                                      name) if cur_path else '/' + name
                        walk_existing(child, child_path)

            walk_existing(self.file_tree.get('', {}), '')
        else:
            to_refresh = [
                '/' + p.strip('/') if p.strip('/') else '/' for p in paths]

        # 去重
        dirs = list(dict.fromkeys(to_refresh))

        # 遍历刷新
        for directory in dirs:
            try:
                node = self._find_node_by_path(directory)
                if node is None:
                    if directory == '/':
                        if '' not in self.file_tree:
                            self.file_tree[''] = {}
                        node = self.file_tree['']
                    else:
                        parts = [p for p in directory.strip(
                            '/').split('/') if p]
                        if '' not in self.file_tree:
                            self.file_tree[''] = {}
                        cur = self.file_tree['']
                        for part in parts:
                            if part not in cur or cur[part] == "is_file":
                                cur[part] = {}
                            cur = cur[part]
                        node = cur

                try:
                    entries = self.sftp.listdir_attr(directory)
                except IOError as e:
                    print(
                        f"_refresh_paths_impl: listdir_attr({directory}) failed: {e}")
                    continue

                new_map = {}
                for attr in entries:
                    name = attr.filename
                    full = directory.rstrip(
                        '/') + '/' + name if directory != '/' else '/' + name
                    try:
                        if stat.S_ISLNK(attr.st_mode):
                            try:
                                tattr = self.sftp.stat(full)
                                if stat.S_ISDIR(tattr.st_mode):
                                    new_map[name] = node.get(name, {}) if isinstance(
                                        node.get(name), dict) else {}
                                else:
                                    new_map[name] = "is_file"
                            except Exception:
                                new_map[name] = "is_symlink_broken"
                        elif stat.S_ISDIR(attr.st_mode):
                            new_map[name] = node.get(name, {}) if isinstance(
                                node.get(name), dict) else {}
                        else:
                            new_map[name] = "is_file"
                    except Exception:
                        new_map[name] = "is_file"

                if not isinstance(node, dict):
                    if directory == '/':
                        self.file_tree[''] = new_map
                    else:
                        parent_path = '/' + \
                            '/'.join(directory.strip('/').split('/')
                                     [:-1]) if '/' in directory.strip('/') else '/'
                        parent_node = self._find_node_by_path(parent_path)
                        last_name = directory.strip('/').split('/')[-1]
                        if isinstance(parent_node, dict):
                            parent_node[last_name] = new_map
                else:
                    node.clear()
                    node.update(new_map)

            except Exception as e:
                print(f"_refresh_paths_impl error for {directory}: {e}")

        self.file_tree_updated.emit(self.file_tree, "")

    # ---------------------------
    # 辅助方法
    # ---------------------------
    def _remote_untar(self, remote_tar_path: str, target_dir: str, remove_tar: bool = True):
        """
        在远程服务器解压 tar.gz 文件

        :param remote_tar_path: 远程 tar.gz 文件完整路径
        :param target_dir: 解压到目标目录
        :param remove_tar: 是否解压后删除远程 tar.gz 文件
        """
        try:
            self.start_to_uncompression.emit(remote_tar_path)
            # 确保目标目录存在
            mkdir_cmd = f'mkdir -p "{target_dir}"'
            self._exec_remote_command(mkdir_cmd)

            # 解压 tar.gz
            untar_cmd = f'tar -xzf "{remote_tar_path}" -C "{target_dir}"'
            out, err = self._exec_remote_command(untar_cmd)

            if err:
                print(f"⚠️ Remote untar error: {err}")
            else:
                print(
                    f"✅ Remote untar completed: {remote_tar_path} -> {target_dir}")

            # 删除远程 tar.gz
            if remove_tar:
                rm_cmd = f'rm -f "{remote_tar_path}"'
                self._exec_remote_command(rm_cmd)
                print(f"🗑️ Remote tar.gz removed: {remote_tar_path}")

        except Exception as e:
            print(f"❌ Remote untar failed: {e}")
            import traceback
            traceback.print_exc()

    def _handle_get_permission_task(self, file_path: str):
        """
        内部处理获取权限任务
        """
        if self.conn is None:
            error_msg = "SSH 连接未就绪"
            print(f"❌ 获取权限失败: {file_path}, {error_msg}")
            self.permission_got.emit(file_path, 0, False, error_msg)
            return

        try:
            # 检查文件/目录是否存在
            path_type = self.check_path_type(file_path)
            if not path_type:
                error_msg = f"路径不存在: {file_path}"
                print(f"❌ 获取权限失败: {error_msg}")
                self.permission_got.emit(file_path, 0, False, error_msg)
                return

            # 使用 stat 命令获取文件权限
            cmd = f'stat -c "%a" "{file_path}"'
            print(f"🔍 执行获取权限命令: {cmd}")

            # 执行获取权限命令
            stdin, stdout, stderr = self.conn.exec_command(cmd)
            exit_status = stdout.channel.recv_exit_status()
            error_output = stderr.read().decode('utf-8').strip()
            permission_output = stdout.read().decode('utf-8').strip()

            if exit_status == 0 and permission_output:
                permission_num = int(permission_output, 8)  # 将八进制字符串转换为整数
                print(f"📊 获取权限成功: {file_path} -> {permission_num:03o}")
                self.permission_got.emit(file_path, permission_num, True, "")
            else:
                error_msg = error_output if error_output else "获取权限失败"
                print(f"❌ 获取权限失败: {error_msg}")
                self.permission_got.emit(file_path, 0, False, error_msg)

        except ValueError as e:
            error_msg = f"权限格式解析错误: {str(e)}"
            print(f"❌ 获取权限失败: {error_msg}")
            self.permission_got.emit(file_path, 0, False, error_msg)
        except Exception as e:
            error_msg = f"获取权限过程错误: {str(e)}"
            print(f"❌ 获取权限失败: {error_msg}")
            import traceback
            traceback.print_exc()
            self.permission_got.emit(file_path, 0, False, error_msg)

    def _handle_permission_task(self, file_path: str, permission_num: int):
        """
        内部处理权限设置任务
        """
        if self.conn is None:
            error_msg = "SSH 连接未就绪"
            print(f"❌ 权限设置失败: {file_path}, {error_msg}")
            self.permission_finished.emit(
                file_path, permission_num, False, error_msg)
            return

        try:
            # 检查文件/目录是否存在
            path_type = self.check_path_type(file_path)
            if not path_type:
                error_msg = f"路径不存在: {file_path}"
                print(f"❌ 权限设置失败: {error_msg}")
                self.permission_finished.emit(
                    file_path, permission_num, False, error_msg)
                return

            print(f"📁 设置权限的目标路径: {file_path} (类型: {path_type})")

            # 调试信息
            print(
                f"🔧 权限数字 - 十进制: {permission_num}, 八进制: 0o{permission_num:03o}")

            # 关键修改：使用八进制数字传递给 chmod
            # permission_num 是八进制数值，但 Python 中以十进制存储
            # 需要格式化为八进制字符串，但不带 '0o' 前缀
            # 使用 :03o 格式化为3位八进制
            cmd = f'chmod {permission_num:03o} "{file_path}"'
            print(f"🔧 执行权限命令: {cmd}")

            # 执行权限设置命令
            stdin, stdout, stderr = self.conn.exec_command(cmd)
            exit_status = stdout.channel.recv_exit_status()
            error_output = stderr.read().decode('utf-8').strip()

            if exit_status == 0:
                print(f"✅ 权限设置成功: {file_path} -> 0o{permission_num:03o}")
                self.permission_finished.emit(
                    file_path, permission_num, True, "")

                # 刷新文件所在目录
                parent_dir = os.path.dirname(file_path)
                self.refresh_paths([parent_dir])

            else:
                error_msg = error_output if error_output else "权限设置失败"
                print(f"❌ 权限设置失败: {error_msg}")
                self.permission_finished.emit(
                    file_path, permission_num, False, error_msg)

        except Exception as e:
            error_msg = f"权限设置过程错误: {str(e)}"
            print(f"❌ 权限设置失败: {error_msg}")
            import traceback
            traceback.print_exc()
            self.permission_finished.emit(
                file_path, permission_num, False, error_msg)

    def _exec_remote_command(self, command: str):
        """
        在远程服务器执行命令
        :param command: shell 命令字符串
        :return: (stdout, stderr)
        """
        if not hasattr(self, "conn") or self.conn is None:
            print("SSH connection is not established")

        stdin, stdout, stderr = self.conn.exec_command(command)
        out = stdout.read().decode(errors="ignore")
        err = stderr.read().decode(errors="ignore")
        return out, err

    def _human_readable_size(self, size_bytes: int) -> str:
        """将字节数转换为可读的格式"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        for unit in ["KB", "MB", "GB", "TB"]:
            size_bytes /= 1024.0
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
        return f"{size_bytes:.2f} PB"

    def _find_node_by_path(self, path: str) -> Optional[Dict]:
        if not path:
            return None
        if path == '/' or path.strip('/') == '':
            return self.file_tree.get('', {})

        parts = [p for p in path.strip('/').split('/') if p]
        node = self.file_tree.get('', {})
        for part in parts:
            if not isinstance(node, dict):
                return None
            if part not in node:
                return None
            node = node[part]
        return node if isinstance(node, dict) else None

    def get_file_tree(self) -> Dict:
        return self.file_tree

    def check_path_type(self, path: str):
        try:
            attr = self.sftp.lstat(path)
            if stat.S_ISDIR(attr.st_mode):
                return "directory"
            elif stat.S_ISREG(attr.st_mode):
                return "file"
            elif stat.S_ISLNK(attr.st_mode):
                try:
                    target = self.sftp.stat(path)
                    return "directory" if stat.S_ISDIR(target.st_mode) else "file"
                except Exception:
                    return "symlink_broken"
            else:
                return False
        except IOError:
            return False

    def check_path_type_list(self, paths: List[str]) -> Dict[str, str]:
        """
        Checks the type of multiple remote paths using a single shell command.
        Returns a dictionary mapping each path to its type ('directory', 'file', or 'unknown').
        If a path is a directory, it will be the only result for that directory tree.
        """
        if not paths or self.conn is None:
            return {p: 'unknown' for p in paths}

        # 第一步：快速筛选出所有目录路径
        quoted_paths = " ".join([shlex.quote(p) for p in paths])
        dir_check_command = f"""
        for p in {quoted_paths}; do
            if [ -d "$p" ]; then echo "directory:$p"; fi
        done
        """

        try:
            stdin, stdout, stderr = self.conn.exec_command(
                dir_check_command, timeout=10)
            exit_status = stdout.channel.recv_exit_status()
            output = stdout.read().decode('utf-8', errors='ignore').strip()

            # 收集所有目录路径
            directories = set()
            for line in output.splitlines():
                if not line:
                    continue
                try:
                    type_str, path_str = line.split(':', 1)
                    if type_str == 'directory':
                        directories.add(path_str)
                except ValueError:
                    continue

            # 第二步：构建结果，目录优先，文件去重
            result = {}
            remaining_paths = set(paths)

            # 先处理目录：如果路径在某个目录下，就跳过
            for dir_path in sorted(directories, key=len, reverse=True):  # 长路径优先
                if dir_path in remaining_paths:
                    result[dir_path] = 'directory'
                    # 移除该目录及其所有子路径
                    remaining_paths = {p for p in remaining_paths
                                       if not p.startswith(dir_path + '/') and p != dir_path}

            # 第三步：对剩余路径进行快速文件检查
            if remaining_paths:
                quoted_remaining = " ".join(
                    [shlex.quote(p) for p in remaining_paths])
                file_check_command = f"""
                for p in {quoted_remaining}; do
                    if [ -f "$p" ]; then echo "file:$p"
                    elif [ ! -d "$p" ]; then echo "unknown:$p"; fi
                done
                """

                stdin, stdout, stderr = self.conn.exec_command(
                    file_check_command, timeout=10)
                output = stdout.read().decode('utf-8', errors='ignore').strip()

                for line in output.splitlines():
                    if not line:
                        continue
                    try:
                        type_str, path_str = line.split(':', 1)
                        result[path_str] = type_str
                    except ValueError:
                        continue

            # 确保所有原始路径都有结果（至少标记为unknown）
            for path in paths:
                if path not in result:
                    # 检查这个路径是否被某个目录覆盖了
                    is_covered = any(path.startswith(dir_path + '/')
                                     for dir_path in directories)
                    if not is_covered:
                        result[path] = 'unknown'

            return result

        except Exception as e:
            print(f"Exception in check_path_type_list: {e}")
            # 降级方案：逐个检查，但同样应用目录优先逻辑
            return self._fallback_check_with_dir_priority(paths)
    # def check_path_type_list(self, paths: List[str]) -> Dict[str, str]:
    #     """
    #     Checks the type of multiple remote paths using a single shell command.
    #     Returns a dictionary mapping each path to its type ('directory', 'file', or 'unknown').
    #     This is a synchronous method and will block until the command completes.
    #     """
    #     if not paths or self.conn is None:
    #         return {p: 'unknown' for p in paths}

    #     quoted_paths = " ".join([shlex.quote(p) for p in paths])
    #     command = f"""
    #     for p in {quoted_paths}; do
    #         if [ -L "$p" ]; then
    #             if [ -d "$p" ]; then echo "directory:$p"; else echo "file:$p"; fi
    #         elif [ -d "$p" ]; then echo "directory:$p"
    #         elif [ -f "$p" ]; then echo "file:$p"
    #         else echo "unknown:$p"; fi
    #     done
    #     """

    #     try:
    #         stdin, stdout, stderr = self.conn.exec_command(command, timeout=20)
    #         exit_status = stdout.channel.recv_exit_status()
    #         output = stdout.read().decode('utf-8', errors='ignore').strip()
    #         error_output = stderr.read().decode('utf-8', errors='ignore').strip()

    #         if exit_status != 0:
    #             print(f"Error in check_path_type_list command: {error_output}")
    #             return {p: self.check_path_type(p) for p in paths}

    #         result = {}
    #         for line in output.splitlines():
    #             if not line:
    #                 continue
    #             try:
    #                 type_str, path_str = line.split(':', 1)
    #                 result[path_str] = type_str
    #             except ValueError:
    #                 print(
    #                     f"Could not parse line from check_path_type_list: {line}")
    #         # Ensure all paths get a result
    #         for p in paths:
    #             if p not in result:
    #                 result[p] = 'unknown'
    #         return result

    #     except Exception as e:
    #         print(f"Exception in check_path_type_list: {e}")
    #         return {p: self.check_path_type(p) for p in paths}

    def get_default_path(self, default_path: str = None) -> Optional[str]:
        try:
            if self.conn is None:
                print("SSH 连接未建立")
                return None
            if default_path:
                stdin, stdout, stderr = self.conn.exec_command(
                    f'if [ -d "{default_path}" ]; then echo "exists"; else echo "not found"; fi')
                result = stdout.read().decode('utf-8').strip()
                if result == "exists":
                    return default_path
            stdin, stdout, stderr = self.conn.exec_command("pwd")
            exit_status = stdout.channel.recv_exit_status()
            path = stdout.read().decode('utf-8').strip()
            error = stderr.read().decode('utf-8').strip()
            if exit_status != 0 or error:
                print(f"执行 pwd 出错: {error}")
                return None
            return path
        except Exception as e:
            print(f"获取默认路径失败: {e}")
            return None

    def list_dir_simple(self, path: str) -> Optional[Dict[str, bool]]:
        """
        列出目录内容，返回 {name: True/False}
        True 表示目录，False 表示文件/其他
        """
        if self.sftp is None:
            print("list_dir_simple: sftp 未就绪")
            return None
        print(path)
        result: Dict[str, bool] = {}
        try:
            items = self.sftp.listdir_attr(path)
            # print(items)
            for attr in items:
                name = attr.filename
                full_path = f"{path.rstrip('/')}/{name}"

                if stat.S_ISDIR(attr.st_mode):
                    result[name] = True
                elif stat.S_ISLNK(attr.st_mode):
                    try:
                        target = self.sftp.stat(full_path)
                        result[name] = stat.S_ISDIR(target.st_mode)
                    except Exception:
                        result[name] = False
                else:
                    result[name] = False
            print(f"处理result完成 {result}")
            return result
        except Exception as e:
            print(f"list_dir_simple 获取目录内容时出错: {e}")
            return None

    def _fetch_user_group_maps(self):
        """
        Fetch and parse /etc/passwd and /etc/group to cache UID/GID mappings.
        """
        if self.conn is None:
            return

        # Fetch /etc/passwd
        try:
            stdin, stdout, stderr = self.conn.exec_command("cat /etc/passwd")
            passwd_content = stdout.read().decode('utf-8', errors='ignore')
            for line in passwd_content.strip().split('\n'):
                parts = line.split(':')
                if len(parts) >= 3:
                    username, _, uid = parts[0], parts[1], parts[2]
                    self.uid_map[int(uid)] = username
        except Exception as e:
            print(f"Could not fetch or parse /etc/passwd: {e}")

        # Fetch /etc/group
        try:
            stdin, stdout, stderr = self.conn.exec_command("cat /etc/group")
            group_content = stdout.read().decode('utf-8', errors='ignore')
            for line in group_content.strip().split('\n'):
                parts = line.split(':')
                if len(parts) >= 3:
                    groupname, _, gid = parts[0], parts[1], parts[2]
                    self.gid_map[int(gid)] = groupname
        except Exception as e:
            print(f"Could not fetch or parse /etc/group: {e}")

    def _get_owner_group(self, uid, gid):
        owner = self.uid_map.get(uid, str(uid))
        group = self.gid_map.get(gid, str(gid))
        return owner, group

    def _handle_kill_task(self, pid: int, callback=None):
        """
        内部处理杀死远程进程的任务
        """
        if self.conn is None:
            error_msg = "SSH 连接未就绪"
            print(f"❌ 杀死进程失败 - {error_msg}: PID {pid}")
            self.kill_finished.emit(pid, False, error_msg)
            if callback:
                callback(False, error_msg)
            return

        try:
            # 执行 kill 命令
            cmd = f"kill {pid}"
            print(f"🔪 执行命令: {cmd}")

            stdin, stdout, stderr = self.conn.exec_command(cmd)
            exit_status = stdout.channel.recv_exit_status()
            error_output = stderr.read().decode('utf-8').strip()
            output = stdout.read().decode('utf-8').strip()

            if exit_status == 0:
                print(f"✅ 进程杀死成功: PID {pid}")
                self.kill_finished.emit(pid, True, "")
                if callback:
                    callback(True, "")
            else:
                error_msg = error_output if error_output else f"kill 命令失败 (exit code: {exit_status})"
                print(f"❌ 杀死进程失败: {error_msg}")
                self.kill_finished.emit(pid, False, error_msg)
                if callback:
                    callback(False, error_msg)

        except Exception as e:
            error_msg = f"杀死进程过程错误: {str(e)}"
            print(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()
            self.kill_finished.emit(pid, False, error_msg)
            if callback:
                callback(False, error_msg)

    def list_dir_detailed(self, path: str) -> Optional[List[dict]]:
        if self.conn is None:
            print("list_dir_detailed: ssh connection not ready")
            return None
        start_time = time.perf_counter()
        detailed_result = []
        safe_path = shlex.quote(path)
        command = f'''
        sh -c 'cd {safe_path} && for item in * .*; do
            if [ "$item" = "." ] || [ "$item" = ".." ]; then continue; fi;
            info=$(stat -c "%A	%s	%Y	%u	%g" "$item" 2>/dev/null);
            if [ -z "$info" ]; then continue; fi;
            printf "%s	%s" "$info" "$item";
            if [ -L "$item" ] && [ -d "$item" ]; then printf "	DIRLINK"; fi;
            printf "\\0";
        done'
        '''
        try:
            stdin, stdout, stderr = self.conn.exec_command(command, timeout=20)
            output = stdout.read().decode('utf-8', errors='ignore')
            error_output = stderr.read().decode('utf-8', errors='ignore').strip()
            if error_output:
                print(
                    f"Error executing remote command for path {path}: {error_output}")
                return None
            records = output.strip('\0').split('\0')
            for record in records:
                if not record:
                    continue
                parts = record.split('	')
                if len(parts) < 6:
                    continue
                perms, size, mtime_unix, uid, gid, filename = parts[:6]
                is_dir_link = len(parts) > 6 and parts[6] == 'DIRLINK'
                is_dir = perms.startswith('d') or (
                    perms.startswith('l') and is_dir_link)
                owner, group = self._get_owner_group(int(uid), int(gid))
                detailed_result.append({
                    "name": filename,
                    "is_dir": is_dir,
                    "size": int(size),
                    "mtime": datetime.fromtimestamp(int(mtime_unix)).strftime('%Y/%m/%d %H:%M'),
                    "perms": perms,
                    "owner": f"{owner}/{group}"
                })
            end_time = time.perf_counter()
            print(f"获取远程目录 '{path}' 数据耗时: {end_time - start_time:.4f} 秒")
            return detailed_result
        except Exception as e:
            print(f"list_dir_detailed (optimized) error: {e}")

    def _handle_delete_task(self, paths, callback=None):
        """
        Handles the deletion task for one or more remote paths.
        删除逻辑优化：一次性调用 rm -rf 删除多个路径，而不是逐个遍历。
        """
        if self.conn is None:
            error_msg = "SSH connection is not ready"
            print(f"❌ Deletion failed - {error_msg}: {paths}")
            self.delete_finished.emit(str(paths), False, error_msg)
            if callback:
                callback(False, error_msg)
            return

        # 统一成列表
        if isinstance(paths, str):
            paths = [paths]

        try:
            print(f"🗑️ Starting deletion of {len(paths)} paths")

            # 拼接命令，注意路径加引号防止空格问题
            quoted_paths = " ".join(f'"{p}"' for p in paths)
            cmd = f"rm -rf {quoted_paths}"
            print(f"🔧 Executing command: {cmd}")

            stdin, stdout, stderr = self.conn.exec_command(cmd)
            exit_status = stdout.channel.recv_exit_status()
            error_output = stderr.read().decode('utf-8').strip()

            if exit_status == 0:
                print(f"✅ Deletion successful: {paths}")

                # 计算所有父目录，刷新文件树
                parent_dirs = {os.path.dirname(p)
                               for p in paths if os.path.dirname(p)}
                if parent_dirs:
                    print(f"🔄 Refreshing parent directories: {parent_dirs}")
                    self.refresh_paths(list(parent_dirs))

                # 发信号：成功
                display_path = "Multiple files" if len(paths) > 1 else paths[0]
                self.delete_finished.emit(display_path, True, "")
                if callback:
                    callback(True, "")

            else:
                error_msg = f"Deletion failed: {error_output or 'Unknown error'}"
                print(f"❌ {error_msg}")
                display_path = "Multiple files" if len(paths) > 1 else paths[0]
                self.delete_finished.emit(display_path, False, error_msg)
                if callback:
                    callback(False, error_msg)

        except Exception as e:
            error_msg = f"Error during deletion: {str(e)}"
            print(f"❌ {error_msg}")
            traceback.print_exc()
            display_path = "Multiple files" if len(paths) > 1 else paths[0]
            self.delete_finished.emit(display_path, False, error_msg)
            if callback:
                callback(False, error_msg)

    # ---------------------------
    # 辅助方法 - 添加安全的路径处理
    # ---------------------------
    def _sanitize_path(self, path: str) -> str:
        """
        对路径进行基本的清理和安全检查
        """
        if not path or path.strip() == "":
            return ""

        # 移除多余的斜杠和空格
        sanitized = path.strip().rstrip('/')

        # 基本的安全检查（防止删除关键目录）
        critical_paths = ['/', '/root', '/home',
                          '/etc', '/bin', '/sbin', '/usr', '/var']
        if sanitized in critical_paths:
            raise ValueError(f"禁止删除关键目录: {sanitized}")

        return sanitized

    # 修改现有的 remove_path_force 方法，使其使用新的删除逻辑
    def remove_path_force(self, path: str) -> bool:
        """
        尝试删除指定路径（文件或文件夹），使用 rm -rf
        返回 True 表示删除成功，False 表示失败
        """
        try:
            sanitized_path = self._sanitize_path(path)
            if not sanitized_path:
                return False

            # 使用新的删除方法
            success = False
            error_msg = ""

            # 创建同步等待机制
            loop = QEventLoop()

            def delete_callback(s, e):
                nonlocal success, error_msg
                success = s
                error_msg = e
                loop.quit()

            self.delete_path(sanitized_path, delete_callback)

            # 设置超时
            QTimer.singleShot(30000, loop.quit)  # 30秒超时

            loop.exec_()

            return success

        except Exception as e:
            print(f"删除路径 {path} 出错: {e}")
            return False


class FileManagerHandler:
    """负责处理 RemoteFileManager 的所有信号，避免匿名函数乱飞"""

    def __init__(self, file_manager: RemoteFileManager, session_widget, child_key, parent):
        self.fm = file_manager
        self.session_widget = session_widget
        self.child_key = child_key
        self.parent = parent  # main_window or whoever owns the callbacks

        # 绑定信号
        self._connect_signals()

    def _connect_signals(self):
        fm = self.fm
        ck = self.child_key
        fm.kill_finished.connect(self._on_kill_finished)
        fm.file_tree_updated.connect(
            lambda file_tree, path: self.parent.on_file_tree_updated(
                file_tree, self.session_widget, path)
        )
        fm.error_occurred.connect(self.parent.on_file_manager_error)

        fm.delete_finished.connect(
            partial(self._wrap_show_info, type_="delete"))
        fm.upload_finished.connect(
            partial(self._wrap_show_info, type_="upload"))
        fm.download_finished.connect(self._on_download_finished)
        fm.copy_finished.connect(self._on_copy_finished)
        fm.rename_finished.connect(self._on_rename_finished)
        fm.file_type_ready.connect(self._on_file_type_ready)
        fm.file_info_ready.connect(self._on_file_info_ready)
        fm.mkdir_finished.connect(partial(self._wrap_show_info, type_="mkdir"))
        fm.mkfile_finished.connect(
            partial(self._wrap_show_info, type_="mkfile"))
        fm.permission_got.connect(
            partial(self.parent._on_permission_info_got, file_manager=fm))
        # fm.start_to_compression.connect(
        #     partial(self._wrap_show_info, type_="compression"))
        # fm.start_to_uncompression.connect(
        #     partial(self._wrap_show_info, type_="uncompression"))

        fm.compression_finished.connect(self._on_compression_finished)
        fm.upload_progress.connect(partial(self._on_progress, mode="upload"))
        fm.download_progress.connect(
            partial(self._on_progress, mode="download"))

        self.session_widget.file_explorer.upload_file.connect(
            self._on_upload_request)

    # ---- 封装的槽函数 ----
    def _on_kill_finished(self, pid, status, error_msg):
        self._wrap_show_info(pid, status, error_msg, "kill")

    def _wrap_show_info(self, path, status, msg, type_, local_path=None, target_path=None, open_it=False):
        print(f"type : {type_}")
        self.parent._show_info(path, status, msg, type_, self.child_key,
                               local_path=local_path,  open_it=open_it)

    def _on_download_finished(self, remote_path, local_path, status, error_msg, open_it):
        self._wrap_show_info(remote_path, status, error_msg, "download",
                             local_path=local_path, open_it=open_it)

    def _on_copy_finished(self, source_path, target_path, status, error_msg):
        self._wrap_show_info(source_path, status, error_msg,
                             "paste", target_path=target_path)

    def _on_rename_finished(self, source_path, new_path, status, error_msg):
        self._wrap_show_info(source_path, status, error_msg,
                             "rename", local_path=new_path)

    def _on_file_type_ready(self, path, type_):
        self.parent._open_server_files(path, type_, self.child_key)

    def _on_file_info_ready(self, path, info, status, error_msg):
        self._wrap_show_info(path, status, error_msg, "info", local_path=info)

    def _on_compression_finished(self, identifier, new_name):
        self.parent._update_transfer_item_name(
            identifier, new_name, self.child_key)

    def _on_progress(self, path, percentage, bytes_so_far, total_bytes, mode):
        self.parent._show_progresses(path, percentage, bytes_so_far, total_bytes,
                                     self.child_key, mode)

    def _on_upload_request(self, local_path, remote_path, compression):
        self.parent._handle_upload_request(self.child_key, local_path, remote_path,
                                           compression, self.fm)

    def cleanup(self):
        """断开所有信号，防止 widget 删除后还有事件进来"""
        signals = [
            "file_tree_updated",
            "error_occurred",
            "sftp_ready",
            "upload_progress",
            "download_progress",
            "upload_finished",
            "delete_finished",
            "list_dir_finished",
            "path_check_result",
            "download_finished",
            "copy_finished",
            "rename_finished",
            "file_info_ready",
            "file_type_ready",
            "mkdir_finished",
            "kill_finished",
            "start_to_compression",
            "start_to_uncompression",
            "compression_finished",
        ]

        for sig_name in signals:
            sig = getattr(self, sig_name, None)
            if sig is not None:
                try:
                    sig.disconnect()
                except (TypeError, RuntimeError):
                    # 信号没连接任何槽或已经断开，忽略
                    pass
