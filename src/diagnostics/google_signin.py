import json
import re
from urllib.parse import parse_qs, parse_qsl, unquote_plus, urlparse

from src.compat.target import detect_target


GOOGLE_SIGNIN_HOST = "accounts.google.com"
GOOGLE_SIGNIN_PATHS = {
    "/v3/signin/identifier",
    "/v3/signin/_/accountssigninui/data/batchexecute",
    "/v3/signin/_/accountssigninui/browserinfo",
}

_IOS_VERSION_RE = re.compile(
    r"(?:CPU\s+(?:iPhone\s+)?OS|iPhone\s+OS|iOS)\s*"
    r"([0-9]+(?:[._][0-9]+){0,2})",
    re.IGNORECASE,
)
_WEBKIT_RE = re.compile(r"AppleWebKit/([0-9.]+)", re.IGNORECASE)
_GMAIL_RE = re.compile(r"Gmail/([0-9][0-9.]*)", re.IGNORECASE)
_SAFE_RPC_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_BATCH_EXECUTE_PATH = "/v3/signin/_/accountssigninui/data/batchexecute"
_BATCH_RPC_MARKER = "wrb.fr"
_STRUCTURAL_ERROR_KEYS = {
    "error",
    "errors",
    "errorcode",
    "errormessage",
    "error_message",
    "failure",
}

# These are deliberately narrow structural signals.  We only inspect values
# under an explicitly recognised policy key (or a structured status/code
# field); arbitrary response text is never used to infer a client restriction.
_VERSION_POLICY_KEYS = {
    "update_required",
    "upgrade_required",
    "version_restriction",
    "unsupported_version",
    "client_version_unsupported",
}
_SECURITY_POLICY_KEYS = {
    "security_update_required",
    "security_requirement",
    "client_security",
    "client_security_restriction",
    "browser_unsupported",
    "disallowed_useragent",
}
_POLICY_STATUS_KEYS = {
    "code",
    "error_code",
    "errorcode",
    "reason",
    "status",
    "type",
    "category",
}
_POLICY_TRUE_VALUES = {
    "true",
    "required",
    "unsupported",
    "blocked",
    "disallowed",
    "update_required",
    "upgrade_required",
}
_VERSION_POLICY_CODES = {
    "APP_VERSION_TOO_OLD",
    "CLIENT_VERSION_TOO_OLD",
    "CLIENT_VERSION_UNSUPPORTED",
    "OUTDATED_CLIENT",
    "UNSUPPORTED_VERSION",
    "UPDATE_REQUIRED",
    "UPGRADE_REQUIRED",
    "VERSION_TOO_OLD",
}
_SECURITY_POLICY_CODES = {
    "BROWSER_UNSUPPORTED",
    "CLIENT_SECURITY_REQUIRED",
    "CLIENT_SECURITY_RESTRICTION",
    "DISALLOWED_USERAGENT",
    "OUTDATED_CLIENT_SECURITY",
    "SECURITY_REQUIREMENT",
    "SECURITY_UPDATE_REQUIRED",
    "UNSUPPORTED_BROWSER",
}

_KNOWN_PARAMETER_NAMES = {
    "app_version",
    "lib_ver",
    "system_version",
    "client_id",
    "client_secret",
    "redirect_uri",
    "response_type",
    "scope",
    "rpcids",
    "f.req",
    "continue",
    "flowname",
    "flow_name",
    "hl",
}
_PARAMETER_SIGNAL_GROUPS = {
    "app_version": "native_app",
    "system_version": "native_app",
    "lib_ver": "signin_sdk",
    "client_id": "oauth_client",
    "client_secret": "oauth_client",
    "redirect_uri": "oauth_client",
    "response_type": "oauth_client",
    "scope": "oauth_client",
    "rpcids": "web_ui",
    "f.req": "web_ui",
    "continue": "web_ui",
    "flowname": "web_ui",
    "flow_name": "web_ui",
    "hl": "web_ui",
}

