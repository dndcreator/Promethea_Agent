# Intelligent Canvas

## Semantic Expressions Are Separate

Intelligent Canvas builds applications and task-specific work surfaces. Semantic
UI expresses the Agent's participation in the existing host: a note, gesture,
choice or ongoing text panel. The distinction is purpose, not whether a user or
Agent initiated it. Neither path edits Promethea's main UI source at runtime.

`semantic_ui.inspect/present` use the ordinary capability registry. Validated
expression data is rendered by host React components, with personal, conversation,
exact-message or Canvas-component scope. Stable IDs and expected revisions update/hide an existing
expression; no code generation or application deployment is required. This first
grammar is text and choices, not arbitrary charts, layout generation or remote
business actions. Rich custom applications remain in Canvas.

Host presentation uses the existing Workbench SSE subscription and generated SDK
contracts. `/api/semantic-ui` reads expressions; `/context` records an advisory
host view; `/{expression_id}/feedback` records a declared choice or dismissal.
Canvas expressions use `canvas_anchor`: an owned workspace/app reference, component
ID and exact source-definition hash, mutually exclusive with conversation anchors.
The existing opaque-frame bridge forwards only expressions matching that app and
current definition. A trusted text renderer mounts them beside the actual component;
the same ID updates in place, answered choices become disabled, and dismissals remove
the expression. Canvas-targeted expressions are excluded from chat rendering.
The frame can submit feedback only for its forwarded expressions. Runtime rechecks
ownership, the expression revision and current component definition before accepting
a new answer; it still permits dismissal of a stale expression. Save failures keep
the interaction retryable. The frame receives no host token or other apps' expressions.
Presentation/definition checks poll at most once concurrently every 1.5 seconds while
the document is visible and stop on disconnect; unavailable sources withdraw old cards.
There is no arbitrary tool name,
executable script or approval grant in the expression protocol.

SelfModel retains expression intent and feedback alongside working cognition;
business facts remain in their original services. Feedback emits
`semantic_ui.interacted`, and an enabled Ambient service may coalesce it into a
normal activation. Deterministic saves and rendering make no model calls. Choices
are user feedback, not proof that a task succeeded or permission to execute a
sensitive action. An Agent must still use CapabilityService and exact approval.

State survives restart and personal-space transfer; advisory visible-surface
context resets to unknown. Source message anchors are validated against the
authenticated owner's transcript. The browser reports which view it exposes,
not what the user has actually read. Dismissed/answered expressions are available
to the model so it can avoid repetition. Capacity is bounded and updates use
optimistic concurrency; stale writes fail instead of replacing newer feedback.

## Environment Understanding And Component Operations

SelfModel consumes a current environment projection, not a second business-state
store. The host reports surface IDs, monotonically increasing sequence numbers,
visibility/focus and resource references. Authenticated source adapters validate
ownership and read the current Session, Task, uploaded File, workspace Artifact
or Canvas authority. Unknown source kinds stay unsupported. Reports are advisory:
focus is not proof of reading, intent, agreement or successful business action.
Hidden/expired surfaces disappear from model context; restart/import begins with
unknown visibility. Meaningful descriptor changes emit the existing UI event;
heartbeats only renew leases. State-change events accelerate awareness, while a
fresh source snapshot prevents missed events from becoming permanent false state.

Host focus follows the deepest registered work region on pointer/keyboard focus,
not a copy of `document.hasFocus()` on every panel. The frame reports a component
only when that iframe is active; the host and Runtime validate its ID and definition.
Reports debounce within the frame, contain no keystrokes, and remain advisory.
Projection drops component attention when the source definition has changed.

Uploaded files reuse UserFileStore's extracted text (including supported PDF/DOCX
extraction); workspace artifacts expose supported UTF-8 text, JSON, Markdown and XML.
`environment.inspect` accepts character `offset`/`limit` (maximum 12,000 per read,
offset up to 1,000,000). Content includes its offset, truncation/next offset and source
revision. Automatic context contains only a bounded excerpt; the model can explicitly
read subsequent windows. Binary artifacts, missing extraction and unknown source kinds
stay unavailable/unsupported, not guessed from filenames. This does not add universal
OCR, binary document parsing or visual understanding of every file format.

