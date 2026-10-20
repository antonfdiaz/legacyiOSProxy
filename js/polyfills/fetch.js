(function (root) {
  "use strict";

  function ensurePerformance(rootObject) {
    var performance = rootObject.performance;
    var origin;
    if (!performance) {
      performance = {};
      rootObject.performance = performance;
    }
    if (typeof performance.now !== "function") {
      origin = new Date().getTime();
      performance.now = function () {
        return new Date().getTime() - origin;
      };
    }
  }

  ensurePerformance(root);

  function isThenable(value) {
    return value && typeof value.then === "function";
  }

  function deferred() {
    var state = "pending";
    var value;
    var handlers = [];
    var promise = {};

    function settle(nextState, nextValue) {
      var pending;
      if (state !== "pending") {
        return;
      }
      state = nextState;
      value = nextValue;
      pending = handlers;
      handlers = [];
      for (var i = 0; i < pending.length; i += 1) {
        handle(pending[i]);
      }
    }

    function handle(handler) {
      var callback = state === "fulfilled" ? handler.onFulfilled : handler.onRejected;
      var next = handler.next;
      if (!callback) {
        if (state === "fulfilled") {
          next.resolve(value);
        } else {
          next.reject(value);
        }
        return;
      }
      try {
        next.resolve(callback(value));
      } catch (error) {
        next.reject(error);
      }
    }

    promise.then = function (onFulfilled, onRejected) {
      var next = deferred();
      var handler = {
        onFulfilled: typeof onFulfilled === "function" ? onFulfilled : null,
        onRejected: typeof onRejected === "function" ? onRejected : null,
        next: next
      };
      if (state === "pending") {
        handlers.push(handler);
      } else {
        handle(handler);
      }
      return next.promise;
    };
    promise.catch = function (onRejected) {
      return promise.then(null, onRejected);
    };

    var result = {
      promise: promise,
      resolve: function (nextValue) {
        if (nextValue === promise) {
          result.reject(new TypeError("A promise cannot resolve itself"));
          return;
        }
        if (isThenable(nextValue)) {
          try {
            nextValue.then(result.resolve, result.reject);
          } catch (error) {
            result.reject(error);
          }
          return;
        }
        settle("fulfilled", nextValue);
      },
      reject: function (error) {
        settle("rejected", error);
      }
    };
    return result;
  }

  function makePromise(executor) {
    if (typeof root.Promise === "function") {
      return new root.Promise(executor);
    }
    var result = deferred();
    try {
      executor(result.resolve, result.reject);
    } catch (error) {
      result.reject(error);
    }
    return result.promise;
  }

  function resolved(value) {
    return makePromise(function (resolve) {
      resolve(value);
    });
  }

  function normalizeHeaderName(name) {
    var result = String(name);
    if (/[^!#$%&'*+.^_\x60|~0-9A-Za-z-]/.test(result)) {
      throw new TypeError("Invalid character in header field name");
    }
    return result.toLowerCase();
  }

  function normalizeHeaderValue(value) {
    return String(value);
  }

  function pairIterator(pairs) {
    var index = 0;
    return {
      next: function () {
        if (index >= pairs.length) {
          return {value: undefined, done: true};
        }
        return {value: pairs[index++], done: false};
      }
    };
  }

  function Headers(init) {
    this._headers = {};
    if (!init) {
      return;
    }
    if (init instanceof Headers || (init.forEach && typeof init.forEach === "function")) {
      init.forEach(function (value, name) {
        this.append(name, value);
      }, this);
      return;
    }
    if (typeof init.length === "number" && typeof init !== "string") {
      for (var i = 0; i < init.length; i += 1) {
        this.append(init[i][0], init[i][1]);
      }
      return;
    }
    for (var name in init) {
      if (Object.prototype.hasOwnProperty.call(init, name)) {
        this.append(name, init[name]);
      }
    }
  }

  Headers.prototype.append = function (name, value) {
    var key = normalizeHeaderName(name);
    var normalized = normalizeHeaderValue(value);
    this._headers[key] = this.has(name) ? this._headers[key] + ", " + normalized : normalized;
  };

  Headers.prototype.delete = function (name) {
    delete this._headers[normalizeHeaderName(name)];
  };

  Headers.prototype.get = function (name) {
    var key = normalizeHeaderName(name);
    return this.has(name) ? this._headers[key] : null;
  };

  Headers.prototype.has = function (name) {
    return Object.prototype.hasOwnProperty.call(
      this._headers,
      normalizeHeaderName(name)
    );
  };

  Headers.prototype.set = function (name, value) {
    this._headers[normalizeHeaderName(name)] = normalizeHeaderValue(value);
  };

  Headers.prototype.forEach = function (callback, thisArg) {
    for (var name in this._headers) {
      if (Object.prototype.hasOwnProperty.call(this._headers, name)) {
        callback.call(thisArg, this._headers[name], name, this);
      }
    }
  };

  Headers.prototype.entries = function () {
    var pairs = [];
    this.forEach(function (value, name) {
      pairs.push([name, value]);
    });
    return pairIterator(pairs);
  };

  Headers.prototype.keys = function () {
    var iterator = this.entries();
    return {
      next: function () {
        var item = iterator.next();
        return {
          value: item.done ? undefined : item.value[0],
          done: item.done
        };
      }
    };
  };

  Headers.prototype.values = function () {
    var iterator = this.entries();
    return {
      next: function () {
        var item = iterator.next();
        return {
          value: item.done ? undefined : item.value[1],
          done: item.done
        };
      }
    };
  };

  function AbortSignal() {
    this.aborted = false;
    this.onabort = null;
    this._listeners = [];
  }

  AbortSignal.prototype.addEventListener = function (type, listener) {
    if (type !== "abort" || typeof listener !== "function") {
      return;
    }
    if (this._listeners.indexOf(listener) === -1) {
      this._listeners.push(listener);
    }
  };

  AbortSignal.prototype.removeEventListener = function (type, listener) {
    var index;
    if (type !== "abort") {
      return;
    }
    index = this._listeners.indexOf(listener);
    if (index !== -1) {
      this._listeners.splice(index, 1);
    }
  };

  AbortSignal.prototype._dispatchAbort = function () {
    var event = {type: "abort", target: this};
    var listeners = this._listeners.slice();
    var i;
    if (this.aborted) {
      return;
    }
    this.aborted = true;
    if (typeof this.onabort === "function") {
      try {
        this.onabort.call(this, event);
      } catch (ignore) {
        // Abort still propagates to the remaining listeners.
      }
    }
    for (i = 0; i < listeners.length; i += 1) {
      try {
        listeners[i].call(this, event);
      } catch (ignore) {
        // Match DOM event dispatch: one listener must not block the others.
      }
    }
  };

  function AbortController() {
    this.signal = new AbortSignal();
  }

  AbortController.prototype.abort = function () {
    this.signal._dispatchAbort();
  };

  function copyHeaders(headers) {
    return new Headers(headers);
  }

  function Request(input, options) {
    var source = input instanceof Request ? input : null;
    var init = options || {};
    this.url = source ? source.url : String(input);
    this.method = String(init.method || (source && source.method) || "GET").toUpperCase();
    this.headers = init.headers ? new Headers(init.headers) : copyHeaders(source ? source.headers : null);
    this._body = init.body !== undefined ? init.body : (source ? source._body : null);
    this.body = this._body;
    this.mode = init.mode || (source && source.mode) || "cors";
    this.credentials = init.credentials || (source && source.credentials) || "same-origin";
    this.cache = init.cache || (source && source.cache) || "default";
    this.redirect = init.redirect || (source && source.redirect) || "follow";
    this.signal = init.signal || (source && source.signal) || null;
  }

  Request.prototype.clone = function () {
    return new Request(this);
  };

  function parseResponseHeaders(xhr) {
    var headers = new Headers();
    var raw = "";
    if (xhr.getAllResponseHeaders) {
      raw = xhr.getAllResponseHeaders() || "";
    }
    var lines = raw.split(/\r?\n/);
    for (var i = 0; i < lines.length; i += 1) {
      var separator = lines[i].indexOf(":");
      if (separator > 0) {
        headers.append(
          lines[i].slice(0, separator),
          lines[i].slice(separator + 1).replace(/^\s+|\s+$/g, "")
        );
      }
    }
    return headers;
  }

  function Response(body, options) {
    var init = options || {};
    this.type = "default";
    this.status = init.status === undefined ? 200 : init.status;
    this.statusText = init.statusText || "";
    this.headers = new Headers(init.headers);
    this.url = init.url || "";
    this.ok = this.status >= 200 && this.status < 300;
    this._body = body === undefined || body === null ? "" : body;
    this.bodyUsed = false;
  }

  Response.prototype.text = function () {
    this.bodyUsed = true;
    return resolved(String(this._body));
  };

  Response.prototype.json = function () {
    return this.text().then(function (text) {
      return JSON.parse(text);
    });
  };

  Response.prototype.clone = function () {
    return new Response(this._body, {
      status: this.status,
      statusText: this.statusText,
      headers: this.headers,
      url: this.url
    });
  };

  Response.error = function () {
    return new Response(null, {status: 0, statusText: ""});
  };

  function abortError() {
    var error = new Error("The operation was aborted");
    error.name = "AbortError";
    error.code = 20;
    return error;
  }

  function fetch(input, init) {
    var request = new Request(input, init);
    return makePromise(function (resolve, reject) {
      var xhr = new root.XMLHttpRequest();
      var finished = false;

      function removeAbortListener() {
        if (request.signal && request.signal.removeEventListener) {
          request.signal.removeEventListener("abort", abortRequest);
        }
      }

      function resolveResponse() {
        var status;
        if (finished || xhr.readyState !== 4) {
          return;
        }
        finished = true;
        removeAbortListener();
        status = xhr.status === 1223 ? 204 : xhr.status;
        resolve(new Response(xhr.responseText, {
          status: status,
          statusText: xhr.statusText || "",
          headers: parseResponseHeaders(xhr),
          url: xhr.responseURL || request.url
        }));
      }

      function rejectRequest(error) {
        if (finished) {
          return;
        }
        finished = true;
        removeAbortListener();
        reject(error);
      }

      function abortRequest() {
        if (finished) {
          return;
        }
        finished = true;
        removeAbortListener();
        try {
          xhr.abort();
        } catch (ignore) {
          // The fetch promise still rejects with the standard abort error.
        }
        reject(abortError());
      }

      if (request.signal && request.signal.aborted) {
        reject(abortError());
        return;
      }

      try {
        xhr.open(request.method, request.url, true);
        if (request.credentials === "include") {
          xhr.withCredentials = true;
        }
        request.headers.forEach(function (value, name) {
          xhr.setRequestHeader(name, value);
        });
        xhr.onreadystatechange = resolveResponse;
        xhr.onload = resolveResponse;
        xhr.onerror = function () {
          rejectRequest(new Error("Network request failed"));
        };
        xhr.ontimeout = xhr.onerror;
        xhr.onabort = xhr.onerror;
        if (request.signal && request.signal.addEventListener) {
          request.signal.addEventListener("abort", abortRequest);
        }
        if (request.signal && request.signal.aborted) {
          abortRequest();
          return;
        }
        xhr.send(request._body);
      } catch (error) {
        rejectRequest(error);
      }
    });
  }

  if (!root.Headers) {
    root.Headers = Headers;
  }
  if (!root.Request) {
    root.Request = Request;
  }
  if (!root.Response) {
    root.Response = Response;
  }
  if (!root.AbortSignal) {
    root.AbortSignal = AbortSignal;
  }
  if (!root.AbortController) {
    root.AbortController = AbortController;
  }
  if (!root.fetch) {
    root.fetch = fetch;
  }
}(window));
