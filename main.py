from mitmproxy import http,options
from mitmproxy.tools.dump import DumpMaster
from src.services.github import GitHubProxy
from src.services.google import GoogleCaptchaError,GoogleScraper
from src.services.imdb import IMDbProxy
from src.services.reddit import RedditProxy
from src.services.wikipedia import WikipediaProxy
from src.services.google_earth import GoogleEarthProxy
from src.services.youtube import YouTubeProxy
from src.services.twitter import TwitterProxy
from src.config import Config
import src.compat as compat
import asyncio
from pathlib import Path
from urllib.parse import parse_qs,urlparse
from PIL import Image
import PIL
import pystray
from threading import Thread
from src.utils import set_config_value,get_ip_address
import os
import sys

VERSION = "0.9.3"

GOOGLE_HOSTS = {"google.com","www.google.com"}
COMPAT_EXCEPTIONS = {
    "kh.google.com",
    "keyhole.com",
    "googlevideo.com",
    "ytimg.com",
    "ggpht.com",
    "youtube.com",
    "youtubei.googleapis.com",
    "google.com",
    "www.google.com",
    "github.com",
    "www.github.com",
    "wikipedia.org",
    "imdb.com",
    "media-imdb.com",
    "imdbws.com",
    "amazon-adsystem.com",
    "twitter.com",
    "api.twitter.com",
    "mobile.twitter.com",
    "upload.twitter.com",
    "cards.twitter.com",
    "twimg.com",
    "abs.twimg.com",
    "pbs.twimg.com",
    "settings.crashlytics.com",
    "crashlytics.com",
}
IGNORE_HOSTS = [
    r"(^|\.)apple\.com:443$",
    r"(^|\.)icloud\.com:443$",
    r"(^|\.)itunes\.apple\.com:443$",
    r"(^|\.)apps\.apple\.com:443$",
    r"(^|\.)mzstatic\.com:443$",
]
IGNORE_CONTENT_TYPES = (
    "application/json",
    "application/ld+json",
    "application/xml",
    "text/xml",
    "audio/",
    "video/"
)
SKIP_JS_HOSTS = (
    "token.awswaf.com",
    "amazonaws.com",
)
JS_CONTENT_TYPES = (
    "application/javascript",
    "text/javascript",
    "application/x-javascript",
)

config = Config()

