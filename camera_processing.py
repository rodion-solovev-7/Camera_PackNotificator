from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Dict, List, Any, Optional

import numpy as np
from cv2 import VideoCapture, resize, cvtColor, imshow, waitKey, COLOR_BGR2RGB
from numpy import ndarray
from tensorflow.lite.python.interpreter import Interpreter

from recognition import ORIG_X, ORIG_Y, dummy_codes
from worker_events import TaskResult, CamScannerEvent, TaskError, EndScanning, StartScanning


@dataclass(unsafe_hash=True)
class ImagePackData:
    """
    Содержит считанные с изображения QR-код и шрих-код.

    Коды содержатся в единственном экземпляре (не списки!).

    Если какой-то из кодов не считался (или оба),
    то следует оставить вместо него ``None``.
    """
    qr_code: Optional[str] = None
    barcode: Optional[str] = None


class ImagePackScanner:
    """
    Обработчик изображений. Работает с отдельными изображениями.
    Умеет определять наличие пачек на картинке и читать информацию с них.
    """
    def __init__(self, model_path: str):
        self.interpreter = Interpreter(model_path=model_path)
        self.interpreter.allocate_tensors()

    def is_pack_exists(self, image: ndarray) -> bool:
        """
        Проверяет наличие пачки на изображении.

        (Осторожно: очень тяжёлая по производительности функция!)
        """
        input_detail: Dict[str, Any]
        output_detail: Dict[str, Any]
        input_detail = self.interpreter.get_input_details()[0]
        output_detail = self.interpreter.get_output_details()[0]

        input_width, input_height = input_detail['shape'][[2, 1]]

        rgb_image = resize(image, (input_width, input_height))
        rgb_image = cvtColor(rgb_image, COLOR_BGR2RGB)
        rgb_image = np.expand_dims(rgb_image, axis=0)

        try:
            img = rgb_image.astype('float32') / 255
            self.interpreter.set_tensor(input_detail['index'], img)
            self.interpreter.invoke()

            predict_value = self.interpreter.get_tensor(output_detail['index'])[0][0]
            return predict_value > 0.5

        # TODO: проверить наличие и конкретизировать исключение, либо убрать проверку
        except Exception:
            return False

    @staticmethod
    def read_codes(image: ndarray) -> ImagePackData:
        """Читает QR- и штрихкод с изображения."""
        width, height = image.shape[1], image.shape[0]

        try:
            barcode, qr_code = dummy_codes([image], width, height, 0.4)
            barcode = barcode if barcode != '' else None
            qr_code = qr_code if qr_code != '' else None
            return ImagePackData(barcode=barcode, qr_code=qr_code)

        # TODO: проверить наличие и конкретизировать исключение, либо убрать проверку
        except Exception:
            return ImagePackData()


class ImagesSource:
    """
    Обёртка над источником изображений.
    Инкапсулирует в себе видеопоток и переподключение к нему.
    Позволяет получать изображения из источника.
    """

    def __init__(self, video_url: str):
        self.video_url = video_url
        self.video: Optional[VideoCapture]
        self.connect_to_video()

    @staticmethod
    def display_in_window(image: ndarray) -> None:
        """
        Рендерит текущий кадр из видео.
        Позволяет в реальном времени видеть обрабатываемое видео.

        (Осторожно: негативно влияет на производительность!)
        """
        image2display = resize(image, (ORIG_X, ORIG_Y))
        imshow('', image2display)
        waitKey(1)

    def release_resourses(self):
        """Освобождает ресурсы, занятые видепотоком."""
        if self.video is not None:
            self.video.release()

    def connect_to_video(self):
        """
        Подключается к источнику видео. Освобождает ресурсы,
        занятые предыдущим подключением (если такое было).
        """
        # noinspection PyAttributeOutsideInit
        self.video = VideoCapture(self.video_url)

    def get_image(self, display: bool = False) -> ndarray:
        """
        Возвращает текущую картинку с видео.

        Если ``auto_reconnect=True``, при необходимости
        переподключается к источнику видео.
        """
        image: ndarray
        is_image_exists, image = self.video.read()

        if not is_image_exists:
            self.release_resourses()
            message = "Подключение к источнику видео прервано!"
            raise RuntimeError(message)

        if display:
            self.display_in_window(image)

        return image


def get_prepared_packdata_list(images_packdata: List[ImagePackData]) -> List[ImagePackData]:
    """
    Возвращает список различных ``ImagePackData``-записей,
    не содержащих пустых ``None``-кодов.
    """
    # удаляем повторения, не меняя очерёдности элементов
    images_packdata = dict.fromkeys(images_packdata)
    images_packdata = [packdata for packdata in images_packdata
                       if packdata.barcode is not None
                       and packdata.qr_code is not None]
    return images_packdata


def get_events(
        video_url: str,
        model_path: str,
        display: bool = True,
        auto_reconnect: bool = True,
) -> Iterable[CamScannerEvent]:
    """
    Бесконечный итератор, возвращающий события с камеры-сканера.
    """

    images_source = ImagesSource(video_url)
    image_scanner = ImagePackScanner(model_path)

    FRAMES_PER_CHECK = 15

    last_correct_barcode: Optional[str] = None
    # список пар QR- и шрихкодов (именно в таком порядке)
    images_packdata: List[ImagePackData] = []

    is_pack_visible_now = False
    is_pack_visible_before = False

    yield StartScanning(
        message="Начало работы",
        finish_time=datetime.now(),
    )

    frame_counter = 0
    while True:
        try:
            image = images_source.get_image(display=display)
        except RuntimeError as e:
            yield TaskError(
                message=str(e),
                finish_time=datetime.now(),
            )
            if not auto_reconnect:
                break
            continue

        frame_counter = (frame_counter + 1) % FRAMES_PER_CHECK
        if frame_counter == 0:
            is_pack_visible_now = image_scanner.is_pack_exists(image)

        if not is_pack_visible_now and not is_pack_visible_before:
            # пачки не видно сейчас и не было видно до этого, ждём
            continue

        if is_pack_visible_now:
            # пачка проходит в данный момент, пытаемся прочитать QR и шрихкод
            is_pack_visible_before = True

            packdata = image_scanner.read_codes(image)
            # если не смогли считать текущий штрихкод, берём предыдущий считанный
            if packdata.barcode is None:
                packdata.barcode = last_correct_barcode
            last_correct_barcode = packdata.barcode
            images_packdata.append(packdata)
            continue

        if not is_pack_visible_now and is_pack_visible_before:
            # пачка только что прошла, подводим итоги
            is_pack_visible_before = False

            prepared_packdata_list = get_prepared_packdata_list(images_packdata)
            qr_codes = [pack_data.qr_code for pack_data in prepared_packdata_list]
            barcodes = [pack_data.barcode for pack_data in prepared_packdata_list]

            yield TaskResult(
                qr_codes=qr_codes,
                barcodes=barcodes,
                finish_time=datetime.now(),
            )

            images_packdata.clear()
            continue

    yield EndScanning(
        message="Завершение работы",
        finish_time=datetime.now(),
    )
