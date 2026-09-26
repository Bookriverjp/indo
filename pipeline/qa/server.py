"""確認画面（自分のパソコンだけで開く小さな Web ページ）。

  python -m pipeline.qa serve EP0001_nishi_daak   → http://127.0.0.1:8765/

127.0.0.1 だけで待ち受け、エピソードフォルダの中のファイルだけを返す。
"""
from __future__ import annotations

import html
import json
import mimetypes
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pipeline.qa.gates import STATE_LABEL, decide, evaluate
from pipeline.workspace import episode_paths

_CSS = """
:root{--ground:#F2EBDB;--surface:#FBF7EE;--ink:#2B2118;--muted:#6E6152;--rule:#D9CCB2;--ok:#2F6B4F;--ng:#C4442A;
--warn:#A87C24;--wait:#8A8074;--accent:#27438F}
@media (prefers-color-scheme: dark){:root{--ground:#16130F;--surface:#201B15;--ink:#EDE3CF;--muted:#AA9C86;--rule:#3A3228;
--ok:#6FB08E;--ng:#E6795F;--warn:#D6A94B;--wait:#8F867A;--accent:#8FA6E6;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--ground);color:var(--ink);
font-family:"Zen Kaku Gothic New","Hiragino Sans","Yu Gothic",system-ui,sans-serif;line-height:1.7}
.wrap{max-width:1000px;margin:0 auto;padding:32px 16px 64px;display:flex;flex-direction:column;gap:18px}
h1{margin:0;font-size:26px}.sub{color:var(--muted);margin:0}
.gate{background:var(--surface);border:1px solid var(--rule);border-radius:6px;padding:16px 18px;display:flex;flex-direction:column;gap:10px}
.head{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.head h2{margin:0;font-size:19px}
.pill{font-size:12px;font-weight:700;color:#fff;border-radius:999px;padding:2px 10px}
.approved{background:var(--ok)}.rejected,.blocked{background:var(--ng)}.pending{background:var(--accent)}.stale{background:var(--warn)}.waiting{background:var(--wait)}
ul{margin:0;padding-left:1.2em}.err li{color:var(--ng)}.warn li{color:var(--warn)}
pre{white-space:pre-wrap;background:var(--ground);border:1px solid var(--rule);border-radius:4px;padding:10px;max-height:320px;overflow:auto;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}
.grid figure{margin:0;font-size:12px;color:var(--muted)}.grid img{width:100%;border:1px solid var(--rule);background:#888}
video,img.big{max-width:100%;border:1px solid var(--rule)}audio{width:100%}
.aud{display:grid;grid-template-columns:1fr;gap:4px;font-size:13px}
.act{display:flex;gap:8px;flex-wrap:wrap;align-items:flex-start}
textarea{flex:1 1 260px;min-height:40px;font:inherit;padding:6px;border:1px solid var(--rule);border-radius:4px;background:var(--ground);color:var(--ink)}
button{font:inherit;font-weight:700;border-radius:999px;border:1px solid var(--rule);padding:6px 16px;cursor:pointer;background:var(--surface);color:var(--ink)}
button.ok{background:var(--ok);color:#fff;border-color:var(--ok)}button.ng{background:var(--ng);color:#fff;border-color:var(--ng)}
button:disabled{opacity:.4;cursor:not-allowed}button:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.msg{color:var(--ng);font-size:13px}.dec{font-size:13px;color:var(--muted)}
"""

_JS = """
async function decide(gate, decision){
  const note = document.getElementById('note-'+gate).value;
  const res = await fetch('/decide',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({gate,decision,note})});
  const data = await res.json();
  if(!data.ok){ document.getElementById('msg-'+gate).textContent = data.error; return; }
  location.reload();
}
"""


def _file_url(rel: str) -> str:
    return "/file/" + urllib.parse.quote(rel)