class InterceptAddon:
    def __init__(self):
        self.config = config or Config()
        
        #initialize proxy services
        self.github = GitHubProxy() if config.services.github else None
        self.google = GoogleScraper(
            chrome_headless=self.config.general.chrome_headless) if config.services.google else None
        self.imdb = IMDbProxy(config=self.config) if config.services.imdb else None
        self.reddit = RedditProxy(
            cookie=getattr(self.config.services,"reddit_cookie",""),
            token=getattr(self.config.services,"reddit_token",""),
            client_id=getattr(self.config.services,"reddit_client_id",""),
            client_secret=getattr(self.config.services,"reddit_client_secret",""),
            chrome_headless=self.config.general.chrome_headless,
            config=self.config,
        ) if config.services.reddit else None
        self.wikipedia = WikipediaProxy() if config.services.wikipedia else None
        self.google_earth = GoogleEarthProxy() if getattr(config.services, "google_earth", True) else None
        self.youtube = YouTubeProxy(config=self.config) if getattr(config.services, "youtube", True) else None
        self.twitter = TwitterProxy(config=self.config) if getattr(config.services, "twitter", True) else None

    async def request(self,flow):
        path = urlparse(flow.request.url).path.lower()

        if path.endswith((".css",".html",".htm",".js",".mjs")):
            flow.request.headers.pop("If-None-Match",None)
            flow.request.headers.pop("If-Modified-Since",None)
    
        url = flow.request.url
        host = (urlparse(url).hostname or "").lower().rstrip(".")
        
        if self.google:
            if host in GOOGLE_HOSTS and urlparse(url).path == "/":
                #redirect to google_index.html
                flow.response = http.Response.make(
                    200,
                    (Path(__file__).parent/"html"/"google_index.html").read_bytes(),
                    {"Content-Type": "text/html; charset=utf-8"},
                )
                return
            
            if host in GOOGLE_HOSTS and urlparse(url).path == "/legacy-proxy-google-image":
                image_url = parse_qs(urlparse(url).query).get("url",[""])[0]
                if urlparse(image_url).scheme in {"http","https"}:
                    image = await self.google.fetch_image(image_url)
                    if image:
                        content,content_type = image
                        flow.response = http.Response.make(
                            200,
                            content,
                            {
                                "Content-Type": content_type,
                                "Cache-Control": "public,max-age=86400",
                            },
                        )
                    else:
                        flow.response = http.Response.make(404,b"")
                    return

            if host in GOOGLE_HOSTS and flow.request.path == "/images/google.png":
                flow.response = http.Response.make(
                    200,
                    (Path(__file__).parent/"images"/"google.png").read_bytes(),
                    {"Content-Type": "image/png","Cache-Control": "public,max-age=86400"},
                )
                return
            
            if host in GOOGLE_HOSTS and flow.request.path == "/css/google.css":
                flow.response = http.Response.make(
                    200,
                    (Path(__file__).parent/"css"/"google.css").read_bytes(),
                    {"Content-Type": "text/css","Cache-Control": "public,max-age=86400"},
                )
                return

            if host in GOOGLE_HOSTS and flow.request.path == "/css/google_index.css":
                flow.response = http.Response.make(
                    200,
                    (Path(__file__).parent/"css"/"google_index.css").read_bytes(),
                    {"Content-Type": "text/css","Cache-Control": "public,max-age=86400"},
                )
                return

            if host in GOOGLE_HOSTS and flow.request.path == "/css/google_imgs.css":
                flow.response = http.Response.make(
                    200,
                    (Path(__file__).parent/"css"/"google_imgs.css").read_bytes(),
                    {"Content-Type": "text/css","Cache-Control": "public,max-age=86400"},
                )
                return
            
            if host in GOOGLE_HOSTS and flow.request.path == "/js/google.js":
                flow.response = http.Response.make(
                    200,
                    (Path(__file__).parent/"js"/"google.js").read_bytes(),
                    {"Content-Type": "application/javascript","Cache-Control": "public,max-age=86400"},
                )
                return

            if host in GOOGLE_HOSTS and flow.request.path.startswith("/imghp"):
                flow.response = http.Response.make(
                    200,
                    self.google.image_home.encode("utf-8"),
                    {"Content-Type": "text/html; charset=utf-8"},
                )
                return

            if host in GOOGLE_HOSTS and flow.request.path.startswith("/search?"):
                print(f"[INFO] intercepting Google search: {url}")
                try:
                    content = (await self.google.search(url)).encode("utf-8")
                    flow.response = http.Response.make(
                        200,
                        content,
                        {"Content-Type": "text/html; charset=utf-8"},
                    )
                except GoogleCaptchaError as e:
                    print(f"[WARN] Google CAPTCHA detected: {e}")
                    flow.response = http.Response.make(
                        503,
                        (
                            "<!doctype html><meta charset=utf-8>"
                            "<title>Google CAPTCHA</title>"
                            "<p>Oops. Google needs a CAPTCHA! Try again later.</p>"
                        ).encode("utf-8"),
                        {"Content-Type": "text/html; charset=utf-8"},
                    )
                except Exception as e:
                    detail = f"{type(e).__name__}: {e}"
                    print(f"[ERROR] Google intercept failed: {detail}")
                    flow.response = http.Response.make(
                        500,
                        (
                            "<!doctype html><meta charset=utf-8>"
                            "<title>Google Intercept Failed</title>"
                            f"<p>{detail}</p>"
                        ).encode("utf-8"),
                        {"Content-Type": "text/html; charset=utf-8"},
                    )
                    
        if self.reddit:
            if flow.request.path == "/images/reddit.png" and host in {"reddit.com","www.reddit.com"}:
                flow.response = http.Response.make(
                    200,
                    (Path(__file__).parent/"images"/"reddit2.png").read_bytes(),
                    {"Content-Type": "image/png","Cache-Control": "public,max-age=86400"},
                )
                return
                
        if self.imdb and await self.imdb.request(flow):
            return

        if self.reddit and await self.reddit.request(flow):
            return
        
        if self.wikipedia and self.wikipedia.request(flow):
            return

        if getattr(self, "google_earth", None) and self.google_earth.request(flow):
            return

        if getattr(self, "youtube", None) and await self.youtube.request(flow):
            return

        if getattr(self, "twitter", None) and await self.twitter.request(flow):
            return
        
    def should_ignore_response(self,content_type):
        return any(
            content_type.startswith(prefix)
            for prefix in IGNORE_CONTENT_TYPES
        )
        
    def matches_domain(self,host,domain):
        return host == domain or host.endswith("."+domain)
    
    def is_compat_exception(self,host):
        return any(
            self.matches_domain(host,domain)
            for domain in COMPAT_EXCEPTIONS
        )
        
    def response(self,flow):
        content_type = flow.response.headers.get("Content-Type","").lower()

        url = flow.request.url
        host = (urlparse(url).hostname or "").lower().rstrip(".")
        
        self.github.response(flow) if self.github else None
        self.wikipedia.response(flow) if self.wikipedia else None
        self.reddit.response(flow) if self.reddit else None
        self.imdb.response(flow) if self.imdb else None
        self.youtube.response(flow) if getattr(self, "youtube", None) else None
        self.twitter.response(flow) if getattr(self, "twitter", None) else None
        
        if self.should_ignore_response(content_type):
            return
        
        if not self.is_compat_exception(host):
            if "text/html" in content_type or "text/css" in content_type:
                user_agent = flow.request.headers.get("User-Agent","")
                target = compat.detect_target(user_agent)
                if target.ios_major is not None:
                    print(f"[COMPAT] target=iOS {target.ios_major}")

                if "text/html" in content_type:
                    print("[INFO] adapting HTML for legacy WebKit...")
                    flow.response.text = compat.adapt_html(
                        flow.response.text,target=target)
                elif "text/css" in content_type:
                    print("[INFO] adapting CSS for legacy WebKit...")
                    flow.response.text = compat.adapt_css(
                        flow.response.text,target=target)
            elif (any(content_type.startswith(prefix) for prefix in JS_CONTENT_TYPES)
                  and not any(self.matches_domain(host,domain) for domain in SKIP_JS_HOSTS)):
                user_agent = flow.request.headers.get("User-Agent","")
                target = compat.detect_target(user_agent)
                if (getattr(flow.response,"status_code",200) not in {204,304}
                        and flow.response.text):
                    features = compat.analyze_js(flow.response.text)
                    runtime_features = features & compat.RUNTIME_FEATURES
                    if runtime_features:
                        print(f"[COMPAT] runtime JS={','.join(sorted(runtime_features))}")
                    unsupported_features = compat.unsupported_js_features(
                        target,features)
                    target_name = (
                        f"iOS {target.ios_major}"
                        if target.ios_major is not None else "unknown"
                    )
                    if unsupported_features:
                        print(
                            f"[COMPAT] unsupported JS={','.join(sorted(unsupported_features))} "
                            f"target={target_name}"
                        )
                    original = flow.response.text
                    adapted = compat.adapt_js(original,target=target)
                    if adapted != original:
                        print(f"[COMPAT] transpiled JS target={target_name}")
                        flow.response.text = adapted

        print(f"[INFO] intercepted response from: {url}")

    def error(self,flow):
        handled = self.imdb.error(flow) if self.imdb else False
        if not handled:
            request = getattr(flow,"request",None)
            method = getattr(request,"method","UNKNOWN")
            url = getattr(request,"url","unknown URL")
            print(f"[WARN] Unhandled proxy error for {method} {url}: {flow.error}")

    def server_connect_error(self, data):
        server = data.server
        print(
            f"[WARN] Server connection failed for address={server.address}, "
            f"sni={server.sni!r}: {server.error}"
        )

    def tls_failed_server(self, data):
        server = data.conn
        print(
            f"[WARN] Server TLS failed for address={server.address}, "
            f"sni={server.sni!r}: {server.error}"
        )

    async def close(self):
        if self.google:
            await self.google.close()

