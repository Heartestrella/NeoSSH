# [中文文档](README.md)

# ⚠ Do NOT run in paths containing Chinese characters!!!

# 🖥️ NeoSSH — A Next-Gen Win11-Styled SSH Terminal

A cross-platform SSH client developed based on **[PyQt](https://riverbankcomputing.com/software/pyqt/intro)** and **[QFluentWidgets](https://qfluentwidgets.com/)**.  
Its interface follows the **Windows 11 Fluent Design** style.

Built-in **Remote File Manager** and **Integrated Terminal**, providing a modern, elegant, and efficient remote management experience.

> 💡 Please read this document first. Most common questions can be answered here.

---

## ✨ Features

### 🤖 AI Agent Integration

#### 📋 Sidebar Advanced Mode
Provides more powerful Shell assistance features:
- Configure ChatGPT API or Deepseek, etc. (models compatible with the OpenAI protocol)
- Supports automatic reading of files on the server
- Supports automatic capture of terminal commands, allowing multiple automatic commands without repeated instructions
- Supports modifying file content (requires manual user approval for modifications)
- Supports internet access / deep thinking / referencing server files, etc.
- (Many more powerful O&M features - explore them yourself!)
![AI Sidebar](https://github.com/user-attachments/assets/a8aff7f9-fbea-4d45-822d-8a82da08fae4)

---

### 🎨 Win11 Style UI
- Implements Fluent Design style using QFluentWidgets
- Supports light/dark theme auto-switching (Damn light theme, will delete it eventually)

---

### 🖥 SSH Terminal
Implemented based on `xterm.js` and `QWebEngineView`, supports:
- Command-line interaction
- Command history reuse
- Integrated AI Agent
- Adjustable fonts and color schemes
- Connect to target servers via saved Jumpbox servers (useful for special network environments or other needs)
- Built-in file editor (~~Mini IDEA?~~)

---

### 📂 Remote File Manager
- File upload / download
- File rename / delete / permission modification
- Interaction experience similar to Windows File Explorer
- Icon / List view for files
- Real-time progress and status feedback

![File Manager Example](https://github.com/user-attachments/assets/19b585f9-06b3-4b84-ae4a-9d50d6281d9b)
![Detailed View Example](https://github.com/user-attachments/assets/d5ce4196-a958-4b22-9540-6485143c79ef)

---

### ⚡ Multi-Session Management
- Supports simultaneous connections to multiple remote hosts
- Quick switching between different sessions
- Supports direct session copying / closing

---

### 🛜 Network & System Process Management
- Supports viewing and managing network and system processes
- Displays file upload/download progress with the ability to cancel operations
- Multi-NIC speed viewing
- View network status (Doing)
![Process Management Example](https://github.com/user-attachments/assets/0e85ffb9-dde6-4108-a492-aa059599c18a)

---

### Command Book (Translation errors exist during localization)
- Supports preset custom commands for one-click execution
- Supports import/export of presets and automatic cloud sync
![Command Book](https://github.com/user-attachments/assets/a38cb19d-5637-4621-a55f-ece6c08f2bde)

---

## 🚀 How to Run

### Run from Source Code
1. Ensure Python 3.8+ is installed
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the main program:
   ```bash
   python main_window.py
   ```

---

### Running from Precompiled Version
1. Download the latest version from the **[Releases page](https://github.com/Heartestrella/P-SSH/releases)**
2. Extract the archive
3. Run the executable file

> ✅ System Requirements: Windows 10 or higher

---

## 📷 Interface Screenshots

![Main Interface](https://github.com/user-attachments/assets/1759ad08-e630-415c-bc5e-3624c61f1367)
![Settings Page](https://github.com/user-attachments/assets/836500b3-30fb-4a4f-9899-d3a0db7dd07f)

---

## 🌐 Multilingual Internationalization (i18n)

Currently supports only **Chinese / English**.

> ⚠️ **About Chinese Localization**
> - Localization is updated once per major version
> - Main UI uses `tr()` markers for translation
> - A few tips and messages are not fully translated
> - Future versions will improve language consistency

---

## 📝 Source Code Information

PSSH is still under active development:
- Code structure is being organized and refactored
- Some modules are assisted by AI tools
- Comments are being added and refined

---

## ⚠️ Known Issues and Usage Notes

### 🧭 Tips for Use
- To close tabs in the built-in editor, **double-click the tab title**.

---

### 🧩 Dependencies
If the left sidebar functions do not work, please install the following commands on the remote host:
```bash
sudo apt install -y ss lsblk iostat
```
(Use the corresponding package manager for different distributions)
If issues persist, please submit a bug report
(This function may be incompatible with some hosts; future versions may replace the script with an executable)

---

### 🪟 Other Issues
- Due to Webengine limitations, the software may lag when dragging
- If fonts display incorrectly, ensure the appropriate fonts are installed on your system
- Some UI element styles may slightly differ under certain themes

---

## 🔮 Future Development Directions

- ✅ Fully Python-based terminal rendering
  Current terminal depends on `xterm.js`; future plans include a pure PyQt rendering solution
- 🧱 Plugin-based extension architecture

---

> ⚠️ **Beta Version Note**
> If you encounter any bugs, please submit them to [GitHub Issues](https://github.com/Heartestrella/P-SSH/issues) along with logs and reproduction steps
> PR contributions are welcome and will be reviewed within **3 days**.

---

**💙 NeoSSH — A Fluent, Elegant SSH Experience**