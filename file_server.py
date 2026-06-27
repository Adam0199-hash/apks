#!/usr/bin/env python3
"""
Public file server — browse, download, and upload files via HTTP.
Run inside your Docker container and expose the port.

Install: pip install flask
Run:     python file_server.py
"""

import os
import re
import threading
import urllib.request
from flask import Flask, request, send_from_directory, jsonify, abort
from werkzeug.utils import secure_filename

# Track active URL downloads: filename -> {"status", "error"}
download_jobs = {}

# ─── CONFIG ───────────────────────────────────────────────────────────────────
FILES_DIR = "./public_files"   # Directory to serve files from
PORT = 5000                    # Port to listen on
MAX_FILE_SIZE_MB = 100         # Max upload size in MB
ALLOWED_EXTENSIONS = None      # Set of extensions e.g. {"jpg","png","pdf"} or None for all
# ──────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE_MB * 1024 * 1024

os.makedirs(FILES_DIR, exist_ok=True)


def allowed(filename):
    if ALLOWED_EXTENSIONS is None:
        return True
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in ALLOWED_EXTENSIONS


# ── HTML UI ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    files = os.listdir(FILES_DIR)
    file_rows = ""
    for f in sorted(files):
        size = os.path.getsize(os.path.join(FILES_DIR, f))
        size_str = f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B"
        file_rows += f"""
        <tr>
          <td><a href="/files/{f}" download>{f}</a></td>
          <td>{size_str}</td>
          <td><a href="/files/{f}" download>⬇ Download</a></td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head>
  <title>File Server</title>
  <style>
    body {{ font-family: sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; }}
    h1 {{ color: #333; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
    th, td {{ padding: 10px; border: 1px solid #ddd; text-align: left; }}
    th {{ background: #f5f5f5; }}
    a {{ color: #0070f3; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .upload {{ margin-top: 30px; padding: 20px; border: 2px dashed #ccc; border-radius: 8px; }}
    input[type=file] {{ margin: 10px 0; }}
    button {{ background: #0070f3; color: white; border: none; padding: 8px 20px;
              border-radius: 5px; cursor: pointer; font-size: 14px; }}
    button:hover {{ background: #0051a8; }}
    .empty {{ color: #999; font-style: italic; }}
  </style>
</head>
<body>
  <h1>📁 File Server</h1>

  <table>
    <thead><tr><th>Filename</th><th>Size</th><th>Action</th></tr></thead>
    <tbody>
      {''.join([file_rows]) if files else '<tr><td colspan="3" class="empty">No files yet.</td></tr>'}
    </tbody>
  </table>

  <div class="upload">
    <h3>⬆ Upload a File</h3>
    <form action="/upload" method="post" enctype="multipart/form-data">
      <input type="file" name="file" required><br>
      <button type="submit">Upload</button>
    </form>
  </div>

  <div class="upload" style="margin-top:20px;">
    <h3>🔗 Download from URL</h3>
    <form action="/fetch-url" method="post">
      <input type="url" name="url" placeholder="https://example.com/file.zip"
             required style="width:70%; padding:8px; border:1px solid #ccc; border-radius:5px;">
      <button type="submit" style="margin-left:8px;">Fetch</button>
    </form>
  </div>

  <hr style="margin-top:30px">
  <small>API: <code>GET /api/files</code> · <code>GET /files/&lt;name&gt;</code> · <code>POST /upload</code> · <code>POST /fetch-url</code></small>
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
        abort(400, f"File type not allowed.")

    filename = secure_filename(file.filename)
    save_path = os.path.join(FILES_DIR, filename)
    file.save(save_path)

    # Redirect back to UI if browser request, else return JSON
    if request.accept_mimetypes.accept_html:
        from flask import redirect
        return redirect("/")
    return jsonify({"status": "ok", "filename": filename}), 201


# ── FETCH FROM URL ────────────────────────────────────────────────────────────
def _do_download(url: str, save_path: str, filename: str):
    """Download a URL to disk in a background thread."""
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

    # Derive filename from URL
    filename = secure_filename(url.split("?")[0].rstrip("/").split("/")[-1]) or "download"
    save_path = os.path.join(FILES_DIR, filename)

    download_jobs[filename] = {"status": "downloading"}
    thread = threading.Thread(target=_do_download, args=(url, save_path, filename), daemon=True)
    thread.start()

    if request.accept_mimetypes.accept_html:
        from flask import redirect
        return f"""<!DOCTYPE html><html><head><title>Downloading…</title>
        <meta http-equiv="refresh" content="3;url=/">
        </head><body style="font-family:sans-serif;max-width:600px;margin:60px auto;text-align:center">
        <h2>⏳ Downloading <code>{filename}</code>…</h2>
        <p>You'll be redirected back in a few seconds.<br>
        Refresh the main page to see the file once it's done.</p>
        <a href="/">← Back</a>
        </body></html>"""
    return jsonify({"status": "downloading", "filename": filename}), 202


@app.route("/fetch-status/<filename>")
def fetch_status(filename):
    job = download_jobs.get(filename)
    if not job:
        return jsonify({"status": "unknown"}), 404
    return jsonify(job)


# ── API: list files ───────────────────────────────────────────────────────────
@app.route("/api/files")
def api_list():
    files = []
    for f in os.listdir(FILES_DIR):
        path = os.path.join(FILES_DIR, f)
        files.append({
            "name": f,
            "size_bytes": os.path.getsize(path),
            "url": f"/files/{f}"
        })
    return jsonify(files)


if __name__ == "__main__":
    print(f"Serving files from: {os.path.abspath(FILES_DIR)}")
    print(f"Open: http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
