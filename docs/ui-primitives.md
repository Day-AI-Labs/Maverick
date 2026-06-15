# Dashboard UI primitives

Shared, page-agnostic helpers defined once in
`packages/maverick-dashboard/maverick_dashboard/templates/base.html` and
available on every page that `{% extends "base.html" %}`. **Prefer these over
native `confirm()` / `alert()` or hand-rolled toasts** — they are accessible
(assertive vs. polite live regions; a focus-trapping, focus-returning modal),
themed (no hard-coded colors), and consistent across the dashboard.

## `window.mvToast(message, { error })`

Transient notification.

- `error: true` → an assertive (`role="alert"`) live region, prefixed `⚠ `.
- otherwise → a polite (`role="status"`) live region.
- Auto-dismisses (errors linger longer). The two live regions are baked into the
  DOM at load, so announcements are reliable (a `role` injected into an existing
  polite region is not).

```js
mvToast('Schedule deleted');
mvToast('Could not delete schedule', { error: true });
```

## `window.mvConfirm(message, { okText }) -> Promise<boolean>`

Accessible confirmation on the native `<dialog>`: focus trap, `Esc` cancels,
focus returns to the opener on close. Falls back to `window.confirm` where
`<dialog>.showModal` is unavailable. **Not re-entrant** — a call while already
open resolves `false`.

```js
if (!(await mvConfirm('Delete this schedule? It will stop running.', { okText: 'Delete' }))) return;
```

Callers must be `async`. If the confirmed action removes the element that held
focus (e.g. a deleted list row), move focus to a stable landmark afterward — a
`tabindex="-1"` section heading — since the opener no longer exists.

## `window.mvCopy(text)`

Copies `text` to the clipboard (Clipboard API, with a hidden-textarea fallback)
and toasts the outcome.

```js
copyBtn.addEventListener('click', function () { mvCopy(urlEl.textContent); });
```

## `--scrim`

The single overlay-backdrop token (`:root` in base.html). Use it for any modal /
drawer / picker backdrop instead of a bespoke `rgba(...)`:

```css
.my-overlay::backdrop { background: var(--scrim); }
```

## Adoption

In use by: the Automations page, the workflow builder (schedules, triggers,
connector picker), the killswitch pill, fleets, learned-tools, and the goal
cancel action. New destructive actions and notifications should use these rather
than native dialogs.
