from pathlib import Path

import uvicorn

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    uvicorn.run(
        'app.main:app', host='127.0.0.1', port=8008, access_log=False,
        app_dir=str(root), reload=True, reload_dirs=[str(root / 'app')]
    )
