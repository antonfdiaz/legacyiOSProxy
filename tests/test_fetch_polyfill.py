import subprocess
import unittest
from pathlib import Path

from src.compat.js import adapt_js
from src.compat.target import LegacyTarget


ROOT = Path(__file__).resolve().parents[1]
POLYFILL_PATH = ROOT / "js" / "polyfills" / "fetch.js"
URL_SEARCH_PARAMS_PATH = ROOT / "js" / "polyfills" / "url-search-params.js"


NODE_TEST = r'''
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

function FakeXHR() {
  this.readyState = 0;
  this.status = 0;
  this.statusText = "";
  this.responseText = "";
  this.headers = {};
  this.abortCalled = false;
  FakeXHR.last = this;
}
FakeXHR.prototype.open = function (method, url, async) {
  this.method = method;
  this.url = url;
  this.async = async;
};
FakeXHR.prototype.setRequestHeader = function (name, value) {
  this.headers[name] = value;
};
FakeXHR.prototype.getAllResponseHeaders = function () {
  return "Content-Type: application/json\r\nX-Test: response\r\n";
};
FakeXHR.prototype.send = function (body) {
  this.body = body;
  this.status = 201;
  this.statusText = "Created";
  this.responseText = '{"ok":true}';
  if (FakeXHR.complete === false) {
    this.body = body;
    return;
  }
  this.readyState = 4;
  if (this.onreadystatechange) {
    this.onreadystatechange();
  }
};
FakeXHR.prototype.abort = function () {
  this.abortCalled = true;
  this.readyState = 0;
  if (this.onabort) {
    this.onabort();
  }
};

function run(withPromise) {
  const sandbox = {
    Error: Error,
    JSON: JSON,
    Promise: withPromise ? Promise : undefined,
    XMLHttpRequest: FakeXHR
  };
  sandbox.window = sandbox;
  vm.runInNewContext(
    fs.readFileSync(process.argv[1], "utf8"),
    sandbox,
    {filename: process.argv[1]}
  );

  assert.strictEqual(typeof sandbox.fetch, "function");
  assert.strictEqual(typeof sandbox.Headers, "function");
  assert.strictEqual(typeof sandbox.Request, "function");
  assert.strictEqual(typeof sandbox.Response, "function");
  assert.strictEqual(typeof sandbox.AbortController, "function");
  assert.strictEqual(typeof sandbox.AbortSignal, "function");
  assert.strictEqual(typeof sandbox.performance.now, "function");

  const headers = new sandbox.Headers({"X-Example": "one"});
  headers.append("X-Example", "two");
  assert.strictEqual(headers.get("x-example"), "one, two");
  assert.strictEqual(headers.has("X-EXAMPLE"), true);
  var headerEntries = headers.entries();
  var headerEntry = headerEntries.next().value;
  assert.strictEqual(headerEntry[0], "x-example");
  assert.strictEqual(headerEntry[1], "one, two");
  assert.strictEqual(headerEntries.next().done, true);

  const request = new sandbox.Request("/signin", {
    method: "post",
    headers: headers,
    body: "payload"
  });
  assert.strictEqual(request.method, "POST");
  assert.strictEqual(request.headers.get("X-Example"), "one, two");
  assert.strictEqual(request.body, "payload");

  var requestController = new sandbox.AbortController();
  var signalledRequest = new sandbox.Request("/signin", {
    signal: requestController.signal
  });
  assert.strictEqual(signalledRequest.signal, requestController.signal);

  const response = new sandbox.Response('{"manual":true}', {
    status: 202,
    headers: {"X-Manual": "yes"}
  });
  assert.strictEqual(response.ok, true);
  assert.strictEqual(response.headers.get("x-manual"), "yes");

  return response.json().then(function (manual) {
    assert.strictEqual(manual.manual, true);
    return sandbox.fetch("/signin", {
      method: "POST",
      headers: headers,
      body: "payload"
    });
  }).then(function (fetched) {
    assert.strictEqual(fetched.status, 201);
    assert.strictEqual(fetched.headers.get("content-type"), "application/json");
    assert.strictEqual(FakeXHR.last.method, "POST");
    assert.strictEqual(FakeXHR.last.headers["x-example"], "one, two");
    assert.strictEqual(FakeXHR.last.body, "payload");
    return fetched.json();
  }).then(function (data) {
    assert.strictEqual(data.ok, true);
  });
}

function runAbort(withPromise) {
  const sandbox = {
    Error: Error,
    JSON: JSON,
    Promise: withPromise ? Promise : undefined,
    XMLHttpRequest: FakeXHR
  };
  sandbox.window = sandbox;
  FakeXHR.complete = false;
  vm.runInNewContext(
    fs.readFileSync(process.argv[1], "utf8"),
    sandbox,
    {filename: process.argv[1]}
  );

  var controller = new sandbox.AbortController();
  var listenerCalls = 0;
  var removedCalls = 0;
  var signal = controller.signal;
  function listener(event) {
    assert.strictEqual(event.type, "abort");
    assert.strictEqual(event.target, signal);
    listenerCalls += 1;
  }
  function removedListener() {
    removedCalls += 1;
  }
  signal.onabort = function (event) {
    assert.strictEqual(event.type, "abort");
    listenerCalls += 1;
  };
  signal.addEventListener("abort", listener);
  signal.addEventListener("abort", removedListener);
  signal.removeEventListener("abort", removedListener);

  var pending = sandbox.fetch("/signin", {signal: signal});
  controller.abort();
  assert.strictEqual(signal.aborted, true);
  assert.strictEqual(listenerCalls, 2);
  assert.strictEqual(removedCalls, 0);
  assert.strictEqual(FakeXHR.last.abortCalled, true);
  controller.abort();
  assert.strictEqual(listenerCalls, 2);

  return pending.then(function () {
    throw new Error("aborted fetch unexpectedly fulfilled");
  }, function (error) {
    assert.strictEqual(error.name, "AbortError");
    assert.strictEqual(error.code, 20);
  });
}

run(true).then(function () {
  return run(false);
}).then(function () {
  return runAbort(true);
}).then(function () {
  return runAbort(false);
}).then(function () {
  process.stdout.write("fetch-polyfill-ok\n");
}, function (error) {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
'''


