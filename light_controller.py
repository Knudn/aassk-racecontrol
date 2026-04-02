import asyncio
from start_light_lib import RaceController, make_solid_color_image, create_image
import configparser
import json
from PIL import Image
import io
import ast
import random
import aiomqtt
import RPi.GPIO as GPIO
import time
from concurrent.futures import ThreadPoolExecutor

current_state = ""

GPIO.setmode(GPIO.BCM)
GPIO.setup(23, GPIO.IN)
GPIO.setup(24, GPIO.IN)

# Create a thread pool for blocking GPIO operations
gpio_executor = ThreadPoolExecutor(max_workers=1)


async def handle_halt_race(rc, config_data):
    """Separate task for halt race behavior"""
    loop = asyncio.get_event_loop()

    while True:
        rc.send_fill_fast(config_data["halt_color"], brightness=config_data["brightness"])
        await asyncio.sleep(0.2)

        await loop.run_in_executor(gpio_executor, GPIO.setup, 23, GPIO.OUT)
        await asyncio.sleep(0.2)
        await loop.run_in_executor(gpio_executor, GPIO.setup, 23, GPIO.IN)
        await asyncio.sleep(0.2)
        await loop.run_in_executor(gpio_executor, GPIO.setup, 23, GPIO.OUT)
        await asyncio.sleep(0.2)
        await loop.run_in_executor(gpio_executor, GPIO.setup, 23, GPIO.IN)
        await asyncio.sleep(0.2)
        await loop.run_in_executor(gpio_executor, GPIO.setup, 23, GPIO.OUT)
        await asyncio.sleep(0.5)
        await loop.run_in_executor(gpio_executor, GPIO.setup, 23, GPIO.IN)


async def handle_warmup(rc, config_data, publish_queue, cancelled_flag):
    """Iterate through warmup_steps, each being:
        {"rgb_data": bytes, "duration": float seconds}
    Falls back to a single random-timer step if warmup_steps is empty.
    """
    warmup_steps = config_data.get("warmup_steps", [])

    if not warmup_steps:
        # Legacy fallback: single image with a random duration
        warmup_timer = random.uniform(
            float(config_data["warmup_timer_first"]),
            float(config_data["warmup_timer_last"])
        )
        warmup_steps = [
            {"rgb_data": config_data["warmup_image"], "duration": warmup_timer}
        ]

    for step in warmup_steps:
        if cancelled_flag["cancelled"]:
            return

        rc.send_image(
            config_data["width"],
            config_data["height"],
            step["rgb_data"],
            brightness=int(config_data["brightness"])
        )

        elapsed = 0
        while elapsed < step["duration"]:
            if cancelled_flag["cancelled"]:
                return
            await asyncio.sleep(0.1)
            elapsed += 0.1

    if not cancelled_flag["cancelled"]:
        await publish_queue.put({"warmup": False})


async def handle_started(rc, config_data, publish_queue, cancelled_flag):
    """Separate task for started sequence"""
    loop = asyncio.get_event_loop()

    if config_data["use_relay"]:
        await loop.run_in_executor(gpio_executor, GPIO.setup, 24, GPIO.OUT)

        elapsed = 0
        while elapsed < config_data["on_timer"]:
            if cancelled_flag["cancelled"]:
                await loop.run_in_executor(gpio_executor, GPIO.setup, 24, GPIO.IN)
                return
            await asyncio.sleep(0.1)
            elapsed += 0.1

        await loop.run_in_executor(gpio_executor, GPIO.setup, 24, GPIO.IN)
    else:
        rc.send_fill_fast(config_data["start_color"], brightness=config_data["brightness"])

        elapsed = 0
        while elapsed < config_data["on_timer"]:
            if cancelled_flag["cancelled"]:
                rc.reset()
                return
            await asyncio.sleep(0.1)
            elapsed += 0.1

        rc.reset()

    if not cancelled_flag["cancelled"]:
        await publish_queue.put({"started": False})


