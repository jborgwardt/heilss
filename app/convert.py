"""HeilSS conversion core: docker run / compose -> Umbrel community app files."""
import json, re, shlex, hashlib, urllib.request, urllib.error
import yaml

CATEGORIES = ["Development", "Media", "Files", "Networking", "Automation", "AI", "Social", "Finance", "Bitcoin", "Utilities"]


class ConvertError(Exception):
    pass


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "app"


def app_id_for(store_id, name):
    base = slugify(name)
    return base if base.startswith(store_id + "-") else f"{store_id}-{base}"


# ---------- docker run ----------
_BOOL = {"-d", "--detach", "--rm", "-i", "--interactive", "-t", "--tty", "-it", "-dit", "-itd", "-di", "-td",
         "--init", "--privileged", "--read-only", "--no-healthcheck", "-P", "--publish-all"}
_VAL = {"-p": "ports", "--publish": "ports", "-e": "env", "--env": "env", "-v": "volumes", "--volume": "volumes",
        "--name": "name", "--restart": "restart", "-u": "user", "--user": "user", "-w": "working_dir",
        "--workdir": "working_dir", "--entrypoint": "entrypoint", "-h": "hostname", "--hostname": "hostname",
        "--cap-add": "cap_add", "--device": "devices", "--network": "network", "--net": "network",
        "--env-file": "env_file", "--label": "label", "-l": "label", "--add-host": "extra_hosts",
        "--shm-size": "shm_size", "--memory": "mem", "-m": "mem", "--cpus": "cpus", "--platform": "platform",
        "--mount": "mount", "--tmpfs": "tmpfs", "--dns": "dns", "--pull": "pull", "--group-add": "group_add"}


def parse_run(cmd):
    cmd = re.sub(r"\\\s*\n", " ", cmd.strip())
    try:
        t = shlex.split(cmd, comments=False)
    except ValueError as e:
        raise ConvertError(f"cannot parse docker run command: {e}")
    while t and t[0] in ("sudo",):
        t.pop(0)
    if t[:2] == ["docker", "container"]:
        t = ["docker"] + t[2:]
    if t[:2] != ["docker", "run"]:
        raise ConvertError("not a `docker run` command")
    t = t[2:]
    o = {"ports": [], "env": [], "volumes": [], "cap_add": [], "devices": [], "extra_hosts": []}
    warnings, i, image = [], 0, None
    while i < len(t):
        a = t[i]
        if image is not None:
            break
        if not a.startswith("-"):
            image = a
            i += 1
            break
        if a in _BOOL:
            if a == "--privileged":
                o["privileged"] = True
            if a == "--init":
                o["init"] = True
            i += 1
            continue
        key, val = a, None
        if a.startswith("--") and "=" in a:
            key, val = a.split("=", 1)
        elif (not a.startswith("--")) and len(a) > 2 and a[:2] in _VAL:  # -p8080:80
            key, val = a[:2], a[2:]
        if key in _VAL:
            if val is None:
                i += 1
                if i >= len(t):
                    raise ConvertError(f"missing value for {key}")
                val = t[i]
            dst = _VAL[key]
            if dst in ("ports", "env", "volumes", "cap_add", "devices", "extra_hosts"):
                o[dst].append(val)
            else:
                o[dst] = val
            i += 1
            continue
        warnings.append(f"ignored unknown option {a}")
        i += 1
    if not image:
        raise ConvertError("no image found in docker run command")
    rest = t[i:]
    svc = {"image": image}
    if rest:
        svc["command"] = rest
    if o["ports"]:
        svc["ports"] = o["ports"]
    if o["env"]:
        svc["environment"] = o["env"]
    if o["volumes"]:
        svc["volumes"] = o["volumes"]
    for k in ("user", "working_dir", "hostname", "entrypoint", "privileged", "init"):
        if k in o:
            svc[k] = o[k]
    if o["cap_add"]:
        svc["cap_add"] = o["cap_add"]
    if o["devices"]:
        svc["devices"] = o["devices"]
    if o["extra_hosts"]:
        svc["extra_hosts"] = o["extra_hosts"]
    if o.get("shm_size"):
        svc["shm_size"] = o["shm_size"]
    for k in ("env_file", "network", "mount", "tmpfs"):
        if o.get(k):
            warnings.append(f"--{k.replace('_', '-')} is not converted; configure it manually if needed")
    return {"services": {slugify(o.get("name") or image.split("/")[-1].split(":")[0].split("@")[0]): svc}}, warnings


