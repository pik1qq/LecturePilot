// Installed on the managed lecture PAGE, never on the browser context.
// Handles HTML media and Web Audio; not an operating-system or browser-wide mute.
(() => {
  if (typeof globalThis.__lecturePilotSetMuted === 'function') return;
  let muted = true;
  const tracked = new Set();
  const previous = new WeakMap();
  const gains = new Set();
  const byContext = new WeakMap();
  function applyMedia(element) {
    if (!(element instanceof HTMLMediaElement)) return;
    tracked.add(element);
    if (muted) {
      if (!previous.has(element)) previous.set(element, element.muted);
      if (!element.muted) element.muted = true;
    } else if (previous.has(element)) {
      const value = previous.get(element);
      previous.delete(element);
      element.muted = value;
    }
  }
  function scan(root = document) {
    if (root instanceof HTMLMediaElement) applyMedia(root);
    if (root.querySelectorAll) for (const element of root.querySelectorAll('audio,video')) applyMedia(element);
  }
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function (...args) {
    applyMedia(this);
    return Reflect.apply(play, this, args);
  };
  document.addEventListener('volumechange', event => {
    if (muted && event.target instanceof HTMLMediaElement) applyMedia(event.target);
  }, true);
  new MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes) scan(node);
  }).observe(document, {childList:true, subtree:true});
  if (globalThis.AudioNode) {
    const connect = AudioNode.prototype.connect;
    const disconnect = AudioNode.prototype.disconnect;
    function outputGain(context) {
      let gain = byContext.get(context);
      if (!gain) {
        gain = context.createGain();
        gain.gain.value = muted ? 0 : 1;
        byContext.set(context, gain);
        gains.add(gain);
        Reflect.apply(connect, gain, [context.destination]);
      }
      return gain;
    }
    AudioNode.prototype.connect = function(destination, ...args) {
      if (destination === this.context.destination) {
        Reflect.apply(connect, this, [outputGain(this.context), ...args]);
        return destination;
      }
      return Reflect.apply(connect, this, [destination, ...args]);
    };
    AudioNode.prototype.disconnect = function (...args) {
      if (args[0] === this.context.destination && byContext.has(this.context)) args[0] = byContext.get(this.context);
      return Reflect.apply(disconnect, this, args);
    };
  }
  Object.defineProperty(globalThis, '__lecturePilotSetMuted', {value(value) {
    muted = Boolean(value);
    for (const gain of gains) gain.gain.value = muted ? 0 : 1;
    scan();
    for (const element of tracked) applyMedia(element);
    return muted;
  }});
  scan();
  // A small watchdog covers detached media and nodes created inside components.
  setInterval(() => {
    scan();
    for (const element of tracked) {
      if (element.isConnected || !element.paused) applyMedia(element);
      else if (element.paused) tracked.delete(element);
    }
  }, 500);
})();
