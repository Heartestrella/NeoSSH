# transfer_worker.py
import traceback
import paramiko
import os
import stat
import tarfile
import tempfile
from PyQt5.QtCore import QObject, QRunnable, pyqtSignal
import time


class TransferSignals(QObject):
    """
    Defines signals available for a transfer worker.
    """
    progress = pyqtSignal(str, int, int, int)
    # local_path_or_identifier, success, message
    finished = pyqtSignal(str, bool, str)
    # target_zip_path (for compression)
    start_to_compression = pyqtSignal(str)
    # remote_path (for uncompression)
    start_to_uncompression = pyqtSignal(str)
    compression_finished = pyqtSignal(str, str)


class TransferWorker(QRunnable):
    """
    A QRunnable worker for performing a single file/directory transfer operation (upload or download)
    in a separate thread from the QThreadPool.
    """

    def __init__(self, connection, action, local_path, remote_path, compression, download_context=None, upload_context=None, task_id=None, session_id=None):
        super().__init__()
        self.conn = connection  # Now receives an active connection
        self.action = action
        self.local_path = local_path
        self.remote_path = remote_path
        self.compression = compression
        self.download_context = download_context
        self.upload_context = upload_context
        self.task_id = task_id
        self.session_id = session_id
        self.signals = TransferSignals()
        self.sftp = None
        self.is_stopped = False

    def stop(self):
        self.is_stopped = True
        if self.sftp:
            try:
                self.sftp.close()
            except Exception as e:
                print(f"Error closing SFTP in worker stop: {e}")

    def run(self):
        """The main work of the thread. Uses a pre-established SSH connection to perform the transfer."""
        retry_delay = 1  # Delay in seconds between retries
        attempts = 0
        if self.task_id:
            identifier = self.task_id
        else:
            identifier = str(
                self.local_path if self.action == 'upload' else self.remote_path)
        self.signals.progress.emit(identifier, -1, 0, 0)

        while not self.is_stopped:
            try:
                if self.is_stopped:
                    break
                if not self.conn or not self.conn.get_transport() or not self.conn.get_transport().is_active():
                    raise Exception(
                        "SSH connection is not active or provided.")
                self.conn.get_transport().set_keepalive(30)
                self.sftp = self.conn.open_sftp()

                if self.action == 'upload':
                    self._handle_upload_task(
                        identifier, self.local_path, self.remote_path, self.compression, self.upload_context)
                elif self.action == 'download':
                    self._download_files(
                        identifier, self.remote_path, self.compression)

                # If we reach here, the operation was successful
                return

            except paramiko.ssh_exception.ChannelException as e:
                attempts += 1
                tb = traceback.format_exc()
                print(
                    f"⚠️ ChannelException encountered (attempt {attempts}): {e}\n{tb}")
                print(
                    f"Retrying {identifier} in {retry_delay} second(s)...")
                time.sleep(retry_delay)
                # Loop will continue indefinitely
            except Exception as e:
                if self.is_stopped:
                    break
                tb = traceback.format_exc()
                error_msg = f"TransferWorker Error: {e}\n{tb}"
                print(f"❌ {error_msg}")
                self.signals.finished.emit(identifier, False, error_msg)
                # For non-recoverable errors, break the loop
                return
            finally:
                if self.sftp:
                    self.sftp.close()
                    self.sftp = None  # Reset sftp for next retry

        if self.is_stopped:
            identifier = str(
                self.local_path if self.action == 'upload' else self.remote_path)
            error_msg = "Transfer was cancelled by user."
            print(f"🛑 {error_msg} [{identifier}]")
            self.signals.finished.emit(identifier, False, error_msg)

    # ==================================================================================
    # == The following methods are adapted from RemoteFileManager for standalone execution ==
    # ==================================================================================

    def _handle_upload_task(self, identifier, local_path, remote_path, compression, upload_context=None):
        """
        Handles upload of a single file or list of files.
        Emits one finished signal per batch (for non-compressed lists).
        """
        try:
            if isinstance(local_path, list):
                if compression:
                    # Compressed list upload: whole list as one archive
                    self._upload_list_compressed(
                        identifier, local_path, remote_path)
                else:
                    # Non-compressed list: upload each file individually, but emit finished once at the end
                    all_successful = True
                    error_messages = []

                    for path in local_path:
                        if not os.path.exists(path):
                            error_msg = f"Local path does not exist: {path}"
                            all_successful = False
                            error_messages.append(error_msg)
                            continue

                        try:
                            if os.path.isfile(path):
                                self._upload_file(
                                    path, path, remote_path, upload_context)
                            elif os.path.isdir(path):
                                # Non-compressed directory: upload files inside directory
                                for root, _, files in os.walk(path):
                                    for f in files:
                                        local_file = os.path.join(root, f)
                                        self._upload_file(
                                            local_file, local_file, remote_path, upload_context)
                        except Exception as e:
                            tb = traceback.format_exc()
                            all_successful = False
                            error_messages.append(
                                f"Failed to upload {path}: {e}\n{tb}")

                    # Emit a single finished signal for the whole batch
                    final_msg = "; ".join(error_messages)
                    print(f"发送上传钩子:{all_successful}")
                    self.signals.finished.emit(
                        identifier, all_successful, final_msg)

            elif isinstance(local_path, str):
                # Single file or directory
                status, msg = self._upload_item(identifier, local_path,
                                                remote_path, compression, upload_context)
                self.signals.finished.emit(
                    identifier, status, msg)
        except Exception as e:
            tb = traceback.format_exc()
            error_msg = f"Error during upload task: {e}\n{tb}"
            print(f"❌ {error_msg}")
            self.signals.finished.emit(identifier, False, error_msg)

    def _upload_item(self, identifier, item_path, remote_path, compression, upload_context=None):
        """Returns (bool, str) for success status and message, and also emits signals."""
        if not os.path.exists(item_path):
            error_msg = f"Local path does not exist: {item_path}"
            self.signals.finished.emit(item_path, False, error_msg)
            return False, error_msg

        try:
            if compression:
                self._upload_compressed(item_path, item_path, remote_path)
            else:
                if os.path.isfile(item_path):
                    self._upload_file(
                        item_path, item_path, remote_path, upload_context)
                elif os.path.isdir(item_path):
                    # This should no longer be called for non-compressed directory uploads
                    # as the dispatcher breaks them down into files.
                    self._upload_directory(item_path, item_path, remote_path)

            return True, ""
        except Exception as e:
            traceback.print_exc()
            error_msg = f"Failed to upload {item_path}: {e}"
            self.signals.finished.emit(item_path, False, error_msg)
            return False, error_msg

    def _upload_list_compressed(self, identifier, path_list, remote_path):
        tmp_dir = "tmp"
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_fd, tmp_tar_path = tempfile.mkstemp(suffix=".tar.gz", dir=tmp_dir)
        os.close(tmp_fd)
        self.signals.start_to_compression.emit(tmp_tar_path)
        try:
            with tarfile.open(tmp_tar_path, mode="w:gz") as tf:
                for path in path_list:
                    if not os.path.exists(path):
                        continue
                    arcname = os.path.basename(path)
                    tf.add(path, arcname=arcname)
            self.signals.compression_finished.emit(
                identifier, os.path.basename(tmp_tar_path))
            self._upload_file(
                identifier, tmp_tar_path, remote_path)
            remote_zip_path = f"{remote_path.rstrip('/')}/{os.path.basename(tmp_tar_path)}"
            self._remote_untar(remote_zip_path, remote_path)
            self.signals.finished.emit(identifier, True, "")
        except Exception as e:
            tb = traceback.format_exc()
            error_msg = f"Compressed list upload error: {e}\n{tb}"
            self.signals.finished.emit(identifier, False, error_msg)
            raise e
        finally:
            if os.path.exists(tmp_tar_path):
                os.remove(tmp_tar_path)

    def _upload_compressed(self, identifier, local_path, remote_path):
        tmp_dir = "tmp"
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_fd, tmp_tar_path = tempfile.mkstemp(suffix=".tar.gz", dir=tmp_dir)
        os.close(tmp_fd)
        self.signals.start_to_compression.emit(tmp_tar_path)
        try:
            with tarfile.open(tmp_tar_path, mode="w:gz") as tf:
                arcname = os.path.basename(local_path)
                tf.add(local_path, arcname=arcname)

            self.signals.compression_finished.emit(
                identifier, os.path.basename(tmp_tar_path))
            self._upload_file(
                identifier, tmp_tar_path, remote_path, emit_finish_signal=False)
            remote_zip_path = f"{remote_path.rstrip('/')}/{os.path.basename(tmp_tar_path)}"
            self._remote_untar(remote_zip_path, remote_path)
            self.signals.finished.emit(identifier, True, "")
        except Exception as e:
            tb = traceback.format_exc()
            error_msg = f"Compressed upload error: {e}\n{tb}"
            self.signals.finished.emit(identifier, False, error_msg)
            raise e
        finally:
            if os.path.exists(tmp_tar_path):
                os.remove(tmp_tar_path)

    def _upload_file(self, identifier, local_path, remote_path, upload_context=None):
        """
        Upload a single file, emitting progress signals.
        Does NOT emit finished signal (handled at batch level).
        """
        try:
            if upload_context:
                relative_path = os.path.relpath(local_path, upload_context)
                upload_root_name = os.path.basename(upload_context)
                full_remote_path = os.path.join(
                    remote_path, upload_root_name, relative_path).replace('\\', '/')
            else:
                full_remote_path = os.path.join(
                    remote_path, os.path.basename(local_path)).replace('\\', '/')

            # Ensure remote parent directory exists
            self._ensure_remote_directory_exists(
                os.path.dirname(full_remote_path))

            def progress_callback(bytes_so_far, total_bytes):
                if total_bytes > 0:
                    progress = int((bytes_so_far / total_bytes) * 100)
                    self.signals.progress.emit(
                        identifier, progress, bytes_so_far, total_bytes)

            self.sftp.put(local_path, full_remote_path,
                          callback=progress_callback)

        except Exception as e:
            raise e

    def _upload_directory(self, identifier, local_dir, remote_dir):
        try:
            dir_name = os.path.basename(local_dir)
            target_remote_dir = os.path.join(
                remote_dir, dir_name).replace('\\', '/')
            self._ensure_remote_directory_exists(target_remote_dir)

            total_size = sum(os.path.getsize(os.path.join(root, file))
                             for root, _, files in os.walk(local_dir) for file in files)
            uploaded_size = 0

            for root, dirs, files in os.walk(local_dir):
                relative_path = os.path.relpath(root, local_dir)
                current_remote_dir = os.path.join(target_remote_dir, relative_path).replace(
                    '\\', '/') if relative_path != '.' else target_remote_dir

                self._ensure_remote_directory_exists(current_remote_dir)

                for file in files:
                    local_file_path = os.path.join(root, file)
                    remote_file_path = os.path.join(
                        current_remote_dir, file).replace('\\', '/')

                    file_size = os.path.getsize(local_file_path)
                    self.sftp.put(local_file_path, remote_file_path)
                    uploaded_size += file_size
                    progress = int((uploaded_size / total_size)
                                   * 100) if total_size > 0 else 100
                    self.signals.progress.emit(identifier, progress)

            self.signals.finished.emit(
                identifier, True, "Directory upload completed.")
        except Exception as e:
            tb = traceback.format_exc()
            error_msg = f"Directory upload error: {e}\n{tb}"
            self.signals.finished.emit(identifier, False, error_msg)

    def _download_files(self, identifier, remote_path, compression):
        # 根据 open_it 标志决定本地基础路径
        if hasattr(self, '_open_it') and self._open_it and self.session_id:
            # 双击编辑：使用会话隔离的编辑目录
            local_base = os.path.join("tmp", "edit", self.session_id)
        else:
            # 常规下载：使用原有的下载目录
            local_base = "_ssh_download"

        os.makedirs(local_base, exist_ok=True)
        paths = [remote_path] if isinstance(remote_path, str) else remote_path
        print(f"download1 : {remote_path}")
        try:
            if compression:
                import random
                import string
                random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
                tar_name = f"{random_suffix}.tar.gz"
                self.signals.compression_finished.emit(identifier, tar_name)
                
                remote_tar = self._remote_tar(paths, identifier, random_suffix)
                if not remote_tar:
                    raise Exception("Failed to create remote tar file.")

                local_tar_path = os.path.join(
                    local_base, os.path.basename(remote_tar))

                def progress_callback(bytes_so_far, total_bytes):
                    if total_bytes > 0:
                        progress = int((bytes_so_far / total_bytes) * 100)
                        # We can perhaps divide progress for different stages
                        # Assuming download is the main part
                        self.signals.progress.emit(
                            identifier, progress, bytes_so_far, total_bytes)

                self.sftp.get(remote_tar, local_tar_path,
                              callback=progress_callback)

                with tarfile.open(local_tar_path, "r:gz") as tar:
                    tar.extractall(local_base)

                self._exec_remote_command(f'rm -f "{remote_tar}"')
                os.remove(local_tar_path)

                self.signals.finished.emit(identifier, True, local_base)

            else:  # Non-compressed
                # For non-compressed, _download_item will handle its own signals.
                for p in paths:
                    # Each item is its own task, so the identifier is the path itself.
                    self._download_item(p, p, local_base)
                # A batch 'finished' signal is not sent here, to allow individual tracking.

        except Exception as e:
            tb = traceback.format_exc()
            error_msg = f"Error during download task: {e}\n{tb}"
            print(f"❌ {error_msg}")
            self.signals.finished.emit(identifier, False, error_msg)

    def _download_item(self, identifier, remote_item_path, local_base_path):
        """Downloads a single item (file or directory) and emits a finished signal for it."""
        try:
            # 根据 open_it 标志决定本地路径构建方式
            if hasattr(self, '_open_it') and self._open_it and self.session_id:
                # 双击编辑模式：镜像远程路径结构
                # 移除远程路径开头的斜杠，然后拼接到 local_base_path
                remote_path_normalized = remote_item_path.lstrip('/')
                local_target = os.path.join(
                    local_base_path, remote_path_normalized)
            else:
                # 常规下载模式：保持原有逻辑
                # Determine local path, preserving directory structure if context is given
                if self.download_context:
                    if remote_item_path.startswith(self.download_context):
                        # The download root itself should be included in the local path
                        download_root_name = os.path.basename(
                            self.download_context.rstrip('/'))
                        relative_path = os.path.relpath(
                            remote_item_path, self.download_context)
                        local_target = os.path.join(
                            local_base_path, download_root_name, relative_path)
                    else:  # Fallback for safety
                        local_target = os.path.join(
                            local_base_path, os.path.basename(remote_item_path.rstrip("/")))
                else:
                    local_target = os.path.join(
                        local_base_path, os.path.basename(remote_item_path.rstrip("/")))

            # Ensure local directory exists
            os.makedirs(os.path.dirname(local_target), exist_ok=True)

            # Since dispatcher now only sends files for non-compressed, we can simplify this.
            # We still check to be robust.
            attr = self.sftp.stat(remote_item_path)
            if stat.S_ISDIR(attr.st_mode):
                # This part should ideally not be hit in the new flow for non-compressed downloads
                self._download_directory(
                    identifier, remote_item_path, local_target)
            else:
                self._download_file(
                    identifier, remote_item_path, local_target)

            if hasattr(self, '_download_callback'):
                self._download_callback(identifier, True, local_target)
            else:
                self.signals.finished.emit(identifier, True, local_target)

        except Exception as e:
            tb = traceback.format_exc()
            error_msg = f"Failed to download {remote_item_path}: {e}\n{tb}"
            if hasattr(self, '_download_callback'):
                self._download_callback(identifier, False, error_msg)
            else:
                self.signals.finished.emit(identifier, False, error_msg)

    def _download_file(self, identifier, remote_file, local_file):
        def progress_callback(bytes_so_far, total_bytes):
            if total_bytes > 0:
                progress = int((bytes_so_far / total_bytes) * 100)
                self.signals.progress.emit(
                    identifier, progress, bytes_so_far, total_bytes)

        self.sftp.get(remote_file, local_file, callback=progress_callback)

    def _download_directory(self, identifier, remote_dir, local_dir):
        os.makedirs(local_dir, exist_ok=True)
        # This simplified version won't have accurate progress for directory downloads
        # A more complex implementation would be needed to calculate total size first.
        for entry in self.sftp.listdir_attr(remote_dir):
            remote_item = f"{remote_dir.rstrip('/')}/{entry.filename}"
            local_item = os.path.join(local_dir, entry.filename)
            if stat.S_ISDIR(entry.st_mode):
                self._download_directory(identifier, remote_item, local_item)
            else:
                # No progress for individual files in a dir download for now
                self.sftp.get(remote_item, local_item)

    def _remote_tar(self, paths, identifier=None, random_suffix=None):
        if not paths:
            return None
        if random_suffix is None:
            import random
            import string
            random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        common_path = os.path.dirname(paths[0]).replace('\\', '/')
        tar_name = f"{random_suffix}.tar.gz"
        remote_tar_path = f"{common_path}/{tar_name}"
        files_to_tar = ' '.join([f'"{os.path.basename(p)}"' for p in paths])
        self.signals.start_to_compression.emit(remote_tar_path)
        try:
            total_size = 0
            for p in paths:
                size_cmd = f'du -sb "{p}" | cut -f1'
                out, err = self._exec_remote_command(size_cmd)
                if not err and out.strip().isdigit():
                    total_size += int(out.strip())
            if total_size == 0:
                total_size = 1
            cmd = f'cd "{common_path}" && tar -czf "{tar_name}" {files_to_tar} 2>&1'
            stdin, stdout, stderr = self.conn.exec_command(cmd)
            channel = stdout.channel
            last_progress_time = time.time()
            progress_interval = 0.5
            while not channel.exit_status_ready():
                if self.is_stopped:
                    channel.close()
                    try:
                        self._exec_remote_command(f'rm -f "{remote_tar_path}"')
                        print(f"🗑️ Cleaned up incomplete tar file: {remote_tar_path}")
                    except Exception as cleanup_error:
                        print(f"Failed to clean up tar file: {cleanup_error}")
                    return None
                current_time = time.time()
                if current_time - last_progress_time >= progress_interval:
                    try:
                        stat_cmd = f'stat -c%s "{remote_tar_path}" 2>/dev/null || echo 0'
                        size_out, _ = self._exec_remote_command(stat_cmd)
                        current_size = int(size_out.strip()) if size_out.strip().isdigit() else 0
                        if total_size > 0:
                            progress = min(int((current_size / total_size) * 100), 99)
                            if identifier:
                                self.signals.progress.emit(identifier, progress, current_size, total_size)
                    except Exception as e:
                        print(f"Error checking compression progress: {e}")
                    last_progress_time = current_time
                time.sleep(0.1)
            exit_status = channel.recv_exit_status()
            err_output = stderr.read().decode(errors="ignore")
            if exit_status != 0:
                print(f"Error creating remote tar: {err_output}")
                return None
            if identifier:
                self.signals.progress.emit(identifier, 100, total_size, total_size)
            return remote_tar_path
        except Exception as e:
            print(f"Error in _remote_tar: {e}")
            return None

    def _ensure_remote_directory_exists(self, remote_dir):
        parts = remote_dir.strip('/').split('/')
        current_path = ''
        for part in parts:
            current_path = f"{current_path}/{part}" if current_path else f"/{part}"
            try:
                self.sftp.stat(current_path)
            except FileNotFoundError:
                self.sftp.mkdir(current_path)

    def _remote_untar(self, remote_tar_path, target_dir):
        self.signals.start_to_uncompression.emit(remote_tar_path)
        self._ensure_remote_directory_exists(target_dir)
        untar_cmd = f'tar -xzf "{remote_tar_path}" -C "{target_dir}"'
        self._exec_remote_command(untar_cmd)
        rm_cmd = f'rm -f "{remote_tar_path}"'
        self._exec_remote_command(rm_cmd)

    def _exec_remote_command(self, command):
        stdin, stdout, stderr = self.conn.exec_command(command)
        out = stdout.read().decode(errors="ignore")
        err = stderr.read().decode(errors="ignore")
        return out, err
