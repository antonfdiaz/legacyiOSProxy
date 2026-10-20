(function (root) {
  if (root.URLSearchParams) {
    return;
  }

  function decode(value) {
    return decodeURIComponent(value.replace(/\+/g, " "));
  }

  function encode(value) {
    return encodeURIComponent(value).replace(/%20/g, "+");
  }

  function URLSearchParams(init) {
    this._pairs = [];
    if (typeof init === "string") {
      this._parse(init.replace(/^\?/, ""));
    } else if (init && init._pairs) {
      for (var i = 0; i < init._pairs.length; i += 1) {
        this.append(init._pairs[i][0], init._pairs[i][1]);
      }
    } else if (init && typeof init.length === "number") {
      for (var j = 0; j < init.length; j += 1) {
        this.append(init[j][0], init[j][1]);
      }
    } else if (init) {
      for (var key in init) {
        if (Object.prototype.hasOwnProperty.call(init, key)) {
          this.append(key, init[key]);
        }
      }
    }
  }

  URLSearchParams.prototype._parse = function (query) {
    if (!query) {
      return;
    }
    var parts = query.split("&");
    for (var i = 0; i < parts.length; i += 1) {
      var separator = parts[i].indexOf("=");
      if (separator < 0) {
        this.append(decode(parts[i]), "");
      } else {
        this.append(
          decode(parts[i].slice(0, separator)),
          decode(parts[i].slice(separator + 1))
        );
      }
    }
  };

  URLSearchParams.prototype.append = function (name, value) {
    this._pairs.push([String(name), String(value)]);
  };

  URLSearchParams.prototype.delete = function (name) {
    var pairs = [];
    for (var i = 0; i < this._pairs.length; i += 1) {
      if (this._pairs[i][0] !== String(name)) {
        pairs.push(this._pairs[i]);
      }
    }
    this._pairs = pairs;
  };

  URLSearchParams.prototype.get = function (name) {
    var key = String(name);
    for (var i = 0; i < this._pairs.length; i += 1) {
      if (this._pairs[i][0] === key) {
        return this._pairs[i][1];
      }
    }
    return null;
  };

  URLSearchParams.prototype.getAll = function (name) {
    var key = String(name);
    var values = [];
    for (var i = 0; i < this._pairs.length; i += 1) {
      if (this._pairs[i][0] === key) {
        values.push(this._pairs[i][1]);
      }
    }
    return values;
  };

  URLSearchParams.prototype.has = function (name) {
    return this.get(name) !== null;
  };

  URLSearchParams.prototype.set = function (name, value) {
    this.delete(name);
    this.append(name, value);
  };

  URLSearchParams.prototype.toString = function () {
    var values = [];
    for (var i = 0; i < this._pairs.length; i += 1) {
      values.push(encode(this._pairs[i][0]) + "=" + encode(this._pairs[i][1]));
    }
    return values.join("&");
  };

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

  URLSearchParams.prototype.entries = function () {
    return pairIterator(this._pairs.slice());
  };

  URLSearchParams.prototype.keys = function () {
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

  URLSearchParams.prototype.values = function () {
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

  URLSearchParams.prototype.forEach = function (callback, thisArg) {
    for (var i = 0; i < this._pairs.length; i += 1) {
      callback.call(thisArg, this._pairs[i][1], this._pairs[i][0], this);
    }
  };

  root.URLSearchParams = URLSearchParams;
}(window));