_ERROR_PATTERNS = (
    ("auth_rejected", r"invalid|denied|forbidden|unauthori[sz]ed|not[_ -]?allowed|blocked"),
    ("browser_unsupported", r"unsupported[_ -]?(?:browser|user[_ -]?agent)|browser[_ -]?unsupported"),
    ("javascript_required", r"javascript[_ -]?(?:required|disabled)|enable[_ -]?javascript"),
    ("challenge_or_captcha", r"captcha|challenge|verification[_ -]?required"),
    ("rate_limited", r"rate[_ -]?limit|too[_ -]?many[_ -]?requests"),
    ("server_failure", r"internal[_ -]?error|server[_ -]?error|service[_ -]?unavailable"),
)


def is_google_signin_response(flow):
    """Return whether a flow is one of the observed Google sign-in responses."""
    request = getattr(flow, "request", None)
    url = getattr(request, "url", "")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    return host == GOOGLE_SIGNIN_HOST and parsed.path.lower() in GOOGLE_SIGNIN_PATHS


def response_body(response):
    """Read response bytes for measurement/inspection without exposing them."""
    try:
        body = response.get_content(strict=False)
    except (AttributeError, TypeError):
        body = getattr(response, "raw_content", b"")
        if not body:
            text = getattr(response, "text", "")
            body = text.encode("utf-8", errors="replace") if isinstance(text, str) else b""
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8", errors="replace")
    return bytes(body or b"")


def _request_body(request):
    """Read request bytes for local structural inspection only."""
    try:
        body = request.get_content(strict=False)
    except (AttributeError, TypeError):
        body = getattr(request, "raw_content", b"")
        if not body:
            body = getattr(request, "content", b"")
        if not body:
            text = getattr(request, "text", "")
            body = text.encode("utf-8", errors="replace") if isinstance(text, str) else b""
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8", errors="replace")
    return bytes(body or b"")


def _known_parameter_name(value):
    value = value if isinstance(value, str) else ""
    normalised = value.strip().lower().replace("-", "_")
    return normalised if normalised in _KNOWN_PARAMETER_NAMES else None


def _nested_known_parameter_names(value, names):
    """Collect allowlisted keys from nested JSON without retaining values."""
    if isinstance(value, dict):
        for key, child in value.items():
            known = _known_parameter_name(key)
            if known:
                names.add(known)
            _nested_known_parameter_names(child, names)
    elif isinstance(value, list):
        for child in value:
            _nested_known_parameter_names(child, names)
    elif isinstance(value, str):
        nested = _decode_json_candidate(value)
        if nested is not None:
            _nested_known_parameter_names(nested, names)


def _known_parameter_names_from_body(body):
    names = set()
    text = body[:256 * 1024].decode("utf-8", errors="replace")
    for key, value in parse_qsl(text, keep_blank_values=True):
        known = _known_parameter_name(unquote_plus(key))
        if known:
            names.add(known)
        if known == "f.req":
            nested = _decode_json_candidate(unquote_plus(value))
            if nested is not None:
                _nested_known_parameter_names(nested, names)
    decoded = _decode_json_candidate(text)
    if decoded is not None:
        _nested_known_parameter_names(decoded, names)
    return names


def request_parameter_summary(request):
    """Return only allowlisted parameter names and safe origin categories."""
    parsed = urlparse(getattr(request, "url", ""))
    names = {
        known
        for key in parse_qs(parsed.query or "", keep_blank_values=True)
        for known in (_known_parameter_name(key),)
        if known
    }
    names.update(_known_parameter_names_from_body(_request_body(request)))
    groups = {_PARAMETER_SIGNAL_GROUPS[name] for name in names}
    return {
        "names": ",".join(sorted(names)) if names else "none",
        "presence": ",".join(
            f"{name}=present" for name in sorted(names)
        ) or "none",
        "categories": ",".join(sorted(groups)) if groups else "none",
    }


def initial_html_policy_summary(body, content_type=""):
    """Detect only explicit machine-readable policy markers in initial HTML."""
    if "html" not in str(content_type or "").lower():
        return "not_document"
    text = body[:256 * 1024].decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")[:256 * 1024]
    tokens = set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,63}", text))
    normalised = {token.lower().replace("-", "_") for token in tokens}
    if normalised.intersection(_SECURITY_POLICY_KEYS):
        return "client_security_marker"
    if normalised.intersection(_VERSION_POLICY_KEYS):
        return "version_marker"
    return "none"


def _normalise_ios_version(value):
    return value.replace("_", ".")


