"""人类可读索引页（同步根目录下的 index.html）使用的 HTML/CSS/JS 模板。

页面由 human_index.update_human_index() 渲染，模板占位符：

  INDEX_TEMPLATE
    __CSS__                 HUMAN_INDEX_CSS
    __JS__                  HUMAN_INDEX_JS
    __PLATFORM_TABLE_ROWS__ 计算平台 + PEP 503 地址表格的 <tr> 行
    __PLATFORM_BUTTONS__    配置帮助里的平台切换按钮
    __PLATFORM_PANELS__     各平台的 pip/uv/conda/mamba 配置面板
  PLATFORM_TABLE_ROW_TEMPLATE / PLATFORM_TAB_BUTTON_TEMPLATE / PLATFORM_CONFIG_TEMPLATE
    __PLATFORM__         平台名（cpu/cu126/rocm7.2）
    __PLATFORM_ID__      平台名转换出的 HTML id 片段（rocm7.2 → rocm7-2）
    __SIMPLE_REPO_URL__  该平台对外提供的 PEP 503 索引地址
    __UV_TOML_SNIPPET__  build_uv_sources_snippet() 生成的 uv 配置片段
  LEGACY_REDIRECT_TEMPLATE
    __INDEX_URL__        新索引页的绝对地址（旧地址 302 式跳转用）
"""

HUMAN_INDEX_CSS = """    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      max-width: 960px;
      margin: 2rem auto;
      padding: 0 1rem;
      line-height: 1.65;
      color: #1f2328;
      background: #fff;
    }
    h1 { font-size: 1.55rem; margin: 0 0 0.5rem; }
    h2 { font-size: 1.2rem; margin: 1.6rem 0 0.6rem; padding-bottom: 0.3rem; border-bottom: 1px solid #d0d7de; }
    h3 { font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }
    h4 { font-size: 1rem; margin: 1rem 0 0.3rem; }
    h5 { font-size: 0.95rem; margin: 0.9rem 0 0.3rem; color: #24292f; }
    p { margin: 0.5rem 0; }
    code {
      font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
      background: #f6f8fa;
      padding: 0.15em 0.4em;
      border-radius: 4px;
      font-size: 0.9em;
    }
    pre {
      background: #f6f8fa;
      border: 1px solid #d0d7de;
      border-radius: 6px;
      padding: 0.8rem 1rem;
      overflow-x: auto;
      margin: 0.5rem 0;
    }
    pre code { background: none; padding: 0; font-size: 0.9rem; }
    table { border-collapse: collapse; width: 100%; margin: 0.8rem 0; }
    th, td { border: 1px solid #d0d7de; padding: 0.45rem 0.7rem; text-align: left; vertical-align: top; }
    th { background: #f6f8fa; }
    td code { word-break: break-all; }
    a { color: #0969da; text-decoration: none; }
    a:hover { text-decoration: underline; }
    blockquote { margin: 0.8rem 0; padding: 0.4rem 1rem; border-left: 4px solid #d0d7de; color: #57606a; }
    .hint { color: #57606a; }
    .copy-btn {
      font: inherit; padding: 0.25rem 0.8rem; border: 1px solid #d0d7de;
      border-radius: 6px; background: #fff; cursor: pointer; color: #24292f;
    }
    .copy-btn:hover { background: #f6f8fa; }
    .copy-btn.copied { color: #1a7f37; border-color: #1a7f37; }
    .tab-bar { display: flex; flex-wrap: wrap; gap: 0.4rem 0.6rem; margin: 0.6rem 0; }
    .tab-btn {
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 0.95rem; padding: 0.25rem 0.9rem; border: 1px solid #d0d7de;
      border-radius: 999px; background: #fff; cursor: pointer; color: #24292f;
    }
    .tab-btn:hover { background: #f6f8fa; }
    .tab-btn.active { background: #0969da; border-color: #0969da; color: #fff; }
    .config-panel {
      border: 1px solid #d0d7de; border-radius: 8px; background: #fbfcfd;
      padding: 0.2rem 1.1rem 1.1rem; margin: 0.9rem 0;
    }
    /* 有 JS 时默认折叠，点击平台按钮展开对应面板；无 JS 时全部展开，避免内容不可见 */
    .has-js .config-panel { display: none; }
    .has-js .config-panel.active { display: block; }
    ul.logs { padding-left: 1.3rem; margin: 0.6rem 0; }
    ul.logs li { margin: 0.35rem 0; }
    /* 折叠区块：默认收起，summary 沿用 h2 的标题样式，左侧加展开指示三角 */
    details.section { margin: 1.6rem 0 0; }
    details.section > summary {
      display: block; cursor: pointer; list-style: none;
      border-bottom: 1px solid #d0d7de; padding-bottom: 0.3rem;
    }
    details.section > summary::-webkit-details-marker { display: none; }
    details.section > summary::before { content: "\\25B8"; margin-right: 0.4rem; color: #57606a; }
    details.section[open] > summary::before { content: "\\25BE"; }
    details.section > summary h2 { display: inline; margin: 0; padding: 0; border: none; }
    details.section > summary:hover h2 { color: #0969da; }
    details.section > summary:focus-visible { outline: 2px solid #0969da; outline-offset: 2px; }
    .footer { margin-top: 2rem; padding-top: 0.8rem; border-top: 1px solid #d0d7de; font-size: 0.9rem; color: #57606a; }"""

