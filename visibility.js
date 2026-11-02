(() => {
  // Experimental compatibility shim, not a guarantee of server-side status.
  const host = location.hostname;
  if (!(host === 'mts-link.ru' || host.endsWith('.mts-link.ru') || host === 'webinar.ru' || host.endsWith('.webinar.ru'))) return;
  for (const [key, value] of Object.entries({hidden:false, visibilityState:'visible', webkitHidden:false, webkitVisibilityState:'visible'})) {
    try { Object.defineProperty(document, key, {configurable:true, get:()=>value}); } catch {}
  }
  try { Object.defineProperty(document, 'hasFocus', {configurable:true, value:()=>true}); } catch {}
  // Preserve the application's initial focused=true state when Chrome loses focus.
  for (const type of ['blur', 'visibilitychange', 'webkitvisibilitychange']) {
    window.addEventListener(type, event => {
      if (event.target === window || event.target === document) event.stopImmediatePropagation();
    }, true);
  }
})();
