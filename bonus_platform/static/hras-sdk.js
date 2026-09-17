/**
 * HRAS SDK — 子应用接入脚本
 * @version 2.0.0
 * @description
 *  零配置接入 HRAS 壳子平台。自动处理 token 获取、用户上下文接收、
 *  API 请求鉴权注入、iframe 环境适配。重复加载幂等，不影响已有逻辑。
 *
 *  引入方式：
 *    <script src="https://<hras-host>/sdk/hras-sdk.js"></script>
 *
 *  接入后可用 API：
 *    await __HRAS__.ready()          // 等待上下文就绪
 *    __HRAS__.getUser()              // { userId, username, realName, roleName, modulePermissions, orgCode, feishuOpenId, feishuUnionId, feishuUserId, email }
 *    __HRAS__.getToken()             // jwt-string
 *    __HRAS__.requestContext()       // 主动向壳子请求上下文
 *    __HRAS__.destroy()              // 移除所有监听和拦截器
 *
 *  向后兼容（与 hras-init.js 一致）：
 *    window.__hrasToken              // token 字符串
 *    window.__hrasUser               // 用户对象
 *    document.body.classList.contains('embedded')  // 是否在 iframe 中
 */

(function () {
  'use strict';

  // ── 幂等检查：已初始化则跳过 ──────────────────────────────
  if (window.__hras_initialized) {
    return;
  }
  window.__hras_initialized = true;

  // ── 内部状态 ──────────────────────────────────────────────
  let _token = null;
  let _user = null;
  let _contextReceived = false;
  let _readyResolve = null;
  let _readyPromise = null;
  let _originWhitelist = [];  // 空数组表示不校验 origin
  let _destroyed = false;

  // fetch 拦截标记
  let _fetchWrapped = false;
  const _originalFetch = window.fetch;

  // XMLHttpRequest 拦截标记
  let _xhrWrapped = false;
  const _OriginalXHR = window.XMLHttpRequest;

  // ── 工具函数 ──────────────────────────────────────────────
  function isEmbedded() {
    try {
      return window.self !== window.top;
    } catch (e) {
      return true; // 跨域时无法访问 window.top，视为嵌入
    }
  }

  function isStandalone() {
    return !isEmbedded();
  }

  function parseTokenFromURL() {
    try {
      const params = new URLSearchParams(window.location.search);
      return params.get('token') || null;
    } catch (e) {
      return null;
    }
  }

  function cleanTokenFromURL() {
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.has('token')) {
        url.searchParams.delete('token');
        window.history.replaceState({}, document.title, url.pathname + url.search + url.hash);
      }
    } catch (e) {
      // 静默失败
    }
  }

  function parseJWT(token) {
    try {
      const payload = token.split('.')[1];
      return JSON.parse(atob(payload));
    } catch (e) {
      return null;
    }
  }

  // ── 上下文就绪 Promise ────────────────────────────────────
  function createReadyPromise() {
    if (_readyPromise) return _readyPromise;
    _readyPromise = new Promise(function (resolve) {
      _readyResolve = resolve;
      // 如果已经有上下文（同步接收到），直接 resolve
      if (_contextReceived) {
        resolve();
      }
    });
    return _readyPromise;
  }

  // ── 处理壳子上下文 ────────────────────────────────────────
  function handleShellContext(payload) {
    if (!payload) return;

    // token：已有则不覆盖（保留壳子下发的最新值）
    if (payload.token) {
      var existingToken = localStorage.getItem('token');
      if (existingToken !== payload.token) {
        localStorage.setItem('token', payload.token);
      }
      _token = payload.token;
      window.__hrasToken = _token;

      // 如果没有 user 对象但 token 中有数据，从 JWT 中提取
      if (!payload.userId && !payload.username) {
        var jwt = parseJWT(payload.token);
        if (jwt) {
          _user = _user || {};
          _user.userId = _user.userId || jwt.userId;
          _user.username = _user.username || jwt.username || jwt.sub;
          _user.roleName = _user.roleName || jwt.role;
        }
      }
    }

    // user 信息合并：新 payload 中的字段覆盖已有值
    if (payload.userId !== undefined || payload.username !== undefined) {
      _user = _user || {};

      if (payload.userId !== undefined) _user.userId = payload.userId;
      if (payload.username !== undefined) _user.username = payload.username;
      if (payload.realName !== undefined) _user.realName = payload.realName;
      if (payload.roleName !== undefined) _user.roleName = payload.roleName;
      if (payload.modulePermissions !== undefined) {
        _user.modulePermissions = payload.modulePermissions;
      }
      if (payload.feishuOpenId !== undefined) _user.feishuOpenId = payload.feishuOpenId;
      if (payload.feishuUnionId !== undefined) _user.feishuUnionId = payload.feishuUnionId;
      if (payload.feishuUserId !== undefined) _user.feishuUserId = payload.feishuUserId;
      if (payload.email !== undefined) _user.email = payload.email;
      if (payload.orgCode !== undefined) _user.orgCode = payload.orgCode;

      window.__hrasUser = _user;
    }

    // 标记上下文已接收
    if (!_contextReceived && (_token || _user)) {
      _contextReceived = true;
      if (_readyResolve) {
        _readyResolve();
      }
    }

    // 适配壳子主题
    if (payload.theme === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark');
    }
  }

  // ── message 事件监听 ──────────────────────────────────────
  function onMessage(event) {
    if (_destroyed) return;

    // origin 白名单校验
    if (_originWhitelist.length > 0 && !_originWhitelist.includes(event.origin)) {
      return;
    }

    if (event.data && event.data.type === 'SHELL_CONTEXT') {
      handleShellContext(event.data.payload);
    }
  }

  window.addEventListener('message', onMessage);

  // ── fetch 拦截 ────────────────────────────────────────────
  function wrapFetch() {
    if (_fetchWrapped) return;
    _fetchWrapped = true;

    window.fetch = function (url, options) {
      options = options || {};
      var token = _token || localStorage.getItem('token');

      if (token) {
        options.headers = options.headers || {};
        // 支持 Headers 对象和普通对象
        if (options.headers instanceof Headers) {
          if (!options.headers.has('Authorization')) {
            options.headers.set('Authorization', 'Bearer ' + token);
          }
        } else {
          if (!options.headers['Authorization'] && !options.headers['authorization']) {
            options.headers['Authorization'] = 'Bearer ' + token;
          }
        }
      }

      return _originalFetch.call(window, url, options);
    };
  }

  // ── XMLHttpRequest 拦截 ───────────────────────────────────
  function wrapXHR() {
    if (_xhrWrapped) return;
    _xhrWrapped = true;

    window.XMLHttpRequest = function () {
      var xhr = new _OriginalXHR();
      var originalOpen = xhr.open;
      var originalSetRequestHeader = xhr.setRequestHeader;

      var method, url;

      xhr.open = function () {
        method = arguments[0];
        url = arguments[1];
        return originalOpen.apply(xhr, arguments);
      };

      xhr.setRequestHeader = function (header, value) {
        if (header.toLowerCase() === 'authorization') {
          xhr.__hras_auth_set = true;
        }
        return originalSetRequestHeader.call(xhr, header, value);
      };

      var originalSend = xhr.send;
      xhr.send = function () {
        if (!xhr.__hras_auth_set) {
          var token = _token || localStorage.getItem('token');
          if (token) {
            originalSetRequestHeader.call(xhr, 'Authorization', 'Bearer ' + token);
          }
        }
        return originalSend.apply(xhr, arguments);
      };

      return xhr;
    };

    // 保留原型链
    window.XMLHttpRequest.prototype = _OriginalXHR.prototype;
  }

  // ── 自动请求上下文（超时回退） ─────────────────────────────
  function autoRequestContext() {
    if (_contextReceived) return;
    if (isStandalone()) return;  // 独立模式不请求

    setTimeout(function () {
      if (_destroyed || _contextReceived) return;
      // 主动向父窗口请求上下文
      try {
        window.parent.postMessage(
          { type: 'SHELL_CONTEXT_REQUEST', timestamp: Date.now() },
          '*'
        );
      } catch (e) {
        // 跨域发送失败，静默忽略
      }
    }, 1500);  // 1.5 秒后仍未收到则主动请求
  }

  // ── 初始化 ────────────────────────────────────────────────
  function init() {
    if (_destroyed) return;

    // 1. 检测 iframe 嵌入
    if (isEmbedded()) {
      document.body && document.body.classList.add('embedded');
    }

    // 2. 从 URL 解析 token
    var urlToken = parseTokenFromURL();
    if (urlToken) {
      if (!localStorage.getItem('token')) {
        localStorage.setItem('token', urlToken);
      }
      _token = _token || urlToken;
      window.__hrasToken = _token;
      cleanTokenFromURL();

      // 从 JWT 提取基础用户信息
      var jwt = parseJWT(_token);
      if (jwt) {
        _user = _user || {};
        _user.userId = _user.userId || jwt.userId;
        _user.username = _user.username || jwt.username || jwt.sub;
        _user.roleName = _user.roleName || jwt.role;
        window.__hrasUser = _user;
      }
    }

    // 3. 如果 localStorage 中已有 token（前序加载写入的），读取
    if (!_token) {
      var storedToken = localStorage.getItem('token');
      if (storedToken) {
        _token = storedToken;
        window.__hrasToken = _token;
      }
    }

    // 4. 包装 fetch / XHR
    wrapFetch();
    wrapXHR();

    // 5. 创建 ready Promise
    createReadyPromise();

    // 6. 在 iframe 中启动自动请求上下文
    autoRequestContext();

    // 7. 如果独立模式且已有 token，直接标记就绪
    if (isStandalone() && _token) {
      _contextReceived = true;
      if (_readyResolve) {
        _readyResolve();
      }
    }
  }

  // ── 公开 API ──────────────────────────────────────────────
  var HRAS = {
    /**
     * 等待壳子上下文就绪
     * @returns {Promise<void>}
     */
    ready: function () {
      createReadyPromise();
      return _readyPromise;
    },

    /**
     * 获取当前用户信息
     * @returns {Object|null}
     */
    getUser: function () {
      return _user || null;
    },

    /**
     * 获取当前 token
     * @returns {string|null}
     */
    getToken: function () {
      return _token || localStorage.getItem('token') || null;
    },

    /**
     * 主动向壳子请求上下文
     */
    requestContext: function () {
      if (isStandalone()) return;
      try {
        window.parent.postMessage(
          { type: 'SHELL_CONTEXT_REQUEST', timestamp: Date.now() },
          '*'
        );
      } catch (e) {
        // 静默
      }
    },

    /**
     * 设置 origin 白名单
     * @param {string[]} origins
     */
    setOriginWhitelist: function (origins) {
      _originWhitelist = origins || [];
    },

    /**
     * 销毁 SDK（移除监听和拦截器，用于测试）
     */
    destroy: function () {
      _destroyed = true;
      window.removeEventListener('message', onMessage);

      if (_fetchWrapped) {
        window.fetch = _originalFetch;
        _fetchWrapped = false;
      }

      if (_xhrWrapped) {
        window.XMLHttpRequest = _OriginalXHR;
        _xhrWrapped = false;
      }

      delete window.__hrasToken;
      delete window.__hrasUser;
      delete window.__hras_initialized;

      _token = null;
      _user = null;
      _contextReceived = false;
      _readyResolve = null;
      _readyPromise = null;
    },
  };

  window.__HRAS__ = HRAS;

  // 向后兼容：保留旧 API
  if (!window.__hrasToken) {
    window.__hrasToken = null;
  }
  if (!window.__hrasUser) {
    window.__hrasUser = null;
  }

  // 启动
  init();
})();
