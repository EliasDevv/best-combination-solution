# Frontend

Angular 19 standalone app (signals, no NgRx, no UI framework) for the
streaming-package comparison. See the [root README](../README.md) for the
project overview, architecture, and API description.

```bash
npm install
npm start        # ng serve on http://localhost:4200, /api proxied to :8000
npm run build    # production build into dist/
npm test         # karma/jasmine component + store tests
```

The dev server proxies `/api` to the Django backend on port 8000
(`proxy.conf.json`) — start the backend first (`python manage.py runserver`
from `backend/`).
