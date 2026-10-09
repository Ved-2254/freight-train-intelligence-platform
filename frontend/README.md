# Frontend (demo)

React 19 + TypeScript, built with Vite 8. Plain CSS (no UI framework), light and dark themes with a
"System" option. Talks to the backend API at `VITE_API_BASE_URL` (default `http://127.0.0.1:8000`).

## Run

Normally you do not start it on its own: from the repository root, `start-demo` (or
`.venv\Scripts\python demo.py`) starts the backend and this frontend together. To run only the
frontend (backend already running):

```bash
cd frontend
npm install          # first time only
npm run dev          # http://127.0.0.1:5173
npm run build        # type-check + production build into dist/
npm run preview      # serve the production build on http://127.0.0.1:5173
```

The backend must allow this origin (`FTIP_CORS_ORIGINS`, default includes `http://127.0.0.1:5173`
and `http://localhost:5173`).

## Pages

| Route | Purpose |
|---|---|
| `/` | Upload a video (drag and drop, progress, cancel), see its details, optional settings, start the analysis |
| `/jobs` | Job history with status filter and paging; refreshes while jobs are active |
| `/jobs/:jobId` | Live progress and cancel while processing; results when finished: totals, wagon sequence (click a wagon to jump to it in the video), class counts, annotated video, wagon table, warnings, downloads |

## Code layout

```
src/
├── main.tsx                 routes + theme provider
├── styles.css               all styling; colours are CSS variables, dark values under [data-theme="dark"]
├── lib/
│   ├── api.ts               typed API client (fetch) + ApiError
│   ├── upload.ts            upload with progress (XMLHttpRequest; fetch cannot report upload progress)
│   ├── types.ts             API and result types (mirror documentation/backend_api.md, output_schema.md)
│   ├── usePolling.ts        polling hook used for job status, job list and the backend status light
│   ├── theme.tsx            System / Light / Dark preference, saved in localStorage
│   ├── classColors.ts       same per-class colours as the boxes in the annotated video
│   └── format.ts            number, time and label formatting
├── components/              Layout, ServiceStatus, ThemeSwitcher, UploadDropzone, JobOptionsForm,
│                            common (badge, progress bar, alerts, cards), results (chart, sequence,
│                            video player, wagon table, notes, downloads)
└── pages/                   UploadPage, JobsPage, JobDetailPage
```

## How it works with the backend

1. `POST /api/v1/videos` (multipart) uploads the file; the server validates it by decoding it.
2. `POST /api/v1/jobs` with an `Idempotency-Key` header starts processing and returns at once.
3. The job page polls `GET /api/v1/jobs/{id}` every 2 seconds until the job is completed, failed or
   cancelled, then loads `GET /api/v1/jobs/{id}/results` once.
4. The video plays from `/api/v1/jobs/{id}/video` (HTTP Range requests make seeking work); downloads
   use the `links.exports` URLs returned by the API.

Clicking a wagon seeks the annotated video to the moment that wagon crossed the reference line. The
annotated video contains the sampled frames at the sampling rate, so its timeline matches the source
video's timestamps.
