"""Text REPL for Argus."""

from __future__ import annotations

import sys
import time
import threading
import uuid
from argus.agents import submit, Utterance

def _spinner(stop_event: threading.Event):
    chars = ['|', '/', '-', '\\']
    i = 0
    while not stop_event.is_set():
        sys.stdout.write(f"\r  Thinking {chars[i % 4]}")
        sys.stdout.flush()
        time.sleep(0.1)
        i += 1
    sys.stdout.write("\r" + " " * 20 + "\r")
    sys.stdout.flush()

def main():
    sid = uuid.uuid4().hex[:8]
    print(f"Argus Conversational CLI (session: {sid})\n")
    while True:
        try:
            line = input("> ").strip()
            if not line: continue
            if line in {"quit", "exit"}: break
            
            utterance = Utterance.from_text(line, sid)
            
            stop_event = threading.Event()
            spinner_thread = threading.Thread(target=_spinner, args=(stop_event,))
            spinner_thread.start()
            
            try:
                reply = submit(utterance)
            finally:
                stop_event.set()
                spinner_thread.join()
                
            print(f"  {reply.text}")
        except (EOFError, KeyboardInterrupt):
            break
        except Exception as exc:
            print(f"  (Error: {exc})")

if __name__ == "__main__":
    main()
