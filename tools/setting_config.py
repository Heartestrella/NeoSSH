from pathlib import Path
import json
import os
import time
import uuid
# Setting Config Manager

config_dir = Path.home() / ".config" / "pyqt-ssh"


class SCM:
    def __init__(self):
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)

        self.default_config = {
            "bg_color": "Dark",  # Dark or Light
            "bg_pic": None,  # Path or None
            "font_size": 12,  # 12-30
            "locked_ratio": True,  # Bool
            "ssh_widget_text_color": "#FFFFFF",  # color code
            "background_opacity": 100,  # int 0-100
            "window_last_width": 720,  # int
            "window_last_height": 680,  # int
            "follow_cd": False,  # bool
            "language": "system",  # system, EN, CN, JP, RU
            "default_view": "icon",  # icon or details
            "max_concurrent_transfers": 10,  # int 1-10
            "compress_upload": False,  # bool compress_upload
            "splitter_lr_ratio": [0.2, 0.8],  # proportion
            "splitter_tb_ratio": [0.6, 0.4],  # proportion
            "maximized": False,  # bool Restore the last maximized state
            "aigc_api_key": "",  # str Your API key for the AI model
            "aigc_open": False,  # bool Whether to enable the AI model feature
            "aigc_model": "DeepSeek",  # str The AI model to use
            "aigc_history_max_length": 10,  # int The max length of history messages
            "splitter_left_components": [0.18, 0.47, 0.35],
            "open_mode": False,  # bool  true:external editor, false: internal viewer
            "external_editor": "",
            # bool Auto-save editor files when focus is lost
            "editor_auto_save_on_focus_lost": False,
            "splitter_sizes": [500, 500],
            "splitter_lr_left_width": 300,
            "bg_theme_color": None,
            "side_panel_last_width": 300,
            "page_animation": "slide_fade",
            "right_panel_ai_chat": True,
            "file_tree_single_click": False,
            "update_channel": "none",
            # User account information
            "account": {"user": "Guest", "avatar_url": r"resource\icons\guest.png", "combo": "", "qid": "", "email": "", "login_key": "", "password": ""},
        }
        self.config_path = config_dir / "setting-config.json"
        if not os.path.exists(self.config_path):
            self.init_config()
            print("Config file created at:", self.config_path)
        else:
            self._check_and_repair_config(self.read_config())

    def write_config(self, config_data):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Failed to write config file: {e}")

    def _check_and_repair_config(self, config: dict) -> dict:

        repaired = False
        for key in self.default_config:
            if key not in config:
                config[key] = self.default_config[key]
                repaired = True
        if repaired:
            self.write_config(config)
        return config

    def init_config(self):
        self.write_config(self.default_config)

    def revise_config(self, key, value):
        config = self.read_config()
        config[key] = value
        # print(config)
        self.write_config(config)

    def read_config(self) -> dict:
        with open(self.config_path, mode="r", encoding="utf-8") as f:
            config_dict = json.load(f)
        return config_dict
