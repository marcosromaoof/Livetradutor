import queue
from typing import Any


def put_with_drop(target_queue: queue.Queue, item: Any) -> None:
    while True:
        try:
            target_queue.put_nowait(item)
            return
        except queue.Full:
            try:
                target_queue.get_nowait()
            except queue.Empty:
                return


def clear_queue(target_queue: queue.Queue) -> None:
    while True:
        try:
            target_queue.get_nowait()
        except queue.Empty:
            return
