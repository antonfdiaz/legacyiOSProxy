import json
import unittest
from types import SimpleNamespace
from urllib.parse import quote_plus
from unittest.mock import patch
import src.compat as compat
from src.compat.css import adapt_css
from src.compat.html import adapt_html
from src.compat.js import adapt_js, analyze_js
from src.compat.runtime import required_polyfills
from src.compat import js as js_module
from src.compat.target import LegacyTarget, detect_target, unsupported_js_features
from src.diagnostics.google_signin import (
    is_google_signin_response,
    initial_html_policy_summary,
    log_response,
    request_parameter_summary,
    safe_error_summary,
    summarize_batchexecute,
    user_agent_summary,
)
from main import InterceptAddon


class CompatibilityTests(unittest.TestCase):
    def test_public_adapters_are_reexported(self):
        self.assertIs(compat.adapt_html, adapt_html)
        self.assertIs(compat.adapt_css, adapt_css)
        self.assertIs(compat.adapt_js, adapt_js)
        self.assertIs(compat.analyze_js, analyze_js)

    def test_adapt_html_preserves_current_transformations(self):
        html = (
            '<img loading="lazy" src="old.jpg" data-src="new.jpg" inert>'
            '<picture><source srcset="new.webp"><img src="fallback.jpg"></picture>'
        )
        self.assertEqual(
            adapt_html(html,target=LegacyTarget(13)),
            '<img src="new.jpg"><img src="fallback.jpg">',
        )

    def test_adapt_html_injects_fetch_polyfill_for_ios9(self):
        html = "<html><head><title>Page</title></head><body></body></html>"
        with patch("builtins.print") as output:
            adapted = adapt_html(html,target=LegacyTarget(9))
        marker = 'id="legacy-proxy-polyfill-fetch"'
        for feature in (
            "fetch", "object-entries", "object-values", "object-from-entries",
            "url-search-params",
        ):
            self.assertEqual(
                adapted.count(f'id="legacy-proxy-polyfill-{feature}"'),
                1,
            )
        self.assertLess(adapted.index(marker), adapted.index("</head>"))
        self.assertIn("XMLHttpRequest", adapted)
        self.assertIn("function AbortController", adapted)
        logs = [call.args[0] for call in output.call_args_list]
        self.assertEqual(
            logs,
            [
                "[COMPAT] injecting polyfill=fetch target=iOS 9",
                "[COMPAT] injecting polyfill=object-entries target=iOS 9",
                "[COMPAT] injecting polyfill=object-values target=iOS 9",
                "[COMPAT] injecting polyfill=object-from-entries target=iOS 9",
                "[COMPAT] injecting polyfill=url-search-params target=iOS 9",
            ],
        )

    def test_adapt_html_injects_fetch_polyfill_before_external_scripts(self):
        html = '<html><head><script src="/app.js"></script></head></html>'
        adapted = adapt_html(html,target=LegacyTarget(9))
        original_script = adapted.index('<script src="/app.js">')
        for feature in (
            "fetch", "object-entries", "object-values", "object-from-entries",
            "url-search-params",
        ):
            self.assertLess(
                adapted.index(f'id="legacy-proxy-polyfill-{feature}"'),
                original_script,
            )

    def test_adapt_html_copies_script_nonce_to_polyfills(self):
        html = (
            '<html><head><script nonce="nonce-value" src="/app.js"></script>'
            '</head></html>'
        )
        adapted = adapt_html(html,target=LegacyTarget(9))
        for feature in (
            "fetch", "object-entries", "object-values",
            "object-from-entries", "url-search-params",
        ):
            self.assertIn(
                f'id="legacy-proxy-polyfill-{feature}" nonce="nonce-value"',
                adapted,
            )
        self.assertIn('id="legacy-proxy-polyfill-fetch" nonce="nonce-value"', adapted)

    def test_adapt_html_injects_only_unsupported_polyfills_for_ios10(self):
        html = "<html><script>fetch('/data');</script></html>"
        adapted = adapt_html(html,target=LegacyTarget(10))
        self.assertNotIn("legacy-proxy-polyfill-fetch", adapted)
        self.assertNotIn("legacy-proxy-polyfill-object-entries", adapted)
        self.assertNotIn("legacy-proxy-polyfill-object-values", adapted)
        self.assertIn("legacy-proxy-polyfill-object-from-entries", adapted)
        self.assertNotIn("legacy-proxy-polyfill-url-search-params", adapted)

    def test_adapt_html_injects_without_inline_fetch(self):
        html = "<html><script>Promise.resolve('ready');</script></html>"
        self.assertIn(
            "legacy-proxy-polyfill-fetch",
            adapt_html(html,target=LegacyTarget(9)),
        )

    def test_adapt_html_does_not_duplicate_fetch_polyfill(self):
        html = "<html><script>fetch('/data');</script></html>"
        with patch("builtins.print") as output:
            adapted = adapt_html(html,target=LegacyTarget(9))
            repeated = adapt_html(adapted,target=LegacyTarget(9))
        self.assertEqual(repeated, adapted)
        for feature in (
            "fetch", "object-entries", "object-values", "object-from-entries",
            "url-search-params",
        ):
            self.assertEqual(repeated.count(f"legacy-proxy-polyfill-{feature}"), 1)
        self.assertEqual(output.call_count, 5)

    def test_adapt_css_preserves_current_transformations(self):
        css = ".card { display: flex; justify-content: start; transform: scale(1); }"
        self.assertEqual(
            adapt_css(css,target=LegacyTarget(8)),
            ".card { display: -webkit-flex; display: flex; "
            "-webkit-justify-content: flex-start; justify-content: flex-start; "
            "-webkit-transform: scale(1); transform: scale(1); }",
        )

    def test_required_fetch_polyfill(self):
        self.assertEqual(
            required_polyfills(LegacyTarget(9),{"fetch"}),
            {"fetch"},
        )
        self.assertEqual(
            required_polyfills(LegacyTarget(10),{"fetch"}),
            set(),
        )
        self.assertEqual(
            required_polyfills(LegacyTarget(9),{"promise"}),
            set(),
        )

    def test_required_polyfills_by_target(self):
        features = {
            "fetch", "object-entries", "object-values", "object-from-entries",
            "url-search-params",
        }
        self.assertEqual(required_polyfills(LegacyTarget(9),features), features)
        self.assertEqual(
            required_polyfills(LegacyTarget(10),features),
            {"object-from-entries"},
        )
        self.assertEqual(required_polyfills(LegacyTarget(13),features), set())
        self.assertEqual(
            required_polyfills(
                LegacyTarget(9),
                {"array-includes", "element-closest", "mutation-observer"},
            ),
            set(),
        )


