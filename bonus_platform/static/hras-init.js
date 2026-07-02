/**
 * HRAS 壳子平台适配脚本 (hras-init.js)
 *
 * 为 Vanilla HTML 页面提供零代码的壳子嵌入适配：
 * - 从 URL ?token=xxx 解析 JWT Token
 * - 监听 postMessage 接收壳子上下文
 * - 嵌入模式下添加 body.embedded 类
 * - 自动为同源 fetch/XHR 请求注入 Authorization 头
 *
 * 使用方式：在 </body> 前引入 <script src="hras-init.js"></script>
 */

(function () {
  'use strict';

  // ── Token 解析 ──────────────────────────────────
  function parseToken() {
    var params = new URLSearchParams(window.location.search);
    var token = params.get('token');
    if (token) {
      localStorage.setItem('hras_token', token);
      window.__hrasToken = token;
    } else {
      window.__hrasToken = localStorage.getItem('hras_token') || null;
    }
    return window.__hrasToken;
  }

  // ── 嵌入检测 ────────────────────────────────────
  function detectEmbedded() {
    if (window.self !== window.top) {
      document.body.classList.add('embedded');
    }
  }

  // ── 壳子上下文监听 ──────────────────────────────
  function listenShellContext() {
    window.addEventListener('message', function (event) {
      if (event.data && event.data.type === 'SHELL_CONTEXT') {
        var ctx = event.data.payload || {};
        if (ctx.token) {
          localStorage.setItem('hras_token', ctx.token);
          window.__hrasToken = ctx.token;
        }
        if (ctx.userId) {
          window.__hrasUser = {
            userId: ctx.userId,
            username: ctx.username || '',
            realName: ctx.realName || '',
            roleName: ctx.roleName || '',
            modulePermissions: ctx.modulePermissions || '',
          };
        }
        if (ctx.theme === 'dark') {
          document.documentElement.setAttribute('data-theme', 'dark');
        }
        if (ctx.locale) {
          document.documentElement.setAttribute('lang', ctx.locale);
        }
      }
    });
  }

  // ── Fetch 拦截器 ────────────────────────────────
  function interceptFetch() {
    var originalFetch = window.fetch;
    window.fetch = function (url, options) {
      options = options || {};
      options.headers = options.headers || {};
      var token = window.__hrasToken;
      if (token) {
        // 同源请求自动注入 Authorization
        var isSameOrigin = typeof url === 'string' && (url.startsWith('/') || url.startsWith(window.location.origin));
        if (isSameOrigin) {
          if (options.headers instanceof Headers) {
            if (!options.headers.has('Authorization')) {
              options.headers.set('Authorization', 'Bearer ' + token);
            }
          } else if (!options.headers['Authorization'] && !options.headers['authorization']) {
            options.headers['Authorization'] = 'Bearer ' + token;
          }
        }
      }
      return originalFetch.call(this, url, options);
    };
  }

  // ── 初始化 ──────────────────────────────────────
  function init() {
    parseToken();
    detectEmbedded();
    listenShellContext();
    interceptFetch();
  }

  // DOM 就绪后执行
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
