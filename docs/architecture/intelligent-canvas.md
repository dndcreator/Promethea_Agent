# Intelligent Canvas

Promethea separates the conversation interface from generated applications.
Canvas is a shell above the existing UI, not an alternative Agent Core. An
application may be conversation-scoped or retained in a user's library, with
its own persisted data. Reopening an application does not require regenerating
its interface or asking a model to interpret every click.

## Two Authoring Paths, One Lifecycle

```text
Main model / existing Action loop
  -> Self Evolve
     -> component document -> validation -> trusted renderer
     -> custom HTML/JS/CSS -> bounded authoring and repair
  -> declared browser interactions -> validation digest
  -> Canvas environment -> opaque iframe -> restricted state bridge
  -> conversation workspace / retained personal library
```

The component path implements `canvas.ui.v1`: stack layouts, literal or
state-bound text, text/number inputs, checkboxes, selects, buttons, and tables.
Descriptions contain data, not executable HTML, CSS, expressions, or event
handlers. Typed mutations support assignment, increment, toggle, reset, and
bounded arithmetic. These operations are component semantics, not task-specific
presets. There is no keyword routing for particular user requests.

The model obtains the schema through `evolve_get_canvas_schema`, then uses
`evolve_compose_canvas` on an existing canvas task. Composition writes its HTML
entrypoint through the same checkpointed staging writer. It does not bypass
browser verification, ownership checks, immutable publication, or deployment.
Replacing an inspected entrypoint can include its `expected_sha256`.

The Python models in `computer/canvas_components.py` are the source for runtime
validation, tool schema inspection, and the `CanvasDocument` public contract.
The existing generator includes them in JSON Schema and both TypeScript type
bundles:

```bash
python scripts/generate_public_contracts.py
python scripts/generate_public_contracts.py --check
```

The renderer in `computer/canvas_components.js` is bundled into each artifact.
It constructs DOM nodes using text content and explicit properties; it never
evaluates model-authored code. A retained artifact therefore carries the renderer
version it was verified with, rather than silently switching to a future host
renderer. Changing the component grammar incompatibly requires a new version.

Custom applications remain available for interactions outside this grammar.
They use existing sandboxed authoring, build/check commands, diagnostics, and
repair. A custom edit to a compiled document becomes custom application code
and must pass verification again; it does not retain a special trusted status.
Neither path modifies Promethea's main UI or Agent Core.

## Interaction And Persistence

Bindings address declared, flat scalar app-state fields. Inputs and button
actions use `window.promethea.getState()` and
`setState(value, expectedRevision)` through the existing MessageChannel bridge.
The host owns authentication, workspace identity, and app-state revisions; the
iframe receives none of those credentials. All mutations from one component
interaction are saved together. Unknown nodes, incorrect binding types,
undeclared fields, invalid numeric results, and excessive document sizes are
rejected rather than interpreted as code.

Controls remain disabled until state has loaded. Mutations are submitted in
order through a bounded queue, so an input blur cannot swallow a following click.
Text/number inputs autosave on input, including completed IME composition;
consecutive queued changes to the same field coalesce without crossing button
actions. Failed persistence rolls back the host's in-memory state and revision.
Arithmetic errors leave the prior committed value unchanged. A failed or
ambiguous save disables further edits until reload; it is not silently retried
or treated as success. A fresh load uses current persisted state. This prevents
stale clients from replaying increments or overwriting newer values.

Code fingerprints and app-state revisions remain separate: saving data does not
reload the iframe. Retained apps use the existing library, export/import,
checksums, and ownership boundaries. App data is not automatically Agent Memory;
any future memory extraction must go through the existing Memory governance.

Component actions cannot execute tools, fetch arbitrary URLs, change permissions,
or authorize host operations. No new plugin protocol, tool executor, scheduler,
or Agent loop is introduced. This version does not provide model-response
component streaming, inline message widgets, arbitrary charts, or general
remote-data actions. Model selection of this path still depends on tool
availability, configuration, and the model; it is not forced by frontend logic.

## Design References And Limits

[OpenAI Intelligent UI](https://help.openai.com/en/articles/20001598-intelligent-ui-in-chatgpt)
describes generated interactive responses, including some components whose state
survives a thread refresh. It should not be described as universally single-turn
or stateless. Its full implementation is not specified in that public guide.

[ChatKit widgets](https://developers.openai.com/api/docs/guides/chatkit-widgets)
and [actions](https://developers.openai.com/api/docs/guides/chatkit-actions)
provide a concrete public reference for component descriptions and explicit
interaction handling. Promethea borrows that separation, not ChatGPT internals
or the ChatKit runtime. Its design emphasis is independently retained workspace
applications, continued interaction, and portable app data within its existing
Runtime.

Using a bounded grammar removes model-authored component implementation from
the simple path. That is a narrower failure surface, not proof of better
performance or model reliability. No comparative latency benchmark or feature
parity with Intelligent UI is claimed.
