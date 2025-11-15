## [English Documentation](README_en.md)

# 欢迎加入QQ讨论群: 135106330 备注: NeoSSH

# ⚠ 请勿运行在包含中文的路径中!!!

# 🖥️ NeoSSH — 新时代 Win11 风格 SSH 终端

一个基于 **[PyQt](https://riverbankcomputing.com/software/pyqt/intro)** 与 **[QFluentWidgets](https://qfluentwidgets.com/)** 开发的跨平台 SSH 客户端，  
界面风格贴近 **Windows 11 Fluent Design**。

内置 **远程文件管理器** 与 **集成终端**，提供现代化、优雅且高效的远程管理体验。

> 💡 请先阅读本文件，大部分常见问题都能在这里找到答案。
---

## ✨ 功能特点

### 🤖 AI 智能体接入

#### 📋 侧边栏高级模式
提供更强大的 Shell 辅助功能：
- 请配置ChatGpt Api 或 Deepseek 等兼容Openai协议的模型
- 支持自动读取服务器上文件
- 支持自动捕获终端 多次自动进行指令 不需要多次下达指令
- 支持修改文件内容(需要用户手动允许修改)
- 支持联网/深度思考/引用服务器文件等
- (还有很多powerful的运维功能请自行探索)
![AI 侧边栏](https://github.com/user-attachments/assets/a8aff7f9-fbea-4d45-822d-8a82da08fae4)

---

### 🎨 Win11 风格 UI  
- 使用 QFluentWidgets 实现 Fluent Design 风格  
- 支持亮/暗主题自动切换  (傻逼亮色 迟早删了)

---

### 🖥 SSH 终端  
基于 `xterm.js` 与 `QWebEngineView` 实现，支持：
- 命令行交互  
- 历史指令复用  
- 集成 AI 智能命令输入栏（目前支持 DeepSeek）  
- 可调整字体与配色方案  
- 支持通过已保存的跳板服务器(Jumpbox)连接到目标服务器 (特殊网络环境或其他需求可能有用)
---

### 📂 远程文件管理器  
- 文件上传 / 下载  
- 文件重命名 / 删除 / 权限修改  
- 类似 Windows 资源管理器的交互体验  
- 图标 / 列表两种文件视图  
- 实时进度与状态反馈  

![文件管理器示例](https://github.com/user-attachments/assets/19b585f9-06b3-4b84-ae4a-9d50d6281d9b)
![详细视图示例](https://github.com/user-attachments/assets/d5ce4196-a958-4b22-9540-6485143c79ef)


---

### ⚡ 多会话管理  
- 支持同时连接多个远程主机  
- 快速切换不同会话  
- 支持直接复制 / 关闭会话  

---

### 🛜 网络与系统进程管理  
- 支持查看并操作网络与系统进程  
- 显示文件上传/下载进度，可中止操作
- 多网卡速率查看 
- 查看网路状态(Doing)
![进程管理示例](https://github.com/user-attachments/assets/0e85ffb9-dde6-4108-a492-aa059599c18a)

---

### 指令本 (汉化中有翻译错误)
- 支持预设自定义指令一键执行
- 支持预设的导入导出与自动云同步
![指令本](https://github.com/user-attachments/assets/a38cb19d-5637-4621-a55f-ece6c08f2bde)


---

## 🚀 运行方式

### 从源代码运行
1. 确保已安装 Python 3.8+
2. 安装依赖包：
   ```bash
   pip install -r requirements.txt
   ```
3. 运行主程序：
   ```bash
   python main_window.py
   ```

---

### 从预编译版本运行
1. 从 **[Releases 页面](https://github.com/Heartestrella/P-SSH/releases)** 下载最新版本  
2. 解压缩包  
3. 运行可执行文件即可  

> ✅ 系统要求：Windows 10 或更高版本

---

## 📷 界面截图

![主界面](https://github.com/user-attachments/assets/1759ad08-e630-415c-bc5e-3624c61f1367)
![设置页面](https://github.com/user-attachments/assets/836500b3-30fb-4a4f-9899-d3a0db7dd07f)

---

## 🌐 多语言国际化（i18n）

目前仅支持 **中 / 英** 两种语言。  

> ⚠️ **关于中文汉化**
> - 每隔一个大版本 会更新一次汉化
> - 主要 UI 采用 `tr()` 标记实现  
> - 极少部分提示文字（Tips）未完全翻译  
> - 后续版本会进一步优化语言一致性

---

## 📝 源代码说明

PSSH 仍在持续开发中：
- 代码结构尚在整理与重构中  
- 部分模块由 AI 工具辅助生成  
- 注释正在补充完善  

---

## ⚠️ 已知问题与使用须知

### 🧭 使用技巧
- 内置编辑器的标签页关闭方式为 **双击标签标题**。

---

### 🧩 依赖提示
若左侧栏功能无法使用，请在远程主机安装以下命令：
```bash
sudo apt install -y ss lsblk iostat
```
（不同发行版请使用对应包管理器）
若仍然有问题 请提交此Bug
(此功能存在不兼容部分主机的问题 后续将考虑用可执行文件代替脚本)
---

### 🪟 其他问题
- 由于Webengine的问题 导致软件在拖拽的时候存在卡顿现象
- 若字体显示异常，请确认系统中存在相应字体  
- 部分界面元素的样式在特定主题下可能略有偏差  
---

## 🔮 未来发展方向

- ✅ 完全 Python 实现终端渲染  
  当前终端依赖 `xterm.js`，未来计划使用纯 PyQt 渲染方案
- 🧱 插件式扩展架构  

---

> ⚠️ **Beta 测试版本说明**  
> 若遇到任何 bug，请附带运行日志与复现步骤提交到 [GitHub Issues](https://github.com/Heartestrella/P-SSH/issues)  
> 欢迎提交 PR，我们将在 **3 日内** 审核。

---

**💙 PSSH — A Fluent, Elegant SSH Experience**
