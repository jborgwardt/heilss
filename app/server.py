"""Heil Store Studio: tiny stdlib HTTP service. Auth is handled by Umbrel's app_proxy."""
import base64, io, json, os, re, sys, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import yaml
import convert, icon, github

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("HEILSS_DATA", "/data")
STORE_ID = os.environ.get("HEILSS_STORE_ID", "heilss")
STORE_REPO = os.environ.get("HEILSS_STORE_REPO", "jborgwardt/heilss-store")
ASSETS_REPO = os.environ.get("HEILSS_ASSETS_REPO", "jborgwardt/heilss-assets")
CFG = os.path.join(DATA, "settings.json")


def load_cfg():
    try:
        return json.load(open(CFG))
    except Exception:
        return {}


def token():
    return os.environ.get("HEILSS_GITHUB_TOKEN") or load_cfg().get("token") or ""


def store_state():
    """existing app ports/versions from public store repo."""
    out = {}
    try:
        tok = token() or None
        for p in github.list_tree(STORE_REPO, token=tok):
            m = re.match(r"^([^/]+)/umbrel-app\.yml$", p)
            if m:
                y = yaml.safe_load(github.get_file(STORE_REPO, p, token=tok) or "") or {}
                out[m[1]] = {"port": y.get("port"), "version": y.get("version")}
    except Exception as e:
        print("store scan failed:", e, file=sys.stderr)
    return out


def build(p, existing=None):
    name = (p.get("name") or "").strip()
    if not name:
        raise convert.ConvertError("app name is required")
    app_id = convert.app_id_for(STORE_ID, name)
    comp, warns = convert.parse_source(p.get("source", ""))
    wp = int(p["webPort"]) if str(p.get("webPort") or "").strip() else None
    ctext, svc, port, w2 = convert.to_umbrel_compose(app_id, comp, (p.get("webService") or None), wp, bool(p.get("pin")))
    warns += w2
    existing = existing if existing is not None else {}
    cur = existing.get(app_id)
    used = {v["port"] for k, v in existing.items() if k != app_id and v.get("port")}
    if cur and cur.get("port"):
        mport, ver = cur["port"], convert.bump(cur.get("version"))
    else:
        mport = 4100
        while mport in used or mport in (4180,):
            mport += 1
        ver = "1.0.0"
    ic = p.get("icon")
    if ic and ic.get("data"):
        try:
            svg = icon.normalize(base64.b64decode(ic["data"]))
        except ValueError as e:
            raise convert.ConvertError(str(e))
        icon_src = "uploaded"
    else:
        svg, icon_src = icon.generate(name), "generated"
    icon_url = f"https://raw.githubusercontent.com/{ASSETS_REPO}/main/{app_id}/icon.svg"
    repo_url = f"https://github.com/{STORE_REPO}"
    manifest = convert.build_manifest(app_id, name, p.get("description"), mport, icon_url,
                                      p.get("category") or "Utilities", ver, repo=repo_url)
    return {"appId": app_id, "port": mport, "version": ver, "webService": svc, "webPort": port, "icon": icon_src,
            "warnings": warns, "iconUrl": icon_url, "iconSvg": svg,
            "store": {f"{app_id}/umbrel-app.yml": manifest, f"{app_id}/docker-compose.yml": ctext},
            "assets": {f"{app_id}/icon.svg": svg}}


def zip_bytes(r):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in r["store"].items():
            z.writestr(k, v)
        z.writestr(f"{r['appId']}/icon.svg", r["assets"][f"{r['appId']}/icon.svg"])
    return b.getvalue()


def publish(r):
    tok = token()
    if not tok:
        raise github.GitHubError("No GitHub token configured. Set it in Settings (or env HEILSS_GITHUB_TOKEN).")
    github.commit_files(ASSETS_REPO, r["assets"], f"Add icon for {r['appId']}", tok)
    sha = github.commit_files(STORE_REPO, r["store"], f"Add/update {r['appId']} {r['version']}", tok)
    return sha


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self.send(200, open(os.path.join(HERE, "static/index.html"), "rb").read(), "text/html; charset=utf-8")
        if path == "/icon.svg":
            return self.send(200, open(os.path.join(HERE, "static/icon.svg"), "rb").read(), "image/svg+xml")
        if path == "/healthz":
            return self.send(200, {"ok": True})
        if path == "/api/settings":
            return self.send(200, {"tokenSet": bool(token()), "tokenFromEnv": bool(os.environ.get("HEILSS_GITHUB_TOKEN")),
                                   "storeRepo": STORE_REPO, "assetsRepo": ASSETS_REPO, "storeId": STORE_ID,
                                   "categories": convert.CATEGORIES})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 8_000_000:
                return self.send(413, {"error": "too large"})
            p = json.loads(self.rfile.read(n) or b"{}")
            path = self.path.split("?")[0]
            if path == "/api/settings":
                os.makedirs(DATA, exist_ok=True)
                cfg = load_cfg()
                if "token" in p:
                    cfg["token"] = (p["token"] or "").strip()
                fd = os.open(CFG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as f:
                    json.dump(cfg, f)
                return self.send(200, {"tokenSet": bool(token())})
            if path in ("/api/convert", "/api/zip", "/api/publish"):
                r = build(p, store_state())
                if path == "/api/zip":
                    return self.send(200, zip_bytes(r), "application/zip",
                                     {"Content-Disposition": f'attachment; filename="{r["appId"]}.zip"'})
                if path == "/api/publish":
                    r["commit"] = publish(r)
                    r["commitUrl"] = f"https://github.com/{STORE_REPO}/commit/{r['commit']}"
                return self.send(200, r)
            self.send(404, {"error": "not found"})
        except (convert.ConvertError, github.GitHubError, ValueError, KeyError) as e:
            self.send(400, {"error": str(e)})
        except Exception as e:  # noqa
            print("error:", repr(e), file=sys.stderr)
            self.send(500, {"error": "internal error"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
