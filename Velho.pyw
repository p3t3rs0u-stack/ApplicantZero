"""Tuplaklikkaa: käynnistää Velho-agentin taustalle ilman komentoikkunaa ja avaa selaimen.

Jos agentti on jo käynnissä, avataan vain selain. Sammutus: Sammuta-nappi sivun yläkulmassa.
"""

import os
import socket
import sys
import threading
import webbrowser

PORT = 5050
URL = f"http://localhost:{PORT}"

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())


def running() -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORT)) == 0


if running():
    webbrowser.open(URL)
else:
    # pythonw:llä ei ole konsolia: ohjataan tulosteet lokiin, ettei print kaadu
    os.makedirs("data", exist_ok=True)
    sys.stdout = sys.stderr = open("data/velho.log", "a", encoding="utf-8", buffering=1)
    from velho_agent.web import serve

    threading.Timer(1.5, webbrowser.open, args=(URL,)).start()
    serve(PORT)