class FetchPolyfillExecutionTests(unittest.TestCase):
    def test_fetch_headers_request_and_response_execute_in_es5_runtime(self):
        result = subprocess.run(
            ["node", "-e", NODE_TEST, str(POLYFILL_PATH)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fetch-polyfill-ok", result.stdout)

    def test_fetch_polyfill_source_uses_es5_syntax(self):
        source = POLYFILL_PATH.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"\b(?:let|const)\b|=>")

    def test_fetch_polyfill_defines_abort_controller_and_signal(self):
        source = POLYFILL_PATH.read_text(encoding="utf-8")
        self.assertIn("root.AbortController", source)
        self.assertIn("root.AbortSignal", source)
        self.assertIn("signal.aborted", source)
        self.assertIn('"AbortError"', source)

    def test_fetch_polyfill_preserves_native_performance_now(self):
        source = POLYFILL_PATH.read_text(encoding="utf-8")
        script = """
var sandbox = {performance: {now: function () { return 123; }}};
sandbox.window = sandbox;
vm.runInNewContext(source, sandbox);
assert.strictEqual(sandbox.performance.now(), 123);
"""
        result = subprocess.run(
            ["node", "-e", """const assert=require('assert'); const fs=require('fs'); const vm=require('vm'); const source=fs.readFileSync(process.argv[1], 'utf8');""" + script, str(POLYFILL_PATH)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fetch_polyfill_is_not_changed_by_babel_for_ios8(self):
        source = POLYFILL_PATH.read_text(encoding="utf-8")
        self.assertEqual(adapt_js(source, target=LegacyTarget(8)), source)


if __name__ == "__main__":
    unittest.main()
