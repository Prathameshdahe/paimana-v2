# Report inbox

Drop a new report here. The live watcher (`backend/live/watcher.py`) checks the
folder every `WATCH_INTERVAL_S` seconds while the backend runs, or at once on
`POST /api/jobs/watch`. `POST /api/jobs/ingest` uploads a file into this folder.

Accepted files:

- a portal export `Projects_Report.csv` (the PAIMANA portal project list)
- a PAIMANA flash report PDF, named with its month as the extractor reads it,
  e.g. `FlashReport_August_2026.pdf`

For each file the watcher runs the extractor, the clean merge and the pipeline
steps silver, external, gold, score and profile (train stays the monthly run,
started by hand), then raises tier-change alerts and fills realised outcomes in
the prediction log. A processed file moves to `dataset/raw/csv/<fiscal year>/`
or `dataset/raw/pdf/<fiscal year>/`; a flash PDF is also copied into the flash
extractor's source folder in the Dataset drive folder. A file that fails stays
here, the previous scores keep serving and a `pipeline_error` alert is raised.
The same bytes are not processed twice by the same pipeline code.

Everything in this folder except this README is ignored by git.