async def handle_message(msg, rc, config_data, publish_queue, task_holder):
    global current_state
    message = json.loads(msg.payload.decode())
    current_state = message
    print(message)

    # Cancel any ongoing warmup/started tasks
    if task_holder["warmup_task"] is not None:
        task_holder["warmup_cancelled"]["cancelled"] = True
        task_holder["warmup_task"].cancel()
        try:
            await task_holder["warmup_task"]
        except asyncio.CancelledError:
            pass
        task_holder["warmup_task"] = None
        rc.reset()

    if task_holder["started_task"] is not None:
        task_holder["started_cancelled"]["cancelled"] = True
        task_holder["started_task"].cancel()
        try:
            await task_holder["started_task"]
        except asyncio.CancelledError:
            pass
        task_holder["started_task"] = None
        rc.reset()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(gpio_executor, GPIO.setup, 24, GPIO.IN)

    # Handle halt
    if message["halt_race"]:
        if task_holder["halt_task"] is None or task_holder["halt_task"].done():
            task_holder["halt_task"] = asyncio.create_task(handle_halt_race(rc, config_data))
        return
    else:
        if task_holder["halt_task"] is not None and not task_holder["halt_task"].done():
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(gpio_executor, GPIO.setup, 23, GPIO.IN)
            rc.reset()
            task_holder["halt_task"].cancel()
            try:
                await task_holder["halt_task"]
            except asyncio.CancelledError:
                pass
            task_holder["halt_task"] = None

    if message["warmup"] == True:
        task_holder["warmup_cancelled"] = {"cancelled": False}
        task_holder["warmup_task"] = asyncio.create_task(
            handle_warmup(rc, config_data, publish_queue, task_holder["warmup_cancelled"])
        )

    elif message["started"] == True:
        task_holder["started_cancelled"] = {"cancelled": False}
        task_holder["started_task"] = asyncio.create_task(
            handle_started(rc, config_data, publish_queue, task_holder["started_cancelled"])
        )


