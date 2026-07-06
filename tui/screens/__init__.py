"""Focused screens for the 320x480 portrait (≈40x30 cell) touch display.

One screen per job — home/status, logs, config, model browser — navigated with
``push_screen``/``pop_screen`` instead of tabs, so each layout fits 40 columns
with height-3 tappable controls. Screens are thin views: live state (supervisor,
log pumps, health, pull queue) stays on the app.
"""

from tui.screens.config import ConfigScreen
from tui.screens.home import HomeScreen
from tui.screens.logs import LogsScreen
from tui.screens.models import InstalledScreen, ModelDetailScreen, ModelsScreen
from tui.screens.now import NowScreen
from tui.screens.picker import PickerScreen
from tui.screens.voices import VoicesScreen

__all__ = [
    "ConfigScreen",
    "HomeScreen",
    "InstalledScreen",
    "LogsScreen",
    "ModelDetailScreen",
    "ModelsScreen",
    "NowScreen",
    "PickerScreen",
    "VoicesScreen",
]