For each proactive activation, Ambient projects fresh, owner-validated visible Canvas
and Artifact workspace references into its existing delegation scope as observation-only
access. This lets SelfModel inspect the active app and validate a presentation anchor
even if the delivery conversation uses another workspace. It grants no ordinary tool,
command or app-state write scope, is not inherited as child workspace access, and is
recomputed for continuation/new activation rather than persisted as permission.

The protected `environment_observations` block has its own bounded JSON budget,
separate from normal cognition text, and is refreshed at each Action model step.
It enters as user-level data, never system instructions. Existing model-call
manifests retain the actual request and refreshed block hash. Source failures
produce unavailable observations without aborting the Agent loop; cancellation
still propagates. This path does not invoke an extractor or another model.
SelfModel interpretations/questions remain distinct from these source snapshots;
neither can override source-service facts or permissions.

Generated component documents can include descriptions and `object_ref` relations.
`environment.inspect` and `GET /api/canvas/{workspace}/{environment}/semantics`
expose parent relationships, binding values, operation names, input schemas and
both definition/state revisions, text/table contents and declared button effects.
Focused components are prioritized in the bounded context with their descriptions
and object references. `component_id` selects complete semantics on demand, resolving
at most one related object through its own authority; a declaration never grants access
to that object. Descriptions, relations and source text remain untrusted data, not
system instructions or proof of business meaning. The packaged source is classified as `compiled`
only when it exactly matches the current renderer; a custom embedded declaration
is `declared`, not verified visual correspondence. Legacy/custom apps without a
document remain `undeclared`; process apps currently have no packaged declaration.
Object relations inside a document are app declarations, not proof that the
referenced business object exists. Resolve that object through its source.

`environment.interact` and the authenticated Canvas `/interact` endpoint execute
only the existing scalar component DSL: set a declared field or activate a
declared button. Runtime validates definition hash, state revision, types, enums,
finite arithmetic and workspace/delegation scope, then commits through the
existing app-state store. A failed commit publishes no change. The existing
environment event records changed field names and committed revisions, not model
claims. App data cannot dispatch tools, approve actions, alter Tasks or write
external business state; those operations retain their original services and
confirmation policies. These are ordinary registered capabilities, not a new
plugin protocol or execution engine.

The restricted iframe bridge supports `subscribe(listener)` in addition to
`getState/setState`. Its host watcher reads app state at most once concurrently,
every 1.5 seconds while visible, and stops on disconnect. Newer committed state
updates mounted components without reloading the app; local concurrent edits are
still fenced by revisions rather than silently overwritten or replayed. No model
is used to synchronize the UI. Existing retained artifacts keep their bundled
renderer; they need recomposition to acquire new renderer behavior.

## Application Canvas

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

Composition returns the automatically embedded semantic document's definition
revision and component count, explicitly marked not yet browser-verified.
Self Evolve's existing browser validation now inspects the actual opaque iframe
before and after declared test steps: IDs, containment, visibility, input types,
labels, options and displayed binding values must agree with the declaration and
the verifier's app-state bridge. Mismatches fail the ordinary validation gate and
therefore block deployment/publication. Results retain the semantic status and
verification outcome for the Agent's next Observation; no model translates the
DOM into purported facts.

The same verifier also applies valid scalar changes through the existing Runtime
component DSL and sends host state-change notifications across the actual frame
bridge. Each declared settable control must display the new stored value, then
the original state is restored. A page that renders correctly but omits state
subscription therefore cannot pass semantic verification. These are isolated
verification-page mutations, never changes to a user's retained application.

Custom apps without a declaration remain usable under ordinary browser tests but
report `undeclared` and no semantic verification. A matching custom declaration
is still `declared`, never promoted to the trusted compiler path. These bounded
checks prove only the observed test states, not arbitrary future JavaScript
behavior or the existence of referenced external business objects.

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
