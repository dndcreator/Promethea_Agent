# Computer Module

`computer` wraps host-side control capabilities for tool execution.

## Key Files

- `computer/base.py`: controller base class
- `computer/browser.py`: browser control through Playwright
- `computer/filesystem.py`: filesystem operations
- `computer/process.py`: process management
- `computer/screen.py`: screen-related utilities

## Workflow

1. Upper layer triggers an action.
2. Matching controller executes and returns structured output.
3. Upper layer converts the result into user-visible response or tool observation.

## Notes

- This is high-privilege functionality; scope it carefully.
- Browser control requires Playwright browser binaries.
- Errors should be explicit and observable.