def user_agent_summary(user_agent):
    """Return non-sensitive UA facts; never return the original UA."""
    value = user_agent if isinstance(user_agent, str) else ""
    ios_match = _IOS_VERSION_RE.search(value)
    ios_version = _normalise_ios_version(ios_match.group(1)) if ios_match else "unknown"
    target = detect_target(value)
    webkit_match = _WEBKIT_RE.search(value)
    gmail_match = _GMAIL_RE.search(value)

    if "ipad" in value.lower():
        platform = "ipad"
    elif "iphone" in value.lower():
        platform = "iphone"
    elif "ipod" in value.lower():
        platform = "ipod"
    else:
        platform = "other"

    return {
        "platform": platform,
        "ios_version": ios_version,
        "target": f"iOS {target.ios_major}" if target.ios_major is not None else "unknown",
        "webkit": webkit_match.group(1) if webkit_match else "unknown",
        "gmail": gmail_match.group(1) if gmail_match else "unknown",
    }


def _safe_content_type(value):
    value = value if isinstance(value, str) else str(value or "")
    return re.sub(r"[^A-Za-z0-9_./+;= -]", "?", value) or "unknown"


def _json_error_fields(value):
    fields = set()
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if (
                "error" in key_text
                or key_text in {"status", "code", "reason", "failure"}
            ):
                fields.add("error_field")
            fields.update(_json_error_fields(child))
    elif isinstance(value, list):
        for child in value:
            fields.update(_json_error_fields(child))
    return fields


def safe_error_summary(body, status_code):
    """Summarise error signals without logging messages or response values."""
    text = body[:256 * 1024].decode("utf-8", errors="replace")
    lowered = text.lower()
    labels = set()

    # Google batchexecute responses may have an XSSI prefix or be nested JSON.
    candidate = text.lstrip()
    candidate = re.sub(r"^(?:\)]}'|\)\]\}'|while\s*\(1\);)\s*", "", candidate)
    try:
        labels.update(_json_error_fields(json.loads(candidate)))
    except (ValueError, TypeError):
        pass

    for label, pattern in _ERROR_PATTERNS:
        if re.search(pattern, lowered):
            labels.add(label)

    try:
        is_http_error = status_code is not None and int(status_code) >= 400
    except (TypeError, ValueError):
        is_http_error = False
    if is_http_error:
        labels.add("http_error")
    return ",".join(sorted(labels)) if labels else "none"


def _strip_xssi_prefix(text):
    candidate = text.lstrip("\ufeff \r\n")
    candidate = re.sub(r"^(?:\)]}'|\)\]\}'|while\s*\(1\);)\s*", "", candidate)
    return candidate


def _decode_json_candidate(value):
    """Decode only JSON-shaped strings; never return them in diagnostics."""
    if not isinstance(value, str):
        return None
    candidate = _strip_xssi_prefix(value)
    if not candidate.startswith(("[", "{")):
        return None
    try:
        return json.loads(candidate)
    except (ValueError, TypeError):
        return None


def _decode_batchexecute_body(text):
    """Decode one JSON document or complete JSON lines from a batch body."""
    candidate = _strip_xssi_prefix(text)
    try:
        return "batchexecute_json", json.loads(candidate)
    except (ValueError, TypeError):
        pass

    # Some proxy captures preserve batch records as separate JSON lines.
    # Accept only complete JSON lines; never attempt delimiter guessing.
    records = []
    for line in candidate.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except (ValueError, TypeError):
            return "unknown", None
    if records:
        return "batchexecute_json_lines", records
    return "unknown", None


def _safe_rpc(value):
    value = value if isinstance(value, str) else ""
    return value if _SAFE_RPC_RE.fullmatch(value) else None


def _rpc_records(value):
    """Yield recognised Google batch records without retaining payload values."""
    if isinstance(value, list):
        if (
            len(value) >= 2
            and value[0] == _BATCH_RPC_MARKER
            and _safe_rpc(value[1])
        ):
            yield value
        for child in value:
            yield from _rpc_records(child)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _rpc_records(child)


def _requested_rpcs(query):
    requested = []
    for value in parse_qs(query or "", keep_blank_values=True).get("rpcids", []):
        for candidate in re.split(r"[,\s]+", value):
            rpc = _safe_rpc(candidate)
            if rpc and rpc not in requested:
                requested.append(rpc)
    return requested[:8]


