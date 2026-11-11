"""Запуск бота и сервера: python run.py  (python run.py --dev — только мини-апа в браузере)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

for _a in sys.argv:
    if _a.startswith("--port="):
        os.environ["PORT"] = _a.split("=", 1)[1]

from platesbot.main import run  # noqa: E402

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
