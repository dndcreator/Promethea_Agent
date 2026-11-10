"""Fixed DOM projection; never execute model-supplied JavaScript here."""


async def snapshot(page, *, query="", max_nodes=120, include_state=False):
    return await page.evaluate("""({query, max_nodes, include_state}) => {
      const q = query.trim().toLowerCase();
      const path = el => {
        if (el.id) return '#' + CSS.escape(el.id);
        const parts = [];
        for (let cur = el; cur?.nodeType === 1; cur = cur.parentElement) {
          let part = cur.tagName.toLowerCase();
          const siblings = cur.parentElement ? [...cur.parentElement.children].filter(n => n.tagName === cur.tagName) : [];
          if (siblings.length > 1) part += ':nth-of-type(' + (siblings.indexOf(cur) + 1) + ')';
          parts.unshift(part);
        }
        return parts.join(' > ');
      };
      const nodes = [];
      for (const el of document.querySelectorAll('a,button,input,textarea,select,[role="button"],[onclick],[tabindex]')) {
        const isField = ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
        const label = el.getAttribute('aria-label') || el.labels?.[0]?.innerText || el.getAttribute('placeholder') || '';
        const text = String(isField || (include_state && label) ? label : el.innerText || label).trim();
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0 || (q && !text.toLowerCase().includes(q))) continue;
        nodes.push({tag: el.tagName.toLowerCase(), text: text.slice(0, 220), selector: path(el),
          role: el.getAttribute('role') || '', input_type: el.getAttribute('type') || '', name: el.getAttribute('name') || '',
          required: Boolean(el.required), disabled: Boolean(el.disabled), filled: isField && Boolean(el.value),
          ...(include_state && typeof el.checked === 'boolean' ? {checked: el.checked} : {}),
          ...(include_state && el.hasAttribute('aria-pressed') ? {pressed: el.getAttribute('aria-pressed')} : {}),
          href: el.getAttribute('href') || '', x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2),
          width: Math.round(r.width), height: Math.round(r.height)});
        if (nodes.length >= max_nodes) break;
      }
      const frames = [...document.querySelectorAll('iframe,frame')].slice(0, 32).map(el => {
        const r = el.getBoundingClientRect();
        return {selector: path(el), title: String(el.title || '').slice(0, 220), name: String(el.name || '').slice(0, 220),
          src: String(el.getAttribute('src') || '').slice(0, 2048), visible: r.width > 0 && r.height > 0,
          width: Math.round(r.width), height: Math.round(r.height)};
      });
      return {nodes, frames, frame_count: document.querySelectorAll('iframe,frame').length,
        ...(include_state ? {text: (document.body?.innerText || '').slice(0, 4000)} : {})};
    }""", {"query": str(query), "max_nodes": min(200, max(1, int(max_nodes))), "include_state": include_state})