class TargetDetectionTests(unittest.TestCase):
    def test_detects_ios_major_version(self):
        cases = {
            "Mozilla/5.0 (iPhone; CPU iPhone OS 8_4_1 like Mac OS X)": 8,
            "Mozilla/5.0 (iPhone; CPU iPhone OS 6_1 like Mac OS X)": 6,
            "Reddit/2.0.1 (iOS 9.3.5)": 9,
        }
        for user_agent, expected_major in cases.items():
            with self.subTest(user_agent=user_agent):
                self.assertEqual(
                    detect_target(user_agent),
                    LegacyTarget(expected_major),
                )

    def test_unknown_target(self):
        self.assertEqual(
            detect_target("Mozilla/5.0 (Macintosh; Intel Mac OS X)"),
            LegacyTarget(None),
        )
        self.assertEqual(detect_target(None), LegacyTarget(None))


class JavaScriptCompatibilityTests(unittest.TestCase):
    def setUp(self):
        js_module._JS_CACHE.clear()

    def test_analyze_js_detects_supported_features(self):
        source = (
            "let value = 1; const fn = item => `value=${item}`; "
            "class Example {}; async function load() { await Promise.resolve(); } "
            "value?.name ?? 'unknown'; fetch('/data'); Object.assign({}, value); "
            "Array.from(value);"
        )
        self.assertEqual(
            analyze_js(source),
            {
                "let", "const", "arrow-functions", "class", "template-literals",
                "async", "await", "optional-chaining", "nullish-coalescing",
                "promise", "fetch", "object-assign", "array-from",
            },
        )

    def test_analyze_js_detects_runtime_and_dom_features_without_duplicates(self):
        source = (
            "Symbol(); new Map(); new Set(); new WeakMap(); new WeakSet(); "
            "new URL('/'); new URLSearchParams(); Object.entries({}); "
            "Object.values({}); Object.fromEntries([]); "
            "items.includes(value); text.includes('x'); text.startsWith('x'); "
            "text.endsWith('x'); element.closest('.item'); element.matches('.item'); "
            "new CustomEvent('ready'); new IntersectionObserver(fn); "
            "new MutationObserver(fn); items.includes(value);"
        )
        self.assertEqual(
            analyze_js(source) & compat.RUNTIME_FEATURES,
            {
                "symbol", "map", "set", "weakmap", "weakset", "url",
                "url-search-params", "object-entries", "object-values",
                "object-from-entries", "array-includes", "string-includes",
                "string-starts-with", "string-ends-with", "element-closest",
                "element-matches", "custom-event", "intersection-observer",
                "mutation-observer",
            },
        )

    def test_adapt_js_is_passthrough(self):
        source = "Promise.resolve(Object.assign({}, Array.from([])));"
        self.assertEqual(adapt_js(source,target=LegacyTarget(9)), source)

    def test_adapt_js_transpiles_modern_syntax_for_ios9(self):
        source = "const add = (left, right) => left + right;"
        adapted = adapt_js(source,target=LegacyTarget(9))
        self.assertNotEqual(adapted, source)
        self.assertNotIn("const", adapted)
        self.assertNotIn("=>", adapted)
        self.assertNotIn("core-js", adapted)

    def test_adapt_js_target_none_is_unchanged(self):
        source = "const value = item => item?.value ?? null;"
        self.assertEqual(adapt_js(source), source)

    def test_adapt_js_failure_returns_original_source(self):
        source = "const value = item => item;"
        with patch("src.compat.js.subprocess.run", side_effect=OSError("node missing")):
            with patch("builtins.print") as output:
                adapted = adapt_js(source,target=LegacyTarget(9))
        self.assertEqual(adapted, source)
        self.assertIn(
            "[WARN] JS transpilation failed: node missing",
            output.call_args[0][0],
        )

    def test_js_cache_miss_runs_babel(self):
        source = "const value = item => item;"
        result = SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps({"code": "transpiled"}),
        )
        with patch("src.compat.js.subprocess.run", return_value=result) as run:
            self.assertEqual(adapt_js(source,target=LegacyTarget(9)), "transpiled")
        run.assert_called_once()

    def test_second_identical_call_uses_js_cache(self):
        source = "const value = item => item;"
        result = SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps({"code": source}),
        )
        with patch("src.compat.js.subprocess.run", return_value=result) as run:
            with patch("builtins.print") as output:
                self.assertEqual(adapt_js(source,target=LegacyTarget(9)), source)
                self.assertEqual(adapt_js(source,target=LegacyTarget(9)), source)
        run.assert_called_once()
        self.assertIn(
            "[COMPAT] JS cache hit target=iOS 9",
            output.call_args[0][0],
        )

    def test_same_source_with_different_targets_has_different_cache_entries(self):
        source = "const value = item => item;"
        result = SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps({"code": "transpiled"}),
        )
        with patch("src.compat.js.subprocess.run", return_value=result) as run:
            adapt_js(source,target=LegacyTarget(8))
            adapt_js(source,target=LegacyTarget(9))
        self.assertEqual(run.call_count, 2)

    def test_failed_babel_run_is_not_cached(self):
        source = "const value = item => item;"
        with patch(
            "src.compat.js.subprocess.run",
            side_effect=OSError("node missing"),
        ) as run:
            with patch("builtins.print"):
                self.assertEqual(adapt_js(source,target=LegacyTarget(9)), source)
                self.assertEqual(adapt_js(source,target=LegacyTarget(9)), source)
        self.assertEqual(run.call_count, 2)

    def test_unsupported_features_by_ios_major(self):
        features = {
            "let", "const", "arrow-functions", "class", "template-literals",
            "async", "await", "optional-chaining", "nullish-coalescing",
            "promise", "fetch", "object-assign", "array-from",
        }
        expected = {
            3: features,
            4: features,
            5: features,
            6: features,
            7: features,
            8: features - {"promise", "object-assign"},
            9: features - {"class", "template-literals", "promise", "object-assign", "array-from"},
        }
        for ios_major, unsupported in expected.items():
            with self.subTest(ios_major=ios_major):
                self.assertEqual(
                    unsupported_js_features(LegacyTarget(ios_major),features),
                    unsupported,
                )

    def test_unknown_features_and_non_ios_target_are_not_unsupported(self):
        self.assertEqual(
            unsupported_js_features(
                LegacyTarget(9),{"promise", "not-in-the-table"}),
            set(),
        )
        self.assertEqual(
            unsupported_js_features(LegacyTarget(None),{"async", "fetch"}),
            set(),
        )


