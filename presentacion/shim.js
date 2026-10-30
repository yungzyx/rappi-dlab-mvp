/* Se inyecta al inicio del MVP y del panel (build.mjs cambia __NS__ por "mvp:" o "panel:"). No cambia nada visible:
   1) guarda localStorage y sessionStorage con un prefijo propio, para que la app y el panel (mismo origen que la página
      de la presentación) no compartan lo guardado y la presentación pueda borrarlo al volver a cargar uno; también
      length, key() y Object.keys(), porque la app recorre sus claves al cambiar de persona o al "Olvidar";
   2) le da a la app un historial en memoria: en un iframe el historial del navegador es uno solo con la página, y el
      "atrás" de la app movería la presentación. */
(function () {
  var NS = "__NS__";
  var S = Storage.prototype;
  var get = S.getItem, set = S.setItem, del = S.removeItem, key = S.key;
  var count = Object.getOwnPropertyDescriptor(S, "length").get;
  var own = function (store) {
    var out = [];
    for (var i = 0, n = count.call(store); i < n; i++) {
      var k = key.call(store, i);
      if (k && k.indexOf(NS) === 0) out.push(k.slice(NS.length));
    }
    return out;
  };
  S.getItem = function (k) { return get.call(this, NS + k); };
  S.setItem = function (k, v) { return set.call(this, NS + k, v); };
  S.removeItem = function (k) { return del.call(this, NS + k); };
  S.key = function (i) { var k = own(this)[i]; return k === undefined ? null : k; };
  S.clear = function () { var self = this; own(this).forEach(function (k) { del.call(self, NS + k); }); };
  Object.defineProperty(S, "length", { configurable: true, enumerable: true, get: function () { return own(this).length; } });
  var keys = Object.keys;
  Object.keys = function (o) { return o instanceof Storage ? own(o) : keys(o); };

  var H = window.history;
  var realReplace = H.replaceState.bind(H);
  var clone = function (s) {
    try { return s == null ? null : structuredClone(s); } catch (e) { return s; }
  };
  var entries = [{ state: null, hash: location.hash }];
  var index = 0;
  var syncUrl = function (hash) {
    try { realReplace(null, "", hash || "#"); } catch (e) { /* srcdoc sin URL: no importa */ }
  };
  var hashOf = function (url) {
    if (url == null) return entries[index].hash;
    var s = String(url), i = s.indexOf("#");
    return i < 0 ? "" : s.slice(i);
  };
  Object.defineProperty(H, "state", { configurable: true, get: function () { return entries[index].state; } });
  Object.defineProperty(H, "length", { configurable: true, get: function () { return entries.length; } });
  H.pushState = function (state, _t, url) {
    entries = entries.slice(0, index + 1);
    entries.push({ state: clone(state), hash: hashOf(url) });
    index++;
    syncUrl(entries[index].hash);
  };
  H.replaceState = function (state, _t, url) {
    entries[index] = { state: clone(state), hash: hashOf(url) };
    syncUrl(entries[index].hash);
  };
  H.go = function (n) {
    var to = index + (n | 0);
    if (!n || to < 0 || to >= entries.length) return;
    setTimeout(function () {
      index = to;
      syncUrl(entries[index].hash);
      window.dispatchEvent(new PopStateEvent("popstate", { state: entries[index].state }));
    }, 0);
  };
  H.back = function () { H.go(-1); };
  H.forward = function () { H.go(1); };
})();