async def start_proxy(host,port):
    opts = options.Options(
        listen_host=host,
        listen_port=port,
    )

    opts.update(ignore_hosts=IGNORE_HOSTS, ssl_insecure=True)
    opts.update_defer(tls_version_client_min="TLS1")
    
    master = DumpMaster(opts)
    addon = InterceptAddon()
    master.addons.add(addon)

    if addon.reddit:
        asyncio.create_task(addon.reddit.start_auto_refresh())
    if addon.imdb:
        asyncio.create_task(addon.imdb.start_auto_refresh())
    
    try:
        print(r""" _                               ___                     
| | ___  __ _  __ _  ___ _   _  / _ \_ __ _____  ___   _ 
| |/ _ \/ _` |/ _` |/ __| | | |/ /_)/ '__/ _ \ \/ / | | |
| |  __/ (_| | (_| | (__| |_| / ___/| | | (_) >  <| |_| |
|_|\___|\__, |\__,_|\___|\__, \/    |_|  \___/_/\_\\__, |
        |___/            |___/                     |___/""")
        print(f"legacyiOSProxy v{VERSION} - MITM proxy for legacy iOS devices")
        print(f"[INFO] starting proxy at {host}:{port}...")
        ip_address = get_ip_address()
        print(f"[INFO] set the server to {ip_address}!")
        await master.run()
    except KeyboardInterrupt:
        print("[INFO] stopping proxy...")
        master.shutdown()
    finally:
        print("[INFO] stopping proxy...")
        await addon.close()
        
