"""
Инструментарий для чтения QR- и штрихкодов с изображений.
"""
from collections import defaultdict
from enum import Enum
from typing import Union

import cv2
import numpy as np
from pyzbar import pyzbar

from .image_utils import get_resized

__all__ = ['CodeType', 'get_codes_from_image']


class CodeType(str, Enum):
    """
    Тип кода, считанного камерой
    """
    QR_CODE = 'QRCODE'
    BARCODE = 'EAN13'


def get_codes_from_image(
        image: np.ndarray,
        sizer: float = None,
) -> defaultdict[Union[str, CodeType], list[str]]:
    """
    Возращает QR-коды и штрих-коды прочитанные с данного изображения.

    Без повторений (хотя их никогда и нет).

    Returns:
        codes: словарь с штрих и QR-кодами

    Example:
        >>> get_codes_from_image(image)
        { 'QRCODE': ['some_text_data'], 'EAN13': ['12341234'], }
    """
    codes: defaultdict[str, list[str]] = defaultdict(list)

    resized = image if sizer is None else get_resized(image, sizer=sizer)

    grayscaled: np.ndarray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    cv2.threshold(grayscaled, 100, 255, cv2.THRESH_BINARY, grayscaled)

    decoded_values = [decoded for decoded in pyzbar.decode(grayscaled)
                      if decoded.data != b'']

    for decoded in decoded_values:
        code_data: str = bytes.decode(decoded.data, encoding='utf-8', errors='ignore')
        if code_data in codes[decoded.type]:
            continue
        codes[decoded.type].append(code_data)

    # TODO: уточнить насколько актуальны эти телодвижения
    codes[CodeType.BARCODE] = [code for code in codes[CodeType.BARCODE]
                               if len(code) >= 13]
    return codes
