/**
 * HRAS 壳子平台 SDK (hras-sdk.js)
 *
 * 为子应用提供零代码的壳子嵌入适配：
 * - 从 URL ?token=xxx 解析 JWT Token
 * - 监听 postMessage 接收壳子上下文
 * - 嵌入模式下添加 body.embedded 类
 * - 自动为同源 fetch/XHR 请求注入 Authorization 头
 * - 提供 __HRAS__ 全局 API
 *
 * 使用方式：在 </body> 前引入 <script src="hras-sdk.js"></script>
 *
 * 版本：v2.0（兼容旧版 hras-init.js）
 */

(function () {
  'use strict';

  // ── 内部状态 ────────────────────────────────────
  var _token = null;
  var _user = null;
  var _readyResolve = null;
  var _readyPromise = null;
  var _readyTimeout = null;
  var _originWhitelist = [];
  var _moduleKey = '';
  var _logEnabled = true;
  var _destroyed = false;
  var _originalFetch = null;

  function _noop() {}

  // ── Token 解析 ──────────────────────────────────
  function _parseTokenFromURL() {
    try {
      var params = new URLSearchParams(window.location.search);
      var t = params.get('token');
      if (t) {
        _setToken(t);
      } else if (!_token) {
        var stored = localStorage.getItem('hras_token');
        if (stored) {
          _token = stored;
          window.__hrasToken = _token;
        }
      }
    } catch (_) { /* ignore */ }
  }

  function _setToken(token) {
    if (!token) return;
    _token = token;
    try { localStorage.setItem('hras_token', token); } catch (_) { /* ignore */ }
    window.__hrasToken = token;
  }

  // ── 用户信息 ────────────────────────────────────
  function _setUser(ctx) {
    _user = {
      userId: ctx.userId || null,
      username: ctx.username || '',
      realName: ctx.realName || '',
      feishuOpenId: ctx.feishuOpenId || '',
      feishuUnionId: ctx.feishuUnionId || '',
      feishuUserId: ctx.feishuUserId || '',
      email: ctx.email || '',
      roleName: ctx.roleName || '',
      buId: ctx.buId || null,
      buCode: ctx.buCode || '',
      orgCode: ctx.orgCode || '',
      orgBsCode: ctx.orgBsCode || '',
      modulePermissions: ctx.modulePermissions || '',
    };
    window.__hrasUser = _user;
  }

  // ── 嵌入检测 ────────────────────────────────────
  function _detectEmbedded() {
    try {
      if (window.self !== window.top) {
        document.body.classList.add('embedded');
      }
    } catch (_) {
      // cross-origin access to window.top may throw → treat as embedded
      document.body.classList.add('embedded');
    }
  }

  // ── Origin 白名单检查 ───────────────────────────
  function _isOriginAllowed(origin) {
    if (_originWhitelist.length === 0) return true;
    for (var i = 0; i < _originWhitelist.length; i++) {
      if (_originWhitelist[i] === origin) return true;
    }
    return false;
  }

  // ── 壳子上下文监听 ──────────────────────────────
  function _listenShellContext() {
    window.addEventListener('message', function (event) {
      if (_destroyed) return;

      // origin 白名单过滤
      if (event.origin && event.origin !== window.location.origin && !_isOriginAllowed(event.origin)) {
        return;
      }

      var data = event.data;
      if (!data || data.type !== 'SHELL_CONTEXT') return;

      var ctx = data.payload || {};
      if (ctx.token) {
        _setToken(ctx.token);
      }
      if (ctx.userId) {
        _setUser(ctx);
      }
      if (ctx.theme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
      }
      if (ctx.locale) {
        document.documentElement.setAttribute('lang', ctx.locale);
      }

      // resolve ready promise
      if (_readyResolve) {
        _readyResolve();
        _readyResolve = null;
      }
    });
  }

  // ── 主动请求壳子上下文 ──────────────────────────
  function _requestContextFromShell() {
    try {
      window.parent.postMessage({ type: 'SHELL_CONTEXT_REQUEST' }, '*');
    } catch (_) { /* ignore */ }
  }

  // ── 就绪 Promise ────────────────────────────────
  function _createReadyPromise() {
    if (_readyPromise) return;

    var resolved = false;
    _readyPromise = new Promise(function (resolve) {
      _readyResolve = resolve;

      // 1.5s 后自动请求壳子上下文
      _readyTimeout = setTimeout(function () {
        _requestContextFromShell();
      }, 1500);

      // 5s 超时自动 resolve（壳子不可达时也不阻塞）
      var fallback = setTimeout(function () {
        if (!resolved) {
          resolved = true;
          resolve();
          _readyResolve = null;
        }
      }, 5000);

      // 包装 resolve：resolve 时清理 fallback
      var origResolve = resolve;
      _readyResolve = function () {
        if (resolved) return;
        resolved = true;
        clearTimeout(fallback);
        origResolve();
      };
    });
  }

  // ── Fetch 拦截器 ────────────────────────────────
  function _interceptFetch() {
    if (_originalFetch !== null) return; // already intercepted
    _originalFetch = window.fetch;
    window.fetch = function (url, options) {
      options = options || {};
      options.headers = options.headers || {};

      var token = _token;
      if (token) {
        var isSameOrigin = false;
        if (typeof url === 'string') {
          isSameOrigin = url.startsWith('/') || url.startsWith(window.location.origin);
        } else if (url instanceof Request) {
          isSameOrigin = url.url.startsWith('/') || url.url.startsWith(window.location.origin);
        }

        if (isSameOrigin) {
          if (options.headers instanceof Headers) {
            if (!options.headers.has('Authorization')) {
              options.headers.set('Authorization', 'Bearer ' + token);
            }
          } else if (typeof options.headers === 'object' && options.headers !== null) {
            if (!options.headers['Authorization'] && !options.headers['authorization']) {
              options.headers['Authorization'] = 'Bearer ' + token;
            }
          }
        }
      }

      return _originalFetch.call(this, url, options);
    };
  }

  // ── XHR 拦截器 ──────────────────────────────────
  var _originalXHROpen = null;
  function _interceptXHR() {
    if (_originalXHROpen !== null) return;
    _originalXHROpen = XMLHttpRequest.prototype.open;
    var _originalSetRequestHeader = XMLHttpRequest.prototype.setRequestHeader;

    XMLHttpRequest.prototype.open = function (method, url) {
      this._hras_url = url;
      this._hras_method = method;
      return _originalXHROpen.apply(this, arguments);
    };

    XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
      if (name.toLowerCase() === 'authorization') {
        this._hras_hasAuth = true;
      }
      return _originalSetRequestHeader.apply(this, arguments);
    };

    var _originalSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function (body) {
      var token = _token;
      if (token && !this._hras_hasAuth) {
        var url = this._hras_url || '';
        var isSameOrigin = typeof url === 'string' && (url.startsWith('/') || url.startsWith(window.location.origin));
        if (isSameOrigin) {
          _originalSetRequestHeader.call(this, 'Authorization', 'Bearer ' + token);
        }
      }
      return _originalSend.call(this, body);
    };
  }

  // ── 恢复 fetch ──────────────────────────────────
  function _restoreFetch() {
    if (_originalFetch !== null) {
      window.fetch = _originalFetch;
      _originalFetch = null;
    }
  }

  // ── 恢复 XHR ────────────────────────────────────
  function _restoreXHR() {
    if (_originalXHROpen !== null) {
      XMLHttpRequest.prototype.open = _originalXHROpen;
      _originalXHROpen = null;
    }
  }

  // ── 公开 API（__HRAS__）─────────────────────────
  var HRAS = {
    /**
     * 等待壳子上下文就绪。
     * 如果 1.5 秒内未收到 SHELL_CONTEXT，自动向壳子发送 SHELL_CONTEXT_REQUEST。
     * @returns {Promise<void>}
     */
    ready: function () {
      if (_destroyed) return Promise.reject(new Error('SDK has been destroyed'));
      if (!_readyPromise) _createReadyPromise();
      return _readyPromise;
    },

    /**
     * 获取当前用户信息。
     * @returns {{ userId: number|null, username: string, realName: string, roleName: string,
     *             buId: number|null, buCode: string, orgCode: string, orgBsCode: string,
     *             modulePermissions: string } | null}
     */
    getUser: function () {
      return _user;
    },

    /**
     * 获取当前 JWT Token。
     * @returns {string | null}
     */
    getToken: function () {
      return _token;
    },

    /**
     * 主动向壳子发送 SHELL_CONTEXT_REQUEST，壳子收到后重新下发上下文。
     */
    requestContext: function () {
      _requestContextFromShell();
    },

    /**
     * 设置 postMessage origin 白名单。仅接受来自指定源的 SHELL_CONTEXT 消息。
     * @param {string[]} origins - 允许的 origin 列表
     */
    setOriginWhitelist: function (origins) {
      _originWhitelist = Array.isArray(origins) ? origins.slice() : [];
    },

    /**
     * 设置当前模块标识（用于操作日志上报）。
     * @param {string} key - 模块标识
     */
    setModuleKey: function (key) {
      _moduleKey = key || '';
    },

    /**
     * 启用/暂停日志采集。
     * @param {boolean} enabled
     */
    setLogEnabled: function (enabled) {
      _logEnabled = !!enabled;
    },

    /**
     * 壳子内自动登录：用壳子 JWT Token + 用户上下文向后端换取 sigma_session。
     * @returns {Promise<object|null>} 成功后返回用户对象，失败返回 null
     */
    login: function () {
      if (_destroyed) return Promise.reject(new Error('SDK has been destroyed'));
      if (!_token) return Promise.resolve(null);

      // 优先使用 postMessage 上下文；无上下文时用空 body（后端从 JWT payload 提取 username）
      var body = {};
      if (_user) {
        body = {
          userId: _user.userId,
          username: _user.username,
          realName: _user.realName,
          feishuOpenId: _user.feishuOpenId || null,
          feishuUnionId: _user.feishuUnionId || null,
          feishuUserId: _user.feishuUserId || null,
          email: _user.email || null,
          roleName: _user.roleName,
          buId: _user.buId,
          buCode: _user.buCode,
          orgCode: _user.orgCode,
          orgBsCode: _user.orgBsCode,
        };
      }

      return fetch('/api/auth/shell/login', {
        method: 'POST',
        headers: {
          'Authorization': 'Bearer ' + _token,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
      }).then(function (resp) {
        if (resp.ok) return resp.json();
        return null;
      }).catch(function () {
        return null;
      });
    },

    /**
     * 移除所有事件监听器和拦截器，恢复 fetch 和 XMLHttpRequest 原始实现。
     * 用于测试或 SDK 重载场景。
     */
    destroy: function () {
      _destroyed = true;
      _restoreFetch();
      _restoreXHR();
      if (_readyTimeout) {
        clearTimeout(_readyTimeout);
        _readyTimeout = null;
      }
      _readyResolve = null;
      _readyPromise = null;
    },
  };

  // ── 初始化 ──────────────────────────────────────
  function _init() {
    if (_destroyed) return;

    // 向后兼容：暴露全局变量
    window.__HRAS__ = HRAS;
    window.__hrasToken = window.__hrasToken || null;
    window.__hrasUser = window.__hrasUser || null;

    _parseTokenFromURL();
    _detectEmbedded();
    _listenShellContext();
    _interceptFetch();
    _interceptXHR();
    _createReadyPromise();

    // 有 token 时自动向 shell/login 换取 sigma_session cookie
    // （不限于 iframe 嵌入模式，直接访问 URL?token=xxx 也支持）
    if (_token) {
      _readyPromise.then(function () {
        if (_token && !_destroyed) {
          HRAS.login().catch(function () { /* silent fallback */ });
        }
      });
    }
  }

  // DOM 就绪后执行
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _init);
  } else {
    _init();
  }
})();