async def publish_worker(client, publish_queue, stop_event):
    """Handles all MQTT publishes from a queue"""
    while not stop_event.is_set():
        try:
            try:
                message_update = await asyncio.wait_for(publish_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            try:
                if isinstance(current_state, dict):
                    updated_state = current_state.copy()
                    updated_state.update(message_update)
                    print(f"Publishing: {message_update}")
                    await client.publish("start/state", json.dumps(updated_state), retain=True)
                    print(f"Published successfully")
            except Exception as e:
                print(f"Publish error: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
        except Exception as e:
            print(f"Unexpected error in publish_worker: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    print("Publish worker stopped")


async def mqtt_listener(config_data, rc):
    task_holder = {
        "halt_task": None,
        "warmup_task": None,
        "started_task": None,
        "warmup_cancelled": {"cancelled": False},
        "started_cancelled": {"cancelled": False}
    }

    publish_queue = asyncio.Queue()
    reconnect_delay = 5
    max_reconnect_delay = 60

    while True:
        try:
            stop_event = asyncio.Event()

            async with aiomqtt.Client(
                hostname=config_data["mqtt_host"],
                port=1883,
                identifier="STARTLIGHT",
                keepalive=60
            ) as client:
                print(f"Connected to MQTT broker")
                reconnect_delay = 5

                await client.subscribe("start/state")
                print("Subscribed to start/state")

                publish_task = asyncio.create_task(
                    publish_worker(client, publish_queue, stop_event)
                )

                try:
                    async for msg in client.messages:
                        try:
                            await handle_message(msg, rc, config_data, publish_queue, task_holder)
                        except Exception as e:
                            print(f"Error in handle_message: {type(e).__name__}: {e}")
                            import traceback
                            traceback.print_exc()
                finally:
                    stop_event.set()
                    try:
                        await asyncio.wait_for(publish_task, timeout=5.0)
                    except asyncio.TimeoutError:
                        print("Publish task didn't stop in time, cancelling")
                        publish_task.cancel()
                    except Exception as e:
                        print(f"Error waiting for publish task: {e}")

        except aiomqtt.MqttError as e:
            print(f"MQTT error [code:{getattr(e, 'rc', 'unknown')}]: {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 1.5, max_reconnect_delay)
        except Exception as e:
            print(f"Unexpected error: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 1.5, max_reconnect_delay)


def parse_image_from_config(raw_value, width, height):
    """Convert a config value to RGB byte data for LED matrix.
    Accepts:
      - A list of ints  (raw PNG bytes from get_rgb_values["image_1/2"])
      - A base64 string (data URI or plain base64)
      - A legacy path/descriptor string (passed to create_image)
    Returns RGB byte array suitable for send_image()
    """
    import base64 as _b64

    img = None

    if isinstance(raw_value, list):
        img = Image.open(io.BytesIO(bytes(raw_value)))
    elif isinstance(raw_value, str):
        if raw_value.startswith("data:"):
            raw_value = raw_value.split(",", 1)[1]
        try:
            image_bytes = _b64.b64decode(raw_value)
            img = Image.open(io.BytesIO(image_bytes))
        except Exception:
            pass

        # Fall back to the original create_image helper
        if img is None:
            # create_image returns RGB bytes directly
            return create_image(raw_value)

    if img is None:
        return None

    # Convert PIL Image to RGB byte array for LED matrix
    # Resize to matrix dimensions if needed
    if img.size != (width, height):
        img = img.resize((width, height), Image.Resampling.NEAREST)

    # Convert to RGB mode if not already
    if img.mode != 'RGB':
        img = img.convert('RGB')

    # Return raw RGB bytes
    return img.tobytes()


async def main():
    config = configparser.ConfigParser()
    config.read("config.ini")
    config = config["General"]

    # Parse dimensions with defaults
    matrix_size = config.get("sl_matric_size", "24x32").strip("[]'\"")
    width, height = map(int, matrix_size.split("x"))

    # Parse brightness with error handling
    try:
        brightness = ast.literal_eval(config.get("sl_brightness", "150"))[0]
    except (ValueError, TypeError, IndexError):
        brightness = int(config.get("sl_brightness", "150"))

    # Parse active timer with error handling
    try:
        on_timer = int(ast.literal_eval(config.get("sl_active_timer", "3"))[0])
    except (ValueError, TypeError, IndexError):
        on_timer = int(config.get("sl_active_timer", "3"))

    # Parse colors
    start_color = config.get("sl_start_color", "[0,255,0]")
    halt_color = config.get("sl_halt_color", "[255,0,0]")
    stop_color = config.get("sl_stop_color", "[0,0,255]")
    ready_color = config.get("sl_ready_color", "[0,0,0]")
    start_using_relay = config.get("sl_start_using_relay", "False") == "True"

    # Legacy random-range kept as fallback only
    try:
        start_delay_str = ast.literal_eval(config.get("sl_start_delay", "1.2-2.5"))[0]
    except (ValueError, TypeError, IndexError):
        start_delay_str = config.get("sl_start_delay", "1.2-2.5")

    warmup_timer_first, warmup_timer_last = start_delay_str.split("-")

    # ── Build warmup steps ────────────────────────────────────────────────────
    warmup_steps = []

    # Image 1 — required
    raw_image_1 = ast.literal_eval(config["sl_warmup_image_data"])
    rgb_data_1 = parse_image_from_config(raw_image_1, width, height)
    duration_1 = float(config.get("sl_warmup_duration_1", "3.0"))
    if rgb_data_1 is not None:
        warmup_steps.append({"rgb_data": rgb_data_1, "duration": duration_1})
        print(f"First warmup image loaded, duration: {duration_1}s")

    # Image 2 — optional (only if toggle is enabled)
    use_warmup_2 = config.get("sl_use_warmup_image_2", "False") == "True"
    print(f"Second warmup image enabled: {use_warmup_2}")

    if use_warmup_2:
        if "sl_warmup_image_data_2" in config:
            try:
                raw_image_2 = ast.literal_eval(config["sl_warmup_image_data_2"])
                # Only parse if there's actual data
                if raw_image_2 and (isinstance(raw_image_2, list) and len(raw_image_2) > 0):
                    rgb_data_2 = parse_image_from_config(raw_image_2, width, height)
                    duration_2 = float(config.get("sl_warmup_duration_2", "5.0"))
                    if rgb_data_2 is not None:
                        warmup_steps.append({"rgb_data": rgb_data_2, "duration": duration_2})
                        print(f"Second warmup image loaded, duration: {duration_2}s")
                    else:
                        print("Warning: Second warmup image data could not be parsed")
                else:
                    print("Warning: Second warmup image data is empty")
            except Exception as e:
                print(f"Error loading second warmup image: {e}")
        else:
            print("Warning: Second warmup image enabled but no image data found")

    print(f"Loaded {len(warmup_steps)} warmup step(s) total")
    print(f"Using relay: {start_using_relay}")

    config_data = {
        "width":  width,
        "height": height,
        "brightness": brightness,
        "on_timer":   on_timer,
        # Legacy keys kept for handle_warmup fallback
        "warmup_timer_first": warmup_timer_first,
        "warmup_timer_last":  warmup_timer_last,
        "warmup_image":  rgb_data_1,       # single-image fallback (RGB bytes)
        # Structured steps consumed by handle_warmup
        "warmup_steps":  warmup_steps,
        "start_color":   start_color,
        "halt_color":    halt_color,
        "stop_color":    stop_color,
        "ready_color":   ready_color,
        "use_warmup_image": True,
        "use_relay":     start_using_relay,
        "mqtt_host":     "192.168.1.50"
    }

    rc = RaceController()
    await mqtt_listener(config_data, rc)


if __name__ == "__main__":
    asyncio.run(main())
