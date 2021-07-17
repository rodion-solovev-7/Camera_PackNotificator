"""
Created on Sat Jun  6 12:29:01 2020

@author: sergey
"""
from collections import Counter
from typing import List, Tuple

import cv2
import numpy as np
import tensorflow as tf
from numpy import ndarray
from pyzbar.pyzbar import decode

from tensorflow.python.keras import models

# Размеры исходного изображения
ORIG_X, ORIG_Y = 853, 480
# Размеры картинки - входа НС
PIC_X, PIC_Y = 320, 240
# Размер матрицы выхода НС
MAT_Y, MAT_X = 26, 36

# Делители - преобразователи координат картинки в координвты матрицы
DIV_X = PIC_X / MAT_X
DIV_Y = PIC_Y / MAT_Y

# Множители картинки и картинки входа - для пересчета координат разметки.
SIZER_X = PIC_X / ORIG_X
SIZER_Y = PIC_Y / ORIG_Y


def get_most_common(values: List[str]) -> str:
    """Возвращает наиболее встречаемую непустую строку из списка"""
    counter = Counter(values)
    counter.pop('', None)
    if len(counter) == 0:
        return ''
    value, frequency = counter.most_common(1)[0]
    return value


def dummy_codes(
        pics: List[ndarray],
        width: float,
        height: float,
        sizer: float,
) -> Tuple[str, str]:
    """Возвращает штрих-код (barcode) и QR-код из серии снимков"""
    qr_codes = []
    barcodes = []

    for pic in pics:
        new_width = int(round(width * sizer))
        new_height = int(round(height * sizer))

        sized: ndarray = cv2.resize(pic, (new_width, new_height))
        codePict: ndarray = cv2.cvtColor(sized, cv2.COLOR_BGR2GRAY)
        ret, codePict = cv2.threshold(codePict, 100, 255, cv2.THRESH_BINARY)

        code = decode(codePict)

        for lss in code:
            if lss.type == 'QRCODE':
                qr_codes.append(lss.data)
            else:
                barcodes.append(lss.data)

    qr_code = get_most_common(qr_codes)
    barcode = get_most_common(barcodes)

    barcode = '' if len(barcode) < 13 else barcode

    return barcode, qr_code


# TODO: Все функции ниже этого комментария НЕ используются в коде.
#  Возможно, стоит часть из них удалить или отрефакторить


def get_bc_from_loc(pics):
    """Возвращает штрих-код из серии снимков. Наводится на него нейросетью."""
    ans = []

    regs = models.load_model('OMNY_YOLO_8549.h5', custom_objects={
        'iou_loss': iou_loss,
        'iou_loss_core': iou_loss_core
    })

    for i, pic in enumerate(pics):

        img = cv2.resize(pic, (PIC_X, PIC_Y))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = np.expand_dims(img, axis=0)

        reg = regs.predict(img)

        reg = np.reshape(reg, (MAT_Y, MAT_X))
        m, n = np.where(reg > 0.6)

        if len(m) == 0:
            continue

        # un, co = np.unique(m, return_counts=True)

        x1, y1 = int(round(n.min() * DIV_X / SIZER_X * 2.25)), int(round(m.min() * DIV_Y / SIZER_Y * 2.25))
        x2, y2 = int(round((n.max() + 1) * DIV_X / SIZER_X * 2.25)), int(round((m.max() + 1) * DIV_Y / SIZER_Y * 2.25))

        # x1, y1 = int(round(n.min() * DIV_X / SIZER_X * 2.25)), int(round(un[i] * DIV_Y / SIZER_Y * 2.25))
        # x2, y2 = int(round((n.max() + 1) * DIV_X / SIZER_X * 2.25)), int(round((un[i] + 1) * DIV_Y / SIZER_Y * 2.25))
        codePict = pic[y1:y2, x1:x2, :]

        # Бинаризация
        # codePict = cv2.cvtColor(codePict, cv2.COLOR_BGR2GRAY)
        # mid = codePict.mean()
        # ret, codePict = cv2.threshold(codePict, mid, 255, cv2.THRESH_BINARY)

        # cv2.imwrite('2/tratata_' + str(j) + '.jpg', codePict)
        try:

            # Бинаризация
            codePict = cv2.cvtColor(codePict, cv2.COLOR_BGR2GRAY)
            mid = codePict.mean()
            ret, codePict = cv2.threshold(codePict, mid, 255, cv2.THRESH_BINARY)

            code = decode(codePict)
            s = str(code[0][0])
            ans.append(s[2:-1])
            # print(s[2:-1])

        except Exception:
            # unknown error type
            pass

    return get_most_common(ans)


def get_bc_from_ROI(pics, x1, y1, x2, y2, sizer):
    """Возвращает штрих-код из серии снимков. Штрих-код берет из указанного ROI."""
    ans = []

    for i, pic in enumerate(pics):

        codePict = pic[y1:y2, x1:x2, :]

        # Бинаризация
        codePict = cv2.cvtColor(codePict, cv2.COLOR_BGR2GRAY)
        mid = codePict.mean()
        ret, codePict = cv2.threshold(codePict, mid, 255, cv2.THRESH_BINARY)

        if sizer != 1:
            newX = int(round((x2 - x1) * sizer))
            newY = int(round((y2 - y1) * sizer))

            codePict = cv2.resize(codePict, (newX, newY))

        # cv2.imwrite('2/tratata_'+str(j)+'.jpg',codePict)
        try:
            code = decode(codePict)
            s = str(code[0][0])
            ans.append(s[2:-1])

        except Exception:
            # PyZbarError ?
            pass

    return get_most_common(ans)


def dummy_pics(pics, ww, hh, sizer):
    """Возвращает ШК и QR из серии JPEG-изображений"""
    qr_codes = []
    barcodes = []

    for pic in pics:
        new_width = int(round(ww * sizer))
        new_height = int(round(hh * sizer))

        sized = cv2.resize(pic, (new_width, new_height))
        sized = pic.array_to_img(sized)
        code = decode(sized)

        for lss in code:
            if lss.type == 'QRCODE':
                qr_codes.append(lss.data)
            else:
                barcodes.append(lss.data)

    qr_code = get_most_common(qr_codes)
    barcode = get_most_common(barcodes)

    return barcode, qr_code


def dummy_codes_one(pic, ww, hh, sizer):
    """Возвращает ШК и QR с одного снимка"""
    BC, QR = '', ''
    # pic = cv2.cvtColor(pic, cv2.COLOR_BGR2RGB)
    newX = int(round(ww * sizer))
    newY = int(round(hh * sizer))

    sized = cv2.resize(pic, (newX, newY))
    # codePict = cv2.cvtColor(sized, cv2.COLOR_BGR2GRAY)
    # ret, codePict = cv2.threshold(codePict, 127, 255, cv2.THRESH_BINARY)

    code = decode(sized)

    for lss in code:

        if lss.type == 'QRCODE':
            QR = lss.data
        else:
            BC = lss.data

    return BC, QR


# this can be used as a loss if you make it negative
def iou_loss_core(true, pred):
    """Определяем метрику и функцию потерь"""
    intersection = true * pred
    notTrue = 1 - true
    union = true + (notTrue * pred)
    return tf.keras.backend.sum(intersection) / tf.keras.backend.sum(union)


def iou_loss(y_true, y_pred):
    return -iou_loss_core(y_true, y_pred)
