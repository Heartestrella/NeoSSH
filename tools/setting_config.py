from pathlib import Path
import json
import os
import time
import uuid

config_dir = Path.home() / ".config" / "pyqt-ssh"


class SCM:
    _instance = None  # 单例模式
    _lock = None  # 文件锁（防并发）

    def __new__(cls):
        """实现单例模式，确保全局只有一个 SCM 实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # 防止重复初始化
        if hasattr(self, '_initialized') and self._initialized:
            return

        if not os.path.exists(config_dir):
            os.makedirs(config_dir)

        self.default_config = {
            "bg_color": "Dark",
            "bg_pic": "",
            "font_size": "12",
            "locked_ratio": True,
            "ssh_widget_text_color": "#08ff98",
            "background_opacity": 35,
            "window_last_width": 1615,
            "window_last_height": 778,
            "follow_cd": False,
            "language": "system",
            "default_view": "icon",
            "max_concurrent_transfers": 10,
            "compress_upload": False,
            "splitter_lr_ratio": [0.2, 0.8],
            "splitter_tb_ratio": [0.5206786850477201, 0.47932131495228],
            "maximized": True,
            "aigc_api_key": "",
            "aigc_open": True,
            "aigc_model": "DeepSeek",
            "aigc_history_max_length": 10,
            "splitter_left_components": [0.6127527216174183, 0.38724727838258166],
            "open_mode": False,
            "external_editor": "",
            "editor_auto_save_on_focus_lost": True,
            "splitter_sizes": [1466, 406],
            "splitter_lr_left_width": 358,
            "bg_theme_color": None,
            "side_panel_last_width": 263,
            "page_animation": "slide_fade",
            "right_panel_ai_chat": True,
            "file_tree_single_click": False,
            "update_channel": "none",
            "ai_chat_model": "",
            "terminal_mode": 0,
            "account": {
                "user": "Guest",
                "avatar_url": r"resource\icons\guest.png",
                "combo": "",
                "qid": "",
                "email": "",
                "apikey": "",
                "password": ""
            },
        }

        self.config_path = config_dir / "setting-config.json"
        self._config_cache = None  # 本地缓存，减少文件读取
        self._cache_timestamp = 0

        if not os.path.exists(self.config_path):
            self.init_config()
            print("Config file created at:", self.config_path)
        else:
            # 仅在启动时检查修复一次
            try:
                initial_config = self._read_config_raw()
                repaired_config = self._check_and_repair_config(initial_config)
                if repaired_config != initial_config:
                    self.write_config(repaired_config)
                    print("Config file repaired with missing fields")
            except Exception as e:
                print(f"Error during config repair: {e}")

        self._initialized = True

    def _read_config_raw(self):
        """直接读取配置文件，不修复"""
        try:
            with open(self.config_path, mode="r", encoding="utf-8") as f:
                data = json.load(f)
                # 更新缓存时间戳
                self._cache_timestamp = os.path.getmtime(self.config_path)
                return data
        except Exception as e:
            print(f"Error reading config: {e}")
            return {}

    def _check_and_repair_config(self, config: dict) -> dict:
        """检查并修复配置，仅补充缺失字段，不删除已有字段"""
        repaired = False
        config_copy = config.copy()

        for key, default_value in self.default_config.items():
            if key not in config_copy:
                config_copy[key] = default_value
                repaired = True
                print(f"Added missing field: {key}")
            elif isinstance(default_value, dict) and isinstance(config_copy[key], dict):
                if self._recursive_repair(config_copy[key], default_value):
                    repaired = True

        return config_copy

    def _recursive_repair(self, current: dict, default: dict) -> bool:
        """递归修复嵌套字典"""
        repaired = False
        for key, default_value in default.items():
            if key not in current:
                current[key] = default_value
                repaired = True
                print(f"Added missing nested field: {key}")
            elif isinstance(default_value, dict) and isinstance(current[key], dict):
                if self._recursive_repair(current[key], default_value):
                    repaired = True
        return repaired

    def write_config(self, config_data):
        """写入配置文件（加防护）"""
        try:
            # 先写入临时文件，再原子性地替换原文件（防止写入中断导致数据丢失）
            temp_path = str(self.config_path) + ".tmp"
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)

            # 原子性替换
            import shutil
            shutil.move(temp_path, self.config_path)

            # 更新缓存
            self._config_cache = config_data
            self._cache_timestamp = os.path.getmtime(self.config_path)
            print(f"Config saved successfully")
        except Exception as e:
            print(f"Failed to write config file: {e}")
            # 清理临时文件
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except:
                pass

    def init_config(self):
        """初始化配置文件"""
        self.write_config(self.default_config)

    def revise_config(self, key, value):
        """修改配置（支持嵌套键如 'account.user'）"""
        config = self.read_config()

        if '.' in key:
            keys = key.split('.')
            current = config
            for k in keys[:-1]:
                if k not in current:
                    current[k] = {}
                current = current[k]
            current[keys[-1]] = value
        else:
            config[key] = value

        self.write_config(config)

    def read_config(self) -> dict:
        """读取配置（带缓存机制）"""
        # 检查文件是否被外部修改过
        if os.path.exists(self.config_path):
            current_mtime = os.path.getmtime(self.config_path)
            # 如果缓存存在且文件未修改，直接返回缓存
            if self._config_cache is not None and current_mtime == self._cache_timestamp:
                return self._config_cache.copy()

        # 重新读取文件
        config = self._read_config_raw()
        if not config:
            print("Config is empty, restoring defaults")
            config = self.default_config.copy()
            self.write_config(config)

        # 检查是否缺失字段（但不删除已有字段）
        repaired = False
        for key in self.default_config:
            if key not in config:
                config[key] = self.default_config[key]
                repaired = True

        if repaired:
            self.write_config(config)

        # 更新缓存
        self._config_cache = config.copy()
        return config

    def get_account_info(self):
        """获取账户信息"""
        config = self.read_config()
        return config.get("account", {})

    def update_account_info(self, account_data: dict):
        """更新账户信息"""
        config = self.read_config()
        if "account" not in config:
            config["account"] = {}
        config["account"].update(account_data)
        self.write_config(config)
