import os, sys, unittest, yaml
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import convert, icon


class T(unittest.TestCase):
    def test_run_basic(self):
        c, w = convert.parse_run("docker run -d --name my-app -p 8080:80 -e FOO=bar -e 'X=a b' -v /srv/data:/data -v cfg:/config --restart unless-stopped nginx:1.27 nginx -g 'daemon off;'")
        s = c["services"]["my-app"]
        self.assertEqual(s["image"], "nginx:1.27")
        self.assertEqual(s["ports"], ["8080:80"])
        self.assertEqual(s["environment"], ["FOO=bar", "X=a b"])
        self.assertEqual(s["command"], ["nginx", "-g", "daemon off;"])

    def test_run_multiline_and_equals(self):
        c, _ = convert.parse_run("docker run \\\n --name=x \\\n --publish=3000:3000 \\\n -p9000:9000 \\\n ghcr.io/o/i:1")
        s = c["services"]["x"]
        self.assertEqual(s["ports"], ["3000:3000", "9000:9000"])

    def test_umbrel_compose(self):
        c, _ = convert.parse_run("docker run -d --name my-app -p 8080:80 -p 2222:22 -v /srv/data:/data -v cfg:/config nginx:1.27")
        text, svc, port, w = convert.to_umbrel_compose("heilss-my-app", c)
        y = yaml.safe_load(text)
        self.assertEqual(y["services"]["app_proxy"]["environment"], {"APP_HOST": "heilss-my-app_my-app_1", "APP_PORT": 80})
        s = y["services"]["my-app"]
        self.assertEqual(s["ports"], ["2222:22"])
        self.assertEqual(s["volumes"], ["${APP_DATA_DIR}/data/data:/data", "${APP_DATA_DIR}/data/cfg:/config"])
        self.assertEqual(s["restart"], "on-failure")
        self.assertNotIn("container_name", s)
        self.assertNotIn("PROXY_AUTH_ADD", text)

    def test_compose_multi(self):
        src = """
services:
  db:
    image: postgres:16
    container_name: pg
    volumes: [pgdata:/var/lib/postgresql/data]
    networks: [back]
  web:
    image: ghcr.io/x/web:2
    ports: ["127.0.0.1:8081:3000/tcp"]
    depends_on: [db]
volumes: {pgdata: {}}
networks: {back: {}}
"""
        comp, _ = convert.parse_source(src)
        text, svc, port, w = convert.to_umbrel_compose("heilss-x", comp)
        y = yaml.safe_load(text)
        self.assertEqual((svc, port), ("web", 3000))
        self.assertNotIn("ports", y["services"]["web"])
        self.assertNotIn("networks", y["services"]["db"])
        self.assertNotIn("networks", y)
        self.assertEqual(y["services"]["db"]["volumes"], ["${APP_DATA_DIR}/data/pgdata:/var/lib/postgresql/data"])
        self.assertEqual(y["services"]["web"]["depends_on"], ["db"])

    def test_build_rejected(self):
        with self.assertRaises(convert.ConvertError):
            convert.to_umbrel_compose("heilss-x", {"services": {"a": {"build": "."}}})

    def test_bad_input(self):
        with self.assertRaises(convert.ConvertError):
            convert.parse_source("hello world")

    def test_ids_manifest(self):
        self.assertEqual(convert.app_id_for("heilss", "My Cool App!"), "heilss-my-cool-app")
        self.assertEqual(convert.app_id_for("heilss", "heilss-foo"), "heilss-foo")
        m = convert.build_manifest("heilss-a", "A", "Hello. More.", 4100, "https://x/icon.svg", "Media")
        y = yaml.safe_load(m)
        self.assertEqual((y["id"], y["port"], y["version"], y["tagline"], y["category"]), ("heilss-a", 4100, "1.0.0", "Hello.", "Media"))
        self.assertEqual(y["icon"], "https://x/icon.svg")
        self.assertEqual(convert.bump("1.0.9"), "1.0.10")

    def test_icons(self):
        s = icon.generate("Foo Bar")
        self.assertIn('width="256" height="256"', s)
        self.assertNotIn("rx=", s)
        n = icon.normalize(b'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><script>x</script><rect width="32" height="32"/></svg>')
        self.assertIn('viewBox="0 0 32 32"', n)
        self.assertIn('width="256"', n)
        self.assertNotIn("script", n)
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
        self.assertIn("data:image/png;base64", icon.normalize(png))
        with self.assertRaises(ValueError):
            icon.normalize(b"nope")


if __name__ == "__main__":
    unittest.main()