class CompatibilityPipelineTests(unittest.TestCase):
    def test_main_passes_ios_target_and_logs_it(self):
        addon = InterceptAddon.__new__(InterceptAddon)
        addon.github = None
        addon.wikipedia = None
        addon.reddit = None
        addon.imdb = None
        flow = SimpleNamespace(
            request=SimpleNamespace(
                url="https://example.test/page",
                headers={
                    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 8_4_1 like Mac OS X)"
                },
            ),
            response=SimpleNamespace(
                headers={"Content-Type": "text/html; charset=utf-8"},
                text="<html></html>",
            ),
        )

        with patch("main.compat.adapt_html", return_value="adapted") as adapter:
            with patch("builtins.print") as output:
                addon.response(flow)

        adapter.assert_called_once_with(
            "<html></html>",target=LegacyTarget(8))
        self.assertEqual(flow.response.text, "adapted")
        log = "\n".join(call.args[0] for call in output.call_args_list)
        self.assertIn("[COMPAT] target=iOS 8", log)

    def test_main_analyzes_and_passes_javascript_target(self):
        addon = InterceptAddon.__new__(InterceptAddon)
        addon.github = None
        addon.wikipedia = None
        addon.reddit = None
        addon.imdb = None
        flow = SimpleNamespace(
            request=SimpleNamespace(
                url="https://example.test/script.js",
                headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 9_3 like Mac OS X)"},
            ),
            response=SimpleNamespace(
                headers={"Content-Type": "application/javascript; charset=utf-8"},
                text="const fn = item => fetch(item);",
                status_code=200,
            ),
        )

        with patch("main.compat.analyze_js", return_value={"arrow-functions", "const", "fetch"}) as analyze:
            with patch("main.compat.adapt_js", return_value="transpiled") as adapter:
                with patch("builtins.print") as output:
                    addon.response(flow)

        analyze.assert_called_once_with("const fn = item => fetch(item);")
        adapter.assert_called_once_with(
            "const fn = item => fetch(item);",target=LegacyTarget(9))
        self.assertEqual(flow.response.text, "transpiled")
        compat_logs = [
            call.args[0] for call in output.call_args_list
            if call.args and call.args[0].startswith("[COMPAT]")
        ]
        self.assertEqual(
            compat_logs,
            [
                "[COMPAT] runtime JS=fetch",
                "[COMPAT] unsupported JS=arrow-functions,const,fetch target=iOS 9",
                "[COMPAT] transpiled JS target=iOS 9",
            ],
        )

    def test_main_skips_javascript_for_excluded_hosts(self):
        addon = InterceptAddon.__new__(InterceptAddon)
        addon.github = None
        addon.wikipedia = None
        addon.reddit = None
        addon.imdb = None
        flow = SimpleNamespace(
            request=SimpleNamespace(
                url="https://token.awswaf.com/script.js",
                headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 9_3 like Mac OS X)"},
            ),
            response=SimpleNamespace(
                headers={"Content-Type": "text/javascript"},
                text="const value = 1;",
            ),
        )

        with patch("main.compat.analyze_js") as analyze:
            with patch("main.compat.adapt_js") as adapter:
                addon.response(flow)

        analyze.assert_not_called()
        adapter.assert_not_called()

    def test_main_logs_runtime_features_not_in_support_matrix(self):
        addon = InterceptAddon.__new__(InterceptAddon)
        addon.github = None
        addon.wikipedia = None
        addon.reddit = None
        addon.imdb = None
        flow = SimpleNamespace(
            request=SimpleNamespace(
                url="https://example.test/script.js",
                headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 9_3 like Mac OS X)"},
            ),
            response=SimpleNamespace(
                headers={"Content-Type": "application/javascript"},
                text="new Map(); new IntersectionObserver(fn);",
                status_code=200,
            ),
        )

        with patch(
            "main.compat.analyze_js",
                return_value={"map", "intersection-observer"},
        ) as analyze:
            with patch("main.compat.adapt_js", return_value=flow.response.text):
                with patch("builtins.print") as output:
                    addon.response(flow)

            analyze.assert_called_once_with("new Map(); new IntersectionObserver(fn);")
        compat_logs = [
            call.args[0] for call in output.call_args_list
            if call.args and call.args[0].startswith("[COMPAT]")
        ]
        self.assertEqual(
            compat_logs,
            ["[COMPAT] runtime JS=intersection-observer,map"],
        )

    def test_main_does_not_analyze_empty_or_no_content_javascript(self):
        addon = InterceptAddon.__new__(InterceptAddon)
        addon.github = None
        addon.wikipedia = None
        addon.reddit = None
        addon.imdb = None
        for status_code, text in ((204,"const value = 1;"),(304,"const value = 1;"),(200,"")):
            flow = SimpleNamespace(
                request=SimpleNamespace(
                    url="https://example.test/script.js",
                    headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 9_3 like Mac OS X)"},
                ),
                response=SimpleNamespace(
                    headers={"Content-Type": "application/javascript"},
                    text=text,
                    status_code=status_code,
                ),
            )
            with patch("main.compat.analyze_js") as analyze:
                with patch("main.compat.adapt_js") as adapter:
                    addon.response(flow)
            analyze.assert_not_called()
            adapter.assert_not_called()


class RequestCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_clears_cache_headers_for_script_paths(self):
        addon = InterceptAddon.__new__(InterceptAddon)
        addon.google = None
        addon.imdb = None
        addon.reddit = None
        addon.wikipedia = None
        addon.google_earth = None
        for path in ("/style.css", "/page.html", "/page.htm", "/script.js", "/module.mjs"):
            flow = SimpleNamespace(
                request=SimpleNamespace(
                    url=f"https://example.test{path}?v=1",
                    headers={"If-None-Match": "etag", "If-Modified-Since": "yesterday"},
                ),
            )
            await addon.request(flow)
            with self.subTest(path=path):
                self.assertNotIn("If-None-Match", flow.request.headers)
                self.assertNotIn("If-Modified-Since", flow.request.headers)


class GoogleSignInDiagnosticsTests(unittest.TestCase):
    def _flow(self,path="/v3/signin/identifier",method="GET",status_code=200,
              content_type="text/html; charset=utf-8"):
        return SimpleNamespace(
            request=SimpleNamespace(
                url=f"https://accounts.google.com{path}",
                method=method,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 8_4_1 like Mac OS X) "
                        "AppleWebKit/600.1.4 Mobile/12H321 Gmail/5.0.180122"
                    )
                },
            ),
            response=SimpleNamespace(
                headers={"Content-Type": content_type},
                status_code=status_code,
                text="<html><head></head><body></body></html>",
            ),
        )

    def _addon(self):
        addon = InterceptAddon.__new__(InterceptAddon)
        addon.github = None
        addon.wikipedia = None
        addon.reddit = None
        addon.imdb = None
        return addon

    def test_google_search_hosts_keep_their_compatibility_exception(self):
        addon = self._addon()
        self.assertTrue(addon.is_compat_exception("google.com"))
        self.assertTrue(addon.is_compat_exception("www.google.com"))
        self.assertFalse(addon.is_compat_exception("accounts.google.com"))

    def test_gmail_webview_user_agent_identifies_full_ios_version(self):
        summary = user_agent_summary(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 8_4_1 like Mac OS X) "
            "AppleWebKit/600.1.4 (KHTML, like Gecko) Mobile/12H321 "
            "Gmail/5.0.180122"
        )
        self.assertEqual(summary["ios_version"], "8.4.1")
        self.assertEqual(summary["target"], "iOS 8")
        self.assertEqual(summary["webkit"], "600.1.4")
        self.assertEqual(summary["gmail"], "5.0.180122")

    def test_request_parameter_summary_exposes_names_not_values(self):
        request = SimpleNamespace(
            url=(
                "https://accounts.google.com/v3/signin/identifier"
                "?rpcids=MI613e&client_id=placeholder-client-value"
            ),
            content=(
                "app_version=5.0.180122&lib_ver=3.3&system_version=8.4.1"
                "&email=person%40example.com"
            ).encode("utf-8"),
        )
        summary = request_parameter_summary(request)
        self.assertEqual(
            summary["names"],
            "app_version,client_id,lib_ver,rpcids,system_version",
        )
        self.assertIn("app_version=present", summary["presence"])
        self.assertIn("lib_ver=present", summary["presence"])
        self.assertIn("system_version=present", summary["presence"])
        self.assertEqual(
            summary["categories"], "native_app,oauth_client,signin_sdk,web_ui"
        )
        self.assertNotIn("5.0.180122", str(summary))
        self.assertNotIn("placeholder-client-value", str(summary))
        self.assertNotIn("placeholder-account", str(summary))

    def test_request_parameter_summary_finds_allowlisted_nested_f_req_names(self):
        nested = quote_plus(
            '[{"app_version":"5.0.180122","lib_ver":"3.3",'
            '"system_version":"8.4.1"}]'
        )
        request = SimpleNamespace(
            url="https://accounts.google.com/v3/signin/identifier",
            content=(f"f.req={nested}&token=placeholder-auth-value").encode("utf-8"),
        )
        summary = request_parameter_summary(request)
        self.assertEqual(
            summary["names"], "app_version,f.req,lib_ver,system_version"
        )
        self.assertNotIn("placeholder-auth-value", str(summary))

    def test_initial_html_policy_summary_only_accepts_structured_markers(self):
        marked = (
            '<html><script type="application/json">'
            '{"update_required":true}</script></html>'
        )
        generic = "<html><body>Please update your app</body></html>"
        self.assertEqual(
            initial_html_policy_summary(marked, "text/html"), "version_marker"
        )
        self.assertEqual(
            initial_html_policy_summary(generic, "text/html"), "none"
        )
        self.assertEqual(
            initial_html_policy_summary("{}", "application/json"), "not_document"
        )

    def test_signin_endpoint_matching_uses_path_without_query_values(self):
        flow = SimpleNamespace(
            request=SimpleNamespace(
                url="https://accounts.google.com/v3/signin/identifier?continue=placeholder",
            ),
        )
        self.assertTrue(is_google_signin_response(flow))

    def test_safe_error_summary_does_not_include_response_values(self):
        body = (
            b'{"error":"invalid_grant","email":"placeholder-account",'
            b'"token":"placeholder-auth-value"}'
        )
        summary = safe_error_summary(body, 400)
        self.assertIn("auth_rejected", summary)
        self.assertIn("http_error", summary)
        self.assertNotIn("placeholder-account", summary)
        self.assertNotIn("placeholder-auth-value", summary)

    def test_batchexecute_summary_classifies_xssi_result_without_payload(self):
        body = (
            b')]}\'\n[[["wrb.fr","MI613e",'
            b'"{\\"next\\":\\"identifier\\"}",null]]]'
        )
        summary = summarize_batchexecute(body, "rpcids=MI613e", 200)
        self.assertEqual(summary["format"], "batchexecute_json")
        self.assertEqual(summary["rpc"], "MI613e")
        self.assertEqual(summary["rpc_match"], "yes")
        self.assertEqual(summary["result"], "present")
        self.assertEqual(summary["error"], "absent")
        self.assertEqual(summary["category"], "valid_result")

    def test_batchexecute_summary_classifies_application_error(self):
        body = (
            b')]}\'\n[[["wrb.fr","MI613e",'
            b'"{\\"error\\":{\\"code\\":\\"APP_ERROR\\"}}",null]]]'
        )
        summary = summarize_batchexecute(body, "rpcids=MI613e", 200)
        self.assertEqual(summary["result"], "present")
        self.assertEqual(summary["error"], "present")
        self.assertEqual(summary["category"], "application_error")

    def test_batchexecute_summary_uses_unknown_for_unrecognised_or_malformed_data(self):
        unrecognised = summarize_batchexecute(b'{"safe":true}', "rpcids=MI613e", 200)
        malformed = summarize_batchexecute(b"not-json", "rpcids=MI613e", 200)
        self.assertEqual(unrecognised["format"], "json_unrecognized")
        self.assertEqual(unrecognised["category"], "unknown")
        self.assertEqual(malformed["format"], "unknown")
        self.assertEqual(malformed["category"], "unknown")

    def test_batchexecute_summary_accepts_complete_json_lines(self):
        body = (
            b')]}\'\n'
            b'[["wrb.fr","OTHER","{\\"ok\\":true}"]]\n'
            b'[["wrb.fr","MI613e","{\\"ok\\":true}"]]\n'
        )
        summary = summarize_batchexecute(body, "rpcids=MI613e", 200)
        self.assertEqual(summary["format"], "batchexecute_json_lines")
        self.assertEqual(summary["rpc"], "OTHER,MI613e")
        self.assertEqual(summary["category"], "valid_result")

    def test_batchexecute_summary_classifies_each_rpc_independently(self):
        body = (
            b')]}\'\n'
            b'[[["wrb.fr","Aho3hb","{\\"ok\\":true}",null],'
            b'["wrb.fr","rmzYpe","{\\"error\\":{\\"code\\":'
            b'\\"CLIENT_VERSION_TOO_OLD\\"}}",null],'
            b'["wrb.fr","MALFORMED"]]]'
        )
        summary = summarize_batchexecute(
            body, "rpcids=Aho3hb,rmzYpe", 200
        )

        details = {item["rpc_id"]: item for item in summary["rpc_details"]}
        self.assertEqual(details["Aho3hb"]["has_result"], "present")
        self.assertEqual(details["Aho3hb"]["has_error"], "absent")
        self.assertEqual(details["Aho3hb"]["batch_state"], "valid_result")
        self.assertEqual(details["Aho3hb"]["policy_category"], "none")
        self.assertEqual(details["rmzYpe"]["has_result"], "present")
        self.assertEqual(details["rmzYpe"]["has_error"], "present")
        self.assertEqual(details["rmzYpe"]["batch_state"], "application_error")
        self.assertEqual(
            details["rmzYpe"]["policy_category"], "version_restriction"
        )
        self.assertEqual(details["MALFORMED"]["has_result"], "unknown")
        self.assertEqual(details["MALFORMED"]["has_error"], "unknown")
        self.assertEqual(details["MALFORMED"]["batch_state"], "unknown")
        self.assertEqual(details["MALFORMED"]["policy_category"], "unknown")

    def test_batchexecute_policy_category_requires_structured_signal(self):
        update_required = summarize_batchexecute(
            b'[[["wrb.fr","rmzYpe","{\\"update_required\\":true}",null]]]',
            "rpcids=rmzYpe",
            200,
        )
        generic_text = summarize_batchexecute(
            b'[[["wrb.fr","rmzYpe","{\\"message\\":'
            b'\\"please update your app\\"}",null]]]',
            "rpcids=rmzYpe",
            200,
        )
        self.assertEqual(
            update_required["policy_category"], "version_restriction"
        )
        self.assertEqual(generic_text["policy_category"], "none")

    def test_batchexecute_log_includes_safe_multi_rpc_details(self):
        flow = self._flow(
            path=(
                "/v3/signin/_/AccountsSignInUi/data/batchexecute"
                "?rpcids=Aho3hb,rmzYpe"
            ),
            method="POST",
            content_type="application/json",
        )
        flow.response.text = (
            ')]}\'\n[[["wrb.fr","Aho3hb","{\\"ok\\":true}",null],'
            '["wrb.fr","rmzYpe","{\\"error\\":{\\"code\\":'
            '\\"CLIENT_VERSION_TOO_OLD\\"}}",null]]]'
        )
        with patch("builtins.print") as output:
            log_response(flow)
        log = output.call_args[0][0]
        self.assertIn(
            "rpc_id=Aho3hb,has_result=present,has_error=absent,"
            "batch_state=valid_result,policy_category=none",
            log,
        )
        self.assertIn(
            "rpc_id=rmzYpe,has_result=present,has_error=present,"
            "batch_state=application_error,policy_category=version_restriction",
            log,
        )
        self.assertNotIn("CLIENT_VERSION_TOO_OLD", log)

    def test_log_response_reports_parameter_presence_without_values(self):
        flow = self._flow(
            path=(
                "/v3/signin/identifier?app_version=5.0.180122"
                "&lib_ver=3.3&system_version=8.4.1"
            ),
            content_type="text/html; charset=utf-8",
        )
        flow.request.content = b"client_id=placeholder-client-value&email=placeholder-account"
        flow.response.text = (
            '<html><script type="application/json">'
            '{"update_required":true}</script></html>'
        )
        with patch("builtins.print") as output:
            log_response(flow)
        log = output.call_args[0][0]
        self.assertIn(
            "param_names=app_version,client_id,lib_ver,system_version",
            log,
        )
        self.assertIn("param_categories=native_app,oauth_client,signin_sdk", log)
        self.assertIn("initial_html_policy=version_marker", log)
        self.assertNotIn("app_version=5.0.180122", log)
        self.assertNotIn("placeholder-client-value", log)
        self.assertNotIn("placeholder-account", log)

    def test_batchexecute_log_contains_only_structural_summary(self):
        flow = self._flow(
            path="/v3/signin/_/AccountsSignInUi/data/batchexecute?rpcids=MI613e",
            method="POST",
            content_type="application/json",
        )
        account_marker = "placeholder-account"
        flow.response.text = (
            ')]}\'\n[[["wrb.fr","MI613e",'
            '"{\\"next\\":\\"identifier\\",\\"email\\":\\"'
            + account_marker
            + '\\"}",null]]]'
        )
        with patch("builtins.print") as output:
            log_response(flow)
        log = output.call_args[0][0]
        self.assertIn("batch_format=batchexecute_json", log)
        self.assertIn("batch_rpc=MI613e", log)
        self.assertIn("batch_result=present", log)
        self.assertIn("batch_error=absent", log)
        self.assertIn("batch_state=valid_result", log)
        self.assertNotIn(account_marker, log)

    def test_babel_preserves_rpc_response_processing(self):
        source = (
            'const processRpc = (response) => response.json().then((data) => '
            'data[0]); const rpc = "MI613e";'
        )
        adapted = adapt_js(source, target=LegacyTarget(8))
        self.assertNotIn("=>", adapted)
        self.assertIn("response.json()", adapted)
        self.assertIn(".then", adapted)
        self.assertIn('"MI613e"', adapted)

    def test_identifier_document_enters_compatibility_path(self):
        addon = self._addon()
        flow = self._flow()
        original = flow.response.text

        with patch("main.compat.adapt_html", return_value="adapted") as adapter:
            with patch("builtins.print") as output:
                addon.response(flow)

        adapter.assert_called_once_with(original,target=LegacyTarget(8))
        self.assertEqual(flow.response.text,"adapted")
        logs = "\n".join(call.args[0] for call in output.call_args_list)
        self.assertIn("[GMAIL-DIAG]", logs)
        self.assertIn("target=iOS 8", logs)
        self.assertIn("ua_ios=8.4.1", logs)
        self.assertIn("identifier_compat=document_eligible", logs)

    def test_identifier_document_reuses_existing_ios8_polyfills(self):
        addon = self._addon()
        flow = self._flow()
        with patch("builtins.print"):
            addon.response(flow)

        for feature in (
            "fetch",
            "object-entries",
            "object-values",
            "object-from-entries",
            "url-search-params",
        ):
            self.assertEqual(
                flow.response.text.count(f"legacy-proxy-polyfill-{feature}"),
                1,
            )

    def test_accounts_api_post_and_redirect_are_not_adapted(self):
        addon = self._addon()
        cases = (
            ("/v3/signin/_/AccountsSignInUi/data/batchexecute", "POST", 200),
            ("/v3/signin/identifier", "POST", 200),
            ("/v3/signin/identifier", "GET", 302),
            ("/oauth2/v4/token", "GET", 200),
        )
        for path, method, status_code in cases:
            flow = self._flow(path=path,method=method,status_code=status_code)
            original = flow.response.text
            with self.subTest(path=path,method=method,status_code=status_code):
                with patch("main.compat.adapt_html") as adapter:
                    addon.response(flow)
                adapter.assert_not_called()
                self.assertEqual(flow.response.text,original)

    def test_accounts_non_html_response_is_not_adapted(self):
        addon = self._addon()
        flow = self._flow(content_type="application/json")
        with patch("main.compat.adapt_html") as adapter:
            addon.response(flow)
        adapter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
