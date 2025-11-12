from pathlib import Path
import json
import os
import time
import uuid

config_dir = Path.home() / ".config" / "pyqt-ssh"


class SCM:
    def __init__(self):
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)

        self.default_config = {
            # ... 您的默认配置 ...
            "bg_color": "Dark",
            "bg_pic": None,
            "font_size": 12,
            # ... 其他配置 ...
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
        self._config_loaded = False  # 标记配置是否已加载

        if not os.path.exists(self.config_path):
            self.init_config()
            print("Config file created at:", self.config_path)
            self._config_loaded = True
        else:
            # 只在初始化时检查和修复一次
            initial_config = self._read_config_raw()
            repaired_config = self._check_and_repair_config(initial_config)
            if repaired_config != initial_config:
                self.write_config(repaired_config)
            self._config_loaded = True

    def _read_config_raw(self):
        """直接读取配置，不进行修复"""
        try:
            with open(self.config_path, mode="r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error reading config: {e}")
            return {}

    def _check_and_repair_config(self, config: dict) -> dict:
        """
        检查并修复配置，包括嵌套字典
        只在初始化时调用一次
        """
        repaired = False
        config_copy = config.copy()  # 创建副本避免修改原数据

        for key, default_value in self.default_config.items():
            if key not in config_copy:
                # 缺失的键，直接添加默认值
                config_copy[key] = default_value
                repaired = True
                print(f"Added missing field: {key}")
            elif isinstance(default_value, dict) and isinstance(config_copy[key], dict):
                # 如果两者都是字典，递归检查嵌套字典
                sub_repaired = self._recursive_repair(
                    config_copy[key], default_value)
                if sub_repaired:
                    repaired = True
            # 移除类型检查，避免干扰用户设置
            # 只有在值完全缺失时才修复

        if repaired:
            print("Config file repaired with missing fields")

        return config_copy

    def _recursive_repair(self, current: dict, default: dict) -> bool:
        """
        递归修复配置字典
        返回布尔值表示是否进行了修复
        """
        repaired = False

        for key, default_value in default.items():
            if key not in current:
                # 只修复缺失的字段，不检查类型
                current[key] = default_value
                repaired = True
                print(f"Added missing nested field: {key}")
            elif isinstance(default_value, dict) and isinstance(current[key], dict):
                # 递归检查嵌套字典
                if self._recursive_repair(current[key], default_value):
                    repaired = True

        return repaired

    def write_config(self, config_data):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Failed to write config file: {e}")

    def init_config(self):
        self.write_config(self.default_config)

    def revise_config(self, key, value):
        config = self.read_config()

        # 支持嵌套键的修改，例如 "account.user"
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
        """读取配置，如果已经初始化过就直接读取"""
        if self._config_loaded:
            # 已经初始化过，直接读取
            return self._read_config_raw()
        else:
            # 第一次读取，进行修复
            initial_config = self._read_config_raw()
            repaired_config = self._check_and_repair_config(initial_config)
            if repaired_config != initial_config:
                self.write_config(repaired_config)
            self._config_loaded = True
            return repaired_config

    def get_account_info(self):
        """获取账户信息的便捷方法"""
        config = self.read_config()
        return config.get("account", {})

    def update_account_info(self, account_data: dict):
        """更新账户信息的便捷方法"""
        config = self.read_config()
        # 合并现有的账户信息，避免覆盖其他字段
        if "account" not in config:
            config["account"] = {}
        config["account"].update(account_data)
        self.write_config(config)
