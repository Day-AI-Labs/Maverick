# Embeddable widget

A dependency-free floating chat button that drops onto any page and talks to a
Maverick dashboard's chat endpoint. Self-hostable: it posts to **your**
dashboard origin, not a hosted service.

```html
<script src="/widget/maverick-widget.js"
        data-maverick-url="https://your-dashboard.example.com"
        data-maverick-title="Ask Maverick"></script>
```

- `data-maverick-url` — base URL of your dashboard (where `/chat/send` lives).
- `data-maverick-title` — header/button label.

The widget `fetch`es `POST {base}/chat/send` with `credentials: include`, so the
embedding origin must be allowed by the dashboard's auth / CORS policy (serve the
widget from the same origin, or configure CORS). No build step, no dependencies —
one `<script>` tag.
