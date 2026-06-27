#!/usr/bin/env python3
"""
Public file server — browse, download, upload, delete files via HTTP.
API routes are protected by PW header.

Install: pip install flask
Run:     python file_server.py
"""

import os
import threading
import urllib.request
from flask import Flask, request, send_from_directory, jsonify, abort, redirect
from werkzeug.utils import secure_filename
from functools import wraps

# ─── CONFIG ───────────────────────────────────────────────────────────────────
FILES_DIR       = "./public_files"   # Directory to serve files from
PORT            = 5000               # Port to listen on
MAX_FILE_SIZE_MB = 100               # Max upload size in MB
ALLOWED_EXTENSIONS = None            # e.g. {"jpg","png","pdf"} or None for all
API_PASSWORD    = "2000AM"           # Required in PW header for all API calls
# ──────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE_MB * 1024 * 1024
os.makedirs(FILES_DIR, exist_ok=True)

download_jobs = {}  # filename -> {"status", "error"}


# ── AUTH ──────────────────────────────────────────────────────────────────────
def require_pw(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        pw = request.headers.get("PW") or request.args.get("pw")
        if pw != API_PASSWORD:
            return jsonify({"error": "Unauthorized — invalid or missing PW header"}), 401
        return f(*args, **kwargs)
    return decorated


def allowed(filename):
    if ALLOWED_EXTENSIONS is None:
        return True
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in ALLOWED_EXTENSIONS


def fmt_size(size):
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    elif size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


# ── HTML UI ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    files = sorted(os.listdir(FILES_DIR))
    file_rows = ""
    for f in files:
        path = os.path.join(FILES_DIR, f)
        size_str = fmt_size(os.path.getsize(path))
        file_rows += f"""
        <tr>
          <td class="fname">
            <span class="icon">📄</span>
            <a href="/files/{f}" download>{f}</a>
          </td>
          <td class="fsize">{size_str}</td>
          <td class="actions">
            <a class="btn btn-dl" href="/files/{f}" download>⬇ Download</a>
            <button class="btn btn-del" onclick="deleteFile('{f}')">🗑 Delete</button>
          </td>
        </tr>"""

    empty_row = '<tr><td colspan="3" class="empty">No files yet. Upload one below!</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>📁 File Server</title>
  <style>
    :root {{
      --bg: #f4f6fb;
      --surface: #ffffff;
      --border: #e2e8f0;
      --text: #1a202c;
      --muted: #718096;
      --accent: #4f46e5;
      --accent-hover: #3730a3;
      --danger: #e53e3e;
      --danger-hover: #c53030;
      --success: #38a169;
      --shadow: 0 2px 12px rgba(0,0,0,0.08);
      --radius: 12px;
    }}
    [data-theme="dark"] {{
      --bg: #0f1117;
      --surface: #1a1d27;
      --border: #2d3148;
      --text: #e2e8f0;
      --muted: #a0aec0;
      --accent: #7c70f5;
      --accent-hover: #6558f0;
      --danger: #fc8181;
      --danger-hover: #f56565;
      --shadow: 0 2px 16px rgba(0,0,0,0.4);
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      transition: background 0.3s, color 0.3s;
    }}

    /* ── TOP BAR ── */
    header {{
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 16px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      box-shadow: var(--shadow);
      position: sticky;
      top: 0;
      z-index: 100;
    }}
    header h1 {{ font-size: 1.3rem; font-weight: 700; letter-spacing: -0.3px; }}
    .header-actions {{ display: flex; gap: 10px; align-items: center; }}

    .toggle-btn {{
      background: var(--bg);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 7px 14px;
      border-radius: 8px;
      cursor: pointer;
      font-size: 0.85rem;
      font-weight: 500;
      transition: all 0.2s;
    }}
    .toggle-btn:hover {{ border-color: var(--accent); color: var(--accent); }}

    /* ── LAYOUT ── */
    .container {{
      max-width: 960px;
      margin: 32px auto;
      padding: 0 20px;
    }}
    @media (max-width: 600px) {{
      .container {{ margin: 16px auto; padding: 0 12px; }}
      header {{ padding: 12px 16px; }}
      header h1 {{ font-size: 1.1rem; }}
    }}

    /* ── CARDS ── */
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      margin-bottom: 20px;
      overflow: hidden;
    }}
    .card-header {{
      padding: 16px 20px;
      border-bottom: 1px solid var(--border);
      font-weight: 600;
      font-size: 0.95rem;
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    /* ── TABLE ── */
    table {{ width: 100%; border-collapse: collapse; }}
    th {{
      padding: 11px 16px;
      text-align: left;
      font-size: 0.78rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--muted);
      background: var(--bg);
      border-bottom: 1px solid var(--border);
    }}
    td {{
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
      font-size: 0.9rem;
      vertical-align: middle;
    }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: var(--bg); }}

    .fname {{ display: flex; align-items: center; gap: 8px; }}
    .fname a {{ color: var(--accent); text-decoration: none; font-weight: 500; word-break: break-all; }}
    .fname a:hover {{ text-decoration: underline; }}
    .icon {{ font-size: 1.1rem; flex-shrink: 0; }}
    .fsize {{ color: var(--muted); font-size: 0.82rem; white-space: nowrap; }}
    .actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .empty {{ text-align: center; color: var(--muted); padding: 32px; font-style: italic; }}

    /* ── BUTTONS ── */
    .btn {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 6px 12px;
      border-radius: 7px;
      font-size: 0.8rem;
      font-weight: 500;
      cursor: pointer;
      border: none;
      text-decoration: none;
      transition: all 0.15s;
      white-space: nowrap;
    }}
    .btn-dl {{ background: var(--accent); color: #fff; }}
    .btn-dl:hover {{ background: var(--accent-hover); }}
    .btn-del {{ background: transparent; border: 1px solid var(--danger); color: var(--danger); }}
    .btn-del:hover {{ background: var(--danger); color: #fff; }}
    .btn-primary {{
      background: var(--accent); color: #fff;
      padding: 9px 20px; font-size: 0.9rem; border-radius: 8px;
      margin-top: 12px;
    }}
    .btn-primary:hover {{ background: var(--accent-hover); }}

    /* ── FORMS ── */
    .form-body {{ padding: 20px; display: flex; flex-direction: column; gap: 14px; }}
    .form-row {{ display: flex; flex-direction: column; gap: 5px; }}
    label {{ font-size: 0.85rem; font-weight: 500; color: var(--muted); }}
    input[type=text], input[type=url], input[type=file] {{
      width: 100%;
      padding: 9px 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--bg);
      color: var(--text);
      font-size: 0.9rem;
      transition: border-color 0.2s;
      outline: none;
    }}
    input:focus {{ border-color: var(--accent); box-shadow: 0 0 0 3px rgba(79,70,229,0.15); }}
    .hint {{ font-size: 0.78rem; color: var(--muted); }}

    /* ── TOAST ── */
    #toast {{
      position: fixed; bottom: 24px; right: 24px;
      background: #1a202c; color: #fff;
      padding: 12px 20px; border-radius: 10px;
      font-size: 0.88rem; box-shadow: 0 4px 20px rgba(0,0,0,0.3);
      opacity: 0; pointer-events: none;
      transition: opacity 0.3s;
      z-index: 999;
    }}
    #toast.show {{ opacity: 1; }}
    #toast.ok {{ background: var(--success); }}
    #toast.err {{ background: var(--danger); }}

    /* ── API DOCS ── */
    .api-docs {{ padding: 16px 20px; font-size: 0.82rem; color: var(--muted); line-height: 1.8; }}
    code {{
      background: var(--bg); border: 1px solid var(--border);
      padding: 1px 6px; border-radius: 4px;
      font-family: 'SF Mono', monospace; font-size: 0.8rem; color: var(--accent);
    }}

    /* ── RESPONSIVE TABLE ── */
    @media (max-width: 520px) {{
      th.fsize-th, td.fsize {{ display: none; }}
      .actions {{ flex-direction: column; }}
      .btn {{ font-size: 0.75rem; padding: 5px 10px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>📁 File Server</h1>
    <div class="header-actions">
      <button class="toggle-btn" onclick="toggleTheme()" id="themeBtn">🌙 Dark</button>
    </div>
  </header>

  <div class="container">

    <!-- File list -->
    <div class="card">
      <div class="card-header">🗂 Files</div>
      <table>
        <thead>
          <tr>
            <th>Filename</th>
            <th class="fsize-th">Size</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody id="fileTable">
          {file_rows if files else empty_row}
        </tbody>
      </table>
    </div>

    <!-- Upload -->
    <div class="card">
      <div class="card-header">⬆ Upload a File</div>
      <form class="form-body" action="/upload" method="post" enctype="multipart/form-data">
        <div class="form-row">
          <label>Choose file</label>
          <input type="file" name="file" required>
        </div>
        <div><button class="btn btn-primary" type="submit">Upload</button></div>
      </form>
    </div>

    <!-- Fetch from URL -->
    <div class="card">
      <div class="card-header">🔗 Fetch from URL</div>
      <form class="form-body" action="/fetch-url" method="post">
        <div class="form-row">
          <label>URL</label>
          <input type="url" name="url" placeholder="https://example.com/file.zip" required>
        </div>
        <div class="form-row">
          <label>Custom filename <span class="hint">(optional — leave blank to use name from URL)</span></label>
          <input type="text" name="filename" placeholder="my-file.zip">
        </div>
        <div><button class="btn btn-primary" type="submit">Fetch File</button></div>
      </form>
    </div>

    <!-- API Docs -->
    <div class="card">
      <div class="card-header">🔌 API Reference</div>
      <div class="api-docs">
        All API requests require header: <code>PW: 2000AM</code><br><br>
        <code>GET  /api/files</code> — list all files<br>
        <code>GET  /files/&lt;name&gt;</code> — download a file<br>
        <code>POST /upload</code> — upload a file (multipart)<br>
        <code>POST /fetch-url</code> — fetch file from URL (JSON body: url, filename?)<br>
        <code>GET  /fetch-status/&lt;name&gt;</code> — check URL fetch progress<br>
        <code>DELETE /api/delete/&lt;name&gt;</code> — delete a file
      </div>
    </div>

  </div>

  <div id="toast"></div>

  <script>
    // ── THEME ──
    const saved = localStorage.getItem('theme') || 'light';
    setTheme(saved);

    function setTheme(t) {{
      document.documentElement.setAttribute('data-theme', t);
      document.getElementById('themeBtn').textContent = t === 'dark' ? '☀️ Light' : '🌙 Dark';
      localStorage.setItem('theme', t);
    }}
    function toggleTheme() {{
      const cur = document.documentElement.getAttribute('data-theme');
      setTheme(cur === 'dark' ? 'light' : 'dark');
    }}

    // ── TOAST ──
    function toast(msg, type = 'ok') {{
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.className = 'show ' + type;
      setTimeout(() => t.className = '', 3000);
    }}

    // ── DELETE ──
    async function deleteFile(filename) {{
      if (!confirm(`Delete "${{filename}}"? This cannot be undone.`)) return;
      const res = await fetch(`/api/delete/${{encodeURIComponent(filename)}}`, {{
        method: 'DELETE',
        headers: {{ 'PW': '2000AM' }}
      }});
      const data = await res.json();
      if (res.ok) {{
        toast(`✅ "${{filename}}" deleted`);
        // Remove row from table
        const rows = document.querySelectorAll('#fileTable tr');
        rows.forEach(row => {{
          if (row.querySelector('a') && row.querySelector('a').textContent.trim() === filename) {{
            row.remove();
          }}
        }});
        if (document.querySelectorAll('#fileTable tr').length === 0) {{
          document.getElementById('fileTable').innerHTML =
            '<tr><td colspan="3" class="empty">No files yet. Upload one below!</td></tr>';
        }}
      }} else {{
        toast(`❌ ${{data.error || 'Delete failed'}}`, 'err');
      }}
    }}
  </script>
</body>
</html>"""


# ── DOWNLOAD ──────────────────────────────────────────────────────────────────
@app.route("/files/<filename>")
def download(filename):
    return send_from_directory(os.path.abspath(FILES_DIR), filename, as_attachment=True)


# ── UPLOAD ────────────────────────────────────────────────────────────────────
@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        abort(400, "No file part in request.")
    file = request.files["file"]
    if file.filename == "":
        abort(400, "No file selected.")
    if not allowed(file.filename):
        abort(400, "File type not allowed.")
    filename = secure_filename(file.filename)
    file.save(os.path.join(FILES_DIR, filename))
    if request.accept_mimetypes.accept_html:
        return redirect("/")
    return jsonify({"status": "ok", "filename": filename}), 201


# ── DELETE ────────────────────────────────────────────────────────────────────
@app.route("/api/delete/<filename>", methods=["DELETE"])
@require_pw
def delete_file(filename):
    filename = secure_filename(filename)
    path = os.path.join(FILES_DIR, filename)
    if not os.path.isfile(path):
        return jsonify({"error": "File not found"}), 404
    os.remove(path)
    return jsonify({"status": "deleted", "filename": filename})


# ── FETCH FROM URL ────────────────────────────────────────────────────────────
def _do_download(url: str, save_path: str, filename: str):
    try:
        urllib.request.urlretrieve(url, save_path)
        download_jobs[filename] = {"status": "done"}
    except Exception as e:
        download_jobs[filename] = {"status": "error", "error": str(e)}


@app.route("/fetch-url", methods=["POST"])
def fetch_url():
    url = request.form.get("url") or (request.json or {}).get("url", "")
    if not url:
        abort(400, "No URL provided.")

    custom_name = request.form.get("filename") or (request.json or {}).get("filename", "")
    if custom_name:
        filename = secure_filename(custom_name)
    else:
        filename = secure_filename(url.split("?")[0].rstrip("/").split("/")[-1]) or "download"

    save_path = os.path.join(FILES_DIR, filename)
    download_jobs[filename] = {"status": "downloading"}
    threading.Thread(target=_do_download, args=(url, save_path, filename), daemon=True).start()

    if request.accept_mimetypes.accept_html:
        return f"""<!DOCTYPE html><html><head><title>Fetching…</title>
        <meta http-equiv="refresh" content="3;url=/">
        <style>body{{font-family:sans-serif;max-width:500px;margin:80px auto;text-align:center;color:#1a202c}}</style>
        </head><body>
        <h2>⏳ Fetching <code>{filename}</code>…</h2>
        <p>Redirecting back in a moment. Refresh the page if the file doesn't appear.</p>
        <a href="/">← Back now</a>
        </body></html>"""
    return jsonify({"status": "downloading", "filename": filename}), 202


@app.route("/fetch-status/<filename>")
def fetch_status(filename):
    job = download_jobs.get(filename)
    if not job:
        return jsonify({"status": "unknown"}), 404
    return jsonify(job)


# ── API: LIST FILES ───────────────────────────────────────────────────────────
@app.route("/api/files")
@require_pw
def api_list():
    files = []
    for f in os.listdir(FILES_DIR):
        path = os.path.join(FILES_DIR, f)
        files.append({
            "name": f,
            "size_bytes": os.path.getsize(path),
            "size": fmt_size(os.path.getsize(path)),
            "url": f"/files/{f}"
        })
    return jsonify(files)


if __name__ == "__main__":
    print(f"📁 Serving files from: {os.path.abspath(FILES_DIR)}")
    print(f"🌐 Open: http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