# ---------- helpers ----------
def parse_port(p):
    """Return (host or None, container int, proto) from compose port entry."""
    if isinstance(p, dict):
        return p.get("published"), int(p["target"]), p.get("protocol", "tcp")
    p = str(p)
    proto = "tcp"
    if "/" in p:
        p, proto = p.rsplit("/", 1)
    parts = p.split(":")
    cont = parts[-1]
    host = parts[-2] if len(parts) >= 2 else None
    cont = cont.split("-")[0]
    return host, int(cont), proto


def _data_path(src):
    name = slugify(src.rstrip("/").split("/")[-1].lstrip(".~")) if src else "data"
    return "${APP_DATA_DIR}/data/" + name


def convert_volume(v, warnings, sname):
    if isinstance(v, dict):
        typ, src, tgt = v.get("type"), v.get("source"), v.get("target")
        if not tgt:
            return None
        if typ == "tmpfs":
            return None
        ro = ":ro" if v.get("read_only") else ""
        v = (f"{src}:{tgt}{ro}" if src else tgt)
    v = str(v)
    parts = v.split(":")
    if len(parts) == 1:
        return f"{_data_path(slugify(parts[0]))}:{parts[0]}"
    src, tgt = parts[0], parts[1]
    mode = (":" + parts[2]) if len(parts) > 2 else ""
    if src.startswith("/var/run/docker.sock") or src in ("/var/run/docker.sock",):
        warnings.append(f"{sname}: mounts docker.sock (discouraged by Umbrel)")
        return v
    if src.startswith("/dev") or src.startswith("/sys") or src.startswith("/proc"):
        return v
    if "${" in src:
        return v
    return f"{_data_path(src)}:{tgt}{mode}"


def pick_web(services, hint=None, web_port=None):
    names = list(services)
    if not names:
        raise ConvertError("compose has no services")
    if hint:
        if hint not in services:
            raise ConvertError(f"web service '{hint}' not found")
        main = hint
    else:
        main = next((n for n in names if services[n].get("ports")), None) or \
            next((n for n in names if services[n].get("expose")), None) or names[0]
    port = web_port
    if not port:
        s = services[main]
        if s.get("ports"):
            tcp = [parse_port(p) for p in s["ports"]]
            tcp = [x for x in tcp if x[2] == "tcp"] or tcp
            port = tcp[0][1]
        elif s.get("expose"):
            port = int(str(s["expose"][0]).split("/")[0])
        else:
            port = 80
    return main, int(port)


def resolve_digest(image, timeout=10):
    """Return image with @sha256 digest pinned, or None on failure."""
    try:
        if "@sha256:" in image:
            return image
        ref = image
        tag = "latest"
        last = ref.rsplit("/", 1)[-1]
        if ":" in last:
            ref, tag = ref.rsplit(":", 1)
        parts = ref.split("/")
        if len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
            reg, repo = parts[0], "/".join(parts[1:])
        else:
            reg, repo = "registry-1.docker.io", ref if len(parts) > 1 else "library/" + ref
        if reg in ("docker.io", "index.docker.io"):
            reg = "registry-1.docker.io"
        url = f"https://{reg}/v2/{repo}/manifests/{tag}"
        accept = ", ".join(["application/vnd.oci.image.index.v1+json",
                            "application/vnd.docker.distribution.manifest.list.v2+json",
                            "application/vnd.oci.image.manifest.v1+json",
                            "application/vnd.docker.distribution.manifest.v2+json"])

        def head(auth=None):
            req = urllib.request.Request(url, method="HEAD", headers={"Accept": accept})
            if auth:
                req.add_header("Authorization", "Bearer " + auth)
            return urllib.request.urlopen(req, timeout=timeout)
        try:
            r = head()
        except urllib.error.HTTPError as e:
            if e.code != 401:
                return None
            ch = e.headers.get("WWW-Authenticate", "")
            m = dict(re.findall(r'(\w+)="([^"]*)"', ch))
            if "realm" not in m:
                return None
            q = f"{m['realm']}?service={m.get('service', '')}&scope=repository:{repo}:pull"
            tok = json.load(urllib.request.urlopen(q, timeout=timeout))
            r = head(tok.get("token") or tok.get("access_token"))
        d = r.headers.get("Docker-Content-Digest")
        return f"{ref}:{tag}@{d}" if d else None
    except Exception:
        return None


