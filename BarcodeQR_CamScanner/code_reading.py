"""
Функции для чтения QR- и штрихкодов с изображений.
"""
from collections import defaultdict
from enum import Enum
from typing import Iterable

import cv2
import numpy as np
from pyzbar import pyzbar


class CodeType(str, Enum):
    QR_CODE = 'QRCODE'
    BARCODE = 'EAN13'


def _get_list_without_dublicates(items: list):
    """
    Возвращает список без повторений. Сохраняет упорядоченность (по первым элементам)
    """
    return list(dict.fromkeys(items))


def get_codes_from_image(
        image: np.ndarray,
        sizer: float = 0.4,
) -> defaultdict[str, list[str]]:
    """
    Чтение QR-кодов и штрих-кодов с одного изображения

    Returns:
        codes: словарь с штрих и QR-кодами

    Usage:
        >> get_codes_from_image(image)
        { 'QRCODE': ['some_text_data'], 'EAN13': ['12341234'], }
    """

    codes: defaultdict[str, list[str]] = defaultdict(list)

    new_height, new_width, *_ = (int(dim * sizer) for dim in image.shape)

    resized: np.ndarray = cv2.resize(image, (new_width, new_height))
    grayscaled: np.ndarray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    blackwhite: np.ndarray = cv2.threshold(grayscaled, 100, 255, cv2.THRESH_BINARY)[1]

    decoded_values = [decoded for decoded in pyzbar.decode(blackwhite)
                      if decoded.data != b'']

    for decoded in decoded_values:
        code_data: str = bytes.decode(decoded.data, encoding='utf-8', errors='ignore')
        if code_data in codes[decoded.type]:
            continue
        codes[decoded.type].append(code_data)

    codes[CodeType.BARCODE] = [code for code in codes[CodeType.BARCODE]
                               if len(code) >= 13]

    return codes


def get_codes_from_images(
        images: Iterable[np.ndarray],
        sizer: float = 0.4,
) -> defaultdict[str, list[str]]:
    """
    Чтение QR-кодов и штрих-кодов с серии изображений

    Returns:
        codes: словарь с штрих и QR-кодами

    Usage:
        >> get_codes_from_images(image)
        { 'QRCODE': ['some_text_data', 'some_text_data2'], 'EAN13': ['12341234'], }
    """

    all_codes: defaultdict[str, list[str]] = defaultdict(list)

    for image in images:
        codes_from_image = get_codes_from_image(image, sizer)
        for code_type, codes in codes_from_image.items():
            all_codes[code_type] = _get_list_without_dublicates(all_codes[code_type] + codes)

    return all_codes
