import os

from loguru import logger


def setup_logger():
    log_path = os.getenv('LOG_PATH', 'logs/1camera.log')
    log_level = os.getenv('LOG_LEVEL', 'DEBUG')

    logger.add(sink=log_path, level=log_level, rotation='2 MB', compression='zip')


def collect_scanners_args() -> list[tuple]:
    video_urls = os.getenv('VIDEO_URLS', 'video1.mp4;video2.mp4')
    display_window = os.getenv('DISPLAY_WINDOW', '1')
    auto_reconnect = os.getenv('AUTO_RECONNECT', '1')
    recognition_method = os.getenv('RECOGNITION_METHOD', 'BACKGROUND')
    threshold_value = os.getenv('RECOGNITION_THRESHOLD_VALUE', '0.5')
    model_path = os.getenv('MODEL_PATH', './model.tflite')

    video_urls = video_urls.split(';')
    threshold_value = float(threshold_value)
    display_window = int(display_window) != 0
    auto_reconnect = int(auto_reconnect) != 0

    if recognition_method == "BACKGROUND":
        recognizer_args = dict(
            background=None,
            borders=(15, -20),
            learning_rate=1e-4,
            threshold_score=threshold_value,
            size_multiplier=0.4,
        )
    elif recognition_method == "NEURONET":
        recognizer_args = dict(
            model_path=model_path,
            threshold_score=threshold_value,
        )
    else:
        raise ValueError(f"Неподдерживаемый способ распознавания: '{recognition_method}'")

    scanners_args = [
        (
            video_url,
            display_window,
            auto_reconnect,
            recognition_method,
            recognizer_args,
        ) for video_url in video_urls
    ]
    return scanners_args
