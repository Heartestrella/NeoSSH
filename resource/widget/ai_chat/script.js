const UserInfoManager = {
  state: 'pending',
  data: { name: '加载中...', avatarUrl: null },
  _promise: null,
  _subscribers: new Set(),
  subscribe(callback) {
    this._subscribers.add(callback);
    if (this.state !== 'pending') {
      callback(this.data);
    }
  },
  _notify() {
    for (const callback of this._subscribers) {
      callback(this.data);
    }
  },
  get() {
    if (!this._promise) {
      this._promise = this._fetch()
        .then((userInfo) => {
          this.state = 'resolved';
          this.data = userInfo;
          this._notify();
          return userInfo;
        })
        .catch((error) => {
          console.error('获取用户信息失败:', error);
          this.state = 'failed';
          this.data = { name: '用户', avatarUrl: null };
          this._notify();
          return this.data;
        });
    }
    return this._promise;
  },
  async _fetch() {
    return new Promise((resolve) => {
      initializeBackendConnection(async (backendObject) => {
        if (backendObject) {
          try {
            const qqInfo = await callBackend(backendObject, 'getQQUserInfo');
            if (qqInfo && qqInfo.qq_name && qqInfo.qq_number && qqInfo.qq_name !== '' && qqInfo.qq_number !== '') {
              const avatarUrl = 'http://q.qlogo.cn/headimg_dl?dst_uin=' + qqInfo.qq_number + '&spec=640&img_type=png';
              const userInfo = { name: qqInfo.qq_name, avatarUrl: avatarUrl };
              window.currentUserInfo = userInfo;
              resolve(userInfo);
              return;
            }
          } catch (e) {
            console.error('后端调用失败:', e);
          }
        }
        resolve({ name: '用户', avatarUrl: null });
      });
    });
  },
  update(newUserInfo) {
    this.state = 'resolved';
    this.data = newUserInfo;
    window.currentUserInfo = newUserInfo;
    this._promise = Promise.resolve(newUserInfo);
    this._notify();
  },
};
const pendingRequests = new Map();
const pendingBackendCalls = new Map();
const ABORTABLE_TOOLS_WHITELIST = ['exe_shell', 'fetchWeb'];
function isToolAbortable(toolName) {
  const normalizedToolName = toolName.includes('->') ? toolName.split('->')[1].trim() : toolName;
  return ABORTABLE_TOOLS_WHITELIST.includes(normalizedToolName);
}
function generateUniqueId() {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}
async function callBackend(backendObject, methodName, args = null) {
  return new Promise((resolve, reject) => {
    const requestId = generateUniqueId();
    const handler = async (receivedId, resultJson) => {
      if (receivedId === requestId) {
        cleanup();
        try {
          const result = JSON.parse(resultJson);
          if (result.status === 'error') {
            console.error(result);
            resolve(await callBackend(backendObject, methodName, args));
          } else {
            resolve(result);
          }
        } catch (e) {
          resolve(resultJson);
        }
      }
    };
    const cleanup = () => {
      backendObject.backendCallReady.disconnect(handler);
      pendingBackendCalls.delete(requestId);
    };
    pendingBackendCalls.set(requestId, {
      methodName,
      handler,
      startTime: Date.now(),
    });
    backendObject.backendCallReady.connect(handler);
    try {
      const argsJson = args !== null ? JSON.stringify(args) : '';
      backendObject.callBackend(requestId, methodName, argsJson);
    } catch (error) {
      cleanup();
      reject(error);
    }
  });
}
function getPendingBackendCalls() {
  const calls = [];
  for (const [id, info] of pendingBackendCalls) {
    calls.push({
      id,
      method: info.methodName,
      duration: Date.now() - info.startTime,
    });
  }
  return calls;
}
function isContextLengthError(errorJson) {
  if (errorJson.error?.code === 'context_length_exceeded') {
    return true;
  }
  const message = (errorJson.error?.message || '').toLowerCase();
  const keywords = ['maximum context length', 'context length', 'context window', 'token limit', 'tokens exceed', 'too many tokens', 'requested too many tokens'];
  return keywords.some((keyword) => message.includes(keyword));
}
function cleanupRequest(requestId) {
  const request = pendingRequests.get(requestId);
  if (request && request.handler) {
    backend.toolResultReady.disconnect(request.handler);
  }
  pendingRequests.delete(requestId);
}
function setQQUserInfo(qq_name, qq_number) {
  let messageId = generateUniqueId();
  if (!window.ws) {
    return;
  }
  if (window.ws.readyState === WebSocket.CONNECTING) {
    return;
  }
  if (qq_name == null || qq_number == null || qq_name == '' || qq_number == '') {
    return;
  }
  window.ws.send(JSON.stringify({ action: 'setQQUser', data: JSON.stringify({ qq_name, qq_number, id: messageId }) }));
  const avatarUrl = 'http://q.qlogo.cn/headimg_dl?dst_uin=' + qq_number + '&spec=640&img_type=png';
  const newUserInfo = { name: qq_name, avatarUrl: avatarUrl };
  UserInfoManager.update(newUserInfo);
}
window.OnlineUser = {};
window.setQQUserInfo = setQQUserInfo;
window.currentUserInfo = { name: '用户', avatarUrl: null };
function updateTokenUsage() {
  return new Promise(async (resolve) => {
    const tokenElement = document.getElementById('token-count');
    const rawCountStr = await callBackend(backend, 'getTokenUsage', [aiChatApiOptionsBody.messages]);
    const num = parseInt(rawCountStr, 10);
    if (isNaN(num)) {
      tokenElement.textContent = rawCountStr;
      resolve();
      return;
    }
    let displayText = num.toString();
    if (num >= 1000000) {
      displayText += ` (${(num / 1000000).toFixed(1)}M)`;
    } else if (num >= 1000) {
      displayText += ` (${(num / 1000).toFixed(1)}K)`;
    }
    tokenElement.textContent = displayText;
    resolve();
  });
}
async function executeMcpTool(serverName, toolName, args, providedRequestId = null) {
  return new Promise((resolve, reject) => {
    const requestId = providedRequestId || generateUniqueId();
    const handler = (receivedId, result) => {
      if (receivedId === requestId) {
        const request = pendingRequests.get(requestId);
        const wasCancelled = request && request.cancelled;
        cleanupRequest(requestId);
        try {
          const parsedResult = JSON.parse(result);
          if (parsedResult.status === 'cancelled') {
            if (wasCancelled) {
              resolve(result);
            } else {
              reject(new Error(parsedResult.content));
            }
          } else {
            resolve(result);
          }
        } catch (e) {
          resolve(result);
        }
      }
    };
    pendingRequests.set(requestId, {
      handler,
      reject,
      serverName,
      toolName,
      startTime: Date.now(),
    });
    backend.toolResultReady.connect(handler);
    try {
      backend.executeMcpTool(serverName, toolName, args, requestId);
    } catch (error) {
      cleanupRequest(requestId);
      reject(error);
    }
  });
}
function getPendingRequests() {
  const requests = [];
  for (const [id, info] of pendingRequests) {
    requests.push({
      id,
      tool: `${info.serverName}.${info.toolName}`,
      duration: Date.now() - info.startTime,
    });
  }
  return requests;
}
function cancelMcpRequest(requestId) {
  const request = pendingRequests.get(requestId);
  if (request) {
    request.cancelled = true;
    backend.cancelMcpTool(requestId);
  }
}
function copyToClipboard(text, buttonElement) {
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.style.position = 'fixed';
  textarea.style.opacity = 0;
  document.body.appendChild(textarea);
  textarea.select();
  try {
    document.execCommand('copy');
    const originalTitle = buttonElement.title;
    buttonElement.title = '已复制!';
    setTimeout(() => {
      buttonElement.title = originalTitle;
    }, 2000);
  } catch (err) {
    console.error('Fallback: Oops, unable to copy', err);
    const originalTitle = buttonElement.title;
    buttonElement.title = '复制失败!';
    setTimeout(() => {
      buttonElement.title = originalTitle;
    }, 2000);
  }
  document.body.removeChild(textarea);
}
class ChatController {
  constructor(chatBodySelector) {
    this.chatBody = document.querySelector(chatBodySelector);
    if (!this.chatBody) {
      throw new Error(`Container element '${chatBodySelector}' not found.`);
    }
    this.userHasScrolled = false;
    this.chatBody.addEventListener('scroll', () => {
      const threshold = 15;
      const isAtBottom = this.chatBody.scrollHeight - this.chatBody.scrollTop - this.chatBody.clientHeight < threshold;
      this.userHasScrolled = !isAtBottom;
    });
  }
  scrollToBottom() {
    setTimeout(() => {
      this.chatBody.scrollTop = this.chatBody.scrollHeight;
    }, 100);
  }
  addUserBubble(text, imageUrls, messageIndex = -1, historyIndex = -1) {
    return new Promise(async (resolve) => {
      const bubble = new UserBubble();
      await bubble.init(this.chatBody, messageIndex, historyIndex);
      bubble.setContent(text, imageUrls);
      this.userHasScrolled = false;
      this.scrollToBottom();
      resolve(bubble);
    });
  }
  addAIBubble(messageIndex = -1, historyIndex = -1) {
    const bubble = new AIBubble(this.chatBody, this, messageIndex, historyIndex);
    return bubble;
  }
  addSystemBubble(toolName, code, relatedMessageIndex = -1, historyIndex = -1) {
    const bubble = new SystemBubble(this.chatBody, relatedMessageIndex, historyIndex);
    bubble.setToolCall(toolName, code);
    return bubble;
  }
}
class UserBubble {
  init(container, messageIndex = -1, historyIndex = -1) {
    return new Promise(async (resolve) => {
      const senderName = UserInfoManager.data.name;
      const senderIcon = UserInfoManager.data.avatarUrl ? `<img src="${UserInfoManager.data.avatarUrl}" style="width:64px;height:64px; border-radius: 50%; object-fit: cover;" />` : '<svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" clip-rule="evenodd"></path></svg>';
      const template = `<div class="message-group user"${messageIndex >= 0 ? ` data-message-index="${messageIndex}"` : ''}${historyIndex >= 0 ? ` data-history-index="${historyIndex}"` : ''}>
              <div class="message-wrapper">
                <div class="message-sender">
                  <div class="message-actions">
                    <button class="copy-button" title="复制">
                      <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                        <path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/>
                        <path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/>
                      </svg>
                    </button>
                    <button class="edit-button" title="编辑">
                      <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                        <path d="M12.146.146a.5.5 0 0 1 .708 0l3 3a.5.5 0 0 1 0 .708l-10 10a.5.5 0 0 1-.168.11l-5 2a.5.5 0 0 1-.65-.65l2-5a.5.5 0 0 1 .11-.168l10-10zM11.207 2.5 13.5 4.793 14.793 3.5 12.5 1.207 11.207 2.5zm1.586 3L10.5 3.207 4 9.707V10h.5a.5.5 0 0 1 .5.5v.5h.5a.5.5 0 0 1 .5.5v.5h.293l6.5-6.5zm-9.761 5.175-.106.106-1.528 3.821 3.821-1.528.106-.106A.5.5 0 0 1 5 12.5V12h-.5a.5.5 0 0 1-.5-.5V11h-.5a.5.5 0 0 1-.468-.325z"/>
                      </svg>
                    </button>
                    <button class="retry-button" title="重试">
                      <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                        <path d="M11.534 7h3.932a.25.25 0 0 1 .192.41l-1.966 2.36a.25.25 0 0 1-.384 0l-1.966-2.36a.25.25 0 0 1 .192-.41zm-11 2h3.932a.25.25 0 0 0 .192-.41L2.692 6.23a.25.25 0 0 0-.384 0L.342 8.59A.25.25 0 0 0 .534 9z"/>
                        <path fill-rule="evenodd" d="M8 3c-1.552 0-2.94.707-3.857 1.818a.5.5 0 1 1-.771-.636A6.002 6.002 0 0 1 13.917 7H12.9A5.002 5.002 0 0 0 8 3zM3.1 9a5.002 5.002 0 0 0 8.757 2.182.5.5 0 1 1 .771.636A6.002 6.002 0 0 1 2.083 9H3.1z"/>
                      </svg>
                    </button>
                    <button class="delete-button" title="删除">
                      <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                        <path d="M5.5 5.5A.5.5 0 0 1 6 6v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5zm2.5 0a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5zm3 .5a.5.5 0 0 0-1 0v6a.5.5 0 0 0 1 0V6z"/>
                        <path fill-rule="evenodd" d="M14.5 3a1 1 0 0 1-1 1H13v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4h-.5a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1H6a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1h3.5a1 1 0 0 1 1 1v1zM4.118 4 4 4.059V13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V4.059L11.882 4H4.118zM2.5 3V2h11v1h-11z"/>
                      </svg>
                    </button>
                  </div>
                  <div>${senderName}</div>
                </div>
                <div class="user-response"></div>
              </div>
              <span class="icon">${senderIcon}</span>
            </div>`;
      container.insertAdjacentHTML('beforeend', template);
      this.element = container.lastElementChild;
      this.contentElement = this.element.querySelector('.user-response');
      this.messageIndex = messageIndex;
      this.historyIndex = historyIndex;
      this.bindEventListeners();
      resolve();
    });
  }
  bindEventListeners() {
    const copyBtn = this.element.querySelector('.copy-button');
    const editBtn = this.element.querySelector('.edit-button');
    const retryBtn = this.element.querySelector('.retry-button');
    const deleteBtn = this.element.querySelector('.delete-button');
    if (copyBtn) {
      copyBtn.addEventListener('click', () => {
        copyToClipboard(this.contentElement.textContent, copyBtn);
      });
    }
    if (editBtn) {
      editBtn.addEventListener('click', () => editUserMessage(this.element));
    }
    if (retryBtn) {
      retryBtn.addEventListener('click', () => retryUserMessage(this.element));
    }
    if (deleteBtn) {
      deleteBtn.addEventListener('click', () => deleteUserMessage(this.element));
    }
  }
  setContent(text, imageUrls) {
    this.contentElement.innerHTML = '';
    if (text) {
      const textBlock = document.createElement('div');
      textBlock.className = 'user-text-block';
      textBlock.textContent = text;
      this.contentElement.appendChild(textBlock);
    }
    if (imageUrls && imageUrls.length > 0) {
      const imageContainer = document.createElement('div');
      imageContainer.style.display = 'flex';
      imageContainer.style.flexWrap = 'wrap';
      imageContainer.style.gap = '10px';
      imageContainer.style.marginTop = text ? '10px' : '0';
      imageUrls.forEach((url) => {
        const img = document.createElement('img');
        img.src = url;
        img.style.maxWidth = '150px';
        img.style.maxHeight = '150px';
        img.style.borderRadius = '8px';
        img.style.objectFit = 'cover';
        imageContainer.appendChild(img);
      });
      this.contentElement.appendChild(imageContainer);
    }
  }
}
class AIBubble {
  constructor(container, chatController, messageIndex = -1, historyIndex = -1) {
    const template = `<div class="message-group ai"${messageIndex >= 0 ? ` data-message-index="${messageIndex}"` : ''}${historyIndex >= 0 ? ` data-history-index="${historyIndex}"` : ''}>
              <div class="message-sender">
                <span class="icon">💬</span>
                <div>智能助手</div>
                <span class="request-duration" style="margin-left:4px; color: #888; font-size: 16px; display: none;">⏱️ 0.00s</span>
                <div class="message-actions">
                  <button class="copy-button" title="复制">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                      <path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/>
                      <path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/>
                    </svg>
                  </button>
                  <button class="retry-button" title="重试">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                      <path d="M11.534 7h3.932a.25.25 0 0 1 .192.41l-1.966 2.36a.25.25 0 0 1-.384 0l-1.966-2.36a.25.25 0 0 1 .192-.41zm-11 2h3.932a.25.25 0 0 0 .192-.41L2.692 6.23a.25.25 0 0 0-.384 0L.342 8.59A.25.25 0 0 0 .534 9z"/>
                      <path fill-rule="evenodd" d="M8 3c-1.552 0-2.94.707-3.857 1.818a.5.5 0 1 1-.771-.636A6.002 6.002 0 0 1 13.917 7H12.9A5.002 5.002 0 0 0 8 3zM3.1 9a5.002 5.002 0 0 0 8.757 2.182.5.5 0 1 1 .771.636A6.002 6.002 0 0 1 2.083 9H3.1z"/>
                    </svg>
                  </button>
                  <button class="delete-button" title="删除">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                      <path d="M5.5 5.5A.5.5 0 0 1 6 6v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5zm2.5 0a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5zm3 .5a.5.5 0 0 0-1 0v6a.5.5 0 0 0 1 0V6z"/>
                      <path fill-rule="evenodd" d="M14.5 3a1 1 0 0 1-1 1H13v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4h-.5a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1H6a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1h3.5a1 1 0 0 1 1 1v1zM4.118 4 4 4.059V13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V4.059L11.882 4H4.118zM2.5 3V2h11v1h-11z"/>
                    </svg>
                  </button>
                </div>
              </div>
              <div class="thinking-container" style="display: none;">
                <div class="thinking-header">
                  <span class="thinking-icon">🤔</span>
                  <span class="thinking-title">深度思考</span>
                  <button class="thinking-toggle">▲</button>
                </div>
                <div class="thinking-content"></div>
              </div>
              <div class="message-content"></div>
              <div class="list-options-container" style="display: none;">
                <div class="list-options-header">
                  <span class="list-options-title path-value"></span>
                  <button class="list-options-toggle">▲</button>
                </div>
                <div class="list-options-content"></div>
              </div>
            </div>`;
    container.insertAdjacentHTML('beforeend', template);
    this.element = container.lastElementChild;
    this.contentElement = this.element.querySelector('.message-content');
    this.durationElement = this.element.querySelector('.request-duration');
    this.thinkingContainer = this.element.querySelector('.thinking-container');
    this.thinkingHeader = this.element.querySelector('.thinking-header');
    this.thinkingContent = this.element.querySelector('.thinking-content');
    this.thinkingToggle = this.element.querySelector('.thinking-toggle');
    this.listOptionsContainer = this.element.querySelector('.list-options-container');
    this.listOptionsHeader = this.element.querySelector('.list-options-header');
    this.listOptionsTitle = this.element.querySelector('.list-options-title');
    this.listOptionsContent = this.element.querySelector('.list-options-content');
    this.listOptionsToggle = this.element.querySelector('.list-options-toggle');
    this.requestStartTime = null;
    this.durationInterval = null;
    this.finalDuration = null;
    this.fullContent = '';
    this.fullThinkingContent = '';
    this.translatedThinkingContent = '';
    this.contentSentForTranslation = '';
    this.translationDebounceTimer = null;
    this.isThinkingStreamFinished = false;
    this.isTranslating = false;
    this.isStreaming = false;
    this.isThinkingStreaming = false;
    this.thinkingUserHasScrolled = false;
    this.chatController = chatController;
    this.messageIndex = messageIndex;
    this.historyIndex = historyIndex;
    this.bindEventListeners();
  }
  bindEventListeners() {
    const copyBtn = this.element.querySelector('.copy-button');
    const retryBtn = this.element.querySelector('.retry-button');
    const deleteBtn = this.element.querySelector('.delete-button');
    if (copyBtn) {
      copyBtn.addEventListener('click', () => {
        copyToClipboard(this.fullContent, copyBtn);
      });
    }
    if (retryBtn) {
      retryBtn.addEventListener('click', () => retryAIMessage(this.element));
    }
    if (deleteBtn) {
      deleteBtn.addEventListener('click', () => deleteAIMessage(this.element));
    }
    if (this.thinkingHeader) {
      this.thinkingHeader.addEventListener('click', () => this.toggleThinking());
    }
    if (this.thinkingContent) {
      this.thinkingContent.addEventListener('scroll', () => {
        const threshold = 5;
        const isAtBottom = this.thinkingContent.scrollHeight - this.thinkingContent.scrollTop - this.thinkingContent.clientHeight < threshold;
        this.thinkingUserHasScrolled = !isAtBottom;
      });
    }
    if (this.listOptionsHeader) {
      this.listOptionsHeader.addEventListener('click', () => this.toggleListOptions());
    }
  }
  updateThinking(chunk) {
    if (this.thinkingContainer.style.display === 'none') {
      this.thinkingContainer.style.display = 'block';
    }
    if (!this.isThinkingStreaming) {
      this.isThinkingStreaming = true;
      this.fullThinkingContent = '';
    }
    this.fullThinkingContent += chunk;
    const dirtyHtml = marked.parse(this.fullThinkingContent);
    this.thinkingContent.innerHTML = DOMPurify.sanitize(dirtyHtml) + '<div class="loader"></div>';
    if (!this.thinkingUserHasScrolled) {
      this.thinkingContent.scrollTop = this.thinkingContent.scrollHeight;
    }
    if (this.chatController && !this.chatController.userHasScrolled) {
      this.chatController.scrollToBottom();
    }
    clearTimeout(this.translationDebounceTimer);
  }
  finishThinking() {
    this.isThinkingStreaming = false;
    this.isThinkingStreamFinished = true;
    if (this.fullThinkingContent) {
      const dirtyHtml = marked.parse(this.fullThinkingContent);
      this.thinkingContent.innerHTML = DOMPurify.sanitize(dirtyHtml);
    }
    clearTimeout(this.translationDebounceTimer);
    this.triggerTranslation();
  }
  renderTranslatedContent() {
    if (!this.element.isConnected) {
      return;
    }
    const untranslatedTail = this.fullThinkingContent.substring(this.contentSentForTranslation.length);
    const displayContent = this.translatedThinkingContent + untranslatedTail;
    let finalHtml = DOMPurify.sanitize(marked.parse(displayContent));
    if (this.isThinkingStreaming || this.isTranslating) {
      finalHtml += '<div class="loader"></div>';
    }
    this.thinkingContent.innerHTML = finalHtml;
    if (!this.thinkingUserHasScrolled) {
      this.thinkingContent.scrollTop = this.thinkingContent.scrollHeight;
    }
  }
  updateThinkingTitle() {
    const titleSpan = this.element.querySelector('.thinking-title');
    if (!titleSpan) return;
    if (this.isTranslating) {
      titleSpan.innerHTML = '深度思考 [正在翻译] <svg class="translating-spinner" width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-dasharray="31.4 31.4" stroke-dashoffset="0"/></svg>';
    } else {
      titleSpan.textContent = '深度思考';
    }
  }
  async triggerTranslation() {
    if (!this.element.isConnected || this.reasoningTranslated) {
      return;
    }
    const newTextToTranslate = this.fullThinkingContent.substring(this.contentSentForTranslation.length);
    if (newTextToTranslate.trim() === '') {
      if (this.isThinkingStreamFinished && this.translatedThinkingContent) {
        this._finalizeTranslation();
      }
      return;
    }
    this.contentSentForTranslation += newTextToTranslate;
    if (!this.isTranslating) {
      this.isTranslating = true;
      this.updateThinkingTitle();
    }
    try {
      const detectResult = await callBackend(backend, 'detectLanguage', [newTextToTranslate]);
      const isTargetLanguage = detectResult.language === window.SystemLanguage.split('-')[0];
      const translatedText = isTargetLanguage ? newTextToTranslate : await callBackend(backend, 'translateText', [newTextToTranslate, window.SystemLanguage]);
      if (!this.element.isConnected) {
        return;
      }
      if (translatedText) {
        this.translatedThinkingContent += translatedText;
        this.renderTranslatedContent();
      }
      if (this.isThinkingStreamFinished && this.contentSentForTranslation.length === this.fullThinkingContent.length) {
        this._finalizeTranslation();
      }
    } catch (error) {
      console.error('翻译失败:', error);
      this.contentSentForTranslation = this.contentSentForTranslation.slice(0, this.contentSentForTranslation.length - newTextToTranslate.length);
    }
  }
  async _finalizeTranslation() {
    this.isTranslating = false;
    this.updateThinkingTitle();
    if (window.messagesHistory[this.historyIndex]) {
      window.messagesHistory[this.historyIndex].messages.reasoning = this.translatedThinkingContent;
      window.messagesHistory[this.historyIndex].messages.reasoningTranslated = true;
      await saveHistory(window.firstUserMessage, window.messagesHistory);
      const dirtyHtml = marked.parse(this.translatedThinkingContent);
      this.thinkingContent.innerHTML = DOMPurify.sanitize(dirtyHtml);
    }
  }
  toggleThinking(forceState) {
    const isCollapsed = this.thinkingContainer.classList.contains('collapsed');
    let shouldBeOpen;
    if (forceState === 'open') {
      shouldBeOpen = true;
    } else if (forceState === 'closed') {
      shouldBeOpen = false;
    } else {
      shouldBeOpen = isCollapsed;
    }
    if (shouldBeOpen) {
      this.thinkingContainer.classList.remove('collapsed');
    } else {
      this.thinkingContainer.classList.add('collapsed');
    }
  }
  getHtml() {
    return this.contentElement.innerHTML;
  }
  setHTML(markdown) {
    if (isEmptyObject(markdown)) {
      return;
    }
    try {
      this.isStreaming = false;
      this.fullContent = markdown;
      const dirtyHtml = marked.parse(markdown);
      const cleanHtml = DOMPurify.sanitize(dirtyHtml);
      this.contentElement.innerHTML = cleanHtml;
      if (this.chatController && !this.chatController.userHasScrolled) {
        this.chatController.scrollToBottom();
      }
    } catch (e) {
      console.log(e);
      debugger;
      throw new Error('setHTML error');
    }
  }
  updateStream(chunk) {
    if (!this.isStreaming) {
      this.isStreaming = true;
      this.fullContent = '';
    }
    this.fullContent += chunk;
    const dirtyHtml = marked.parse(this.fullContent);
    const cleanHtml = DOMPurify.sanitize(dirtyHtml);
    this.contentElement.innerHTML = cleanHtml + '<div class="loader"></div>';
    if (this.chatController && !this.chatController.userHasScrolled) {
      this.chatController.scrollToBottom();
    }
  }
  finishStream() {
    this.isStreaming = false;
    const dirtyHtml = marked.parse(this.fullContent);
    const cleanHtml = DOMPurify.sanitize(dirtyHtml);
    this.contentElement.innerHTML = cleanHtml;
    if (this.chatController && !this.chatController.userHasScrolled) {
      this.chatController.scrollToBottom();
    }
  }
  _getDurationColor(seconds) {
    if (seconds < 30) {
      return '#22c55e';
    } else if (seconds < 90) {
      return '#eab308';
    } else {
      return '#ef4444';
    }
  }
  startDuration() {
    this.requestStartTime = Date.now();
    this.durationElement.style.display = 'inline';
    this.durationInterval = setInterval(() => {
      if (this.requestStartTime) {
        const elapsed = (Date.now() - this.requestStartTime) / 1000;
        this.durationElement.style.color = this._getDurationColor(elapsed);
        this.durationElement.textContent = `⏱️ ${elapsed.toFixed(2)}s`;
      }
    }, 100);
  }
  finishDuration() {
    if (this.durationInterval) {
      clearInterval(this.durationInterval);
      this.durationInterval = null;
    }
    if (this.requestStartTime) {
      this.finalDuration = (Date.now() - this.requestStartTime) / 1000;
      this.durationElement.style.color = this._getDurationColor(this.finalDuration);
      this.durationElement.textContent = `⏱️ ${this.finalDuration.toFixed(2)}s`;
      this.durationElement.style.display = 'inline';
    }
  }
  setDuration(duration) {
    if (duration && duration > 0) {
      this.finalDuration = duration;
      this.durationElement.style.color = this._getDurationColor(duration);
      this.durationElement.textContent = `⏱️ ${duration.toFixed(2)}s`;
      this.durationElement.style.display = 'inline';
    } else {
      this.durationElement.style.display = 'none';
    }
  }
  getDuration() {
    return this.finalDuration;
  }
  setListOptions(title = '快速回复', options) {
    if (!options || options.length === 0) {
      return;
    }
    this.listOptionsTitle.textContent = title;
    this.listOptionsContent.innerHTML = '';
    options.forEach((optionText) => {
      const optionElement = document.createElement('div');
      optionElement.className = 'list-option-item';
      optionElement.textContent = optionText;
      this.listOptionsContent.appendChild(optionElement);
      optionElement.addEventListener('click', () => {
        const messageInput = document.querySelector('#message-input');
        if (messageInput) {
          messageInput.value = optionText;
        }
        const sendButton = document.querySelector('.send-button');
        if (sendButton) {
          sendButton.click();
        }
        this.listOptionsContainer.style.display = 'none';
      });
    });
    this.listOptionsContainer.style.display = 'block';
    if (this.chatController && !this.chatController.userHasScrolled) {
      this.chatController.scrollToBottom();
    }
  }
  toggleListOptions() {
    this.listOptionsContainer.classList.toggle('collapsed');
  }
}
class SystemBubble {
  constructor(container, relatedMessageIndex = -1, historyIndex = -1) {
    const template = `<div class="message-group system"${relatedMessageIndex >= 0 ? ` data-related-message-index="${relatedMessageIndex}"` : ''}${historyIndex >= 0 ? ` data-history-index="${historyIndex}"` : ''}>
              <div class="tool-call-card">
                <div class="tool-call-header">
                  <span class="tool-name"></span>
                  <div class="tool-status-icon"><div class="loader"></div></div>
                </div>
                <div class="tool-call-body">
                  <div class="code-block"></div>
                </div>
                <div class="tool-call-result" style="display: none;">
                  <div class="code-block"></div>
                </div>
              </div>
            </div>`;
    container.insertAdjacentHTML('beforeend', template);
    this.element = container.lastElementChild;
    this.toolCardElement = this.element.querySelector('.tool-call-card');
    this.toolNameElement = this.element.querySelector('.tool-name');
    this.detailElement = this.element.querySelector('.tool-call-body .code-block');
    this.bodyContainer = this.element.querySelector('.tool-call-body');
    this.resultContainer = this.element.querySelector('.tool-call-result');
    this.resultContentElement = this.element.querySelector('.tool-call-result .code-block');
    this.headerElement = this.element.querySelector('.tool-call-header');
    this.statusIconElement = this.element.querySelector('.tool-status-icon');
    this.detailElement.style.maxHeight = '400px';
    this.detailElement.style.overflow = 'auto';
    this.resultContentElement.style.maxHeight = '400px';
    this.resultContentElement.style.overflow = 'auto';
  }
  isDangerousTool(toolName, detail) {
    if (!toolName.toLowerCase().includes('exe_shell')) {
      return [];
    }
    const dangerousCommands = ['rm', 'chmod', 'mv', 'killall', 'kill', 'mkfs'];
    let argsXml = detail;
    let shellCommand = '';
    try {
      argsXml = JSON.parse(detail);
      const shellMatch = argsXml.match(/<shell>([\s\S]*?)<\/shell>/);
      if (shellMatch && shellMatch[1]) {
        shellCommand = shellMatch[1];
      } else {
        return [];
      }
    } catch (e) {
      return [];
    }
    const foundCommands = new Set();
    const regex = new RegExp(`\\b(${dangerousCommands.join('|')})\\b`, 'gi');
    let match;
    while ((match = regex.exec(shellCommand)) !== null) {
      foundCommands.add(match[0].toLowerCase());
    }
    return Array.from(foundCommands);
  }
  _prettyPrintXml(xml) {
    const PADDING = '  ';
    const reg = /(>)(<)(\/*)/g;
    let pad = 0;
    xml = xml.replace(reg, '$1\n$2$3');
    return xml
      .split('\n')
      .map((node) => {
        let indent = 0;
        if (node.match(/.+<\/\w[^>]*>$/)) {
          indent = 0;
        } else if (node.match(/^<\/\w/)) {
          if (pad !== 0) {
            pad -= 1;
          }
        } else if (node.match(/^<\w[^>]*[^\/]>.*$/)) {
          indent = 1;
        }
        const padding = PADDING.repeat(pad);
        pad += indent;
        return padding + node;
      })
      .join('\n');
  }
  _formatAndHighlight(code) {
    let content = code.trim();
    if (content.startsWith('"') && content.endsWith('"')) {
      content = content.substring(1, content.length - 1);
    }
    try {
      const jsonObj = JSON.parse(content);
      const formatted = JSON.stringify(jsonObj, null, 2);
      return hljs.highlight(formatted, { language: 'json' }).value;
    } catch (e) {}
    const trimmedContent = content.trim();
    if (trimmedContent.startsWith('<') && trimmedContent.endsWith('>')) {
      const unescapedContent = content.replace(/\\n/g, '\n');
      const formattedXml = this._prettyPrintXml(unescapedContent);
      return hljs.highlight(formattedXml, { language: 'xml' }).value;
    }
    return hljs.highlight(code, { language: 'plaintext' }).value;
  }
  setToolCall(toolName, detail) {
    this.toolNameElement.textContent = toolName;
    const dangerousCmds = this.isDangerousTool(toolName, detail);
    if (toolName.toLowerCase().includes('exe_shell') && dangerousCmds.length > 0) {
      this.toolCardElement.classList.add('dangerous');
      this.toolNameElement.innerHTML = '⚠️ ' + this.toolNameElement.textContent;
      try {
        let argsXml = JSON.parse(detail);
        const shellMatch = argsXml.match(/<shell>([\s\S]*?)<\/shell>/);
        const cwdMatch = argsXml.match(/<cwd>([\s\S]*?)<\/cwd>/);
        if (shellMatch) {
          const fullCommand = shellMatch[1];
          const escapedCmds = dangerousCmds.map((cmd) => cmd.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
          const regex = new RegExp(`(\\b(?:${escapedCmds.join('|')})\\b)`, 'gi');
          const parts = fullCommand.split(regex);
          this.detailElement.innerHTML = '';
          this.detailElement.appendChild(document.createTextNode('<exe_shell>\n  <shell>'));
          parts.forEach((part) => {
            if (part) {
              if (dangerousCmds.includes(part.toLowerCase())) {
                const dangerousSpan = document.createElement('span');
                dangerousSpan.className = 'dangerous-command';
                dangerousSpan.textContent = part;
                this.detailElement.appendChild(dangerousSpan);
              } else {
                this.detailElement.appendChild(document.createTextNode(part));
              }
            }
          });
          this.detailElement.appendChild(document.createTextNode('</shell>'));
          if (cwdMatch) {
            this.detailElement.appendChild(document.createTextNode(`\n  <cwd>${cwdMatch[1]}</cwd>`));
          }
          this.detailElement.appendChild(document.createTextNode('\n</exe_shell>'));
        } else {
          this.detailElement.innerHTML = this._formatAndHighlight(detail);
        }
      } catch (e) {
        this.detailElement.innerHTML = this._formatAndHighlight(detail);
      }
    } else {
      this.detailElement.innerHTML = this._formatAndHighlight(detail);
    }
  }
  setCollapsed() {
    if (this.toolCardElement.classList.contains('collapsed')) {
      return;
    }
    this.toolCardElement.classList.add('collapsed');
  }
  setResult(status, content) {
    this.statusIconElement.innerHTML = '';
    setTimeout(() => {
      if (this.toolCardElement.classList.contains('collapsed')) {
        return;
      }
      this.toolCardElement.classList.add('collapsed');
    }, 12000);
    if (status === 'approved') {
      let longContent = false;
      if (content.length > 10000) {
        longContent = true;
      }
      if (!longContent) {
        this.resultContentElement.innerHTML = this._formatAndHighlight(content);
      } else {
        this.resultContentElement.textContent = content;
      }
      this.resultContainer.style.display = 'block';
      this.statusIconElement.textContent = '▼';
      this.statusIconElement.classList.add('success');
      this.headerElement.addEventListener('click', () => {
        const isCollapsed = this.toolCardElement.classList.contains('collapsed');
        if (isCollapsed) {
          this.toolCardElement.classList.remove('collapsed');
          this.statusIconElement.textContent = '▲';
        } else {
          this.toolCardElement.classList.add('collapsed');
          this.statusIconElement.textContent = '▼';
        }
      });
    } else if (status === 'rejected') {
      this.statusIconElement.textContent = '❌';
      this.resultContainer.style.display = 'none';
      this.headerElement.addEventListener('click', () => {
        const isCollapsed = this.toolCardElement.classList.contains('collapsed');
        if (isCollapsed) {
          this.toolCardElement.classList.remove('collapsed');
        } else {
          this.toolCardElement.classList.add('collapsed');
        }
      });
    }
  }
  async requireApproval() {
    return new Promise((resolve) => {
      const approvalContainer = document.getElementById('approve-reject-buttons');
      const approveBtn = approvalContainer.querySelector('.cmd-button');
      const rejectBtn = approvalContainer.querySelector('.reject-button');
      approvalContainer.style.display = 'flex';
      const cleanup = () => {
        approvalContainer.style.display = 'none';
        approveBtn.replaceWith(approveBtn.cloneNode(true));
        rejectBtn.replaceWith(rejectBtn.cloneNode(true));
      };
      approveBtn.addEventListener(
        'click',
        () => {
          cleanup();
          resolve('approved');
        },
        { once: true },
      );
      rejectBtn.addEventListener(
        'click',
        () => {
          cleanup();
          resolve('rejected');
        },
        { once: true },
      );
    });
  }
}
let pastedImageDataUrls = [];
function editUserMessage(bubbleElement) {
  return new Promise(async (resolve) => {
    const messageIndex = parseInt(bubbleElement.dataset.messageIndex);
    const historyIndex = parseInt(bubbleElement.dataset.historyIndex);
    if (isNaN(historyIndex) || historyIndex < 0) {
      console.error('Invalid history index');
      return;
    }
    const messageItem = window.messagesHistory[historyIndex];
    if (!messageItem || messageItem.messages.role !== 'user' || messageItem.isMcp) {
      console.error('Can only edit user messages');
      return;
    }
    const messageContent = messageItem.messages.content;
    let text = '';
    let images = [];
    if (Array.isArray(messageContent)) {
      messageContent.forEach((item) => {
        if (item.type === 'text') {
          if (!item.text.startsWith('<附加系统数据>')) {
            text = item.text || '';
          }
        } else if (item.type === 'image_url' && item.image_url) {
          images.push(item.image_url.url);
        }
      });
    } else if (typeof messageContent === 'string') {
      text = messageContent;
    }
    await truncateFromMessage(messageIndex, historyIndex);
    const messageInput = document.querySelector('#message-input');
    if (messageInput) {
      messageInput.value = text;
      updateHighlights();
    }
    pastedImageDataUrls = [...images];
    renderImagePreviews();
    if (messageInput) {
      messageInput.focus();
    }
    resolve();
  });
}
function retryUserMessage(bubbleElement) {
  editUserMessage(bubbleElement);
  setTimeout(() => {
    const sendButton = document.querySelector('.send-button');
    if (sendButton) {
      sendButton.click();
    }
  }, 100);
}
function deleteUserMessage(bubbleElement) {
  return new Promise(async (resolve) => {
    const messageIndex = parseInt(bubbleElement.dataset.messageIndex);
    const historyIndex = parseInt(bubbleElement.dataset.historyIndex);
    if (isNaN(historyIndex) || historyIndex < 0) {
      console.error('Invalid history index');
      return;
    }
    const messageItem = window.messagesHistory[historyIndex];
    if (!messageItem || messageItem.messages.role !== 'user' || messageItem.isMcp) {
      console.error('Can only delete user messages');
      return;
    }
    await truncateFromMessage(messageIndex, historyIndex);
    resolve();
  });
}
function truncateFromMessage(messageIndex, historyIndex) {
  return new Promise(async (resolve) => {
    if (!isNaN(messageIndex) && messageIndex >= 0) {
      const hasSystemMessage = aiChatApiOptionsBody.messages.length > 0 && aiChatApiOptionsBody.messages[0].role === 'system';
      if (hasSystemMessage) {
        aiChatApiOptionsBody.messages = aiChatApiOptionsBody.messages.slice(0, messageIndex);
      } else {
        const actualIndex = messageIndex - 1;
        if (actualIndex >= 0) {
          aiChatApiOptionsBody.messages = aiChatApiOptionsBody.messages.slice(0, actualIndex);
        } else {
          aiChatApiOptionsBody.messages = [];
        }
      }
    }
    window.messagesHistory = window.messagesHistory.slice(0, historyIndex);
    const bubblesToRemove = document.querySelectorAll('[data-history-index]');
    bubblesToRemove.forEach((bubble) => {
      const bubbleHistoryIndex = parseInt(bubble.dataset.historyIndex);
      if (bubbleHistoryIndex >= historyIndex) {
        bubble.remove();
      }
    });
    if (typeof window.saveHistory === 'function' && window.firstUserMessage) {
      await window.saveHistory(window.firstUserMessage, window.messagesHistory);
    }
    resolve();
  });
}
function updateAIBubbleMaxWidth() {
  const chatBody = document.querySelector('body');
  if (!chatBody) {
    return;
  }
  const maxWidth = chatBody.clientWidth;
  let styleTag = document.getElementById('dynamic-ai-bubble-style');
  if (!styleTag) {
    styleTag = document.createElement('style');
    styleTag.id = 'dynamic-ai-bubble-style';
    document.head.appendChild(styleTag);
  }
  styleTag.innerHTML = `
      .message-group.ai {
        max-width: ${maxWidth}px;
      }
      .message-content {
        box-sizing: border-box;
      }
    `;
}
function createAIResponseHandler(aiBubble, aiMessageIndex, aiHistoryIndex, controller, onComplete, isRetryForDuplicate = false) {
  const cancelButtonContainer = document.getElementById('cancel-button-container');
  const cancelButton = cancelButtonContainer.querySelector('.cancel-button');
  const sendButton = document.querySelector('.send-button');
  return async (fullContent) => {
    const lastAssistantMessage = [...window.messagesHistory].reverse().find((item) => item.messages.role === 'assistant');
    if (lastAssistantMessage && lastAssistantMessage.messages.content === fullContent) {
      if (isRetryForDuplicate) {
        const errorMessage = `❌ **AI响应重复**\n\n已尝试压缩上下文并重试,但AI仍然返回了重复的内容。\n\n**建议:**\n- 请尝试修改您的问题或开启新对话`;
        aiBubble.setHTML(errorMessage);
        if (onComplete) {
          onComplete();
        }
        return;
      } else {
        aiBubble.element.remove();
        let obj = await compressContext(aiChatApiOptionsBody, window.messagesHistory);
        if (obj) {
          aiChatApiOptionsBody = obj.aiChatApiOptionsBody;
          window.messagesHistory = obj.messagesHistory;
        }
        const newAiBubble = chat.addAIBubble(aiMessageIndex, aiHistoryIndex);
        newAiBubble.updateStream('');
        newAiBubble.startDuration();
        const newController = new AbortController();
        const newAbortHandler = () => {
          cancelButtonContainer.style.display = 'none';
          newController.abort();
        };
        cancelButton.addEventListener('click', newAbortHandler);
        const newOnComplete = () => {
          cancelButton.removeEventListener('click', newAbortHandler);
          if (onComplete) {
            onComplete();
          }
        };
        const newResponseHandler = createAIResponseHandler(newAiBubble, aiMessageIndex, aiHistoryIndex, newController, newOnComplete, true);
        requestAiChat(newAiBubble.updateStream.bind(newAiBubble), newResponseHandler, newController.signal, newAiBubble);
        return;
      }
    }
    aiBubble.finishDuration();
    await updateTokenUsage();
    aiBubble.finishStream();
    aiBubble.finishThinking();
    const historyAssistantMessage = {
      role: 'assistant',
      content: fullContent,
      reasoning: aiBubble.fullThinkingContent || undefined,
      reasoningTranslated: false,
      duration: aiBubble.getDuration(),
    };
    const apiAssistantMessage = {
      role: 'assistant',
      content: fullContent,
    };
    aiChatApiOptionsBody.messages.push(apiAssistantMessage);
    messagesHistory.push({ messages: historyAssistantMessage, isMcp: false });
    await saveHistory(window.firstUserMessage, messagesHistory);
    cancelButtonContainer.style.display = 'none';
    if (backend) {
      const toolCall = await callBackend(backend, 'processMessage', [fullContent]);
      try {
        if (toolCall && toolCall.server_name && toolCall.tool_name && toolCall.arguments) {
          let xml = toolCall._xml_;
          if (xml) {
            let newContent = fullContent.replace(xml, '');
            if (newContent == '') {
              newContent = toolCall.server_name + ' -> ' + toolCall.tool_name;
            }
            aiBubble.setHTML(newContent);
          }
          const toolName = `${toolCall.server_name} -> ${toolCall.tool_name}`;
          const toolArgsStr = JSON.stringify(toolCall.arguments, null, 2);
          const systemBubble = chat.addSystemBubble(toolName, toolArgsStr, aiMessageIndex, aiHistoryIndex);
          let userDecision = 'rejected';
          if (toolCall['auto_approve'] === true) {
            userDecision = 'approved';
          } else {
            if (toolCall.tool_name === 'edit_file' && !(await callBackend(backend, 'showFileDiff', [toolCall.arguments]))) {
              userDecision = 'approved';
            } else {
              userDecision = await systemBubble.requireApproval();
            }
          }
          if (userDecision === 'approved') {
            const toolRequestId = generateUniqueId();
            const mcpToolContainer = document.getElementById('mcp-tool-control-container');
            const abortToolButton = mcpToolContainer.querySelector('.abort-tool-button');
            const continueButton = mcpToolContainer.querySelector('.continue-button');
            const abortToolHandler = () => {
              mcpToolContainer.style.display = 'none';
              cancelMcpRequest(toolRequestId);
            };
            abortToolButton.addEventListener('click', abortToolHandler);
            const continueHandler = () => {
              callBackend(backend, 'forceContinueTool', [toolRequestId]);
            };
            continueButton.addEventListener('click', continueHandler, { once: true });
            const showContinueButton = toolCall.tool_name === 'exe_shell';
            if (showContinueButton) {
              continueButton.style.display = 'block';
            } else {
              continueButton.style.display = 'none';
            }
            const showAbortButton = isToolAbortable(toolCall.tool_name);
            if (showAbortButton) {
              abortToolButton.style.display = 'block';
            } else {
              abortToolButton.style.display = 'none';
            }
            if (showContinueButton || showAbortButton) {
              mcpToolContainer.style.display = 'flex';
            } else {
              mcpToolContainer.style.display = 'none';
            }
            sendButton.disabled = true;
            try {
              let executionResultStr = await executeMcpTool(toolCall.server_name, toolCall.tool_name, JSON.stringify(toolCall.arguments), toolRequestId);
              if (toolCall.tool_name === 'exe_shell') {
                executionResultStr = compressTerminalOutput(executionResultStr);
              }
              try {
                const executionResult = JSON.parse(executionResultStr);
                if (executionResult.action === 'provideListOptions' && executionResult.options) {
                  systemBubble.element.style.display = 'none';
                  aiBubble.setListOptions(executionResult.title, executionResult.options);
                  mcpToolContainer.style.display = 'none';
                  abortToolButton.removeEventListener('click', abortToolHandler);
                  continueButton.removeEventListener('click', continueHandler);
                  if (onComplete) {
                    onComplete();
                  }
                  return;
                }
              } catch (e) {}
              systemBubble.setResult('approved', executionResultStr);
              let mcpMessages = {
                role: 'user',
                content: [
                  { type: 'text', text: '[' + toolCall.server_name + ' -> ' + toolCall.tool_name + '] 执行结果:' },
                  { type: 'text', text: executionResultStr },
                ],
              };
              aiChatApiOptionsBody.messages.push(mcpMessages);
              messagesHistory.push({ messages: mcpMessages, isMcp: true });
              await saveHistory(window.firstUserMessage, messagesHistory);
              abortToolButton.removeEventListener('click', abortToolHandler);
              continueButton.removeEventListener('click', continueHandler);
              mcpToolContainer.style.display = 'none';
              const newController = new AbortController();
              const newAbortHandler = () => {
                cancelButtonContainer.style.display = 'none';
                newController.abort();
              };
              cancelButton.addEventListener('click', newAbortHandler);
              const newOnComplete = () => {
                cancelButton.removeEventListener('click', newAbortHandler);
                if (onComplete) {
                  onComplete();
                }
              };
              const newAiMessageIndex = aiChatApiOptionsBody.messages.length;
              const newAiHistoryIndex = messagesHistory.length;
              const newAiBubble = chat.addAIBubble(newAiMessageIndex, newAiHistoryIndex);
              newAiBubble.updateStream('');
              newAiBubble.startDuration();
              const newHandler = createAIResponseHandler(newAiBubble, newAiMessageIndex, newAiHistoryIndex, newController, newOnComplete, false);
              cancelButtonContainer.style.display = 'flex';
              requestAiChat(newAiBubble.updateStream.bind(newAiBubble), newHandler, newController.signal, newAiBubble);
              return;
            } catch (error) {
              systemBubble.setResult('rejected', `执行已取消:${error.message}`);
              mcpToolContainer.style.display = 'none';
              if (onComplete) {
                onComplete();
              }
            } finally {
              abortToolButton.removeEventListener('click', abortToolHandler);
              continueButton.removeEventListener('click', continueHandler);
            }
          } else {
            systemBubble.setResult('rejected', 'User rejected the tool call.');
          }
        }
      } catch (e) {
        console.error('Failed to process or execute MCP tool call:', e);
      }
    }
    if (onComplete) {
      onComplete();
    }
  };
}
function retryAIMessage(bubbleElement) {
  return new Promise(async (resolve) => {
    const messageIndex = parseInt(bubbleElement.dataset.messageIndex);
    const historyIndex = parseInt(bubbleElement.dataset.historyIndex);
    if (isNaN(historyIndex) || historyIndex < 0) {
      console.error('Invalid history index');
      return;
    }
    const messageItem = window.messagesHistory[historyIndex];
    if (!messageItem || messageItem.messages.role !== 'assistant') {
      console.error('Can only retry AI messages');
      return;
    }
    const sendButton = document.querySelector('.send-button');
    if (sendButton && sendButton.disabled) {
      console.log('Another request is in progress');
      return;
    }
    await truncateFromMessage(messageIndex, historyIndex);
    const aiMessageIndex = aiChatApiOptionsBody.messages.length;
    const aiHistoryIndex = messagesHistory.length;
    let aiBubble = chat.addAIBubble(aiMessageIndex, aiHistoryIndex);
    aiBubble.updateStream('');
    aiBubble.startDuration();
    sendButton.disabled = true;
    chat.chatBody.classList.add('request-in-progress');
    const cancelButtonContainer = document.getElementById('cancel-button-container');
    const controller = new AbortController();
    const cancelButton = cancelButtonContainer.querySelector('.cancel-button');
    const abortRequest = () => {
      cancelButtonContainer.style.display = 'none';
      controller.abort();
    };
    cancelButton.addEventListener('click', abortRequest);
    cancelButtonContainer.style.display = 'flex';
    const onComplete = () => {
      sendButton.disabled = false;
      chat.chatBody.classList.remove('request-in-progress');
      cancelButton.removeEventListener('click', abortRequest);
      if (chat.chatController && !chat.chatController.userHasScrolled) {
        chat.chatController.scrollToBottom();
      }
    };
    const responseHandler = createAIResponseHandler(aiBubble, aiMessageIndex, aiHistoryIndex, controller, onComplete, false);
    requestAiChat(aiBubble.updateStream.bind(aiBubble), responseHandler, controller.signal, aiBubble);
    resolve();
  });
}
function deleteAIMessage(bubbleElement) {
  return new Promise(async (resolve) => {
    const messageIndex = parseInt(bubbleElement.dataset.messageIndex);
    const historyIndex = parseInt(bubbleElement.dataset.historyIndex);
    if (isNaN(historyIndex) || historyIndex < 0) {
      console.error('Invalid history index');
      return;
    }
    const messageItem = window.messagesHistory[historyIndex];
    if (!messageItem || messageItem.messages.role !== 'assistant') {
      console.error('Can only delete AI messages');
      return;
    }
    await truncateFromMessage(messageIndex, historyIndex);
    resolve();
  });
}
function isEmptyObject(obj) {
  const isPlainObject = Object.prototype.toString.call(obj) === '[object Object]';
  if (!isPlainObject) {
    return false;
  }
  return Object.keys(obj).length === 0;
}
function renderImagePreviews() {
  const inputArea = document.querySelector('.input-area');
  let previewContainer = document.getElementById('image-preview-container');
  if (pastedImageDataUrls.length === 0) {
    if (previewContainer) {
      previewContainer.remove();
    }
    return;
  }
  if (!previewContainer) {
    previewContainer = document.createElement('div');
    previewContainer.id = 'image-preview-container';
    inputArea.parentNode.insertBefore(previewContainer, inputArea.nextSibling);
  }
  previewContainer.style.display = 'flex';
  previewContainer.style.overflowX = 'auto';
  previewContainer.style.overflowY = 'hidden';
  previewContainer.style.gap = '10px';
  previewContainer.style.padding = '10px 0';
  previewContainer.style.width = '100%';
  previewContainer.innerHTML = '';
  pastedImageDataUrls.forEach((dataUrl, index) => {
    const imageWrapper = document.createElement('div');
    imageWrapper.style.position = 'relative';
    imageWrapper.style.flexShrink = '0';
    const img = document.createElement('img');
    img.src = dataUrl;
    img.style.width = '80px';
    img.style.height = '80px';
    img.style.borderRadius = '8px';
    img.style.objectFit = 'cover';
    img.style.display = 'block';
    const removeBtn = document.createElement('button');
    removeBtn.textContent = '×';
    removeBtn.style.position = 'absolute';
    removeBtn.style.top = '-5px';
    removeBtn.style.right = '-5px';
    removeBtn.style.background = 'rgba(0,0,0,0.7)';
    removeBtn.style.color = 'white';
    removeBtn.style.border = '1px solid white';
    removeBtn.style.borderRadius = '50%';
    removeBtn.style.cursor = 'pointer';
    removeBtn.style.width = '20px';
    removeBtn.style.height = '20px';
    removeBtn.style.lineHeight = '18px';
    removeBtn.style.textAlign = 'center';
    removeBtn.style.padding = '0';
    removeBtn.style.fontSize = '16px';
    removeBtn.style.fontWeight = 'bold';
    removeBtn.onclick = () => {
      pastedImageDataUrls.splice(index, 1);
      renderImagePreviews();
    };
    imageWrapper.appendChild(img);
    imageWrapper.appendChild(removeBtn);
    previewContainer.appendChild(imageWrapper);
  });
}
function escapeHtml(text) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}
function adjustTextareaHeight() {
  const textarea = document.getElementById('message-input');
  if (!textarea) {
    return;
  }
  if (textarea.value === '') {
    textarea.style.height = '70px';
    return;
  }
  textarea.style.height = 'auto';
  const newHeight = Math.min(Math.max(textarea.scrollHeight, 70), 250);
  textarea.style.height = newHeight + 'px';
}
function updateHighlights() {
  const textarea = document.getElementById('message-input');
  const highlightLayer = document.getElementById('highlight-layer');
  if (!textarea || !highlightLayer) {
    return;
  }
  let text = textarea.value;
  let processedText = escapeHtml(text);
  const mentionRegex = /(\s)(@[a-zA-Z]+:[^\s]+)/g;
  processedText = processedText.replace(mentionRegex, (match, space, mention) => {
    return space + '<mark>' + match.substring(space.length) + '</mark>';
  });
  highlightLayer.innerHTML = processedText;
  highlightLayer.scrollTop = textarea.scrollTop;
  highlightLayer.scrollLeft = textarea.scrollLeft;
  adjustTextareaHeight();
}
function handlePaste(event) {
  event.preventDefault();
  const clipboardData = event.clipboardData || window.clipboardData;
  const items = clipboardData.items;
  let imageFound = false;
  for (const item of items) {
    if (item.kind === 'file' && item.type.startsWith('image/')) {
      imageFound = true;
      const file = item.getAsFile();
      const reader = new FileReader();
      reader.onload = function (e) {
        pastedImageDataUrls.push(e.target.result);
        renderImagePreviews();
      };
      reader.readAsDataURL(file);
    }
  }
  if (!imageFound) {
    const plainText = clipboardData.getData('text/plain');
    if (plainText) {
      const textarea = event.target;
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const currentValue = textarea.value;
      textarea.value = currentValue.substring(0, start) + plainText + currentValue.substring(end);
      const newPos = start + plainText.length;
      textarea.setSelectionRange(newPos, newPos);
      updateHighlights();
    }
  }
}
window.messagesHistory = [];
let aiChatApiOptionsBody = {
  model: '',
  temperature: 0.6,
  messages: [],
  stream: true,
  stream_options: {
    include_usage: true,
  },
};
window.firstUserMessage = '';
let backend;
let lastSystemData = {};
const chat = new ChatController('.chat-body');
const chatHistoryContainer = document.querySelector('.chat-history');
window.loadHistory = function (filename) {
  initializeBackendConnection(async (backend) => {
    if (!backend) {
      return;
    }
    const history = await callBackend(backend, 'loadHistory', [filename]);
    if (!history) {
      return;
    }
    chatHistoryContainer.style.display = 'none';
    window.firstUserMessage = filename.replace('.json', '');
    window.messagesHistory = history;
    chat.chatBody.innerHTML = '';
    for (let i = 0; i < window.messagesHistory.length; i++) {
      const item = window.messagesHistory[i];
      const messageForApi = { ...item.messages };
      delete messageForApi.reasoning;
      delete messageForApi.reasoningTranslated;
      delete messageForApi.duration;
      aiChatApiOptionsBody.messages.push(messageForApi);
      if (i === 0 && item.messages.role === 'system') {
        continue;
      }
      const messageIndex = aiChatApiOptionsBody.messages.length - 1;
      if (item.messages.role === 'user') {
        if (item.isMcp) {
          continue;
        }
        let userText = '';
        let imageUrls = [];
        if (Array.isArray(item.messages.content)) {
          item.messages.content.forEach((contentPart) => {
            if (contentPart.type === 'text') {
              const text = contentPart.text || '';
              if (!text.startsWith('<附加系统数据>')) {
                userText += text;
              }
            } else if (contentPart.type === 'image_url' && contentPart.image_url) {
              imageUrls.push(contentPart.image_url.url);
            }
          });
        } else {
          userText = item.messages.content;
        }
        await chat.addUserBubble(userText, imageUrls, messageIndex, i);
      } else if (item.messages.role === 'assistant') {
        const aiBubble = chat.addAIBubble(messageIndex, i);
        let aiContent = item.messages.content;
        aiBubble.setHTML(aiContent);
        if (item.messages.duration) {
          aiBubble.setDuration(item.messages.duration);
        }
        if (item.messages.reasoning) {
          aiBubble.thinkingContainer.style.display = 'block';
          aiBubble.fullThinkingContent = item.messages.reasoning;
          aiBubble.isThinkingStreamFinished = true;
          aiBubble.reasoningTranslated = item.messages.reasoningTranslated;
          if (item.messages.reasoningTranslated) {
            aiBubble.translatedThinkingContent = item.messages.reasoning;
            aiBubble.contentSentForTranslation = item.messages.reasoning;
            const dirtyHtml = marked.parse(aiBubble.translatedThinkingContent);
            aiBubble.thinkingContent.innerHTML = DOMPurify.sanitize(dirtyHtml);
          } else {
            const dirtyHtml = marked.parse(aiBubble.fullThinkingContent);
            aiBubble.thinkingContent.innerHTML = DOMPurify.sanitize(dirtyHtml);
            aiBubble.triggerTranslation();
          }
          aiBubble.toggleThinking('closed');
        }
        const toolCall = await callBackend(backend, 'processMessage', [aiContent]);
        if (toolCall) {
          try {
            if (toolCall && toolCall.server_name && toolCall.tool_name && toolCall.arguments) {
              let xml = toolCall._xml_;
              if (xml) {
                let newContent = aiContent.replace(xml, '');
                if (newContent == '') {
                  newContent = toolCall.server_name + ' -> ' + toolCall.tool_name;
                }
                aiBubble.setHTML(newContent);
              }
              if (toolCall.tool_name == 'provideListOptions') {
                if (i === window.messagesHistory.length - 1) {
                  const executionResultStr = await executeMcpTool(toolCall.server_name, toolCall.tool_name, JSON.stringify(toolCall.arguments));
                  try {
                    const executionResult = JSON.parse(executionResultStr);
                    if (executionResult.options) {
                      aiBubble.setListOptions(executionResult.title, executionResult.options);
                    }
                  } catch (e) {}
                }
                continue;
              }
              const toolName = `${toolCall.server_name} -> ${toolCall.tool_name}`;
              const toolArgsStr = JSON.stringify(toolCall.arguments, null, 2);
              const systemBubble = chat.addSystemBubble(toolName, toolArgsStr, messageIndex, i);
              systemBubble.setCollapsed();
              const nextItem = i + 1 < window.messagesHistory.length ? window.messagesHistory[i + 1] : null;
              if (nextItem && nextItem.isMcp === true) {
                let resultText = '';
                if (Array.isArray(nextItem.messages.content) && nextItem.messages.content.length > 1 && nextItem.messages.content[1].type === 'text') {
                  resultText = nextItem.messages.content[1].text || '';
                } else {
                  resultText = nextItem.messages.content.map((c) => c.text || '').join('\n');
                }
                systemBubble.setResult('approved', resultText);
              } else {
                systemBubble.setResult('rejected', '用户拒绝了工具调用.');
              }
            }
          } catch (e) {
            console.error('Failed to process tool call from history:', e);
          }
        }
      }
    }
    chat.scrollToBottom();
    await updateTokenUsage();
  });
};
function initializeBackendConnection(callback) {
  if (backend) {
    if (callback) {
      callback(backend);
    }
    return;
  }
  if (typeof qt !== 'undefined' && typeof qt.webChannelTransport !== 'undefined') {
    new QWebChannel(qt.webChannelTransport, (channel) => {
      backend = channel.objects.backend;
      if (backend) {
        updateModelTags();
        if (callback) {
          callback(backend);
        }
      }
    });
  } else {
    console.error('QWebChannel transport not available.');
  }
}
async function initializeSystemMessage() {
  if (aiChatApiOptionsBody.messages.length === 0 || aiChatApiOptionsBody.messages[0].role !== 'system') {
    try {
      if (backend && typeof backend.getSystemPrompt === 'function') {
        const systemPrompt = await callBackend(backend, 'getSystemPrompt');
        if (systemPrompt) {
          aiChatApiOptionsBody.messages.unshift({
            role: 'system',
            content: systemPrompt,
          });
        }
      }
    } catch (err) {
      console.error('Error getting system prompt:', err);
    }
  }
}
document.addEventListener('DOMContentLoaded', function () {
  UserInfoManager.subscribe((userInfo) => {
    document.querySelectorAll('.message-group.user').forEach((groupDiv) => {
      const iconSpan = groupDiv.querySelector(':scope > .icon');
      const nameDiv = groupDiv.querySelector('.message-sender > div:last-child');
      if (iconSpan && userInfo.avatarUrl) {
        iconSpan.innerHTML = `<img src="${userInfo.avatarUrl}" style="width:64px;height:64px; border-radius: 50%; object-fit: cover;" />`;
      }
      if (nameDiv && userInfo.name !== '加载中...') {
        nameDiv.textContent = userInfo.name;
      }
    });
  });
  UserInfoManager.get();
  const attrDataStrPlugin = {
    'after:highlight': (result) => {
      const tempDiv = document.createElement('div');
      tempDiv.innerHTML = result.value;
      const elements = tempDiv.querySelectorAll('.hljs-attr, .hljs-name');
      elements.forEach((el) => {
        const text = el.textContent;
        if (el.classList.contains('hljs-attr')) {
          if (text.startsWith('"') && text.endsWith('"')) {
            const dataStr = text.substring(1, text.length - 1);
            el.setAttribute('data-str', dataStr);
          }
        } else if (el.classList.contains('hljs-name')) {
          el.setAttribute('data-str', text);
        }
      });
      const pathKeys = tempDiv.querySelectorAll('[data-str="path"]');
      pathKeys.forEach((keyEl) => {
        if (keyEl.classList.contains('hljs-attr')) {
          let currentNode = keyEl;
          while ((currentNode = currentNode.nextSibling)) {
            if (currentNode.nodeType === Node.ELEMENT_NODE) {
              if (currentNode.classList.contains('hljs-string')) {
                currentNode.classList.add('path-value');
                break;
              }
              if (currentNode.classList.contains('hljs-attr')) {
                break;
              }
            }
          }
        } else if (keyEl.classList.contains('hljs-name')) {
          const tagWrapper = keyEl.parentElement;
          if (tagWrapper && tagWrapper.classList.contains('hljs-tag')) {
            let valueNode = tagWrapper.nextSibling;
            if (valueNode && valueNode.nodeType === Node.TEXT_NODE && valueNode.textContent.trim() === '') {
              valueNode = valueNode.nextSibling;
            }
            if (valueNode && valueNode.nodeType === Node.TEXT_NODE && valueNode.textContent.trim() !== '') {
              const span = document.createElement('span');
              span.className = 'path-value';
              span.textContent = valueNode.textContent;
              valueNode.parentNode.replaceChild(span, valueNode);
            }
          }
        }
      });
      result.value = tempDiv.innerHTML;
    },
  };
  hljs.addPlugin(attrDataStrPlugin);
  marked.setOptions({
    highlight: function (code, lang) {
      const language = hljs.getLanguage(lang) ? lang : 'plaintext';
      return hljs.highlight(code, { language }).value;
    },
    langPrefix: 'hljs language-',
  });
  const messageInput = document.querySelector('#message-input');
  const sendButton = document.querySelector('.send-button');
  let isRequesting = false;
  function _sanitize_filename(name) {
    name = name.replace(/[\\/*?:"<>|]/g, '');
    name = name.replace('\n', '').replace('\t', '').replace('\r', '');
    return name.substring(0, 16);
  }
  async function sendMessage() {
    const approvalContainer = document.getElementById('approve-reject-buttons');
    if (approvalContainer && approvalContainer.style.display === 'flex') {
      const rejectBtn = approvalContainer.querySelector('.reject-button');
      if (rejectBtn) {
        rejectBtn.click();
        await new Promise((resolve) => setTimeout(resolve, 200));
      }
    }
    if (isRequesting) {
      return;
    }
    isRequesting = true;
    sendButton.disabled = true;
    await initializeSystemMessage();
    const [cwdResult, fileManagerResult, systemInfoResult] = await Promise.all([callBackend(backend, 'get_current_cwd'), callBackend(backend, 'get_file_manager_cwd'), callBackend(backend, 'get_system_info')]);
    let sshCwd = cwdResult.cwd;
    let fileManagerCwd = fileManagerResult.cwd;
    let systemInfo = JSON.stringify(systemInfoResult.content);
    const message = messageInput.value;
    if (message || pastedImageDataUrls.length > 0) {
      chatHistoryContainer.style.display = 'none';
      if (window.firstUserMessage === '') {
        window.firstUserMessage = _sanitize_filename(message) + '_' + Date.now().toString();
      }
      chat.chatBody.classList.add('request-in-progress');
      const currentMessageIndex = aiChatApiOptionsBody.messages.length;
      const currentHistoryIndex = messagesHistory.length;
      await chat.addUserBubble(message, [...pastedImageDataUrls], currentMessageIndex, currentHistoryIndex);
      const userMessageContent = [];
      if (message) {
        userMessageContent.push({
          type: 'text',
          text: message,
        });
      }
      if (pastedImageDataUrls.length > 0) {
        pastedImageDataUrls.forEach((dataUrl) => {
          userMessageContent.push({
            type: 'image_url',
            image_url: {
              url: dataUrl,
            },
          });
        });
      }
      const currentSystemData = { sshCwd, fileManagerCwd, systemInfo, systemLanguage: window.SystemLanguage };
      const systemDataMap = {
        sshCwd: '终端cwd',
        fileManagerCwd: '文件管理器cwd',
        systemInfo: '系统信息',
        systemLanguage: '回复语言',
      };
      const changedDataXmlParts = [];
      for (const key in systemDataMap) {
        if (currentSystemData[key] !== lastSystemData[key]) {
          const tagName = systemDataMap[key];
          const value = currentSystemData[key];
          changedDataXmlParts.push(`<${tagName}>${value}</${tagName}>`);
        }
      }
      if (changedDataXmlParts.length > 0) {
        const systemDataXml = `<附加系统数据>\n${changedDataXmlParts.join('\n')}\n</附加系统数据>`;
        userMessageContent.push({
          type: 'text',
          text: systemDataXml,
        });
        Object.assign(lastSystemData, currentSystemData);
      }
      const userMessage = {
        role: 'user',
        content: userMessageContent,
      };
      aiChatApiOptionsBody.messages.push(userMessage);
      messagesHistory.push({ messages: userMessage, isMcp: false });
      await saveHistory(window.firstUserMessage, messagesHistory);
      await updateTokenUsage();
      pastedImageDataUrls = [];
      renderImagePreviews();
      const aiMessageIndex = aiChatApiOptionsBody.messages.length;
      const aiHistoryIndex = messagesHistory.length;
      let aiBubble = chat.addAIBubble(aiMessageIndex, aiHistoryIndex);
      aiBubble.updateStream('');
      aiBubble.startDuration();
      const cancelButtonContainer = document.getElementById('cancel-button-container');
      const controller = new AbortController();
      const abortRequest = () => {
        cancelButtonContainer.style.display = 'none';
        controller.abort();
      };
      const cancelButton = cancelButtonContainer.querySelector('.cancel-button');
      cancelButton.addEventListener('click', abortRequest);
      cancelButtonContainer.style.display = 'flex';
      const onComplete = () => {
        isRequesting = false;
        sendButton.disabled = false;
        chat.chatBody.classList.remove('request-in-progress');
        cancelButton.removeEventListener('click', abortRequest);
        if (chat.chatController && !chat.chatController.userHasScrolled) {
          chat.chatController.scrollToBottom();
        }
        updateTokenUsage();
      };
      const onDone = createAIResponseHandler(aiBubble, aiMessageIndex, aiHistoryIndex, controller, onComplete, false);
      requestAiChat(aiBubble.updateStream.bind(aiBubble), onDone, controller.signal, aiBubble);
      messageInput.value = '';
      updateHighlights();
    }
  }
  let mentionManager = null;
  if (messageInput) {
    mentionManager = new MentionManager(messageInput);
    mentionManager.onInsert = () => updateHighlights();
    messageInput.addEventListener('scroll', function () {
      updateHighlights();
    });
    const mentionItemsMap = {
      Dir: (parentItem) => {
        return new Promise((resolve) => {
          initializeBackendConnection(async (backendObject) => {
            if (!backendObject) {
              resolve([]);
              return;
            }
            try {
              let targetPath;
              if (parentItem && parentItem.data && parentItem.data.path) {
                if (parentItem.data.path === '.') {
                  const cwdResult = await callBackend(backendObject, 'get_file_manager_cwd');
                  targetPath = cwdResult.cwd;
                } else {
                  targetPath = parentItem.data.path;
                }
              } else {
                const cwdResult = await callBackend(backendObject, 'get_file_manager_cwd');
                targetPath = cwdResult.cwd;
              }
              const dirsResult = await callBackend(backendObject, 'listDirs', { path: targetPath });
              if (dirsResult.status === 'error') {
                console.error('获取目录列表失败:', dirsResult.content);
                resolve([]);
                return;
              }
              const list = [
                {
                  id: `dir00_${Date.now()}`,
                  icon: '📁',
                  label: `Dir:${targetPath}`,
                  hasChildren: false,
                  type: 'directory',
                },
              ];
              const dirs = dirsResult.dirs || [];
              for (let i = 0; i < dirs.length; i++) {
                list.push({
                  id: `dir${i}_${Date.now()}`,
                  icon: '📁',
                  label: `Dir:${targetPath}/${dirs[i]}`,
                  hasChildren: true,
                  type: 'directory',
                  data: { path: `${targetPath}/${dirs[i]}` },
                });
              }
              resolve(list);
            } catch (error) {
              console.error('获取目录列表异常:', error);
              resolve([]);
            }
          });
        });
      },
      File: () => {
        return new Promise((resolve) => {
          initializeBackendConnection(async (backendObject) => {
            if (!backendObject) {
              resolve([]);
              return;
            }
            const cwdResult = await callBackend(backendObject, 'get_file_manager_cwd');
            const cwd = cwdResult.cwd;
            const filesResult = await callBackend(backendObject, 'listFiles', { cwd: cwd });
            const files = filesResult.files;
            const list = files.map((file, i) => ({
              id: `file${i}`,
              icon: '📄',
              label: `File:${cwd}/${file}`,
              hasChildren: false,
              type: 'file',
            }));
            resolve(list);
          });
        });
      },
      Terminal: () => {
        return new Promise((resolve) => {
          const terminalOptions = [];
          for (let i = 1; i <= 10; i++) {
            terminalOptions.push({
              id: `terminal${i}`,
              icon: '💻',
              label: `Terminal:${i}`,
              hasChildren: false,
              type: 'terminal',
            });
          }
          resolve(terminalOptions);
        });
      },
    };
    mentionManager.onGetSubItems = async function (item) {
      if (!this.ctrlPressed) {
        if (item.type === 'directory' && item.label.startsWith('Dir:')) {
          return null;
        }
      }
      if (mentionItemsMap[item.type]) {
        return await mentionItemsMap[item.type](item);
      }
      return null;
    };
    messageInput.addEventListener('paste', handlePaste);
    messageInput.addEventListener('input', function (event) {
      updateHighlights();
      if (mentionManager.checkForMentionTrigger()) {
        const defaultItems = [
          { id: 'dir', icon: '📁', label: '目录', hasChildren: true, type: 'Dir', data: { path: '.' } },
          { id: 'file', icon: '📄', label: '文件', hasChildren: true, type: 'File', data: { path: '.' } },
          { id: 'url', icon: '🔗', label: '网址', hasChildren: false, type: 'Url', inputMode: true, placeholder: '请输入完整URL(如:https://example.com)' },
          { id: 'terminal', icon: '💻', label: '终端', hasChildren: true, type: 'Terminal' },
        ];
        mentionManager.show(defaultItems);
      } else if (mentionManager.isActive) {
        const text = messageInput.value;
        if (!text.includes('@')) {
          mentionManager.hide();
        }
      }
    });
    document.addEventListener('click', function (event) {
      if (mentionManager.isActive) {
        const popup = document.getElementById('mention-popup');
        if (!popup.contains(event.target)) {
          mentionManager.hide();
        }
      }
    });
    let justDeletedSpaceAfterMention = false;
    messageInput.addEventListener('keydown', function (event) {
      if (mentionManager.isActive) {
        mentionManager.ctrlPressed = event.ctrlKey;
        if (event.key === 'ArrowUp') {
          event.preventDefault();
          mentionManager.moveSelection('up');
          return;
        } else if (event.key === 'ArrowDown') {
          event.preventDefault();
          mentionManager.moveSelection('down');
          return;
        } else if (event.key === 'Enter') {
          event.preventDefault();
          mentionManager.selectItem();
          return;
        } else if (event.key === 'Escape') {
          event.preventDefault();
          mentionManager.hide();
          return;
        }
      }
      if (event.key === 'Backspace' && messageInput.selectionStart === messageInput.selectionEnd) {
        const cursorPos = messageInput.selectionStart;
        if (cursorPos === 0) {
          justDeletedSpaceAfterMention = false;
          return;
        }
        const textBefore = messageInput.value.substring(0, cursorPos);
        const charBeforeCursor = textBefore[cursorPos - 1];
        const isWhitespace = charBeforeCursor === ' ' || charBeforeCursor === '\n';
        if (isWhitespace) {
          const mentionRegex = /(\s)(@[a-zA-Z]+:[^\s]+)\s$/;
          const match = textBefore.match(mentionRegex);
          if (match) {
            event.preventDefault();
            messageInput.value = messageInput.value.substring(0, cursorPos - 1) + messageInput.value.substring(cursorPos);
            const newPos = cursorPos - 1;
            messageInput.setSelectionRange(newPos, newPos);
            justDeletedSpaceAfterMention = true;
            updateHighlights();
            return;
          }
        } else if (justDeletedSpaceAfterMention) {
          const mentionRegex = /(\s)(@[a-zA-Z]+:[^\s]+)$/;
          const match = textBefore.match(mentionRegex);
          if (match) {
            event.preventDefault();
            const fullMatch = match[0];
            const mentionWithSpace = match[1] + match[2];
            const startPos = cursorPos - match[2].length;
            const beforeMention = messageInput.value.substring(0, startPos - match[1].length);
            const afterMention = messageInput.value.substring(cursorPos);
            messageInput.value = beforeMention + afterMention;
            messageInput.setSelectionRange(beforeMention.length, beforeMention.length);
            justDeletedSpaceAfterMention = false;
            updateHighlights();
            return;
          }
        }
        justDeletedSpaceAfterMention = false;
      } else if (event.key !== 'Backspace') {
        justDeletedSpaceAfterMention = false;
      }
      if (event.key === 'Enter' && !event.shiftKey && !event.ctrlKey) {
        event.preventDefault();
        sendMessage();
      }
    });
    updateHighlights();
  }
  if (sendButton) {
    sendButton.addEventListener('click', sendMessage);
  }
  const imageButton = document.querySelector('#image-button');
  if (imageButton) {
    imageButton.addEventListener('click', () => {
      const fileInput = document.createElement('input');
      fileInput.type = 'file';
      fileInput.accept = 'image/*';
      fileInput.multiple = true;
      fileInput.addEventListener('change', (event) => {
        const files = event.target.files;
        if (files.length > 0) {
          Array.from(files).forEach((file) => {
            const reader = new FileReader();
            reader.onload = function (e) {
              pastedImageDataUrls.push(e.target.result);
              renderImagePreviews();
            };
            reader.readAsDataURL(file);
          });
        }
      });
      fileInput.click();
    });
  }
  const newChatButton = document.querySelector('.new-chat-button');
  if (newChatButton) {
    newChatButton.addEventListener('click', () => {
      window.location.reload();
    });
  }
  const settingsBtn = document.getElementById('settings-btn');
  const settingsPopup = document.getElementById('settings-popup');
  const closeSettingsBtn = document.getElementById('close-settings-btn');
  const settingsIframe = settingsPopup.querySelector('iframe');
  settingsIframe.addEventListener('load', () => {
    initializeBackendConnection(async (backendObject) => {
      window.SystemLanguage = await callBackend(backendObject, 'getSystemLanguage');
      if (backendObject) {
        const iframeWindow = settingsIframe.contentWindow;
        iframeWindow.backend = backendObject;
        if (iframeWindow.initializeWithBackend) {
          iframeWindow.initializeWithBackend(backendObject);
        }
      }
    });
  });
  settingsIframe.src = 'iframe/setting/index.html';
  settingsBtn.addEventListener('click', () => {
    settingsPopup.style.display = 'flex';
  });
  closeSettingsBtn.addEventListener('click', () => {
    const iframeWindow = settingsIframe.contentWindow;
    if (iframeWindow && typeof iframeWindow.getmodelsData === 'function') {
      const modelsData = iframeWindow.getmodelsData();
      if (backend) {
        callBackend(backend, 'saveModels', [JSON.stringify(modelsData)]);
        updateModelTags();
      }
    }
    settingsPopup.style.display = 'none';
  });
  window.addEventListener('click', (event) => {
    if (event.target === settingsPopup) {
      settingsPopup.style.display = 'none';
    }
  });
  const onlineStatusBtn = document.getElementById('online-status');
  const onlineUserPopup = document.getElementById('online-user-popup');
  const closeOnlineUserBtn = document.getElementById('close-online-user-btn');
  if (onlineStatusBtn && onlineUserPopup && closeOnlineUserBtn) {
    onlineStatusBtn.addEventListener('click', () => {
      onlineUserPopup.style.display = 'flex';
    });
    closeOnlineUserBtn.addEventListener('click', () => {
      onlineUserPopup.style.display = 'none';
    });
    window.addEventListener('click', (event) => {
      if (event.target === onlineUserPopup) {
        onlineUserPopup.style.display = 'none';
      }
    });
  }
  initializeBackendConnection(async (backend) => {
    await initializeSystemMessage();
    initializeHistoryPanel(backend);
  });
  updateAIBubbleMaxWidth();
  window.addEventListener('resize', updateAIBubbleMaxWidth);
  setupWebSocket();
  const tokenUsageElement = document.getElementById('token-usage');
  const compressionConfirmOverlay = document.getElementById('compression-confirm-overlay');
  const confirmYesButton = compressionConfirmOverlay.querySelector('.confirm-yes');
  const confirmNoButton = compressionConfirmOverlay.querySelector('.confirm-no');
  tokenUsageElement.addEventListener('click', () => {
    const messageCount = aiChatApiOptionsBody.messages.filter((m) => m.role !== 'system').length;
    if (messageCount < 3) {
      return;
    }
    compressionConfirmOverlay.style.display = 'flex';
  });
  confirmNoButton.addEventListener('click', () => {
    compressionConfirmOverlay.style.display = 'none';
  });
  confirmYesButton.addEventListener('click', async () => {
    compressionConfirmOverlay.style.display = 'none';
    try {
      const result = await compressContext(aiChatApiOptionsBody, window.messagesHistory);
      if (result) {
        aiChatApiOptionsBody = result.aiChatApiOptionsBody;
        window.messagesHistory = result.messagesHistory;
        await saveHistory(window.firstUserMessage, window.messagesHistory);
        await updateTokenUsage();
      }
    } catch (error) {}
  });
  compressionConfirmOverlay.addEventListener('click', (e) => {
    if (e.target === compressionConfirmOverlay) {
      compressionConfirmOverlay.style.display = 'none';
    }
  });
});
function setupWebSocket() {
  const onlineStatusElement = document.getElementById('online-status');
  const statusIcon = onlineStatusElement.querySelector('.icon');
  const statusText = onlineStatusElement.querySelector('.status-text');
  const wsUrl = 'ws://aurashell-aichatapi.beefuny.shop/ws';
  let ws;
  let pingInterval;
  const onlineUserIframe = document.getElementById('online-user-iframe');
  const iframeWindow = onlineUserIframe ? onlineUserIframe.contentWindow : null;
  function connect() {
    ws = new WebSocket(wsUrl);
    window.ws = ws;
    ws.onopen = () => {
      statusIcon.classList.remove('error-icon');
      statusIcon.classList.add('success-icon');
      if (pingInterval) {
        clearInterval(pingInterval);
      }
      pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ action: 'ping', id: Date.now() }));
        }
      }, 30000);
      initializeBackendConnection(async (backendObject) => {
        if (backendObject) {
          let qqInfo = await callBackend(backendObject, 'getQQUserInfo');
          setQQUserInfo(qqInfo.qq_name, qqInfo.qq_number);
        }
      });
    };
    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.action === 'updateUserCount') {
          const data = JSON.parse(message.data);
          statusText.textContent = `在线用户:${data.userCount}`;
        }
        if (message.action === 'addUser') {
          const data = JSON.parse(message.data);
          let qq_number = data.qq_number.toString();
          if (qq_number == null || qq_number == '') {
            return;
          }
          if (window.OnlineUser[qq_number]) {
            return;
          }
          window.OnlineUser[qq_number] = data.qq_name;
          iframeWindow.addUser(qq_number, data.qq_name);
        }
        if (message.action === 'removeUser') {
          const data = JSON.parse(message.data);
          let qq_number = data.qq_number.toString();
          if (qq_number == null || qq_number == '') {
            return;
          }
          if (!window.OnlineUser[qq_number]) {
            return;
          }
          delete window.OnlineUser[data.qq_number.toString()];
          iframeWindow.removeUser(qq_number);
        }
        if (message.action === 'allUser') {
          try {
            const userList = JSON.parse(message.data);
            if (!Array.isArray(userList)) {
              return;
            }
            window.OnlineUser = {};
            if (iframeWindow.allUser) {
              iframeWindow.allUser([]);
            }
            for (const user of userList) {
              if (user && user.qq_number && user.qq_name) {
                const qq_number = user.qq_number.toString();
                const qq_name = user.qq_name;
                window.OnlineUser[qq_number] = qq_name;
                if (iframeWindow.addUser) {
                  iframeWindow.addUser(qq_number, qq_name);
                }
              }
            }
          } catch (e) {
            console.error('Error processing allUser message:', e);
          }
        }
      } catch (error) {
        console.error('Error parsing WebSocket message:', error);
      }
    };
    ws.onclose = () => {
      clearInterval(pingInterval);
      onlineStatusElement.title = '与在线状态服务器断开连接，正在尝试重新连接...';
      statusIcon.classList.remove('success-icon');
      statusIcon.classList.add('error-icon');
      statusText.textContent = '已断开';
      setTimeout(connect, 1000);
    };
    ws.onerror = (error) => {
      // console.error('WebSocket error:', error);
      ws.close();
    };
  }
  connect();
}
const modelSelectTrigger = document.getElementById('model-select-trigger');
const currentModelNameSpan = document.getElementById('current-model-name');
const modelSelectPopup = document.getElementById('model-select-popup');
const modelSearchInput = document.getElementById('model-search-input');
const modelOptionsContainer = document.getElementById('model-options-container');
let allModels = {};
window.currentModel = '';
function getCurrentModelData() {
  return allModels[window.currentModel];
}
async function updateModelTags() {
  if (!backend) {
    return;
  }
  allModels = await callBackend(backend, 'getModels');
  const modelNames = Object.keys(allModels);
  if (modelNames.length > 0) {
    const savedModel = await callBackend(backend, 'getSetting', ['ai_chat_model']);
    if (savedModel && allModels.hasOwnProperty(savedModel)) {
      window.currentModel = savedModel;
    } else {
      window.currentModel = modelNames[0];
      callBackend(backend, 'saveSetting', ['ai_chat_model', window.currentModel]);
    }
  } else {
    window.currentModel = '';
  }
  currentModelNameSpan.textContent = window.currentModel;
  populateModelOptions();
}
function populateModelOptions(filter = '') {
  modelOptionsContainer.innerHTML = '';
  const lowerCaseFilter = filter.toLowerCase();
  Object.keys(allModels)
    .filter((modelName) => modelName.toLowerCase().includes(lowerCaseFilter))
    .forEach((modelName) => {
      const optionDiv = document.createElement('div');
      optionDiv.textContent = modelName;
      optionDiv.className = 'model-option';
      if (modelName === window.currentModel) {
        optionDiv.classList.add('active');
      }
      optionDiv.addEventListener('click', () => {
        window.currentModel = modelName;
        currentModelNameSpan.textContent = window.currentModel;
        modelSelectPopup.style.display = 'none';
        callBackend(backend, 'saveSetting', ['ai_chat_model', window.currentModel]);
        populateModelOptions();
      });
      modelOptionsContainer.appendChild(optionDiv);
    });
}
modelSelectTrigger.addEventListener('click', (e) => {
  e.stopPropagation();
  const isHidden = modelSelectPopup.style.display === 'none';
  modelSelectPopup.style.display = isHidden ? 'flex' : 'none';
  if (isHidden) {
    modelSearchInput.value = '';
    populateModelOptions();
    modelSearchInput.focus();
  }
});
modelSearchInput.addEventListener('input', () => {
  populateModelOptions(modelSearchInput.value);
});
document.addEventListener('click', (e) => {
  if (!modelSelectPopup.contains(e.target) && !modelSelectTrigger.contains(e.target)) {
    modelSelectPopup.style.display = 'none';
  }
});
function getAiChatApiOptionsBody() {
  aiChatApiOptionsBody.model = window.getCurrentModelData().model_name;
  return aiChatApiOptionsBody;
}
function getRequestAiChatApiOptions() {
  let key = getCurrentModelData().key;
  return {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${key}`,
      'User-Agent': 'RooCode/99999.99.9',
      Accept: 'application/json',
      'Accept-Encoding': 'br, gzip, deflate',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(getAiChatApiOptionsBody()),
  };
}
window.debugChatIndexes = {
  findByMessageIndex: function (index) {
    return document.querySelector(`[data-message-index="${index}"]`);
  },
  findByHistoryIndex: function (index) {
    return document.querySelector(`[data-history-index="${index}"]`);
  },
  showAllIndexes: function () {
    const elements = document.querySelectorAll('[data-message-index], [data-history-index]');
    const info = [];
    elements.forEach((elem) => {
      info.push({
        type: elem.classList.contains('user') ? 'user' : elem.classList.contains('ai') ? 'ai' : 'system',
        messageIndex: elem.dataset.messageIndex,
        historyIndex: elem.dataset.historyIndex,
        relatedIndex: elem.dataset.relatedMessageIndex,
        element: elem,
      });
    });
    console.table(info);
    return info;
  },
  validateIndexes: function () {
    const hasSystemMessage = aiChatApiOptionsBody.messages.length > 0 && aiChatApiOptionsBody.messages[0].role === 'system';
    const offset = hasSystemMessage ? 0 : 1;
    const issues = [];
    const elements = document.querySelectorAll('[data-message-index]');
    elements.forEach((elem) => {
      const domIndex = parseInt(elem.dataset.messageIndex);
      const actualIndex = domIndex - offset;
      if (actualIndex >= 0 && actualIndex < aiChatApiOptionsBody.messages.length) {
        const message = aiChatApiOptionsBody.messages[actualIndex];
        const expectedRole = elem.classList.contains('user') ? 'user' : 'assistant';
        if (message.role !== expectedRole) {
          issues.push({
            element: elem,
            domIndex,
            actualIndex,
            expectedRole,
            actualRole: message.role,
          });
        }
      } else {
        issues.push({
          element: elem,
          domIndex,
          actualIndex,
          error: 'Index out of bounds',
        });
      }
    });
    if (issues.length > 0) {
      console.error('Index validation issues:', issues);
    } else {
      console.log('All indexes are valid');
    }
    return issues;
  },
  showMessagesState: function () {
    console.log('System message exists:', aiChatApiOptionsBody.messages.length > 0 && aiChatApiOptionsBody.messages[0].role === 'system');
    console.log('Total messages:', aiChatApiOptionsBody.messages.length);
    console.log(
      'Messages:',
      aiChatApiOptionsBody.messages.map((m, i) => ({
        index: i,
        role: m.role,
        contentPreview: typeof m.content === 'string' ? m.content.substring(0, 50) + '...' : 'Complex content',
      })),
    );
  },
  showHistoryState: function () {
    console.log('Total history items:', messagesHistory.length);
    console.log(
      'History:',
      messagesHistory.map((item, i) => ({
        index: i,
        role: item.messages.role,
        isMcp: item.isMcp || false,
        contentPreview: typeof item.messages.content === 'string' ? item.messages.content.substring(0, 50) + '...' : 'Complex content',
      })),
    );
  },
};
async function requestAiChat(onStream, onDone, signal, aiBubble) {
  let fullContent = '';
  let fullThinkingContent = '';
  let hasReceivedMessage = false;
  try {
    let response;
    let retryCount = 0;
    const maxRetries = 5;
    while (true) {
      if (signal.aborted) {
        throw new DOMException('Request aborted by user', 'AbortError');
      }
      const options = getRequestAiChatApiOptions();
      options.signal = signal;
      response = await proxiedFetch(allModels[window.currentModel].api_url + '/chat/completions', options);
      if (response.status === 429) {
        if (retryCount >= maxRetries) {
          const errorMessage = `❌ **请求频率限制**\n\n服务器返回了 429 错误(请求过于频繁),已重试 ${maxRetries} 次后仍然失败。\n\n**建议:**\n- 请稍等片刻后再试\n- 或者切换到其他 API 模型`;
          if (onStream) {
            onStream(errorMessage);
          }
          if (onDone) {
            onDone(errorMessage);
          }
          return;
        }
        retryCount++;
        console.log(`Rate limit exceeded (429). Retrying after 1 second... (Attempt ${retryCount}/${maxRetries})`);
        await new Promise((resolve) => setTimeout(resolve, 1000));
        if (signal.aborted) {
          throw new DOMException('Request aborted by user', 'AbortError');
        }
        continue;
      }
      if (!response.ok) {
        const errorText = await response.text();
        try {
          const errorJson = JSON.parse(errorText);
          if (isContextLengthError(errorJson)) {
            if (retryCount >= maxRetries) {
              const errorMessage = `❌ **上下文长度超限**\n\n已尝试压缩上下文 ${maxRetries} 次，但仍然超出模型限制。\n\n**建议:**\n- 开启新对话\n- 或手动删除部分历史消息\n- 或切换到支持更长上下文的模型`;
              if (onStream) {
                onStream(errorMessage);
              }
              if (onDone) {
                onDone(errorMessage);
              }
              return;
            }
            let obj = await compressContext(aiChatApiOptionsBody, window.messagesHistory);
            if (obj) {
              aiChatApiOptionsBody = obj.aiChatApiOptionsBody;
              window.messagesHistory = obj.messagesHistory;
              retryCount++;
              continue;
            }
          }
        } catch (e) {}
      }
      break;
    }
    if (!response.ok) {
      const errorText = await response.text();
      let errorMessage = `❌ **请求失败 (${response.status} ${response.statusText})**\n\n`;
      try {
        const errorJson = JSON.parse(errorText);
        if (errorJson.error && errorJson.error.message) {
          errorMessage += `**错误详情:**\n${errorJson.error.message}\n\n`;
          if (errorJson.error.type) {
            errorMessage += `**错误类型:** ${errorJson.error.type}\n`;
          }
          if (errorJson.error.code) {
            errorMessage += `**错误代码:** ${errorJson.error.code}\n`;
          }
        } else {
          errorMessage += errorText;
        }
      } catch (e) {
        errorMessage += errorText;
      }
      errorMessage += `\n**建议:** 请检查请求参数或稍后重试`;
      if (onStream) {
        onStream(errorMessage);
      }
      if (onDone) {
        onDone(errorMessage);
      }
      return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let eventType = 'message';
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        if (aiBubble) {
          aiBubble.finishThinking();
        }
        if (onDone) {
          onDone(fullContent);
        }
        return;
      }
      console.log('done', done, 'value', decoder.decode(value, { stream: true }));
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (line.startsWith('event:')) {
          eventType = line.substring(6).trim();
          continue;
        }
        if (line.startsWith('data: ')) {
          const dataStr = line.substring(6).trim();
          if (dataStr === '[DONE]') {
            if (aiBubble) {
              aiBubble.finishThinking();
            }
            if (onDone) {
              onDone(fullContent);
            }
            return;
          }
          try {
            const data = JSON.parse(dataStr);
            if (data.choices && data.choices[0]) {
              if (data.choices[0].finish_reason === 'stop') {
                if (aiBubble) {
                  aiBubble.finishThinking();
                }
                if (onDone) {
                  onDone(fullContent);
                }
                return;
              }
              if (data.choices[0].delta) {
                const delta = data.choices[0].delta;
                const reasoningChunk = delta.reasoning_content;
                const contentChunk = delta.content;
                if (reasoningChunk) {
                  fullThinkingContent += reasoningChunk;
                  if (aiBubble) {
                    aiBubble.updateThinking(reasoningChunk);
                  }
                } else if (contentChunk) {
                  if (eventType === 'reasoning') {
                    fullThinkingContent += contentChunk;
                    if (aiBubble) {
                      aiBubble.updateThinking(contentChunk);
                    }
                  } else {
                    if (!hasReceivedMessage && fullThinkingContent && aiBubble) {
                      aiBubble.toggleThinking('closed');
                      hasReceivedMessage = true;
                    }
                    fullContent += contentChunk;
                    if (onStream) {
                      onStream(contentChunk);
                    }
                  }
                }
              }
            }
          } catch (e) {
            console.error('Error parsing SSE data:', e);
          }
        }
      }
    }
  } catch (error) {
    if (aiBubble) {
      aiBubble.finishDuration();
    }
    if (onDone) {
      onDone('Fetch Error:' + error);
    }
  }
}
async function proxiedFetch(url, options) {
  const proxySettings = await callBackend(backend, 'getSetting', ['ai_chat_proxy']);
  try {
    if (!proxySettings || !proxySettings.protocol || !proxySettings.host || !proxySettings.port) {
      return fetch(url, options);
    }
  } catch (e) {
    return fetch(url, options);
  }
  return new Promise((resolve, reject) => {
    const requestId = generateUniqueId();
    let streamController;
    const readableStream = new ReadableStream({
      start(controller) {
        streamController = controller;
      },
    });
    const onChunk = (receivedId, chunk) => {
      if (receivedId === requestId) {
        streamController.enqueue(new TextEncoder().encode(chunk));
      }
    };
    const onFinish = (receivedId, status, statusText, headersJson) => {
      if (receivedId === requestId) {
        cleanup();
        streamController.close();
        const headers = new Headers(JSON.parse(headersJson));
        const mockedResponse = {
          ok: status >= 200 && status < 300,
          status: status,
          statusText: statusText,
          headers: headers,
          body: readableStream,
          text: async () => {
            const reader = readableStream.getReader();
            let result = '';
            while (true) {
              const { done, value } = await reader.read();
              if (done) return result;
              result += new TextDecoder().decode(value);
            }
          },
          json: async () => {
            const text = await mockedResponse.text();
            return JSON.parse(text);
          },
        };
        resolve(mockedResponse);
      }
    };
    const onFail = (receivedId, errorMsg) => {
      if (receivedId === requestId) {
        cleanup();
        streamController.error(new Error(errorMsg));
        reject(new Error(errorMsg));
      }
    };
    const onAbort = () => {
      callBackend(backend, 'cancelProxiedFetch', [requestId]);
      cleanup();
      reject(new DOMException('Request aborted by user', 'AbortError'));
    };
    const cleanup = () => {
      if (options.signal) {
        options.signal.removeEventListener('abort', onAbort);
      }
      backend.streamChunkReceived.disconnect(onChunk);
      backend.streamFinished.disconnect(onFinish);
      backend.streamFailed.disconnect(onFail);
    };
    if (options.signal) {
      options.signal.addEventListener('abort', onAbort, { once: true });
    }
    backend.streamChunkReceived.connect(onChunk);
    backend.streamFinished.connect(onFinish);
    backend.streamFailed.connect(onFail);
    const optionsForBackend = {
      method: options.method,
      headers: options.headers,
      body: options.body,
    };
    backend.proxiedFetch(requestId, url, JSON.stringify(optionsForBackend));
  });
}
let bodyStyle = '<style id="dynamic-body-style"></style>';
document.body.insertAdjacentHTML('beforeend', bodyStyle);
let bodyStyleElement = document.getElementById('dynamic-body-style');
let onresize = function () {
  bodyStyleElement.textContent = `
    .message-wrapper {
      max-width: calc(100% - 46px);
    }
  `;
};
window.addEventListener('resize', onresize);
onresize();