# ---------- build Umbrel compose ----------
def to_umbrel_compose(app_id, compose, web_service=None, web_port=None, pin=False):
    warnings = []
    if not isinstance(compose, dict) or not isinstance(compose.get("services"), dict):
        raise ConvertError("compose must contain a `services:` mapping")
    services = compose["services"]
    main, port = pick_web(services, web_service, web_port)
    out = {}
    for name, s in services.items():
        s = dict(s or {})
        if "build" in s:
            raise ConvertError(f"service '{name}' uses build:, Umbrel needs a published image")
        if not s.get("image"):
            raise ConvertError(f"service '{name}' has no image")
        for k in ("container_name", "networks", "network_mode", "profiles", "deploy", "version"):
            if k in s:
                if k in ("network_mode",):
                    warnings.append(f"{name}: removed network_mode (Umbrel manages networking)")
                s.pop(k)
        if "env_file" in s:
            warnings.append(f"{name}: env_file removed; inline the variables")
            s.pop("env_file")
        if s.get("ports"):
            keep = []
            for p in s["ports"]:
                h, c, pr = parse_port(p)
                if name == main and c == port and pr == "tcp":
                    continue
                keep.append(p if not isinstance(p, dict) else f"{p.get('published')}:{p['target']}/{p.get('protocol', 'tcp')}")
            if keep:
                s["ports"] = keep
            else:
                s.pop("ports")
        if s.get("volumes"):
            vols = [convert_volume(v, warnings, name) for v in s["volumes"]]
            s["volumes"] = [v for v in vols if v]
            if not s["volumes"]:
                s.pop("volumes")
        if s.get("restart") != "on-failure":
            s["restart"] = "on-failure"
        s["init"] = s.get("init", True)
        if pin:
            p = resolve_digest(s["image"])
            if p:
                s["image"] = p
            else:
                warnings.append(f"{name}: could not pin digest for {s['image']}")
        elif ":" not in s["image"].rsplit("/", 1)[-1] or s["image"].endswith(":latest"):
            warnings.append(f"{name}: image uses :latest; consider pinning a version/digest")
        out[name] = s
    if compose.get("networks"):
        warnings.append("top-level networks removed")
    if compose.get("volumes"):
        warnings.append("named volumes converted to ${APP_DATA_DIR}/data bind mounts")
    full = {"version": "3.7", "services": {"app_proxy": {"environment": {
        "APP_HOST": f"{app_id}_{main}_1", "APP_PORT": port}}}}
    full["services"].update(out)
    text = yaml.safe_dump(full, sort_keys=False, default_flow_style=False, width=1000)
    return text, main, port, warnings


def parse_source(text):
    """Auto-detect compose vs docker run. Returns (compose_dict, warnings)."""
    t = text.strip()
    if not t:
        raise ConvertError("paste a docker-compose.yml or a docker run command")
    if re.match(r"^(sudo\s+)?docker\s+(container\s+)?run\b", t):
        return parse_run(t)
    try:
        data = yaml.safe_load(t)
    except yaml.YAMLError as e:
        raise ConvertError(f"invalid YAML: {e}")
    if not isinstance(data, dict) or "services" not in data:
        raise ConvertError("input is neither a docker run command nor a compose file with services")
    return data, []


# ---------- manifest ----------
def tagline_from(desc, name):
    d = (desc or "").strip().split("\n")[0]
    d = re.split(r"(?<=[.!?])\s", d)[0].strip() if d else f"{name} on Umbrel"
    return d if len(d) <= 60 else d[:57].rstrip() + "..."


def _q(s):
    return json.dumps(s, ensure_ascii=False)


def _fold(s):
    return "\n".join("  " + l if l.strip() else "" for l in (s or "").strip().splitlines())


def bump(v):
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", v or "")
    return f"{m[1]}.{m[2]}.{int(m[3]) + 1}" if m else "1.0.0"


def build_manifest(app_id, name, desc, port, icon_url, category="Utilities", version="1.0.0",
                   developer="HeilSS", repo="", website="", path=""):
    if category not in CATEGORIES:
        category = "Utilities"
    desc = (desc or f"{name}, packaged for Umbrel with Heil Store Studio.").strip()
    return "\n".join([
        "manifestVersion: 1",
        f"id: {app_id}",
        f"category: {_q(category)}",
        f"name: {_q(name)}",
        f"version: {_q(version)}",
        f"tagline: {_q(tagline_from(desc, name))}",
        "description: >-",
        _fold(desc),
        "releaseNotes: >-",
        "  Generated by Heil Store Studio.",
        f"developer: {_q(developer)}",
        f"website: {_q(website or repo)}",
        "dependencies: []",
        f"repo: {_q(repo)}",
        f"support: {_q(repo)}",
        f"port: {port}",
        "gallery: []",
        f"path: {_q(path)}",
        f"icon: {_q(icon_url)}",
        'defaultUsername: ""',
        'defaultPassword: ""',
        'submitter: "HeilSS"',
        "",
    ])