HUMAN_INDEX_JS = """    function copyCmd(id, btn) {
      const code = document.getElementById(id).textContent;
      const done = function() {
        const orig = btn.textContent;
        btn.textContent = "已复制 ✓";
        btn.classList.add("copied");
        setTimeout(function() { btn.textContent = orig; btn.classList.remove("copied"); }, 1500);
      };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(code).then(done).catch(function() { fallback(code, done); });
      } else {
        fallback(code, done);
      }
    }
    function fallback(text, done) {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); } catch (e) {}
      document.body.removeChild(ta);
      done();
    }
    function closeAllConfigs() {
      document.querySelectorAll(".config-panel.active").forEach(function(panel) {
        panel.classList.remove("active");
      });
      document.querySelectorAll(".tab-btn.active").forEach(function(btn) {
        btn.classList.remove("active");
      });
    }
    function showConfig(panelId, btn) {
      const panel = document.getElementById(panelId);
      if (!panel) { return; }
      // 点击已展开的平台按钮时收起，方便看后面的内容
      const wasActive = panel.classList.contains("active");
      closeAllConfigs();
      if (!wasActive) {
        panel.classList.add("active");
        if (btn) { btn.classList.add("active"); }
      }
    }
    // 用属性比较而不是拼接 CSS 选择器，避免 hash 里的引号等字符让 querySelector 抛错
    function findTabButton(panelId) {
      const buttons = document.querySelectorAll(".tab-btn");
      for (let i = 0; i < buttons.length; i++) {
        if (buttons[i].getAttribute("data-panel") === panelId) { return buttons[i]; }
      }
      return null;
    }
    // 折叠区块（<details>）：展开指定区块，供锚点/深链接使用
    function openSection(sectionId) {
      const section = document.getElementById(sectionId);
      if (section && section.tagName === "DETAILS") { section.open = true; }
    }
    function openSectionFromHash() {
      const hash = window.location.hash;
      if (hash === "#platform-help" || hash === "#logs") { openSection(hash.slice(1)); }
    }
    // 支持 index.html#config-cu126 这样的深链接直接展开对应平台
    function openConfigFromHash() {
      const hash = window.location.hash;
      if (hash.indexOf("#config-") !== 0) { return; }
      const panelId = hash.slice(1);
      // 配置面板所在的折叠区块要先展开，否则展开的面板不可见
      openSection("platform-help");
      showConfig(panelId, findTabButton(panelId));
      // 面板展开前是 display:none，浏览器无法定位 fragment，这里手动滚动过去
      const panel = document.getElementById(panelId);
      if (panel && panel.classList.contains("active") && panel.scrollIntoView) {
        panel.scrollIntoView({ block: "start" });
      }
    }
    document.addEventListener("DOMContentLoaded", function() {
      openSectionFromHash();
      openConfigFromHash();
    });
    // 站内锚点跳转到折叠区块时（<a href="#platform-help">）自动展开
    window.addEventListener("hashchange", openSectionFromHash);"""

# 同步根目录下的人类可读索引页（index.html）
INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SEU 镜像站 · PyTorch 索引</title>
  <script>document.documentElement.classList.add("has-js");</script>
  <style>
__CSS__
  </style>
</head>
<body>
  <h1>SEU 镜像站 · PyTorch 索引</h1>
  <p>符合 <a href="https://peps.python.org/pep-0503/">PEP 503</a> 标准、面向 <a href="https://pytorch.org/">PyTorch</a> 的索引，数据由 <a href="https://download.pytorch.org/whl/">https://download.pytorch.org/whl/</a> 同步而来。本页汇总各计算平台的索引地址、对应配置方式，以及同步脚本的调试日志。</p>

  <h2>1. 计算平台与索引地址</h2>
  <p>下表链接可直接作为 <code>pip --index-url</code>、<code>uv</code> 的 index url 使用，点击「复制」即可复制完整地址。不确定该选哪个平台，请先看下面的 <a href="#platform-help">配置帮助</a>。</p>
  <table>
    <thead>
      <tr><th>计算平台</th><th>PEP 503 Simple Repo</th><th>复制</th></tr>
    </thead>
    <tbody>
