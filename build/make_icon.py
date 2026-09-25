"""Генерация иконки приложения `build/app.ico`.

Иконка рисуется кодом, чтобы в репозитории не было бинарного файла, который
нельзя проверить при рецензировании. Запускается один раз перед сборкой:

    python build/make_icon.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen

SIZES = (16, 24, 32, 48, 64, 128, 256)
PNG_FROM_SIZE = 256  # изображения этого размера и больше храним в ICO как PNG

_BACKGROUND_TOP = QColor(37, 63, 110)
_BACKGROUND_BOTTOM = QColor(23, 40, 73)
_FOREGROUND = QColor(245, 248, 252)
_ACCENT = QColor(214, 78, 66)


def render(size: int) -> QImage:
    """Рисует иконку: микрофон на скруглённом тёмном фоне с красной точкой записи."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    unit = size / 100.0

    background = QPainterPath()
    background.addRoundedRect(QRectF(0, 0, size, size), 22 * unit, 22 * unit)
    gradient = _vertical_gradient(size)
    painter.fillPath(background, gradient)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_FOREGROUND)

    # Капсула микрофона.
    capsule = QRectF(38 * unit, 20 * unit, 24 * unit, 38 * unit)
    painter.drawRoundedRect(capsule, 12 * unit, 12 * unit)

    # Дуга держателя и ножка.
    # Перо создаётся заново: painter.pen() вернул бы текущее перо со стилем
    # NoPen, установленным для заливки капсулы, и линии просто не нарисовались бы.
    painter.setBrush(Qt.BrushStyle.NoBrush)
    pen = QPen(_FOREGROUND)
    pen.setStyle(Qt.PenStyle.SolidLine)
    pen.setWidthF(max(1.0, 5 * unit))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawArc(QRectF(29 * unit, 30 * unit, 42 * unit, 42 * unit), 0, -180 * 16)
    painter.drawLine(QPointF(50 * unit, 72 * unit), QPointF(50 * unit, 82 * unit))

    # Индикатор записи — отличает иконку от обычного «микрофона».
    if size >= 32:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_ACCENT)
        radius = 7 * unit
        painter.drawEllipse(QPointF(74 * unit, 74 * unit), radius, radius)

    painter.end()
    return image


def _vertical_gradient(size: int):  # noqa: ANN202 — тип QGradient не нужен наружу
    from PySide6.QtGui import QLinearGradient

    gradient = QLinearGradient(0, 0, 0, size)
    gradient.setColorAt(0.0, _BACKGROUND_TOP)
    gradient.setColorAt(1.0, _BACKGROUND_BOTTOM)
    return gradient


def _png_bytes(image: QImage) -> bytes:
    # QBuffer не владеет QByteArray: ссылку на массив нужно держать самостоятельно,
    # иначе сборщик мусора освободит его прямо во время записи.
    storage = QByteArray()
    buffer = QBuffer(storage)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    try:
        if not image.save(buffer, "PNG"):
            raise RuntimeError("Qt не смог закодировать изображение в PNG")
    finally:
        buffer.close()
    return bytes(storage)


def _dib_bytes(image: QImage) -> bytes:
    """Кодирует изображение как DIB — формат, который ICO использует исторически.

    Заголовок описывает удвоенную высоту: за цветными пикселями следует
    однобитная маска прозрачности, обязательная по формату.
    """
    size = image.width()
    converted = image.convertToFormat(QImage.Format.Format_ARGB32)

    header = struct.pack(
        "<IiiHHIIiiII",
        40,  # размер BITMAPINFOHEADER
        size,
        size * 2,  # цвет + маска
        1,  # плоскости
        32,  # бит на пиксель
        0,  # без сжатия
        size * size * 4,
        0,
        0,
        0,
        0,
    )

    # BMP хранит строки снизу вверх; QImage::Format_ARGB32 в памяти — BGRA,
    # то есть ровно тот порядок байтов, который нужен DIB.
    rows = [bytes(converted.constScanLine(y))[: size * 4] for y in range(size - 1, -1, -1)]
    pixels = b"".join(rows)

    mask_row_bytes = ((size + 31) // 32) * 4
    mask = b"\x00" * (mask_row_bytes * size)

    return header + pixels + mask


def build_ico(destination: Path) -> None:
    entries: list[tuple[int, bytes]] = []
    for size in SIZES:
        image = render(size)
        payload = _png_bytes(image) if size >= PNG_FROM_SIZE else _dib_bytes(image)
        entries.append((size, payload))

    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = len(header) + 16 * len(entries)

    directory = b""
    for size, payload in entries:
        directory += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,
            size if size < 256 else 0,
            0,
            0,
            1,
            32,
            len(payload),
            offset,
        )
        offset += len(payload)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(header + directory + b"".join(payload for _size, payload in entries))


def main() -> int:
    QGuiApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL, True)
    app = QGuiApplication(sys.argv)  # QPainter требует инициализированного Qt
    # Иконка живёт внутри пакета (не в build/), чтобы её можно было найти
    # через resource_path() и в исходниках, и в собранном приложении PyInstaller.
    target = Path(__file__).resolve().parent.parent / "src" / "voicetext_ru" / "resources" / "app.ico"
    build_ico(target)
    print(f"Иконка создана: {target} ({target.stat().st_size} байт)")
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
