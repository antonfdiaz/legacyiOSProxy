import re
from html import escape as html_escape
from pathlib import Path
from .runtime import POLYFILL_FEATURES, required_polyfills

_POLYFILL_ORDER = (
    "fetch", "object-entries", "object-values", "object-from-entries",
    "url-search-params",
)
_SCRIPT_NONCE_RE = re.compile(
    r"<script\b[^>]*\bnonce\s*=\s*([\"'])(.*?)\1",
    re.IGNORECASE | re.DOTALL,
)

def adapt_html(html,target=None):
    #modern attributes that old webkit doesn't need
    html = re.sub(
        r'\s+(?:srcset|loading|decoding|fetchpriority|inert)'
        r'=(?:"[^"]*"|\'[^\']*\')',
        "",
        html,
        flags=re.IGNORECASE,
    )

    #boolean inert attribute without value
    html = re.sub(
        r'\s+inert(?=\s|>)',
        "",
        html,
        flags=re.IGNORECASE,
    )

    #promote common lazy load attributes to src
    html = re.sub(
        r'<img\b([^>]*?)\s(?:data-src|data-original|data-lazy-src)'
        r'=["\']([^"\']+)["\']([^>]*)>',
        _adapt_lazy_img,
        html,
        flags=re.IGNORECASE,
    )

    #simplify <picture> to its fallback <img>
    html = re.sub(
        r'<picture\b[^>]*>.*?(<img\b[^>]*>).*?</picture>',
        r'\1',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    polyfills = required_polyfills(target,POLYFILL_FEATURES)
    injections = []
    nonce_match = _SCRIPT_NONCE_RE.search(html)
    nonce_attr = ""
    if nonce_match:
        nonce_attr = f' nonce="{html_escape(nonce_match.group(2), quote=True)}"'
    for feature in _POLYFILL_ORDER:
        marker = f"legacy-proxy-polyfill-{feature}"
        if feature in polyfills and marker not in html:
            polyfill = Path(__file__).resolve().parents[2]/"js"/"polyfills"/f"{feature}.js"
            injections.append(
                f'<script id="{marker}"{nonce_attr}>\n'
                f'{polyfill.read_text(encoding="utf-8")}\n'
                "</script>"
            )
    if injections:
        script = "".join(injections)
        first_script = re.search(r"<script\b",html,re.IGNORECASE)
        if first_script:
            html = html[:first_script.start()]+script+html[first_script.start():]
        else:
            head = re.search(r"</head\s*>",html,re.IGNORECASE)
            position = head.start() if head else 0
            html = html[:position]+script+html[position:]
        for feature in _POLYFILL_ORDER:
            if feature in polyfills and f"legacy-proxy-polyfill-{feature}" in script:
                print(f"[COMPAT] injecting polyfill={feature} target=iOS {target.ios_major}")

    return html

def _adapt_lazy_img(match):
    before = match.group(1)
    url = match.group(2)
    after = match.group(3)

    attrs = before+after

    attrs = re.sub(
        r'\s+src=(?:"[^"]*"|\'[^\']*\')',
        "",
        attrs,
        flags=re.IGNORECASE,
    )

    return f'<img{attrs} src="{url}">'