__PLATFORM_TABLE_ROWS__
    </tbody>
  </table>

  <details class="section" id="platform-help">
    <summary><h2>2. 配置帮助</h2></summary>

    <h3>2.1 如何确定自己的计算平台</h3>
  <p>选择合适索引的关键是看你的显卡和加速 SDK 的版本号。流程如下：</p>

  <h4>① 查看显卡类型与 SDK 版本</h4>
  <ul>
    <li><strong>NVIDIA 显卡</strong>：在终端执行 <code>nvidia-smi</code>，查看输出右上角的 <code>CUDA Version: X.Y</code>（即当前 NVIDIA 驱动所支持的 CUDA Runtime 最大版本）。示例如下：</li>
  </ul>
  <pre><code>+-----------------------------------------------------------------------------+
| NVIDIA-SMI 535.171.04   Driver Version: 535.171.04   CUDA Version: 12.6   |
+-------------------------------+----------------------+----------------------+
|   ...                         | ...                  | ...                  |
+-------------------------------+----------------------+----------------------+</code></pre>
  <ul>
    <li><strong>AMD 显卡</strong>：执行 <code>rocminfo</code> 查看所安装的 ROCm 版本。</li>
    <li><strong>无 GPU，或不使用 GPU 加速</strong>：选择 <code>cpu</code> 即可。</li>
  </ul>

  <h4>② 根据版本选择索引</h4>
  <table>
    <thead>
      <tr><th>硬件 / 加速 SDK</th><th>对应的索引名</th></tr>
    </thead>
    <tbody>
      <tr><td>无 GPU / 不使用加速</td><td><code>cpu</code></td></tr>
      <tr><td>NVIDIA 显卡 + CUDA Runtime X.Y</td><td><code>cu</code> 后接去掉小数点的 X.Y<br>（CUDA 12.6 → <code>cu126</code>；CUDA 13.0 → <code>cu130</code>；CUDA 13.2 → <code>cu132</code>）</td></tr>
      <tr><td>AMD 显卡 + ROCm X.Y</td><td><code>rocm</code> 后接 X.Y<br>（ROCm 7.2 → <code>rocm7.2</code>）</td></tr>
    </tbody>
  </table>
  <blockquote>提示：PyTorch 的 <code>cuXXX</code> 包内已自带 CUDA Runtime 动态库，通常无需单独安装 CUDA Toolkit；但需保证 NVIDIA 显卡驱动版本支持对应的 CUDA Runtime 版本（参考 <code>nvidia-smi</code> 输出的 <code>Driver Version</code> 与 <code>CUDA Version</code>，或 <a href="https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html#cuda-major-component-versions">NVIDIA CUDA Toolkit Release Notes</a>）。</blockquote>

    <h3>2.2 查看对应平台的配置</h3>
    <p class="hint">点击下方平台按钮展开该平台的 <code>pip</code> / <code>uv</code> / <code>conda</code> / <code>mamba</code> 配置，再次点击同一按钮可收起。</p>
    <div class="tab-bar">
__PLATFORM_BUTTONS__
    </div>
__PLATFORM_PANELS__
  </details>

  <details class="section" id="logs">
    <summary><h2>3. 调试日志</h2></summary>
    <ul class="logs">
      <li><a href="script.log">script.log</a></li>
      <li><a href="aria2.log">aria2.log</a></li>
      <li><a href="packagelist.txt">packagelist.txt</a></li>
      <li><a href="summary.txt">summary.txt</a></li>
      <li><a href="existed_files.bin">existed_files.bin</a></li>
    </ul>
  </details>

  <div class="footer">
    镜像同步脚本：
    <a href="https://gitlab.seu.edu.cn/mirrors/sync-pytorch">校内 GitLab</a>
    ·
    <a href="https://github.com/seu-mirrors/sync-pytorch">GitHub</a>
  </div>
  <script>
__JS__
  </script>
