import asyncio
import multiprocessing as mp
from threading import Thread
from time import sleep

from pynput import keyboard

from src.client.stream_client import StreamClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


class HotKeyListener:
    def __init__(self, combination_str="<ctrl>+<alt>+r"):
        self.pressed = False
        # Parse the string into a combination set.
        self.combination = keyboard.HotKey.parse(combination_str)
        # Initialize a HotKey object with on_activate callback.
        self.hotkey = keyboard.HotKey(self.combination, self.on_activate)

    def on_activate(self):
        if not self.pressed:
            logger.info(f"Global hotkey: {self.combination} activated!")
            self.pressed = True

    def on_deactivate(self, key):
        # Release the key in the HotKey object.
        self.hotkey.release(key)
        if self.pressed:
            logger.info(f"Global hotkey: {self.combination} deactivated!")
            self.pressed = False

    def start(self):
        # Helper function to transform key press events.
        def for_canonical(f):
            return lambda k: f(listener.canonical(k))

        # Create a Listener using the canonical transformation.
        with keyboard.Listener(
            on_press=for_canonical(self.hotkey.press),
            on_release=for_canonical(self.on_deactivate),
        ) as listener:
            listener.join()


class HotKeyRecordingListener(HotKeyListener):
    def __init__(self, combination_str="<ctrl>+<alt>+r"):
        super().__init__(combination_str)
        self.recording = False
        self.stop_event = mp.Event()
        self.streaming_thread = None

    async def _streaming_loop(self):
        messages = []
        total_bytes_sent = 0

        async with StreamClient() as client:
            async for message in client.stream_microphone():
                if self.stop_event.is_set():
                    # this will trigger the stop logic in stream_microphone() by setting END marker
                    client.is_recording.clear()

                messages.append(message)
                # Extract byte count from message text if available.
                if not message.get("is_final"):
                    try:
                        byte_count = int(message["text"].split(": ")[1].split(" ")[0])
                        total_bytes_sent += byte_count
                    except (IndexError, ValueError):
                        pass
                if message.get("is_final"):
                    final_byte_count = int(message["text"].split(": Received ")[1].split(" ")[0])
                    break
        # Optionally, you can log or store the messages/byte counts.
        logger.info(f"Async streaming loop finished. Total bytes sent: {total_bytes_sent}")

    def on_activate(self):
        super().on_activate()
        if not self.recording:
            logger.info("Starting async streaming loop")
            # Run the async _streaming_loop() in a background thread.
            self.streaming_thread = Thread(
                target=lambda: asyncio.run(self._streaming_loop()), daemon=True
            )
            self.streaming_thread.start()
            self.recording = True

    def on_deactivate(self, key):
        super().on_deactivate(key)
        if self.recording:
            self.stop_event.set()
            self.recording = False
            logger.info("Joining streaming thread")
            self.streaming_thread.join()
            logger.info("Streaming thread joined")


if __name__ == "__main__":
    listener = HotKeyRecordingListener("<ctrl>+<alt>+r")
    listener.start()