def render_page(root: Path, episode_id: str) -> str:
    paths = episode_paths(root, episode_id)
    ep = paths["research"].parents[1]
    parts = [f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>確認画面 {html.escape(episode_id)}</title><style>{_CSS}</style></head><body><div class='wrap'>",
             f"<h1>確認画面：{html.escape(episode_id)}</h1>",
             "<p class='sub'>上から順に確認して承認します。承認のあとで中身が変わると「再確認」に戻ります。</p>"]
    for g in evaluate(root, episode_id):
        gate = g["gate"]
        parts.append(f"<section class='gate' id='{gate}'><div class='head'><h2>{html.escape(g['label'])}</h2>"
                     f"<span class='pill {g['state']}'>{STATE_LABEL[g['state']]}</span></div>")
        d = g["decision"]
        if d:
            note = f"　メモ: {html.escape(d['note'])}" if d["note"] else ""
            parts.append(f"<div class='dec'>最後の判断: {'承認' if d['decision'] == 'approved' else '差し戻し'}"
                         f"（{html.escape(d['by'])}, {html.escape(d['at'])}）{note}</div>")
        if g["errors"]:
            parts.append("<ul class='err'>" + "".join(f"<li>{html.escape(e)}</li>" for e in g["errors"]) + "</ul>")
        if g["warnings"]:
            parts.append("<ul class='warn'>" + "".join(f"<li>{html.escape(w)}</li>" for w in g["warnings"]) + "</ul>")
        images = [f for f in g["files"] if f["type"] == "image"]
        audios = [f for f in g["files"] if f["type"] == "audio"]
        for f in g["files"]:
            if f["type"] == "text":
                try:
                    text = (ep / f["path"]).read_text(encoding="utf-8")
                except (FileNotFoundError, UnicodeDecodeError):
                    continue
                parts.append(f"<details open><summary>{html.escape(f['path'])}</summary><pre>{html.escape(text)}</pre></details>")
            elif f["type"] == "video":
                parts.append(f"<video controls preload='metadata' src='{_file_url(f['path'])}'></video>")
        if images:
            parts.append("<div class='grid'>" + "".join(
                f"<figure><img loading='lazy' src='{_file_url(f['path'])}' alt=''><figcaption>{html.escape(f.get('label', f['path']))}</figcaption></figure>"
                for f in images) + "</div>")
        if audios:
            parts.append("<div class='aud'>" + "".join(
                f"<div>{html.escape(f.get('label', ''))}<audio controls preload='none' src='{_file_url(f['path'])}'></audio></div>"
                for f in audios) + "</div>")
        can_decide = g["state"] not in ("waiting",)
        can_approve = g["state"] not in ("waiting", "blocked")
        parts.append(f"<div class='act'><textarea id='note-{gate}' aria-label='メモ（差し戻しのときは理由）' "
                     f"placeholder='メモ（差し戻しのときは理由を書く）'></textarea>"
                     f"<button class='ok' onclick=\"decide('{gate}','approved')\" {'' if can_approve else 'disabled'}>承認</button>"
                     f"<button class='ng' onclick=\"decide('{gate}','rejected')\" {'' if can_decide else 'disabled'}>差し戻し</button></div>"
                     f"<div class='msg' id='msg-{gate}' role='status'></div></section>")
    parts.append(f"<script>{_JS}</script></div></body></html>")
    return "".join(parts)


def make_server(root: Path, episode_id: str, port: int = 8765, by: str = "owner") -> ThreadingHTTPServer:
    ep_dir = episode_paths(root, episode_id)["research"].parents[1].resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # 画面を静かに保つ
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            path = urllib.parse.urlparse(self.path).path
            if path == "/":
                self._send(200, render_page(root, episode_id).encode("utf-8"), "text/html; charset=utf-8")
                return
            if path.startswith("/file/"):
                rel = urllib.parse.unquote(path[len("/file/"):])
                target = (ep_dir / rel).resolve()
                if rel.startswith("/") or not target.is_relative_to(ep_dir):
                    self._send(403, b"forbidden", "text/plain")
                    return
                if not target.is_file():
                    self._send(404, b"not found", "text/plain")
                    return
                ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                if ctype.startswith("text/") or target.suffix in (".md", ".srt", ".json", ".yaml"):
                    ctype = "text/plain; charset=utf-8"
                self._send(200, target.read_bytes(), ctype)
                return
            self._send(404, b"not found", "text/plain")

        def do_POST(self):  # noqa: N802
            if urllib.parse.urlparse(self.path).path != "/decide":
                self._send(404, b"not found", "text/plain")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(min(length, 1 << 16)) or b"{}")
                decide(root, episode_id, str(body.get("gate", "")), str(body.get("decision", "")),
                       str(body.get("note", "")), by=by)
            except (ValueError, json.JSONDecodeError) as e:
                self._send(400, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
                return
            self._send(200, json.dumps({"ok": True}).encode(), "application/json")

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