</body>
</html>"""

# 表格行：计算平台 / PEP 503 索引地址 / 复制按钮
PLATFORM_TABLE_ROW_TEMPLATE = """      <tr>
        <td><code>__PLATFORM__</code></td>
        <td><code id="url-__PLATFORM_ID__">__SIMPLE_REPO_URL__</code></td>
        <td><button type="button" class="copy-btn" onclick="copyCmd('url-__PLATFORM_ID__', this)">复制</button></td>
      </tr>"""

# 配置帮助里的平台切换按钮；data-panel 供 #config-<platform> 深链接定位
PLATFORM_TAB_BUTTON_TEMPLATE = """    <button type="button" class="tab-btn" data-panel="config-__PLATFORM_ID__" onclick="showConfig('config-__PLATFORM_ID__', this)">__PLATFORM__</button>"""

# 单个平台的配置面板（pip / uv / conda / mamba），内容与旧版平台帮助页一致
PLATFORM_CONFIG_TEMPLATE = """  <div class="config-panel" id="config-__PLATFORM_ID__">
    <h4>计算平台 <code>__PLATFORM__</code> 的配置</h4>
    <p class="hint">索引地址：<code>__SIMPLE_REPO_URL__</code></p>

    <h5>① pip</h5>
    <pre><code id="cmd-__PLATFORM_ID__-pip">pip install torch torchvision --index-url __SIMPLE_REPO_URL__</code></pre>
    <button type="button" class="copy-btn" onclick="copyCmd('cmd-__PLATFORM_ID__-pip', this)">复制命令</button>

    <h5>② uv</h5>
    <p>推荐：把下面的内容追加到项目 <code>pyproject.toml</code>（这样 <code>torch</code> 会写入项目依赖配置，删除 <code>.venv</code> 后 <code>uv sync</code> 会自动重新下载安装）：</p>
    <pre><code id="cmd-__PLATFORM_ID__-uv-toml">__UV_TOML_SNIPPET__</code></pre>
    <button type="button" class="copy-btn" onclick="copyCmd('cmd-__PLATFORM_ID__-uv-toml', this)">复制配置</button>
    <p>之后执行以下命令</p>
    <pre><code id="cmd-__PLATFORM_ID__-uv-add">uv add torch torchvision</code></pre>
    <button type="button" class="copy-btn" onclick="copyCmd('cmd-__PLATFORM_ID__-uv-add', this)">复制命令</button>
    <p>即可从本镜像安装 PyTorch。更多 uv 与 PyTorch 集成方式见官方《<a href="https://docs.astral.sh/uv/guides/integration/pytorch/">Using uv with PyTorch</a>》（按 <code>sys_platform</code> 选择不同 backend、用 optional-dependencies 切换等）。把指南中的 <code>https://download.pytorch.org/whl/__PLATFORM__</code> 替换为 <code>__SIMPLE_REPO_URL__</code> 即指向本镜像。</p>
    <p>备选（<strong>不会写入项目配置文件</strong>，删除 <code>.venv</code> 后不会自动重新下载，仅适合临时一次性安装）：将 <code>pip</code> 命令替换为 <code>uv pip</code> 直接安装：</p>
    <pre><code id="cmd-__PLATFORM_ID__-uv-pip">uv pip install torch torchvision --index-url __SIMPLE_REPO_URL__</code></pre>
    <button type="button" class="copy-btn" onclick="copyCmd('cmd-__PLATFORM_ID__-uv-pip', this)">复制命令</button>

    <h5>③ conda</h5>
    <p>conda 本身不消费 PyPI 风格索引，但可在 conda 环境中通过 pip 使用本镜像安装 PyTorch，请将 <code>base</code> 替换为需要安装 <code>PyTorch</code> 的环境：</p>
    <pre><code id="cmd-__PLATFORM_ID__-conda">conda run -n base pip install torch torchvision --index-url __SIMPLE_REPO_URL__</code></pre>
    <button type="button" class="copy-btn" onclick="copyCmd('cmd-__PLATFORM_ID__-conda', this)">复制命令</button>

    <h5>④ mamba</h5>
    <p><a href="https://mamba.readthedocs.io/">mamba</a> 是 conda 的高性能替代品。在 mamba 环境中通过 pip 使用本镜像安装 PyTorch，请将 <code>base</code> 替换为需要安装 <code>PyTorch</code> 的环境：</p>
    <pre><code id="cmd-__PLATFORM_ID__-mamba">mamba run -n base pip install torch torchvision --index-url __SIMPLE_REPO_URL__</code></pre>
    <button type="button" class="copy-btn" onclick="copyCmd('cmd-__PLATFORM_ID__-mamba', this)">复制命令</button>
  </div>"""

# 旧总览页 whl/index.html 覆写为跳转页，保证 /pytorch/whl/ 这类旧链接继续可用。
# 跳转目标用绝对地址：旧地址不带结尾斜杠（/pytorch/whl）时相对路径会解析到站点根。
# 占位符：__INDEX_URL__  新索引页的绝对地址
LEGACY_REDIRECT_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="0; url=__INDEX_URL__">
  <link rel="canonical" href="__INDEX_URL__">
  <title>SEU 镜像站 · PyTorch 索引已迁移</title>
</head>
<body>
  <p>索引页已迁移至 <a href="__INDEX_URL__">__INDEX_URL__</a>，正在跳转……</p>
</body>
</html>"""
