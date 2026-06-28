# coding:utf-8
import os
import sys

import qfluentwidgetspro
qfluentwidgetspro.setLicense("mGR3+Zzt2pWCCCUVLKMgV454OWBvqHhn77jQgMs2i7uowRsodYi8aM2Jn0OPk24/i2UsbgVgXV1oK9jdwgsRYbVYJDLvDCJYair3kFXMO5rWx7WzNYNCB4jjLzLS8HS4K79hWpFCIgrxCkvZRf73AvNTNlTWk3cxIK122P3KjRUf7wrAOA51gH6xVSGPEKGUQZXg0aHy1yyqB9TZSGLzrbAfRhv8KeTpIy1x9ZyAYyUwnP1gPewnZc8KVFwkYEPvbhFebLNRcjCB0pDXakts+5nLM0WL8YhPEmmHIpk6BI6NVvcJMg2bGZjfwScLb0mc")

from PySide6.QtCore import Qt, QTranslator
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication
from qfluentwidgets import FluentTranslator

from app.common.config import cfg
from app.view.main_window import MainWindow



# enable dpi scaleq
if cfg.get(cfg.dpiScale) != "Auto":
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_SCALE_FACTOR"] = str(cfg.get(cfg.dpiScale))

# create application
app = QApplication(sys.argv)
app.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings)

# internationalization
locale = cfg.get(cfg.language).value
translator = FluentTranslator(locale)
galleryTranslator = QTranslator()
galleryTranslator.load(locale, "app", ".", ":/app/i18n")

app.installTranslator(translator)
app.installTranslator(galleryTranslator)

# create main window
w = MainWindow()
w.show()

app.exec()
