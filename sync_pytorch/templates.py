"""人类可读索引页（whl/ 下）使用的 HTML/CSS/JS 模板。"""
from .config import MIRROR_WHL_URL

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
    a { color: #0969da; text-decoration: none; }
    a:hover { text-decoration: underline; }
    ul.platforms { list-style: none; display: flex; flex-wrap: wrap; gap: 0.4rem 0.6rem; padding: 0; margin: 0.5rem 0; }
    ul.platforms li { margin: 0; }
    ul.platforms li a {
      display: inline-block; padding: 0.25rem 0.7rem; border: 1px solid #d0d7de;
      border-radius: 999px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    }
    blockquote { margin: 0.8rem 0; padding: 0.4rem 1rem; border-left: 4px solid #d0d7de; color: #57606a; }
    .copy-btn {
      font: inherit; padding: 0.25rem 0.8rem; border: 1px solid #d0d7de;
      border-radius: 6px; background: #fff; cursor: pointer; color: #24292f;
    }
    .copy-btn:hover { background: #f6f8fa; }
    .copy-btn.copied { color: #1a7f37; border-color: #1a7f37; }
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
    }"""

# 人类可读的总览索引页（whl/index.html）
TOP_INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SEU 镜像站 · PyTorch 索引</title>
  <style>
__CSS__
  </style>
</head>
<body>
  <h1>SEU 镜像站 · PyTorch 索引</h1>
  <p>符合 <a href="https://peps.python.org/pep-0503/">PEP 503</a> 标准、面向 <a href="https://pytorch.org/">PyTorch</a> 的索引。数据由 <a href="https://download.pytorch.org/whl/">https://download.pytorch.org/whl/</a> 同步而来。</p>

  <h2>选择计算平台</h2>
  <ul class="platforms">
__PLATFORM_LIST__
  </ul>

  <h2>我怎么选择 PyTorch 版本？</h2>
  <p>选择合适索引的关键是看你的显卡和加速 SDK 的版本号。流程如下：</p>

  <h3>1. 查看显卡类型与 SDK 版本</h3>
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

  <h3>2. 根据版本选择索引</h3>
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
  <p>从上方列表点进对应索引页，内有 <code>pip</code> / <code>uv</code> / <code>conda</code> / <code>mamba</code> 的安装命令以及“复制命令”按钮。</p>
  <blockquote>提示：PyTorch 的 <code>cuXXX</code> 包内已自带 CUDA Runtime 动态库，通常无需单独安装 CUDA Toolkit；但需保证 NVIDIA 显卡驱动版本支持对应的 CUDA Runtime 版本（参考 <code>nvidia-smi</code> 输出的 <code>Driver Version</code> 与 <code>CUDA Version</code>，或 <a href="https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html#cuda-major-component-versions">NVIDIA CUDA Toolkit Release Notes</a>）。</blockquote>

  <div class="footer">
    镜像同步脚本：
    <a href="https://gitlab.seu.edu.cn/mirrors/sync-pytorch">校内 GitLab</a>
    ·
    <a href="https://github.com/seu-mirrors/sync-pytorch">GitHub</a>
  </div>
</body>
</html>"""

# 人类可读的按平台索引页（whl/<platform>/index.html）
PLATFORM_INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SEU 镜像站 · PyTorch __PLATFORM__ 索引</title>
  <style>
__CSS__
  </style>
</head>
<body>
  <h1>SEU 镜像站 · PyTorch <code>__PLATFORM__</code> 索引</h1>
  <p>面向计算平台 <code>__PLATFORM__</code> 的 <a href="https://peps.python.org/pep-0503/">PEP 503</a> 索引。数据同步自 <a href="https://download.pytorch.org/whl/__PLATFORM__/">https://download.pytorch.org/whl/__PLATFORM__/</a>；进入 <a href="simple/">simple/</a> 即可作为 <code>--index-url</code> 直接使用的简单仓库索引。</p>

  <h2>配置镜像站</h2>

  <h3>① pip</h3>
  <pre><code id="cmd-pip">pip install torch torchvision --index-url """ + MIRROR_WHL_URL + """/__PLATFORM__/simple</code></pre>
  <button type="button" class="copy-btn" onclick="copyCmd('cmd-pip', this)">复制命令</button>

  <h3>② uv</h3>
  <p>推荐：把下面的内容追加到项目 <code>pyproject.toml</code>（这样 <code>torch</code> 会写入项目依赖配置，删除 <code>.venv</code> 后 <code>uv sync</code> 会自动重新下载安装）：</p>
  <pre><code id="cmd-uv-toml">__UV_TOML_SNIPPET__</code></pre>
  <button type="button" class="copy-btn" onclick="copyCmd('cmd-uv-toml', this)">复制配置</button>
  <p>之后执行以下命令</p>
  <pre><code id="cmd-uv-add">uv add torch torchvision</code></pre>
  <button type="button" class="copy-btn" onclick="copyCmd('cmd-uv-add', this)">复制命令</button>
  <p>即可从本镜像安装 PyTorch。更多 uv 与 PyTorch 集成方式见官方《<a href="https://docs.astral.sh/uv/guides/integration/pytorch/">Using uv with PyTorch</a>》（按 <code>sys_platform</code> 选择不同 backend、用 optional-dependencies 切换等）。把指南中的 <code>https://download.pytorch.org/whl/__PLATFORM__</code> 替换为 <code>""" + MIRROR_WHL_URL + """/__PLATFORM__/simple</code> 即指向本镜像。</p>
  <p>备选（<strong>不会写入项目配置文件</strong>，删除 <code>.venv</code> 后不会自动重新下载，仅适合临时一次性安装）：将 <code>pip</code> 命令替换为 <code>uv pip</code> 直接安装：</p>
  <pre><code id="cmd-uv-pip">uv pip install torch torchvision --index-url """ + MIRROR_WHL_URL + """/__PLATFORM__/simple</code></pre>
  <button type="button" class="copy-btn" onclick="copyCmd('cmd-uv-pip', this)">复制命令</button>

  <h3>③ conda</h3>
  <p>conda 本身不消费 PyPI 风格索引，但可在 conda 环境中通过 pip 使用本镜像安装 PyTorch，请将 <code>base</code> 替换为需要安装 <code>PyTorch</code> 的环境：</p>
  <pre><code id="cmd-conda">conda run -n base pip install torch torchvision --index-url """ + MIRROR_WHL_URL + """/__PLATFORM__/simple</code></pre>
  <button type="button" class="copy-btn" onclick="copyCmd('cmd-conda', this)">复制命令</button>

  <h3>④ mamba</h3>
  <p><a href="https://mamba.readthedocs.io/">mamba</a> 是 conda 的高性能替代品。在 mamba 环境中通过 pip 使用本镜像安装 PyTorch，请将 <code>base</code> 替换为需要安装 <code>PyTorch</code> 的环境：</p>
  <pre><code id="cmd-mamba">mamba run -n base pip install torch torchvision --index-url """ + MIRROR_WHL_URL + """/__PLATFORM__/simple</code></pre>
  <button type="button" class="copy-btn" onclick="copyCmd('cmd-mamba', this)">复制命令</button>

  <p>查看其它计算平台的索引请回到 <a href="..">索引总览</a>。</p>

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
