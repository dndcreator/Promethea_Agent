// The child has no host token, tool executor, or access to the parent DOM.
(() => {
  let port;
  let sequence = 0;
  const pending = new Map();
  const ready = new Promise((resolve) => {
    window.addEventListener('message', (event) => {
      if (port || event.source !== parent || event.data?.type !== 'promethea:connect' || !event.ports[0]) return;
      port = event.ports[0];
      port.onmessage = ({ data }) => {
        const request = pending.get(data?.id);
        if (!request) return;
        pending.delete(data.id);
        clearTimeout(request.timer);
        if (data.error) request.reject(new Error(data.error));
        else request.resolve(data.result);
      };
      port.start();
      resolve();
    });
  });
  async function call(method, params = {}) {
    await Promise.race([ready, new Promise((_, reject) => setTimeout(() => reject(new Error('Canvas host unavailable')), 10000))]);
    if (pending.size >= 32) throw new Error('Too many canvas requests');
    return new Promise((resolve, reject) => {
      const id = String(++sequence);
      const timer = setTimeout(() => { pending.delete(id); reject(new Error('Canvas request timed out')); }, 10000);
      pending.set(id, { resolve, reject, timer });
      port.postMessage({ id, method, params });
    });
  }
  Object.defineProperty(window, 'promethea', { value: Object.freeze({
    getState: () => call('state.get'),
    setState: (value, expectedRevision) => call('state.set', { value, expected_revision: expectedRevision }),
  }) });
  window.addEventListener('error', (event) => {
    void call('diagnostic.report', { message: String(event.message).slice(0, 2000) }).catch(() => {});
  });
  window.addEventListener('unhandledrejection', (event) => {
    void call('diagnostic.report', { message: String(event.reason).slice(0, 2000) }).catch(() => {});
  });
})();
