(() => {
  const vertexSmokeySource = `
    attribute vec4 a_position;
    void main() {
      gl_Position = a_position;
    }
  `;
  const fragmentSmokeySource = `
    precision mediump float;
    uniform vec2 iResolution;
    uniform float iTime;
    uniform vec2 iMouse;
    uniform vec3 u_color;

    void mainImage(out vec4 fragColor, in vec2 fragCoord) {
      vec2 centeredUV = (2.0 * fragCoord - iResolution.xy) / min(iResolution.x, iResolution.y);
      float time = iTime * 0.48;
      vec2 mouse = iMouse / iResolution;
      vec2 rippleCenter = 2.0 * mouse - 1.0;
      vec2 distortion = centeredUV;

      for (float i = 1.0; i < 8.0; i++) {
        distortion.x += 0.42 / i * cos(i * 2.0 * distortion.y + time + rippleCenter.x * 3.1415);
        distortion.y += 0.42 / i * cos(i * 2.0 * distortion.x + time + rippleCenter.y * 3.1415);
      }

      float wave = abs(sin(distortion.x + distortion.y + time));
      float glow = smoothstep(0.88, 0.18, wave);
      float vignette = smoothstep(1.35, 0.18, length(centeredUV));
      fragColor = vec4(u_color * glow * vignette, 1.0);
    }

    void main() {
      mainImage(gl_FragColor, gl_FragCoord.xy);
    }
  `;

  const initSmokeyBackground = () => {
    const canvas = document.getElementById("loginSmokeyCanvas");
    if (!(canvas instanceof HTMLCanvasElement)) return;
    const gl = canvas.getContext("webgl", { alpha: true, antialias: false });
    if (!gl) return;

    const compileShader = (type, source) => {
      const shader = gl.createShader(type);
      if (!shader) return null;
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        gl.deleteShader(shader);
        return null;
      }
      return shader;
    };

    const vertexShader = compileShader(gl.VERTEX_SHADER, vertexSmokeySource);
    const fragmentShader = compileShader(gl.FRAGMENT_SHADER, fragmentSmokeySource);
    if (!vertexShader || !fragmentShader) return;

    const program = gl.createProgram();
    if (!program) return;
    gl.attachShader(program, vertexShader);
    gl.attachShader(program, fragmentShader);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return;
    gl.useProgram(program);

    const positionBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
      -1, -1, 1, -1, -1, 1,
      -1, 1, 1, -1, 1, 1,
    ]), gl.STATIC_DRAW);

    const positionLocation = gl.getAttribLocation(program, "a_position");
    gl.enableVertexAttribArray(positionLocation);
    gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0);

    const resolutionLocation = gl.getUniformLocation(program, "iResolution");
    const timeLocation = gl.getUniformLocation(program, "iTime");
    const mouseLocation = gl.getUniformLocation(program, "iMouse");
    const colorLocation = gl.getUniformLocation(program, "u_color");
    gl.uniform3f(colorLocation, 0.17, 0.42, 0.95);

    const mouse = { x: 0, y: 0, active: false };
    const startedAt = Date.now();
    const resize = () => {
      const width = Math.max(1, canvas.clientWidth);
      const height = Math.max(1, canvas.clientHeight);
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(width * ratio);
      canvas.height = Math.floor(height * ratio);
      gl.viewport(0, 0, canvas.width, canvas.height);
    };
    const render = () => {
      resize();
      const width = canvas.width;
      const height = canvas.height;
      gl.uniform2f(resolutionLocation, width, height);
      gl.uniform1f(timeLocation, (Date.now() - startedAt) / 1000);
      gl.uniform2f(
        mouseLocation,
        mouse.active ? mouse.x * (window.devicePixelRatio || 1) : width / 2,
        mouse.active ? height - mouse.y * (window.devicePixelRatio || 1) : height / 2,
      );
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      window.requestAnimationFrame(render);
    };

    canvas.addEventListener("mousemove", (event) => {
      const rect = canvas.getBoundingClientRect();
      mouse.x = event.clientX - rect.left;
      mouse.y = event.clientY - rect.top;
      mouse.active = true;
    });
    canvas.addEventListener("mouseleave", () => {
      mouse.active = false;
    });
    window.addEventListener("resize", resize);
    render();
  };

  initSmokeyBackground();

  const fallbackUsers = [
    { id: "payrollAdmin", name: "Payroll Admin", roleIds: ["admin"] },
    { id: "recruitmentAdminUser", name: "Recruitment Admin", roleIds: ["recruitmentAdmin"] },
    { id: "cnPayrollAdminUser", name: "CN Payroll Admin", roleIds: ["employeeAdmin", "domesticAdmin", "socialInsuranceAdmin"] },
    { id: "fbuAdminUser", name: "FBU Bonus Admin", roleIds: ["fbuAdmin"] },
    { id: "overseasAdminUser", name: "Overseas Audit Admin", roleIds: ["overseasAdmin"] },
  ];
  const roleNames = {
    admin: "系统管理员",
    recruitmentAdmin: "招聘奖金核算管理员",
    employeeAdmin: "国内正式工核算管理员",
    domesticAdmin: "国内外包工核算管理员",
    fbuAdmin: "FBU美洲绩效核算管理员",
    overseasAdmin: "海外报账管理员",
    socialInsuranceAdmin: "社保报盘管理员",
  };
  const userList = document.getElementById("loginUserList");
  const status = document.getElementById("loginStatus");
  const feishuLoginLink = document.getElementById("feishuLoginLink");
  const feishuLoginStatus = document.getElementById("feishuLoginStatus");
  const mockLoginPanel = document.getElementById("mockLoginPanel");
  const searchParams = new URLSearchParams(window.location.search);
  const nextUrl = searchParams.get("next") || "/";
  const isLocalDev = ["localhost", "127.0.0.1", ""].includes(window.location.hostname);
  const mockEnabled = isLocalDev || searchParams.get("mock") === "1";

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);

  const showMockLogin = () => {
    if (!mockLoginPanel) return;
    mockLoginPanel.hidden = false;
    mockLoginPanel.open = mockEnabled;
  };

  const redirectIfAlreadyLoggedIn = async () => {
    if (searchParams.get("force") === "1") return false;
    try {
      const response = await fetch("/api/me", { credentials: "same-origin" });
      if (!response.ok) return false;
      sessionStorage.removeItem("sigma-auth-context-v1");
      sessionStorage.setItem("sigma-auth-context-v2", JSON.stringify({
        createdAt: Date.now(),
        me: await response.json(),
      }));
      if (status) status.textContent = "已登录，正在进入工作台...";
      window.location.replace(nextUrl);
      return true;
    } catch {
      return false;
    }
  };

  const renderUsers = (users) => {
    userList.innerHTML = users.map(user => `
      <button type="button" data-user-id="${escapeHtml(user.id)}">
        <strong>${escapeHtml(user.name)}</strong>
        <span>${escapeHtml((user.roleIds || []).map(roleId => roleNames[roleId] || roleId).join("、") || "待授权")}</span>
      </button>
    `).join("");
  };

  const loadUsers = async () => {
    try {
      const response = await fetch("/api/auth/mock-users");
      if (!response.ok) throw new Error(`API ${response.status}`);
      const data = await response.json();
      renderUsers(data.users || fallbackUsers);
      if (status) status.textContent = "开发调试模式：请选择一个模拟用户登录。";
    } catch {
      renderUsers(fallbackUsers);
      if (status) status.textContent = "开发调试模式：未连接后端，显示本地模拟用户。";
    }
  };

  const loadFeishuConfig = async () => {
    try {
      const response = await fetch("/api/auth/feishu/config");
      if (!response.ok) throw new Error(`API ${response.status}`);
      const data = await response.json();
      if (data.configured) {
        feishuLoginLink.setAttribute("aria-disabled", "false");
        feishuLoginLink.href = `/api/auth/feishu/login?next=${encodeURIComponent(nextUrl)}`;
        if (feishuLoginStatus) feishuLoginStatus.textContent = "飞书应用已配置，可进入授权登录流程。";
        if (mockEnabled) {
          showMockLogin();
          await loadUsers();
        } else {
          if (status) status.textContent = "请使用飞书登录。角色授权由系统管理员在后台管理中配置。";
        }
      } else {
        if (feishuLoginStatus) feishuLoginStatus.textContent = "飞书应用尚未配置，当前仅开放开发调试模拟登录。";
        showMockLogin();
        await loadUsers();
      }
    } catch {
      if (feishuLoginStatus) feishuLoginStatus.textContent = "后端未连接，当前仅开放开发调试模拟登录。";
      showMockLogin();
      await loadUsers();
    }
  };

  feishuLoginLink.addEventListener("click", (event) => {
    if (feishuLoginLink.getAttribute("aria-disabled") !== "false") {
      event.preventDefault();
    }
  });

  userList.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-user-id]");
    if (!button) return;
    if (status) status.textContent = "正在登录...";
    try {
      const response = await fetch("/api/auth/mock-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userId: button.dataset.userId }),
      });
      if (!response.ok) throw new Error(`API ${response.status}`);
      sessionStorage.removeItem("sigma-auth-context-v1");
      sessionStorage.removeItem("sigma-auth-context-v2");
      window.location.href = nextUrl;
    } catch {
      sessionStorage.removeItem("sigma-auth-context-v1");
      sessionStorage.removeItem("sigma-auth-context-v2");
      localStorage.setItem("sigma-admin-console-draft-v3", JSON.stringify({
        selectedUserId: button.dataset.userId,
      }));
      if (status) status.textContent = "后端未连接，已切换本地模拟用户。";
      window.location.href = nextUrl;
    }
  });

  redirectIfAlreadyLoggedIn().then((redirected) => {
    if (!redirected) loadFeishuConfig();
  });
})();
