"""Minimal GitHub REST client (Git Data API) for committing several files at once."""
import json, urllib.request, urllib.error, base64

API = "https://api.github.com"


class GitHubError(Exception):
    pass


def call(method, path, token=None, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "HeilSS",
                                          "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")[:300]
        if e.code == 404:
            return None
        raise GitHubError(f"GitHub {method} {path} -> {e.code}: {msg}")


def get_file(repo, path, branch="main", token=None):
    r = call("GET", f"/repos/{repo}/contents/{path}?ref={branch}", token)
    if not r or isinstance(r, list):
        return None
    return base64.b64decode(r["content"]).decode()


def list_tree(repo, branch="main", token=None):
    r = call("GET", f"/repos/{repo}/git/trees/{branch}?recursive=1", token)
    return [t["path"] for t in (r or {}).get("tree", [])]


def commit_files(repo, files, message, token, branch="main"):
    """files: {path: text}. Returns commit sha."""
    ref = call("GET", f"/repos/{repo}/git/ref/heads/{branch}", token)
    if ref is None:
        raise GitHubError(f"repo {repo} or branch {branch} not found / no access")
    base = ref["object"]["sha"]
    base_tree = call("GET", f"/repos/{repo}/git/commits/{base}", token)["tree"]["sha"]
    tree = call("POST", f"/repos/{repo}/git/trees", token, {
        "base_tree": base_tree,
        "tree": [{"path": p, "mode": "100644", "type": "blob", "content": c} for p, c in files.items()]})
    commit = call("POST", f"/repos/{repo}/git/commits", token,
                  {"message": message, "tree": tree["sha"], "parents": [base]})
    call("PATCH", f"/repos/{repo}/git/refs/heads/{branch}", token, {"sha": commit["sha"]})
    return commit["sha"]
