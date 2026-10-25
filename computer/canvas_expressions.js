// Runtime-owned presentation; all model content is text, never executable markup.
function installCanvasExpressions(bridge) {
  const mounted = new Map();
  let definitions = new Set();
  const style = document.createElement('style');
  style.textContent = `.promethea-expression{box-sizing:border-box;max-width:100%;margin:10px 0;padding:10px 12px;border:1px solid #cbd2cf;border-left:3px solid #617c70;border-radius:5px;background:#fff;color:#26332d;font:13px/1.6 system-ui,sans-serif;overflow-wrap:anywhere;letter-spacing:0}.promethea-expression p{margin:0;white-space:pre-wrap}.promethea-expression header{display:flex;align-items:start;gap:8px}.promethea-expression header p{flex:1;min-width:0}.promethea-expression button{font:inherit;min-height:30px;padding:3px 9px;border:1px solid #cbd2cf;border-radius:4px;background:#fff;color:inherit;cursor:pointer}.promethea-expression button:disabled{opacity:.6;cursor:default}.promethea-expression .choices{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.promethea-expression [role=alert]{color:#9d2b2b;margin-top:6px}`;
  document.head.append(style);
  const element = (tag, text) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    return node;
  };
  bridge.subscribe(({ semantics, expressions, labels }) => {
    definitions = new Set((semantics?.components || []).map(node => node.component_id));
    const live = new Set();
    for (const item of expressions || []) {
      const anchor = item.canvas_anchor;
      const target = anchor && definitions.has(anchor.component_id) && document.getElementById(anchor.component_id);
      if (!target || target.closest('.promethea-expression') || item.hidden || item.state === 'dismissed') continue;
      live.add(item.expression_id);
      const previous = mounted.get(item.expression_id);
      if (previous?.revision === item.revision && previous.node.isConnected) continue;
      previous?.node.remove();
      const card = element('section');
      card.className = 'promethea-expression';
      card.dataset.expressionId = item.expression_id;
      card.dataset.componentId = anchor.component_id;
      const header = element('header');
      const body = element('div');
      body.style.cssText = 'flex:1;min-width:0';
      if (item.title) body.append(element('strong', item.title));
      body.append(element('p', item.content));
      const close = element('button', '\u00d7');
      close.type = 'button';
      close.setAttribute('aria-label', labels?.dismiss || 'Dismiss');
      header.append(body, close);card.append(header);
      const error = element('p');error.setAttribute('role', 'alert');
      const buttons = [close];
      const submit = async (choice) => {
        for (const button of buttons) button.disabled = true;
        error.textContent = '';
        try {
          await bridge.call('semantic.feedback', { expression_id: item.expression_id, command: {
            expected_revision: item.revision, action: choice === undefined ? 'dismiss' : 'respond', choice_id: choice ?? null,
          } });
        } catch {
          error.textContent = labels?.retry || 'Could not save. Please retry.';
          for (const button of buttons) button.disabled = item.state !== 'open' && button !== close;
        }
      };
      close.onclick = () => void submit();
      if (item.kind === 'choice') {
        const choices = element('div');choices.className = 'choices';
        for (const choice of item.choices || []) {
          const button = element('button', choice.label);button.type = 'button';
          button.disabled = item.state !== 'open';
          button.setAttribute('aria-pressed', String(item.response === choice.id));
          button.onclick = () => void submit(choice.id);
          buttons.push(button);choices.append(button);
        }
        card.append(choices);
      }
      card.append(error);
      const placement = target.matches('input,select,textarea') ? target.closest('label') || target : target;
      placement.insertAdjacentElement('afterend', card);
      mounted.set(item.expression_id, { node: card, revision: item.revision });
    }
    for (const [id, value] of mounted) if (!live.has(id)) { value.node.remove();mounted.delete(id); }
  });
  let timer;
  let last;
  const attention = (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const card = target?.closest('.promethea-expression');
    let node = card ? document.getElementById(card.dataset.componentId) : target;
    while (node && !definitions.has(node.id)) node = node.parentElement;
    const id = node?.id || null;
    if (last === id) return;
    last = id;clearTimeout(timer);
    timer = setTimeout(() => { void bridge.call('attention.report', { component_id: id }).catch(() => {}); }, 120);
  };
  document.addEventListener('pointerdown', attention, true);
  document.addEventListener('focusin', attention, true);
}
