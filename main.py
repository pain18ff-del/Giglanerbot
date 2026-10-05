import os
import threading
import subprocess
import time
from flask import Flask

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is alive"


def run_bot():
    while True:
        try:
            subprocess.run(["python", "bot.py"], check=True)
        except Exception as e:
            print(f"Bot crashed: {e}, restarting in 5 sec...")
            time.sleep(5)


def keep_alive():
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        return
    import urllib.request
    while True:
        time.sleep(300)
        try:
            urllib.request.urlopen(url)
            print("Self-ping OK")
        except Exception as e:
            print(f"Self-ping failed: {e}")


if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
