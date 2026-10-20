import subprocess
import unittest
from pathlib import Path


POLYFILL_PATH = (
    Path(__file__).resolve().parents[1]
    / "js"
    / "polyfills"
    / "url-search-params.js"
)


NODE_TEST = r'''
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const sandbox = {decodeURIComponent: decodeURIComponent, encodeURIComponent: encodeURIComponent};
sandbox.window = sandbox;
vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), sandbox);

const params = new sandbox.URLSearchParams("a=1&a=2&b=three");
const entries = params.entries();
let entry = entries.next().value;
assert.strictEqual(entry[0], "a");
assert.strictEqual(entry[1], "1");
entry = entries.next().value;
assert.strictEqual(entry[0], "a");
assert.strictEqual(entry[1], "2");
entry = entries.next().value;
assert.strictEqual(entry[0], "b");
assert.strictEqual(entry[1], "three");
assert.strictEqual(entries.next().done, true);
assert.strictEqual(params.keys().next().value, "a");
assert.strictEqual(params.values().next().value, "1");

let seen = [];
params.forEach(function (value, key) { seen.push(key + "=" + value); });
assert.deepStrictEqual(seen, ["a=1", "a=2", "b=three"]);
process.stdout.write("url-search-params-entries-ok\n");
'''


class URLSearchParamsPolyfillExecutionTests(unittest.TestCase):
    def test_entries_and_iteration_apis_execute(self):
        result = subprocess.run(
            ["node", "-e", NODE_TEST, str(POLYFILL_PATH)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("url-search-params-entries-ok", result.stdout)

    def test_url_search_params_polyfill_uses_es5_syntax(self):
        source = POLYFILL_PATH.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"\b(?:let|const)\b|=>")


if __name__ == "__main__":
    unittest.main()