def start_menu(image):
    if sys.platform == "darwin":
        import io
        import pystray._darwin as _pystray_darwin
        import AppKit,Foundation

        #hide dock icon, menu bar only
        AppKit.NSApplication.sharedApplication().setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

        def _retina_assert_image(self):
            #we need to resize the icon for retina displays, otherwise it will look pixelated
            thickness = self._status_bar.thickness()
            
            scale = AppKit.NSScreen.mainScreen().backingScaleFactor()
            px = int(thickness*scale)
            size = (px,px)

            if self._icon_image and self._icon_image.size() == (int(thickness),int(thickness)):
                return

            source = PIL.Image.new("RGBA",size)
            source.paste(self._icon.resize(size,Image.LANCZOS))

            b = io.BytesIO()
            source.save(b,"png")
            data = Foundation.NSData(b.getvalue())

            ns_image = AppKit.NSImage.alloc().initWithData_(data)
            
            ns_image.setTemplate_(True)
            ns_image.setSize_(AppKit.NSSize(thickness,thickness))
            self._icon_image = ns_image
            self._status_item.button().setImage_(self._icon_image)

        _pystray_darwin.Icon._assert_image = _retina_assert_image #hook for retina support
        image = Image.open(image_path).convert("RGBA")
    else:
        image = image.resize((64,64),getattr(Image,"Resampling",Image).LANCZOS)

    def on_exit(icon,item):
        icon.stop()
        os._exit(0)

    icon = pystray.Icon("legacyProxy",image,"legacyProxy",menu=pystray.Menu(
        pystray.MenuItem(f"legacyProxy {VERSION} - {config.general.host}:{config.general.port}",lambda: None,enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Host...",lambda: set_config_value("general","host",config)),
        pystray.MenuItem("Port...",lambda: set_config_value("general","port",config)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Chrome Headless",lambda: set_config_value("general","chrome_headless",config),checked=lambda item: config.general.chrome_headless),
        pystray.MenuItem("Chrome Path...",lambda: set_config_value("general","chrome_path",config)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Google",lambda: set_config_value("services","google",config),checked=lambda item: config.services.google),
        pystray.MenuItem("Reddit",lambda: set_config_value("services","reddit",config),checked=lambda item: config.services.reddit),
        pystray.MenuItem("Wikipedia",lambda: set_config_value("services","wikipedia",config),checked=lambda item: config.services.wikipedia),
        pystray.MenuItem("GitHub",lambda: set_config_value("services","github",config),checked=lambda item: config.services.github),
        pystray.MenuItem("IMDb",lambda: set_config_value("services","imdb",config),checked=lambda item: config.services.imdb),
        pystray.MenuItem("Google Earth",lambda: set_config_value("services","google_earth",config),checked=lambda item: getattr(config.services,"google_earth",True)),
        pystray.MenuItem("YouTube",lambda: set_config_value("services","youtube",config),checked=lambda item: getattr(config.services,"youtube",True)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit",on_exit)
    ))
    icon.run()
        
if __name__ == "__main__":
    try:
        thread = Thread(target=lambda: asyncio.run(start_proxy(config.general.host,config.general.port)))
        thread.start()
        
        if not "--disable-menu" in sys.argv:
            image_path = Path(__file__).parent/"images"/"tray-icon.png"
            image = Image.open(image_path).convert("RGBA")
            
            start_menu(image)
    except KeyboardInterrupt:
        pass
