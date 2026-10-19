# Heil Store Studio (HeilSS)
Tiny Python service (stdlib + PyYAML) that converts a `docker-compose.yml` or `docker run` command into an Umbrel community app and commits it to `jborgwardt/heilss-store` (icons to `jborgwardt/heilss-assets`). Auth is Umbrel's app_proxy login; the app itself has none.
Env: `HEILSS_GITHUB_TOKEN` (optional; or set in UI), `HEILSS_STORE_REPO`, `HEILSS_ASSETS_REPO`, `HEILSS_STORE_ID`.
Test: `cd app && python -m unittest discover -s tests`. Image: ghcr.io/jborgwardt/heilss (built by Actions).
