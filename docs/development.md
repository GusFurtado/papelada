# Development

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
DATA_DIR=./data .venv/bin/uvicorn app.main:create_app --factory --reload
```

The frontend is plain HTML, CSS and JS in `frontend/`, served as is. The API is
documented at `/api/docs` while the app runs. `app/storage.py` explains the volume
layout and the encryption switch in detail.
