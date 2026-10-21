// Trusted renderer for canvas.ui.v1. Descriptions are data, never JavaScript/HTML.
(() => {
  const doc = JSON.parse(document.getElementById('canvas_document').textContent);
  const root = document.getElementById('canvas_root');
  const status = document.getElementById('canvas_status');
  const bindings = [];
  const controls = [];
  const selects = [];
  let state;
  let busy = false;
  let loaded = false;
  let blocked = false;
  const mutations = [];
  const style = document.createElement('style');
  style.textContent = `
    *{box-sizing:border-box}body{margin:0;background:#fafafa;color:#202525;font:15px/1.5 system-ui,sans-serif;letter-spacing:0}
    main{max-width:960px;margin:0 auto;padding:28px;min-width:0}.stack{display:flex;gap:16px;min-width:0}.column{flex-direction:column}.row{flex-wrap:wrap;align-items:end}
    .stack>*{min-width:0}.row>label{flex:1 1 180px}p,h1{margin:0;overflow-wrap:anywhere}h1{font-size:24px;line-height:1.3}.caption{font-size:13px;color:#626c6b}
    label{display:flex;flex-direction:column;gap:6px;font-size:14px}.checkbox{flex-direction:row;align-items:center;gap:10px}
    input,select,button{font:inherit;min-height:40px;border:1px solid #cbd2cf;border-radius:5px;padding:8px 10px;max-width:100%}
    input,select{width:100%;background:#fff;color:inherit}input[type=checkbox]{width:18px;min-height:18px;accent-color:#26765c}
    button{background:#26765c;border-color:#26765c;color:#fff;cursor:pointer;white-space:normal;overflow-wrap:anywhere}.secondary{background:#fff;color:#26332d;border-color:#cbd2cf}
    button:disabled,input:disabled,select:disabled{opacity:.6;cursor:default}:focus-visible{outline:2px solid #b26023;outline-offset:2px}
    .table-scroll{overflow:auto;max-width:100%}table{border-collapse:collapse;min-width:100%;font-size:14px}td,th{text-align:start;border-bottom:1px solid #dce2df;padding:10px;max-width:320px;overflow-wrap:anywhere}
    #canvas_status{max-width:960px;margin:0 auto;padding:0 28px 20px;color:#9d2b2b;font-size:13px;overflow-wrap:anywhere}
    @media(max-width:480px){main{padding:18px}.row>button{flex:1 1 120px}#canvas_status{padding:0 18px 18px}}
  `;
  document.head.append(style);
  const el = (tag, text) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = String(text);
    return node;
  };
  const sameType = (value, initial) => typeof value === typeof initial && (typeof value !== 'number' || Number.isFinite(value));
  function validate(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid saved state');
    for (const [key, initial] of Object.entries(doc.initial_state)) {
      if (!sameType(value[key], initial)) throw new Error(`Invalid state: ${key}`);
    }
    for (const node of selects) {
      if (!node.options.some(option => option.value === value[node.bind])) throw new Error(`Invalid selection: ${node.bind}`);
    }
  }
  function refresh() {
    for (const update of bindings) update(state.value);
    for (const control of controls) control.disabled = !loaded || blocked;
  }
  async function commit(update, field = null) {
    if (!loaded || blocked) return;
    const last = mutations[mutations.length - 1];
    if (field && last?.field === field) {last.update = update;return;}
    if (mutations.length >= 32) {status.textContent = 'Too many pending changes';return;}
    mutations.push({update, field});
    if (busy) return;
    busy = true;
    status.textContent = '';
    try {
      while (mutations.length && !blocked) {
        let saving = false;
        try {
          const value = {...state.value};
          mutations.shift().update(value);
          validate(value);
          if (JSON.stringify(value) === JSON.stringify(state.value)) continue;
          saving = true;
          const saved = await window.promethea.setState(value, state.revision);
          validate(saved.value);
          state = saved;
        } catch (error) {
          // Never replay a mutation after an ambiguous save or stale revision.
          if (saving) {blocked = true;mutations.length = 0;}
          status.textContent = String(error.message || error);
        }
      }
    } finally {
      busy = false;
      refresh();
    }
  }
  function mutate(value, action) {
    if (action.op === 'reset') Object.assign(value, doc.initial_state);
    else if (action.op === 'set') value[action.field] = action.value;
    else if (action.op === 'increment') value[action.field] += action.value;
    else if (action.op === 'toggle') value[action.field] = !value[action.field];
    else if (action.op === 'calculate') {
      const inputs = action.inputs.map(key => value[key]);
      if (action.operation === 'ratio' && inputs[1] === 0) throw new Error('Division by zero');
      const operations = {
        sum: () => inputs.reduce((a,b) => a+b, 0),
        difference: () => inputs[0] - inputs[1],
        product: () => inputs.reduce((a,b) => a*b, 1),
        ratio: () => inputs[0] / inputs[1],
      };
      value[action.field] = operations[action.operation]();
    }
  }
  function render(node) {
    let element;
    if (node.type === 'stack') {
      element = el('section');
      element.className = `stack ${node.direction}`;
      for (const child of node.children) element.append(render(child));
    } else if (node.type === 'text') {
      element = el(node.emphasis === 'heading' ? 'h1' : 'p', node.text ?? '');
      if (node.emphasis === 'caption') element.className = 'caption';
      if (node.bind) bindings.push(value => {element.textContent = String(value[node.bind]);});
    } else if (node.type === 'button') {
      element = el('button', node.label);
      element.type = 'button';
      element.className = node.variant;
      controls.push(element);
      element.addEventListener('click', () => {void commit(value => {for (const action of node.actions) mutate(value, action);});});
    } else if (node.type === 'table') {
      element = el('div'); element.className = 'table-scroll';
      const table = el('table'); const head = el('thead'); const row = el('tr');
      for (const column of node.columns) {const cell = el('th', column);cell.scope = 'col';row.append(cell);}
      head.append(row);table.append(head);const body = el('tbody');
      for (const values of node.rows) {const row = el('tr');for (const value of values) row.append(el('td', value));body.append(row);}
      table.append(body);element.append(table);
    } else {
      element = el('label');
      let input;
      if (node.type === 'select') {
        selects.push(node);
        input = el('select');
        for (const option of node.options) {const child = el('option', option.label);child.value = option.value;input.append(child);}
      } else {
        input = el('input');input.type = node.type === 'checkbox' ? 'checkbox' : node.input_type;
        if (input.type === 'number') input.step = 'any';
        else if (input.type === 'text') input.maxLength = 4000;
      }
      input.id = node.id;controls.push(input);
      if (node.type === 'checkbox') {element.className = 'checkbox';element.append(input, el('span', node.label));}
      else element.append(el('span', node.label), input);
      bindings.push(value => {
        if (node.type === 'checkbox') input.checked = value[node.bind];
        else if (blocked || document.activeElement !== input) input.value = String(value[node.bind]);
      });
      const saveInput = (event) => {
        if (event.isComposing) return;
        const next = node.type === 'checkbox' ? input.checked : node.input_type === 'number' ? (input.value === '' ? NaN : Number(input.value)) : input.value;
        if (event.type === 'input' && typeof next === 'number' && !Number.isFinite(next)) return;
        void commit(value => {value[node.bind] = next;}, node.bind);
      };
      input.addEventListener('change', saveInput);
      if (node.type === 'input') {
        input.addEventListener('input', saveInput);
        input.addEventListener('compositionend', saveInput);
      }
      return element;
    }
    element.id = node.id;
    return element;
  }
  root.append(render(doc.root));
  state = {revision: 0, value: {...doc.initial_state}};
  refresh();
  void (async () => {
    try {
      const saved = await window.promethea.getState();
      state = {revision: saved.revision, value: {...doc.initial_state, ...saved.value}};
      validate(state.value);
    } catch (error) {
      blocked = true;
      status.textContent = String(error.message || error);
    } finally {
      loaded = true;
      refresh();
    }
  })();
})();