def _structural_error_state(value):
    """Return present, absent, or unknown based on error-shaped JSON keys."""
    if isinstance(value, dict):
        uncertain = False
        for key, child in value.items():
            normalised = str(key).lower().replace("-", "_")
            if normalised in _STRUCTURAL_ERROR_KEYS:
                if child not in (None, "", [], {}):
                    return "present"
                uncertain = True
            state = _structural_error_state(child)
            if state == "present":
                return state
            if state == "unknown":
                uncertain = True
        return "unknown" if uncertain else "absent"
    if isinstance(value, list):
        uncertain = False
        for child in value:
            state = _structural_error_state(child)
            if state == "present":
                return state
            if state == "unknown":
                uncertain = True
        return "unknown" if uncertain else "absent"
    if isinstance(value, str):
        nested = _decode_json_candidate(value)
        return _structural_error_state(nested) if nested is not None else "absent"
    return "absent"


def _record_result_state(record):
    if len(record) < 3:
        return "unknown"
    result = record[2]
    if result in (None, "", [], {}):
        return "absent"
    return "present"


def _record_error_state(record):
    """Return an error state only when the record has enough structure."""
    if len(record) < 3:
        return "unknown"
    return _structural_error_state(record)


def _policy_token(value):
    """Normalise a bounded policy token without returning its source value."""
    if not isinstance(value, str) or len(value) > 96:
        return None
    token = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()
    return token or None


def _policy_category(value):
    """Classify explicit version/security fields, never generic response text."""
    categories = set()

    def visit(node):
        if isinstance(node, str):
            nested = _decode_json_candidate(node)
            if nested is not None:
                visit(nested)
            return
        if isinstance(node, list):
            for child in node:
                visit(child)
            return
        if not isinstance(node, dict):
            return

        for key, child in node.items():
            normalised_key = str(key).lower().replace("-", "_")
            if normalised_key in _VERSION_POLICY_KEYS:
                if child is True or _policy_token(child) in _POLICY_TRUE_VALUES:
                    categories.add("version_restriction")
            elif normalised_key in _SECURITY_POLICY_KEYS:
                if child is True or _policy_token(child) in _POLICY_TRUE_VALUES:
                    categories.add("client_security_restriction")
            elif normalised_key in _POLICY_STATUS_KEYS:
                token = _policy_token(child)
                if token in _VERSION_POLICY_CODES:
                    categories.add("version_restriction")
                elif token in _SECURITY_POLICY_CODES:
                    categories.add("client_security_restriction")
            visit(child)

    visit(value)
    if "client_security_restriction" in categories:
        return "client_security_restriction"
    if "version_restriction" in categories:
        return "version_restriction"
    return "none"


def _batch_state(result_state, error_state, status_code):
    if status_code is not None:
        try:
            if int(status_code) >= 400:
                return "http_error"
        except (TypeError, ValueError):
            pass
    if error_state == "present":
        return "application_error"
    if error_state == "unknown" or result_state == "unknown":
        return "unknown"
    if result_state == "present":
        return "valid_result"
    return "no_result"


def _rpc_detail(record, status_code):
    """Return only safe structural facts for one recognised RPC record."""
    rpc_id = _safe_rpc(record[1]) if len(record) > 1 else None
    result_state = _record_result_state(record)
    error_state = _record_error_state(record)
    policy_category = (
        "unknown"
        if result_state == "unknown" or error_state == "unknown"
        else _policy_category(record)
    )
    return {
        "rpc_id": rpc_id or "unknown",
        "has_result": result_state,
        "has_error": error_state,
        "batch_state": _batch_state(result_state, error_state, status_code),
        "policy_category": policy_category,
    }


def summarize_batchexecute(body, query="", status_code=None):
    """Classify a batch response using structure only, never payload values."""
    requested = _requested_rpcs(query)
    if isinstance(body, str):
        text = body[:256 * 1024]
    else:
        text = bytes(body or b"")[:256 * 1024].decode("utf-8", errors="replace")
    format_name, parsed = _decode_batchexecute_body(text)
    summary = {
        "format": "unknown",
        "rpc": "unknown",
        "requested_rpc": requested[0] if len(requested) == 1 else "unknown",
        "rpc_match": "unknown",
        "result": "unknown",
        "error": "unknown",
        "category": "unknown",
        "rpc_details": [],
        "policy_category": "unknown",
    }
    if parsed is None:
        return summary

    records = list(_rpc_records(parsed))
    if not records:
        summary["format"] = "json_unrecognized"
        return summary
    summary["format"] = format_name
    detected = []
    for record in records:
        rpc = _safe_rpc(record[1])
        if rpc and rpc not in detected:
            detected.append(rpc)
    summary["rpc"] = ",".join(detected[:4]) if detected else "unknown"

    summary["rpc_details"] = [
        _rpc_detail(record, status_code) for record in records
    ]

    if requested:
        selected = [record for record in records if record[1] in requested]
        summary["rpc_match"] = "yes" if selected else "no"
    elif len(records) == 1:
        selected = records
    else:
        selected = []

    if len(selected) != 1:
        return summary

    record = selected[0]
    summary["result"] = _record_result_state(record)
    summary["error"] = _record_error_state(record)
    summary["category"] = _batch_state(
        summary["result"], summary["error"], status_code
    )
    summary["policy_category"] = _policy_category(record)
    return summary


def _batch_summary_text(summary):
    details = "|".join(
        "rpc_id={rpc_id},has_result={has_result},has_error={has_error},"
        "batch_state={batch_state},policy_category={policy_category}".format(**item)
        for item in summary.get("rpc_details", [])
    ) or "none"
    return (
        f"batch_format={summary['format']} "
        f"batch_rpc={summary['rpc']} "
        f"batch_requested_rpc={summary['requested_rpc']} "
        f"batch_rpc_match={summary['rpc_match']} "
        f"batch_result={summary['result']} "
        f"batch_error={summary['error']} "
        f"batch_state={summary['category']} "
        f"batch_policy_category={summary['policy_category']} "
        f"batch_rpc_details={details}"
    )


def log_response(flow):
    """Emit a bounded, credential-free diagnostic line for a sign-in response."""
    request = getattr(flow, "request", None)
    response = getattr(flow, "response", None)
    parsed = urlparse(getattr(request, "url", ""))
    path = parsed.path.lower()
    headers = getattr(response, "headers", {})
    content_type = headers.get("Content-Type", "")
    status_code = getattr(response, "status_code", None)
    body = response_body(response)
    ua = user_agent_summary(getattr(request, "headers", {}).get("User-Agent", ""))
    params = request_parameter_summary(request)
    initial_html_policy = initial_html_policy_summary(body, content_type)
    batch_summary = None
    if path == _BATCH_EXECUTE_PATH:
        batch_summary = summarize_batchexecute(body, parsed.query, status_code)
    batch_text = f" {_batch_summary_text(batch_summary)}" if batch_summary else ""
    print(
        "[GMAIL-DIAG] "
        f"path={path} method={getattr(request, 'method', 'UNKNOWN')} "
        f"http={status_code if status_code is not None else 'unknown'} "
        f"content_type={_safe_content_type(content_type)} size={len(body)} "
        f"ua_platform={ua['platform']} ua_ios={ua['ios_version']} "
        f"target={ua['target']} ua_webkit={ua['webkit']} "
        f"gmail_app={ua['gmail']} app_errors={safe_error_summary(body, status_code)} "
        f"param_names={params['names']} param_presence={params['presence']} "
        f"param_categories={params['categories']} "
        f"initial_html_policy={initial_html_policy}"
        f"{batch_text}"
    )


def log_identifier_compatibility(flow, compat_exception, document_eligible=False):
    """Explain why the identifier HTML did or did not enter compatibility code."""
    request = getattr(flow, "request", None)
    response = getattr(flow, "response", None)
    body = response_body(response)
    ua = user_agent_summary(getattr(request, "headers", {}).get("User-Agent", ""))
    markers = {
        marker
        for marker in (
            "fetch",
            "object-entries",
            "object-values",
            "object-from-entries",
            "url-search-params",
        )
        if f"legacy-proxy-polyfill-{marker}" in body.decode("utf-8", errors="ignore")
    }
    if compat_exception:
        reason = "domain_exception"
    elif document_eligible:
        reason = "document_eligible"
    else:
        reason = "request_or_response_not_document"
    print(
        "[GMAIL-DIAG] identifier_compat="
        f"{reason} target={ua['target']} ua_ios={ua['ios_version']} "
        f"polyfills_present={','.join(sorted(markers)) if markers else 'none'}"
    )
