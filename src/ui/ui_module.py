# ui_module_0.9.4.py
import sys
import os
import time
import random
from datetime import datetime, timedelta # Added timedelta
import PySide6
import logging # Added logging

# Windows specific import for theme detection
if sys.platform == "win32":
    try:
        import winreg
    except ImportError:
        winreg = None # Fallback if winreg is not available
else:
    winreg = None

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QStackedWidget, QListWidget, QRadioButton, QGroupBox,
    QDialog, QFormLayout, QMessageBox, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QProgressBar, QMenuBar, QDialogButtonBox, QSplitter, QHeaderView, QCheckBox, QListWidgetItem,
    QComboBox, QSizePolicy, QSpacerItem, QInputDialog
)
from PySide6.QtGui import (
    QAction, QIcon, QColor, QPalette, QFont, QGuiApplication, QActionGroup, QPixmap, QPainter
)
from PySide6.QtCore import Qt, Signal, QTimer, Slot, QObject, QSettings, QByteArray # Added QByteArray for type hint

# --- Logger Setup ---
# This logger will inherit configuration from the root logger if the module is imported.
# If run standalone, a basicConfig can be set in `if __name__ == '__main__':`.
logger = logging.getLogger("UI_Module")

try:
    import pyqtgraph as pg
    PYQTGRAPH_AVAILABLE = True
except ImportError:
    pg = None
    PYQTGRAPH_AVAILABLE = False
    logger.warning("pyqtgraph not found. Graphing functionality will be disabled.")
    # Define a dummy PlotWidget class if pyqtgraph is not available
    class PlotWidget(QWidget):
        """Dummy PlotWidget to display a message when pyqtgraph is missing."""
        def __init__(self, parent=None):
            super().__init__(parent)
            layout = QVBoxLayout(self)
            label = QLabel("pyqtgraph not installed.\nGraph cannot be displayed.")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
        # Provide dummy methods matching the ones used in the main code
        def plot(self, *args, **kwargs): return None # Return a dummy item perhaps?
        def addLegend(self, *args, **kwargs): pass
        def clear(self, *args, **kwargs): pass
        def setXRange(self, *args, **kwargs): pass
        def setYRange(self, *args, **kwargs): pass
        def setLabel(self, *args, **kwargs): pass
        def showGrid(self, *args, **kwargs): pass
        def setBackground(self, *args, **kwargs): pass
        def enableAutoRange(self, *args, **kwargs): pass
        def autoRange(self, *args, **kwargs): pass
        # Add dummy PlotDataItem if needed by clear() etc.
        class DummyPlotDataItem:
            def clear(self): pass
        # Make plot return something that can be cleared
        def plot(self, *args, **kwargs): return self.DummyPlotDataItem()

# Import from user_management, including the moved dialogs
try:
    # Relative import (when used as a package)
    from .user_management import (
        load_users, save_users,
        add_user, delete_user, verify_password,
        LoginDialog, UserManagementDialog
    )
except ImportError:
    # Absolute import (when run as a standalone script)
    from user_management import (
        load_users, save_users,
        add_user, delete_user, verify_password,
        LoginDialog, UserManagementDialog
    )


APP_VERSION = "1.3.7" # Incremented version
COMPANY_NAME = "Energy Waves"
APP_NAME_FOR_SETTINGS = "AntennaTesterApp" # For QSettings

# --- Theme Detection & Management ---
THEME_MODE_KEY = "ui/theme_mode" # QSettings key
THEME_SETTING_AUTO = "auto"
THEME_SETTING_LIGHT = "light"
THEME_SETTING_DARK = "dark"
# --- QSettings Key for Splitter State ---
TEST_PAGE_SPLITTER_STATE_KEY = "ui/main_testing_page_splitter_state"


def _get_system_theme_is_dark(app=None):
    """
    Attempts to detect the system's theme preference.
    Priority: Windows Registry > Palette Heuristic.
    """
    # 1. Windows Registry Check (Primary for Windows)
    if sys.platform == "win32" and winreg:
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            value_name = "AppsUseLightTheme"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
            value, reg_type = winreg.QueryValueEx(key, value_name)
            winreg.CloseKey(key)
            if reg_type == winreg.REG_DWORD:
                # Value is 0 for dark mode apps, 1 for light mode apps
                return value == 0
        except FileNotFoundError:
            logger.info("Windows 'AppsUseLightTheme' registry key not found. Falling back to palette check.")
        except OSError as e:
            logger.warning(f"Error reading Windows theme registry: {e}. Falling back to palette check.")
        # If registry check fails or key not found, fall through to palette check for Windows as well

    # 2. Palette Heuristic (Fallback or for other OS)
    if app is None:
        app = QApplication.instance()
    if app is None:
        logger.warning("Cannot determine system theme (palette check) without a QApplication instance. Defaulting to light.")
        return False

    palette = app.palette()
    window_color = palette.color(QPalette.ColorRole.Window)
    window_text_color = palette.color(QPalette.ColorRole.WindowText)

    # Heuristic: if the background luminance is less than text luminance
    return window_color.lightnessF() < window_text_color.lightnessF()

def get_effective_theme_is_dark(app=None):
    """
    Determines if dark mode should be used, considering manual override first.
    """
    if app is None:
        app = QApplication.instance()
    # Ensure app instance for QSettings, though it should exist by the time this is called normally
    if app is None:
        logger.critical("QApplication instance missing for QSettings in get_effective_theme_is_dark.")
        return _get_system_theme_is_dark(None) # Fallback to system detection without app context if forced

    settings = QSettings(COMPANY_NAME, APP_NAME_FOR_SETTINGS)
    preferred_mode = settings.value(THEME_MODE_KEY, THEME_SETTING_AUTO)

    if preferred_mode == THEME_SETTING_DARK:
        return True
    if preferred_mode == THEME_SETTING_LIGHT:
        return False
    # If "auto", then detect system theme
    return _get_system_theme_is_dark(app)


# --- Helper Function for Styling ---
def apply_stylesheet(app):
    dark_mode = get_effective_theme_is_dark(app) # Use the new effective theme function
    logger.info(f"Applying Stylesheet (Dark Mode Effective: {dark_mode})")

    # Base colors
    bg_color = "#2c3e50" if dark_mode else "#f0f0f0" # Dark blue-gray / Light gray
    text_color = "#ecf0f1" if dark_mode else "#2c3e50" # Light gray / Dark blue-gray
    base_color = "#34495e" if dark_mode else "#ffffff" # Darker blue-gray / White
    border_color = "#7f8c8d" if dark_mode else "#bdc3c7" # Mid-gray / Silver
    highlight_bg = "#3498db" # Blue (used for selection, buttons)
    highlight_text = "#ffffff" # White
    button_hover = "#2980b9" # Darker blue
    button_pressed = "#1f618d" # Even darker blue
    disabled_bg = "#7f8c8d" if dark_mode else "#bdc3c7"
    disabled_text = "#bdc3c7" if dark_mode else "#7f8c8d"
    good_color = "#2ecc71" # Green
    bad_color = "#e74c3c" # Red
    info_color = "#3498db" if not dark_mode else "#5dade2" # Blue / Lighter Blue
    table_header_bg = "#34495e" if dark_mode else "#e0e0e0"
    table_grid = "#4e6a85" if dark_mode else "#e0e0e0"
    row_alt_bg = "#314152" if dark_mode else "#f8f8f8" # Slightly darker/lighter for alt rows

    # Modified Pass/Fail row background colors for better visibility in light mode
    pass_row_bg = "#27ae60" if dark_mode else "#a5d6a7" # Darker Green / More vibrant Light Green (was #d4efdf)
    fail_row_bg = "#c0392b" if dark_mode else "#ef9a9a" # Darker Red / More vibrant Light Red (was #f9ebea)

    verified_cal_bg_color_hex = "#1abc9c" if dark_mode else "#d1f2eb" # Tealish / Light Tealish

    # Specific Colors for Port Status Highlighting (Defined here for consistency)
    testing_bg_color_hex = "#f39c12" if dark_mode else "#fef9e7" # Orange/Light Yellow
    done_bg_color_hex = pass_row_bg # Use pass color
    cal_bg_color_hex = "#8e44ad" if dark_mode else "#f4ecf7" # Purplish
    inactive_bg_color_hex = "#7f8c8d" if dark_mode else "#f2f3f4" # Grayish
    fail_bg_color_hex = fail_row_bg # Use fail color

    bright_text_color_hex = "#ffffff" # White
    dark_text_color_hex = "#2c3e50"   # Dark Gray/Blue

    testing_fg_color_hex = bright_text_color_hex if dark_mode else "#a0522d" # White / Dark brown
    done_fg_color_hex = bright_text_color_hex if dark_mode else "#145a32"    # White / Dark green
    cal_fg_color_hex = bright_text_color_hex if dark_mode else "#5b2c6f"     # White / Dark purple
    inactive_fg_color_hex = "#bdc3c7" if dark_mode else "#707b7c"             # Lighter/Darker Gray text
    fail_fg_color_hex = bright_text_color_hex if dark_mode else "#943126"    # White / Dark red
    verified_cal_fg_color_hex = bright_text_color_hex if dark_mode else "#0e6655" # White / Dark Teal

    # --- Highlight Colors for User Input ---
    highlight_input_border = "#f1c40f" # A distinct yellow/gold color for attention
    highlight_group_border = "#3498db" # Use theme's highlight blue for the group box


    style = f"""
    QMainWindow {{
        background-color: {bg_color};
    }}
    QWidget {{
        font-size: 10pt;
        color: {text_color}; /* Default text color */
    }}
    QLabel {{
        color: {text_color};
        background-color: transparent; /* Ensure labels don't block background */
    }}
    QLineEdit, QComboBox, QListWidget, QTableWidget, QPlainTextEdit {{
        background-color: {base_color};
        color: {text_color};
        border: 1px solid {border_color};
        padding: 5px;
        border-radius: 3px;
        outline: none; /* Remove outline for non-focused state too, just in case */
    }}
     QLineEdit:focus, QComboBox:focus {{
        outline: none; /* Explicitly remove outline when focused */
        /* You might want to keep a visible border change on focus for text inputs */
        border: 1px solid {highlight_bg}; /* Example: use highlight blue border on focus */
    }}
    QListWidget::item:selected, QTableWidget::item:selected {{
        background-color: {highlight_bg};
        color: {highlight_text};
        outline: none; /* Remove outline from selected items */
    }}
     QListWidget:focus, QTableWidget:focus {{
         outline: none; /* Remove outline from the widget itself when focused */
    }}


    QPushButton {{
        background-color: {highlight_bg};
        color: {highlight_text};
        border: none; /* Default border: none */
        padding: 8px 16px;
        border-radius: 4px;
        font-size: 10pt;
        outline: none; /* Remove outline */
    }}
    QPushButton:hover {{
        background-color: {button_hover};
    }}
    QPushButton:pressed {{
        background-color: {button_pressed};
    }}
    QPushButton:disabled {{
        background-color: {disabled_bg};
        color: {disabled_text};
        border: none;
        outline: none;
    }}
    QPushButton:focus {{
        outline: none; /* Explicitly remove outline when focused */
        /* Optional: Add a subtle visual cue for focus if desired, */
        /*           different from the active_input border.        */
        /* Example: background-color: {button_hover}; */
    }}
    QProgressBar {{
        border: 1px solid {border_color};
        border-radius: 3px;
        text-align: center;
        background-color: {base_color};
        color: {text_color}; /* Progress bar text color */
    }}
    QProgressBar::chunk {{
        background-color: {good_color}; /* Green */
        width: 10px;
        margin: 0.5px;
    }}
    QMenuBar {{
        background-color: {table_header_bg}; /* Match header */
        color: {text_color};
    }}
    QMenuBar::item {{
        background: transparent;
    }}
    QMenuBar::item:selected {{
        background-color: {highlight_bg};
        color: {highlight_text};
    }}
    QMenu {{
        background-color: {base_color};
        color: {text_color};
        border: 1px solid {border_color};
    }}
    QMenu::item:selected {{
        background-color: {highlight_bg};
        color: {highlight_text};
    }}
    QGroupBox {{
        color: {text_color}; /* Title color */
        font-weight: bold;
        border: 1px solid {border_color}; /* Default border */
        border-radius: 5px;
        margin-top: 10px;
        padding-top: 20px; /* More space for title inside */
        padding-left: 10px;
        padding-right: 10px;
        padding-bottom: 10px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 5px;
        background-color: {bg_color}; /* Match main background */
        color: {text_color};
        left: 10px;
        top: 3px; /* Adjust vertical position */
        /* Default title weight */
        font-weight: normal;
    }}
    QTableWidget {{
        gridline-color: {table_grid};
        alternate-background-color: {row_alt_bg}; /* Alt row color */
        selection-background-color: {highlight_bg};
        selection-color: {highlight_text};
    }}
    QHeaderView::section {{
        background-color: {table_header_bg};
        color: {text_color};
        padding: 4px;
        border: 1px solid {border_color};
        font-weight: bold;
    }}
    QSplitter::handle {{
        background-color: {border_color};
        height: 3px; /* Adjust thickness */
        width: 3px;
    }}
    QSplitter::handle:horizontal {{
        width: 5px;
    }}
    QSplitter::handle:vertical {{
        height: 5px;
    }}

    /* Status Label Styles */
    #StatusLabelGood {{ color: {good_color}; font-weight: bold; }}
    #StatusLabelBad {{ color: {bad_color}; font-weight: bold; }}
    #StatusLabelInfo {{ color: {info_color}; font-weight: bold; }}

    /* Specific Widget Styles */
    #TitleLabel {{ font-size: 16pt; font-weight: bold; color: {text_color}; margin-bottom: 10px; }}
    #AbortButton {{ background-color: {bad_color}; color: white; /* Always white on red */ border: none; }}
    #AbortButton:hover {{ background-color: #c0392b; /* Darker Red */ }}
    #AbortButton:disabled {{ background-color: {disabled_bg}; color: {disabled_text}; border: none; }}

    /* Result Row Colors (used in add_table_row) */
    /* .PassRow {{ background-color: {pass_row_bg}; }} */ /* No longer used directly as class */
    /* .FailRow {{ background-color: {fail_row_bg}; }} */ /* No longer used directly as class */
    /* Ensure Fail text is visible - this is handled in add_table_row code using setForeground */

    /* Port Status Table Highlighting (Added Specific Styles) */
    .PortStatusTesting {{ background-color: {testing_bg_color_hex}; color: {testing_fg_color_hex}; }}
    .PortStatusDone {{ background-color: {done_bg_color_hex}; color: {done_fg_color_hex}; }}
    .PortStatusCal {{ background-color: {cal_bg_color_hex}; color: {cal_fg_color_hex}; }}
    .PortStatusCalVerified {{ background-color: {verified_cal_bg_color_hex}; color: {verified_cal_fg_color_hex}; }} /* New Style */
    .PortStatusInactive {{ background-color: {inactive_bg_color_hex}; color: {inactive_fg_color_hex}; }}
    .PortStatusFail {{ background-color: {fail_bg_color_hex}; color: {fail_fg_color_hex}; }}

    /* --- Input Highlight Styles --- */
    QGroupBox[active_group="true"] {{
        /* Make the border slightly thicker and use the highlight color */
        border: 2px solid {highlight_group_border};
    }}
    QGroupBox[active_group="true"]::title {{
        font-weight: bold; /* Make title bold */
    }}

    QLineEdit[active_input="true"],
    QComboBox[active_input="true"] {{
        border: 2px solid {highlight_input_border};
        /* Optional: Slightly change background */
        /* background-color: {"#3a506b" if dark_mode else "#e8e8e8"}; */
        outline: none;
    }}
    /* Adjust QLineEdit:focus border if using active_input border */
    QLineEdit:focus[active_input="true"],
    QComboBox:focus[active_input="true"] {{
         border: 2px solid {highlight_input_border}; /* Keep our highlight border */
         outline: none;
    }}
    QLineEdit:focus {{ /* Style for when line edit has focus but NOT active_input */
         border: 1px solid {highlight_bg}; /* Or keep original {border_color} */
         outline: none;
    }}
     QComboBox:focus {{ /* Style for when combo has focus but NOT active_input */
         border: 1px solid {highlight_bg}; /* Or keep original {border_color} */
         outline: none;
    }}

    QPushButton[active_input="true"] {{
         border: 2px solid {highlight_input_border};
         padding: 6px 14px; /* Adjust padding slightly to compensate for border */
         outline: none;
    }}
    /* Make sure the abort button highlight doesn't get overridden */
    #AbortButton[active_input="true"] {{
        border: 2px solid {highlight_input_border};
        padding: 6px 14px; /* Adjust padding slightly */
        outline: none;
    }}
    /* --- End Input Highlight Styles --- */
    """
    app.setStyleSheet(style)

    # Configure pyqtgraph based on theme
    if PYQTGRAPH_AVAILABLE and pg is not None:
        if dark_mode: # dark_mode is from get_effective_theme_is_dark() at the start of this function
            pg.setConfigOption('background', '#34495e') # Match base color
            pg.setConfigOption('foreground', '#ecf0f1') # Match text color
        else:
            pg.setConfigOption('background', 'w') # White
            pg.setConfigOption('foreground', 'k') # Black

# --- LoginDialog and UserManagementDialog are now imported from user_management.py ---

# --- About Dialog (No changes needed, remains in ui_module.py) ---
class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Antenna Tester")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)

        title_label = QLabel("Antenna Tester")
        title_label.setObjectName("TitleLabel") # For potential specific styling
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        app_version = QApplication.instance().applicationVersion() or APP_VERSION # Fallback to constant
        version_label = QLabel(f"Version: {app_version}")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # --- Add Logo instead of Company Text ---
        developer_label = QLabel(f"Developed by:")
        developer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_label = QLabel()
        logo_path = "assets/icons/EW_Logo.png" # Assuming same logo as main UI
        logo_pixmap = QPixmap(logo_path)
        if not logo_pixmap.isNull():
            scaled_logo_pixmap = logo_pixmap.scaledToHeight(64, Qt.SmoothTransformation)
            logo_label.setPixmap(scaled_logo_pixmap)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            # Fallback text if logo not found
            logo_label.setText(f"{COMPANY_NAME}")
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logger.warning(f"About dialog logo not found at {logo_path}. Displaying text.")
        # --- End Add Logo ---

        info_label = QLabel("This application performs automated testing of antenna gain.")
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_label.setWordWrap(True)

        # Use PySide6.QtCore.__version__ for the library version
        try:
            from PySide6.QtCore import __version__ as pyside_version
        except ImportError:
            pyside_version = "N/A" # Fallback if QtCore version isn't directly available
        pyside_label = QLabel(f"Built with PySide6: {pyside_version}")
        pyside_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pyside_label.setStyleSheet("font-size: 9pt; color: gray;")


        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(self.accept)

        layout.addWidget(title_label)
        layout.addWidget(version_label)
        layout.addSpacing(10)
        layout.addWidget(developer_label)
        layout.addWidget(logo_label) # Add the logo label
        layout.addSpacing(15)
        layout.addWidget(info_label)
        layout.addSpacing(15)
        layout.addWidget(pyside_label)
        layout.addWidget(button_box)
        self.setLayout(layout)

# --- Port Selection Dialog (No changes needed, remains in ui_module.py) ---
class PortSelectionDialog(QDialog):
    ports_confirmed = Signal(list) # List of selected port names

    def __init__(self, available_ports, orientation, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Select Ports for Testing ({orientation})")
        self.setMinimumWidth(350)
        self.setModal(True)

        self.available_ports = available_ports

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Select the {orientation} ports to include in the test:"))

        self.port_list_widget = QListWidget()
        # Changed selection mode to allow checking without row highlight interference
        self.port_list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

        for port in self.available_ports:
            item = QListWidgetItem(port)
            # Ensure the item is checkable
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # Default to checked state
            item.setCheckState(Qt.CheckState.Checked)
            self.port_list_widget.addItem(item)

        layout.addWidget(self.port_list_widget)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.confirm_selection)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def confirm_selection(self):
        selected_ports = []
        for i in range(self.port_list_widget.count()):
            item = self.port_list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected_ports.append(item.text())

        if not selected_ports:
            QMessageBox.warning(self, "No Ports Selected", "Please select at least one port to test.")
            return

        self.ports_confirmed.emit(selected_ports)
        self.accept()
# --- Main UI Window (Incorporating all requested changes) ---
class UiMainWindow(QMainWindow):
    # --- Signals ---
    request_antenna_configs = Signal()
    antenna_selected = Signal(str)
    orientation_selected = Signal(str) # Emits name of orientation ("Horizontal" or "Vertical")
    ports_selected_for_test = Signal(list) # Emits list of port names selected by user
    start_port_selected_for_testing = Signal(str) # Emits the name of the first port chosen by user to start with
    # Calibration signals (include port name)
    request_golden_sample_calibration = Signal(str) # port_name
    golden_sample_scan_received = Signal(str, str) # scanned_sn, port_name
    start_golden_measurement = Signal(str) # port_name
    request_silver_sample_calibration = Signal(str) # port_name
    silver_sample_scan_received = Signal(str, str) # scanned_sn, port_name
    start_silver_measurement = Signal(str) # port_name
    # Testing signals
    order_info_received = Signal(str, str, int) # order_number, charge_number, quantity
    antenna_sn_scan_received = Signal(str, str) # SN, port_name (send port context too)
    retry_test_confirmed = Signal(bool, str) # retry?, serial_number (to re-add if needed)
    start_antenna_test_for_port = Signal(str) # port_name (to start the measurement loop for that port)
    # Workflow control signals
    port_batch_run_complete = Signal(str) # Emits port_name when its batch (all antennas) is done
    request_test_next_port = Signal() # NEW: User clicked "TEST NEXT PORT"
    request_test_next_order = Signal() # NEW: User clicked "TEST NEXT ORDER"
    request_finish_measurements = Signal() # NEW: User clicked "FINISH MEASUREMENTS"
    abort_test_requested = Signal()
    request_retest_failed_unit = Signal(str, str) # NEW: port_name, serial_number for retest
    # User management signals
    request_user_list_update = Signal() # Request main app reload users (after admin changes)
    request_login_change = Signal() # NEW: User wants to log in as someone else
    exit_application = Signal()
    # NEW signal to tell main app to load historical order status
    request_load_order_history = Signal(str) # order_number

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Antenna Tester")
        # --- Set Application Icon ---
        icon = QIcon()
        icon_base_path = "assets/icons/"
        try:
            # Add various sizes
            sizes = ["16", "32", "48", "64", "256"]
            for size in sizes:
                icon_path = os.path.join(icon_base_path, f"app_icon_{size}.png")
                if os.path.exists(icon_path):
                    icon.addPixmap(QPixmap(icon_path), QIcon.Mode.Normal, QIcon.State.Off)
                else:
                    logger.warning(f"Icon file not found: {icon_path}")

            if not icon.isNull():
                self.setWindowIcon(icon) # Sets icon for window title bar
                QApplication.setWindowIcon(icon) # Also try setting it for the application globally
                logger.info("Application window icon set successfully.")
            else:
                logger.warning("No valid icon pixmaps were loaded.")

        except Exception as e:
            logger.warning(f"Could not set application icon - {e}.", exc_info=True)
        # --- End Set Application Icon ---

        # --- Windows-specific Taskbar Icon Fix (when running .py directly) ---
        if sys.platform == "win32":
            try:
                import ctypes
                # Create an AppUserModelID. This should be unique for your app.
                # Format: CompanyName.ProductName.SubProduct.VersionInformation
                # Using your existing constants for consistency.
                myappid = f'{COMPANY_NAME.replace(" ", "")}.{APP_NAME_FOR_SETTINGS}.Tester.1'
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
                logger.info(f"Windows AppUserModelID set to: {myappid}")

                # This part is often what helps the taskbar icon update properly with setWindowIcon
                # when a custom AppUserModelID is used.
                # Ensure the QIcon used for QApplication.setWindowIcon() has a good high-res version.
            except ImportError:
                logger.warning("ctypes module not found. Cannot set AppUserModelID for Windows taskbar icon.")
            except AttributeError:
                logger.warning("Failed to set AppUserModelID (ctypes.windll.shell32 might be missing or SetCurrentProcessExplicitAppUserModelID).")
            except Exception as e:
                logger.error(f"Error setting AppUserModelID: {e}", exc_info=True)
        # --- End Windows-specific Taskbar Icon Fix ---

        # --- QSettings for theme preference ---
        self.settings = QSettings(COMPANY_NAME, APP_NAME_FOR_SETTINGS)
        self._current_theme_setting = self.settings.value(THEME_MODE_KEY, THEME_SETTING_AUTO)

        # --- Internal State ---
        self._users = {} # Loaded later
        self._current_user = None
        self._is_admin = False
        self._antenna_configs = {} # Loaded by main app
        self._selected_antenna_name = None
        self._selected_antenna_pn = None
        self._selected_orientation = None
        self._ports_for_current_orientation = [] # All possible ports for H or V config
        self._ports_to_test = []                 # Ports actively selected (checked) by user for this run
        self._current_test_port = None           # Port currently being calibrated or tested
        self._current_overall_port_index = -1    # Tracks index within _ports_to_test (mainly for UI reference, main app manages queue)
        self._current_order_number = ""
        self._current_charge_number = "" 
        self._current_order_quantity = 0
        self._tested_in_current_port_batch = 0   # Count tested for the CURRENT port's batch
        self._passed_in_current_port_batch = 0   # Count passed for CURRENT port's batch
        self._tested_in_current_order = 0 # Count *port tests* across all ports for the current order (keep for port FPY)
        self._passed_in_current_order = 0 # Count *passed port tests* across all ports for the current order (keep for port FPY)
        self._completed_ports_in_run = 0         # Count of ports whose batches are fully complete in this run
        self._current_antenna_sn_under_test = None # SN currently being processed/measured
        self._test_running = False               # Flag: Is a measurement (Golden/Silver/Antenna) actively running?
        self._current_stage = "Login"            # Tracks the current UI state/step
        self._port_status_data = {}              # Cache for port status table: {port: {"selected": bool, "status": str}}

        # --- NEW State for Antenna Order Pass/Fail Tracking ---
        self._antenna_status_this_order = {}
        self._passed_antennas_in_order = 0
        self._failed_antennas_in_order = 0

        # --- State for Input Highlighting ---
        self._highlighted_group = None
        self._highlighted_widget = None

        # --- NEW State for Recalibration Timer ---
        self._RECALIBRATION_TIME_SECONDS = 180 # 3 minutes for demo
        self._port_calibration_timestamps = {} # {port_name: datetime_object_of_last_successful_silver_cal}

        # --- Splitter for Test Page ---
        self.bottom_splitter = None # Will be initialized in _create_main_testing_page


        # Internal Plot Data Storage
        self._current_plot_x = []
        self._current_plot_y = []
        self._current_limit_x = []
        self._current_limit_y_upper = []
        self._current_limit_y_lower = []

        # --- Load Users Early ---
        self._users = load_users()

        # Main Widget and Layout
        self.central_widget = QWidget()
        self.main_layout = QVBoxLayout(self.central_widget)
        self.setCentralWidget(self.central_widget)

        # StackedWidget
        self.stacked_widget = QStackedWidget()
        self.main_layout.addWidget(self.stacked_widget)

        # Create pages
        self._create_initial_placeholder_page()
        self._create_antenna_selection_page()
        self._create_main_testing_page() # Creates structure including tracker panel

        # Add initial pages to stack
        self.stacked_widget.addWidget(self.placeholder_page)
        self.stacked_widget.addWidget(self.antenna_page)
        self.stacked_widget.addWidget(self.test_page)

        # Menu Bar
        self._create_menu() # This will also update theme menu state

        # Status Bar
        self.status_bar = self.statusBar()
      
        # --- NEW: Database Status Label ---
        # We need two labels: one for the icon, one for the text
        self.db_status_icon_label = QLabel()
        self.db_status_icon_label.setToolTip("Database connection status")
        self.db_status_text_label = QLabel()
        self.db_status_text_label.setToolTip("Database connection status")
        
        self.status_bar.addPermanentWidget(self.db_status_icon_label) # Add the icon label
        self.status_bar.addPermanentWidget(self.db_status_text_label) # Add the text label next to it
        # --- END NEW ---
        self.status_bar_label = QLabel("Initializing...")
        self.status_bar.addPermanentWidget(self.status_bar_label) # This is now to the right of the DB status

    
        self.status_bar.showMessage("Please log in.", 5000)

        # Delayed Actions
        QTimer.singleShot(10, lambda: self.set_database_status(None, "Initializing...")) # Set initial DB status
        QTimer.singleShot(50, self._initial_theme_setup) # Apply theme based on settings
        QTimer.singleShot(100, self.show_login_dialog)

    # Add property
    @property
    def current_user(self):
        """Provides read-only access to the currently logged-in username."""
        return self._current_user

    def _initial_theme_setup(self):
        """Apply stylesheet and graph settings after app instance exists."""
        apply_stylesheet(QApplication.instance()) # Uses get_effective_theme_is_dark
        self._configure_graph_theme() # Apply pyqtgraph theme settings

    def _configure_graph_theme(self):
         """Sets the pyqtgraph theme based on detected mode."""
         if PYQTGRAPH_AVAILABLE and hasattr(self, 'plot_widget') and self.plot_widget is not None:
             dark_mode = get_effective_theme_is_dark(QApplication.instance()) # Use effective theme
             bg = '#34495e' if dark_mode else 'w'
             fg = '#ecf0f1' if dark_mode else 'k'
             self.plot_widget.setBackground(bg)
             logger.info(f"Configuring graph theme (Dark Effective: {dark_mode}) Background: {bg}")
             # Force redraw/update if necessary
             if hasattr(self.plot_widget, 'getPlotItem'):
                 self.plot_widget.getPlotItem().getViewBox().update()

    # ... (_create_menu will be modified)
    def _create_menu(self):
        menu_bar = self.menuBar()
        # File Menu
        file_menu = menu_bar.addMenu("&File")
        exit_action = QAction(QIcon.fromTheme("application-exit"), "&Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View Menu (for Theme Selection)
        view_menu = menu_bar.addMenu("&View")
        self.theme_action_group = QActionGroup(self)
        self.theme_action_group.setExclusive(True)

        self.theme_auto_action = QAction("Auto-detect Theme", self, checkable=True)
        self.theme_auto_action.triggered.connect(lambda: self._set_theme_preference(THEME_SETTING_AUTO))
        self.theme_action_group.addAction(self.theme_auto_action)

        self.theme_light_action = QAction("Light Theme", self, checkable=True)
        self.theme_light_action.triggered.connect(lambda: self._set_theme_preference(THEME_SETTING_LIGHT))
        self.theme_action_group.addAction(self.theme_light_action)

        self.theme_dark_action = QAction("Dark Theme", self, checkable=True)
        self.theme_dark_action.triggered.connect(lambda: self._set_theme_preference(THEME_SETTING_DARK))
        self.theme_action_group.addAction(self.theme_dark_action)

        view_menu.addActions(self.theme_action_group.actions())
        self._update_theme_menu_state() # Set initial check state based on loaded QSettings

        # User Menu
        self.user_menu = menu_bar.addMenu("&Users")
        self.login_change_action = QAction("Login As Different User...", self)
        self.login_change_action.triggered.connect(self._on_login_as_different_user_clicked)
        self.login_change_action.setEnabled(False) # Enable after initial login
        self.user_menu.addAction(self.login_change_action)
        self.user_menu.addSeparator()
        manage_users_action = QAction(QIcon.fromTheme("preferences-system-users"), "Manage Users", self)
        manage_users_action.triggered.connect(self.show_user_management_dialog)
        self.manage_users_action = manage_users_action # Store reference
        self.user_menu.addAction(manage_users_action)
        self.manage_users_action.setEnabled(False) # Disabled until admin login

        # Help Menu
        help_menu = menu_bar.addMenu("&Help")
        about_action = QAction(QIcon.fromTheme("help-about"), "&About", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

    def _set_theme_preference(self, theme_mode):
        self.settings.setValue(THEME_MODE_KEY, theme_mode)
        self._current_theme_setting = theme_mode # Update internal state
        self._update_theme_menu_state() # Reflect change in menu

        # Re-apply styles and graph theme
        apply_stylesheet(QApplication.instance())
        self._configure_graph_theme()

        # If dummy PlotWidget is shown, its label color might need update too.
        # This is a minor detail as it's only for when pyqtgraph is missing.
        # We can re-create it or update its palette if it becomes an issue.
        # For now, focusing on the main UI and actual graph.

    def _update_theme_menu_state(self):
        if self._current_theme_setting == THEME_SETTING_AUTO:
            self.theme_auto_action.setChecked(True)
        elif self._current_theme_setting == THEME_SETTING_LIGHT:
            self.theme_light_action.setChecked(True)
        elif self._current_theme_setting == THEME_SETTING_DARK:
            self.theme_dark_action.setChecked(True)
        else: # Default to auto if setting is somehow invalid
            self.theme_auto_action.setChecked(True)
            self.settings.setValue(THEME_MODE_KEY, THEME_SETTING_AUTO)
            self._current_theme_setting = THEME_SETTING_AUTO


    def _create_initial_placeholder_page(self):
        self.placeholder_page = QWidget()
        layout = QVBoxLayout(self.placeholder_page)
        label = QLabel("Please log in to start.")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFont(QFont("Arial", 16))
        layout.addWidget(label)
        layout.addStretch()

    def _create_antenna_selection_page(self):
        self.antenna_page = QWidget()
        layout = QVBoxLayout(self.antenna_page)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter) # Center content
        layout.setContentsMargins(50, 20, 50, 20) # Add some padding

        title = QLabel("Select Antenna for Testing")
        title.setObjectName("TitleLabel")
        layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(10)

        layout.addWidget(QLabel("Available Antenna Configurations:"), alignment=Qt.AlignmentFlag.AlignLeft)
        self.antenna_list_widget = QListWidget()
        self.antenna_list_widget.itemSelectionChanged.connect(self._enable_antenna_selection_button)
        self.antenna_list_widget.setMaximumWidth(400) # Limit width for better centering
        layout.addWidget(self.antenna_list_widget, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(15)

        self.select_antenna_button = QPushButton("Select Antenna and Continue")
        self.select_antenna_button.setEnabled(False)
        self.select_antenna_button.clicked.connect(self._on_antenna_selected)
        self.select_antenna_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed) # Limit button size
        layout.addWidget(self.select_antenna_button, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch()

    def _enable_antenna_selection_button(self):
        self.select_antenna_button.setEnabled(bool(self.antenna_list_widget.selectedItems()))

    # ... (_create_main_testing_page, _create_input_groups, _hide_all_input_groups, _set_active_input_highlight remain the same)
    def _create_main_testing_page(self):
        """Creates the main testing page with Active Details Panel."""
        self.test_page = QWidget()
        main_layout = QHBoxLayout(self.test_page)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(10)

        # --- Left Side: Active Test Details & Port Status ---
        left_panel_widget = QWidget()
        left_panel_layout = QVBoxLayout(left_panel_widget)
        left_panel_layout.setContentsMargins(0, 0, 0, 0)


        # --- Add Logo directly to the left_panel_layout ---
        logo_label = QLabel()
        logo_path = "assets/icons/HS_Logo_blue.png"
        logo_pixmap = QPixmap(logo_path)
        if not logo_pixmap.isNull():
            scaled_logo_pixmap = logo_pixmap.scaledToHeight(64, Qt.SmoothTransformation)
            logo_label.setPixmap(scaled_logo_pixmap )
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_label.setContentsMargins(0, 5, 0, 10) # Add some margin: top, bottom
            left_panel_layout.addWidget(logo_label) # Add logo to the main left panel layout
        else:
            logger.warning(f"Could not load logo: {logo_path}")
        # --- End Add Logo ---


        details_group = QGroupBox("Active Test Details")
        details_layout = QFormLayout()
        details_layout.setContentsMargins(10, 15, 10, 10) # Adjust padding
        details_layout.setSpacing(8)
        self.detail_user_label = QLabel("-")
        self.detail_antenna_label = QLabel("-")
        self.detail_pn_label = QLabel("-")
        self.detail_sn_label = QLabel("-") # Currently testing SN
        self.detail_order_label = QLabel("-")
        self.detail_charge_label = QLabel("-") 
        self.detail_orientation_label = QLabel("-")

        # --- NEW Pass/Fail Order Labels ---
        self.detail_passed_order_label = QLabel("Order Passed: 0")
        self.detail_failed_order_label = QLabel("Order Failed: 0")
        # --- End NEW ---

        details_layout.addRow("Operator:", self.detail_user_label)
        details_layout.addRow("Antenna:", self.detail_antenna_label)
        details_layout.addRow("Part Number:", self.detail_pn_label)
        details_layout.addRow("Order Number:", self.detail_order_label)
        details_layout.addRow("Charge Number:", self.detail_charge_label) # NEW: Add to layout
        details_layout.addRow("Orientation:", self.detail_orientation_label)
        details_layout.addRow("Current SN:", self.detail_sn_label)
        details_layout.addRow(QLabel(" ")) # Spacer
        # --- ADD NEW Labels to Layout ---
        details_layout.addRow(self.detail_passed_order_label)
        details_layout.addRow(self.detail_failed_order_label)
        # --- End ADD ---

        details_group.setLayout(details_layout)
        left_panel_layout.addWidget(details_group)

        port_status_group = QGroupBox("Port Status")
        port_status_layout = QVBoxLayout()
        port_status_layout.setContentsMargins(5, 15, 5, 5)
        self.port_status_table = QTableWidget()
        self.port_status_table.setColumnCount(3) # Port, Selected, Status
        self.port_status_table.setHorizontalHeaderLabels(["Port", "Selected", "Status"])
        self.port_status_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.port_status_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.port_status_table.verticalHeader().setVisible(False)
        self.port_status_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.port_status_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) # Port name fixed
        self.port_status_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents) # Selected fixed
        self.port_status_table.setAlternatingRowColors(True)
        port_status_layout.addWidget(self.port_status_table)
        port_status_group.setLayout(port_status_layout)
        left_panel_layout.addWidget(port_status_group)
        left_panel_layout.addStretch() # Push groups up

        # Set fixed or maximum width for the left panel
        left_panel_widget.setFixedWidth(300) # Adjust width as needed
        main_layout.addWidget(left_panel_widget)

        # --- Right Side: Controls, Graph, Table ---
        right_panel_widget = QWidget()
        right_panel_layout = QVBoxLayout(right_panel_widget)
        right_panel_layout.setContentsMargins(0, 0, 0, 0)

        # Top section: Status, Progress, Stats, Actions
        top_right_widget = QWidget()
        top_right_layout = QVBoxLayout(top_right_widget)
        top_right_layout.setContentsMargins(0,0,0,5)

        # -- Status Display --
        self.status_display_label = QLabel("STATUS: Waiting to start...")
        self.status_display_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_display_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.status_display_label.setWordWrap(True)
        self.status_display_label.setMinimumHeight(40) # Give it some space
        top_right_layout.addWidget(self.status_display_label)

        # -- Progress Bar --
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 11) # Default range for measurements
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        top_right_layout.addWidget(self.progress_bar)

        # -- Statistics (Port Level) --
        stats_widget = QWidget()
        stats_layout = QHBoxLayout(stats_widget)
        stats_layout.setContentsMargins(0, 5, 0, 5)
        self.tested_port_label = QLabel("Tested (Port): 0 / 0") # Renamed
        self.fpy_port_label = QLabel("FPY (Port): N/A")       # Renamed
        stats_layout.addWidget(self.tested_port_label)
        stats_layout.addStretch()
        stats_layout.addWidget(self.fpy_port_label)
        top_right_layout.addWidget(stats_widget)

        # -- Input/Action Area --
        self.input_action_widget = QWidget() # Container for the dynamic groups
        self.input_action_layout = QVBoxLayout(self.input_action_widget)
        self.input_action_layout.setContentsMargins(0, 0, 0, 0) # No margins inside the container
        self.input_action_layout.setSpacing(5) # Spacing between group boxes
        self.input_action_widget.setMinimumHeight(150) # MODIFIED: Increased height for new field
        self.input_action_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._create_input_groups() # Create all input group widgets
        top_right_layout.addWidget(self.input_action_widget) # Add the fixed-height container

        right_panel_layout.addWidget(top_right_widget) # Add the top section

        # Bottom section: Splitter for Graph/Table
        self.bottom_splitter = QSplitter(Qt.Orientation.Vertical) # Store as instance variable

        # -- Graph --
        graph_group = QGroupBox("Antenna Gain vs. Frequency")
        graph_layout = QVBoxLayout()
        if PYQTGRAPH_AVAILABLE and pg is not None:
            self.plot_widget = pg.PlotWidget()
            # _configure_graph_theme will be called after UI is fully set up
            self.plot_widget.showGrid(x=True, y=True)
            self.plot_widget.setLabel('left', 'Antenna Gain', units='dBi')
            self.plot_widget.setLabel('bottom', 'Frequency', units='GHz')
            self.plot_curve = self.plot_widget.plot(pen=pg.mkPen('#3498db', width=2), name="Measurement")
            self.upper_limit_curve = self.plot_widget.plot(pen=pg.mkPen('#e74c3c', width=2, style=Qt.PenStyle.DashLine), name="Upper Limit")
            self.lower_limit_curve = self.plot_widget.plot(pen=pg.mkPen('#e74c3c', width=2, style=Qt.PenStyle.DashLine), name="Lower Limit")
            self.plot_widget.addLegend(offset=(-10, 10))
            graph_layout.addWidget(self.plot_widget)
        else:
            # Dummy plot widget creation remains the same
            self.plot_widget = PlotWidget() # DummyWidget defined if pyqtgraph missing
            self.plot_curve = self.plot_widget.plot()
            self.upper_limit_curve = self.plot_widget.plot()
            self.lower_limit_curve = self.plot_widget.plot()
            graph_layout.addWidget(self.plot_widget)
        graph_group.setLayout(graph_layout)
        self.bottom_splitter.addWidget(graph_group)

        # -- Results Table --
        table_group = QGroupBox("Test Results History")
        table_layout = QVBoxLayout()
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(12)
        self.results_table.setHorizontalHeaderLabels([
             "Timestamp", "Order Number", "ID", "Serial Number", "Port", "Freq (GHz)",
             "Ant Gain (dBi)", "Limits", "Ant Meas (dBm)", "Golden Meas (dBm)",
             "Spec Gain (dBi)", "Status"
        ])
        # Table properties remain the same
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setAlternatingRowColors(True)

        # --- Modified Column Resizing ---
        header = self.results_table.horizontalHeader()

        # Start by setting ResizeToContents for all columns.
        for i in range(self.results_table.columnCount()):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        # Apply specific overrides
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)     # SN stretch
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)  # Order Number
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)  # ID
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)  # Ant Gain (dBi)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Interactive)  # Limits
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.Interactive)  # Ant Meas (dBm)
        header.setSectionResizeMode(9, QHeaderView.ResizeMode.Interactive)  # Golden Meas (dBm)
        header.setSectionResizeMode(10, QHeaderView.ResizeMode.Interactive) # Spec Gain (dBi)

        # --- Add these lines to set INITIAL widths ---
        # Adjust pixel values as needed based on your font/display
        initial_measurement_width = 130 # Pixels for the measurement columns
        initial_gain_width = 110        # Pixels for the gain column

        header.resizeSection(8, initial_measurement_width -20) # Ant Meas (dBm)
        header.resizeSection(9, initial_measurement_width) # Golden Meas (dBm)
        header.resizeSection(10, initial_gain_width)       # Spec Gain (dBi)
        # --- End Add ---

        # Other columns retain ResizeToContents or Stretch

        # --- End Modified Column Resizing ---


        table_layout.addWidget(self.results_table)
        table_group.setLayout(table_layout)
        self.bottom_splitter.addWidget(table_group)

        self.bottom_splitter.setStretchFactor(0, 1) 
        self.bottom_splitter.setStretchFactor(1, 4) 
        right_panel_layout.addWidget(self.bottom_splitter)

        # --- Load and Connect Splitter State ---
        saved_splitter_state = self.settings.value(TEST_PAGE_SPLITTER_STATE_KEY)
        if saved_splitter_state is not None:
            try:
                if self.bottom_splitter.restoreState(saved_splitter_state):
                    logger.info("UI: Restored test page splitter state successfully.")
                else:
                    logger.warning(f"UI: Failed to restore test page splitter state. Using default sizes. Value type: {type(saved_splitter_state)}")
            except Exception as e:
                logger.error(f"UI: Exception during splitter state restoration: {e}. Using default sizes.", exc_info=True)
        else:
            logger.info("UI: No saved test page splitter state found. Using default sizes.")
        
        self.bottom_splitter.splitterMoved.connect(self._save_test_page_splitter_state)
        # --- End Splitter State Handling ---


        # Add Abort Button
        self.abort_button = QPushButton("Abort Test")
        self.abort_button.setObjectName("AbortButton")
        self.abort_button.clicked.connect(self._on_abort_clicked)
        self.abort_button.setEnabled(False) # Initially disabled, enabled when test page is active
        self.abort_button.setFixedHeight(40)
        right_panel_layout.addWidget(self.abort_button)

        right_panel_widget.setLayout(right_panel_layout)
        main_layout.addWidget(right_panel_widget)

        self.test_page.setLayout(main_layout)

    def _create_input_groups(self):
        """Creates the individual group widgets for the input area."""
        while self.input_action_layout.count():
            child = self.input_action_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # --- 1. Orientation Selection ---
        self.orientation_group = QGroupBox("1. Select Jig Orientation")
        orient_layout = QHBoxLayout()
        self.rb_horizontal = QRadioButton("Horizontal")
        self.rb_vertical = QRadioButton("Vertical")
        self.rb_horizontal.setChecked(True)
        confirm_orient_button = QPushButton("Confirm Orientation")
        confirm_orient_button.clicked.connect(self._on_orientation_confirmed)
        orient_layout.addWidget(self.rb_horizontal)
        orient_layout.addWidget(self.rb_vertical)
        orient_layout.addStretch()
        orient_layout.addWidget(confirm_orient_button)
        self.orientation_group.setLayout(orient_layout)
        self.input_action_layout.addWidget(self.orientation_group)

        # --- 2. Select Starting Port ---
        self.select_start_port_group = QGroupBox("2. Select Starting Port")
        start_port_layout = QHBoxLayout()
        self.start_port_combo = QComboBox()
        start_port_button = QPushButton("Start with this Port")
        start_port_layout.addWidget(QLabel("Start Test with:"))
        start_port_layout.addWidget(self.start_port_combo, 1)
        start_port_layout.addWidget(start_port_button)
        self.select_start_port_group.setLayout(start_port_layout)
        self.input_action_layout.addWidget(self.select_start_port_group)
        start_port_button.clicked.connect(self._on_start_port_selected)


        # --- 3. Golden Sample Scan ---
        self.golden_scan_group = QGroupBox("3. Calibrate Port: Scan GOLDEN")
        golden_layout = QHBoxLayout()
        self.sn_input_golden = QLineEdit()
        self.sn_input_golden.setPlaceholderText("Scan Golden SN...")
        confirm_golden_button = QPushButton("Confirm SN")
        confirm_golden_button.setMinimumWidth(100) 
        golden_layout.addWidget(self.sn_input_golden, 1)
        golden_layout.addWidget(confirm_golden_button)
        self.golden_scan_group.setLayout(golden_layout)
        self.input_action_layout.addWidget(self.golden_scan_group)
        self.sn_input_golden.returnPressed.connect(self._on_golden_sn_entered)
        confirm_golden_button.clicked.connect(self._on_golden_sn_entered)

        # --- 4. Start Golden Measurement ---
        self.start_golden_group = QGroupBox("4. Calibrate Port: Start GOLDEN Meas.")
        start_golden_layout = QVBoxLayout()
        self.start_golden_button = QPushButton("Start GOLDEN Measurement")
        self.start_golden_button.clicked.connect(self._on_start_golden_measurement)
        start_golden_layout.addWidget(self.start_golden_button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.start_golden_group.setLayout(start_golden_layout)
        self.input_action_layout.addWidget(self.start_golden_group)

        # --- 5. Silver Sample Scan ---
        self.silver_scan_group = QGroupBox("5. Calibrate Port: Scan SILVER")
        silver_layout = QHBoxLayout()
        self.sn_input_silver = QLineEdit()
        self.sn_input_silver.setPlaceholderText("Scan Silver SN...")
        confirm_silver_button = QPushButton("Confirm SN")
        confirm_silver_button.setMinimumWidth(100) 
        silver_layout.addWidget(self.sn_input_silver, 1)
        silver_layout.addWidget(confirm_silver_button)
        self.silver_scan_group.setLayout(silver_layout)
        self.input_action_layout.addWidget(self.silver_scan_group)
        self.sn_input_silver.returnPressed.connect(self._on_silver_sn_entered)
        confirm_silver_button.clicked.connect(self._on_silver_sn_entered)

        # --- 6. Start Silver Measurement ---
        self.start_silver_group = QGroupBox("6. Calibrate Port: Start SILVER Meas.")
        start_silver_layout = QVBoxLayout()
        self.start_silver_button = QPushButton("Start SILVER Measurement")
        self.start_silver_button.clicked.connect(self._on_start_silver_measurement)
        start_silver_layout.addWidget(self.start_silver_button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.start_silver_group.setLayout(start_silver_layout)
        self.input_action_layout.addWidget(self.start_silver_group)

        # --- 7. Enter Order Info ---
        self.order_info_group = QGroupBox("7. Enter Production Order")
        order_layout = QFormLayout()
        self.order_number_input = QLineEdit()
        self.charge_number_input = QLineEdit() 
        self.order_quantity_input = QLineEdit()
        self.order_number_input.setPlaceholderText("Scan or type Order Number")
        self.charge_number_input.setPlaceholderText("Enter Charge Number") 
        self.order_quantity_input.setPlaceholderText("Enter quantity (e.g., 50)")
        self.confirm_order_button = QPushButton("Confirm Order")
        order_layout.addRow("Order Number:", self.order_number_input)
        order_layout.addRow("Charge Number:", self.charge_number_input) 
        order_layout.addRow("Quantity:", self.order_quantity_input)
        order_layout.addRow(self.confirm_order_button)
        self.order_info_group.setLayout(order_layout)
        self.input_action_layout.addWidget(self.order_info_group)
        self.confirm_order_button.clicked.connect(self._on_order_info_entered)
        self.order_number_input.returnPressed.connect(self.charge_number_input.setFocus)
        self.charge_number_input.returnPressed.connect(self.order_quantity_input.setFocus)
        self.order_quantity_input.returnPressed.connect(self._on_order_info_entered)


        # --- 8. Scan Antenna SN ---
        self.antenna_scan_group = QGroupBox("8. Test Port X: Scan Antenna")
        antenna_scan_layout = QVBoxLayout()
        antenna_scan_layout.setContentsMargins(10, 10, 10, 10)
        antenna_scan_layout.setSpacing(10)

        self.antenna_scan_label = QLabel("Scan Antenna Serial Number (1 of N):")
        scan_hbox = QHBoxLayout()
        scan_hbox.setSpacing(10)

        self.sn_input_antenna = QLineEdit()
        self.sn_input_antenna.setPlaceholderText("Scan antenna SN...")
        self.sn_input_antenna.setMinimumWidth(200)
        self.sn_input_antenna.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        confirm_antenna_button = QPushButton("Confirm SN")
        confirm_antenna_button.setMinimumWidth(100)
        confirm_antenna_button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        scan_hbox.addWidget(self.sn_input_antenna, 2)
        scan_hbox.addWidget(confirm_antenna_button, 1)

        antenna_scan_layout.addWidget(self.antenna_scan_label)
        antenna_scan_layout.addLayout(scan_hbox)
        self.antenna_scan_group.setLayout(antenna_scan_layout)
        self.input_action_layout.addWidget(self.antenna_scan_group)

        self.sn_input_antenna.returnPressed.connect(self._on_antenna_sn_entered)
        confirm_antenna_button.clicked.connect(self._on_antenna_sn_entered)

        # --- 9. Start Antenna Test ---
        self.start_antenna_test_group = QGroupBox("9. Test Port X: Start Test")
        start_antenna_layout = QVBoxLayout()
        self.start_antenna_test_button = QPushButton("Start Test for SN: ...")
        self.start_antenna_test_button.clicked.connect(self._on_start_antenna_test)
        start_antenna_layout.addWidget(self.start_antenna_test_button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.start_antenna_test_group.setLayout(start_antenna_layout)
        self.input_action_layout.addWidget(self.start_antenna_test_group)

        # --- 10. Next Action (Replaces AskContinue and BatchComplete) ---
        self.next_action_group = QGroupBox("Order Progress") # Renamed
        next_action_layout = QVBoxLayout()
        self.next_action_label = QLabel("Port X testing complete. Choose next action.") # Dynamic text
        self.next_action_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_action_label.setWordWrap(True)
        next_action_hbox = QHBoxLayout()

        # NEW BUTTONS
        self.test_next_port_button = QPushButton("TEST NEXT PORT")
        self.test_next_order_button = QPushButton("TEST NEXT ORDER")
        self.finish_measurements_button = QPushButton("FINISH MEASUREMENTS")

        next_action_hbox.addStretch()
        next_action_hbox.addWidget(self.test_next_port_button)
        next_action_hbox.addWidget(self.test_next_order_button)
        next_action_hbox.addWidget(self.finish_measurements_button)
        next_action_hbox.addStretch()

        next_action_layout.addWidget(self.next_action_label)
        next_action_layout.addSpacing(10)
        next_action_layout.addLayout(next_action_hbox)
        self.next_action_group.setLayout(next_action_layout)
        self.input_action_layout.addWidget(self.next_action_group)

        # Connect new buttons
        self.test_next_port_button.clicked.connect(self._on_test_next_port_clicked)
        self.test_next_order_button.clicked.connect(self._on_test_next_order_clicked)
        self.finish_measurements_button.clicked.connect(self._on_test_finish_measurements_clicked)

        # Hide all groups initially
        self._hide_all_input_groups()

    def _hide_all_input_groups(self):
        """Helper to hide all group box widgets in the input action layout."""
        for i in range(self.input_action_layout.count()):
            item = self.input_action_layout.itemAt(i)
            widget = item.widget()
            if widget and isinstance(widget, QGroupBox): # Ensure we only hide GroupBoxes
                widget.setVisible(False)

    def _set_active_input_highlight(self, group=None, widget=None):
        """Clears previous highlights and applies new ones to the specified group/widget."""
        # Clear previous highlights
        if self._highlighted_group and self._highlighted_group != group:
            self._highlighted_group.setProperty("active_group", False)
            self._highlighted_group.style().unpolish(self._highlighted_group)
            self._highlighted_group.style().polish(self._highlighted_group)
            # Also update the title style if necessary
            title_widget = self._highlighted_group.findChild(QWidget, "qt_groupbox_label") # Find title label by object name if set, else look for QLabel
            if title_widget:
                title_widget.style().unpolish(title_widget)
                title_widget.style().polish(title_widget)

        if self._highlighted_widget and self._highlighted_widget != widget:
            self._highlighted_widget.setProperty("active_input", False)
            self._highlighted_widget.style().unpolish(self._highlighted_widget)
            self._highlighted_widget.style().polish(self._highlighted_widget)

        # Apply new highlights
        self._highlighted_group = group
        self._highlighted_widget = widget

        if self._highlighted_group:
            self._highlighted_group.setProperty("active_group", True)
            self._highlighted_group.style().unpolish(self._highlighted_group)
            self._highlighted_group.style().polish(self._highlighted_group)
            # Also update the title style if necessary
            title_widget = self._highlighted_group.findChild(QWidget, "qt_groupbox_label")
            if title_widget:
                title_widget.style().unpolish(title_widget)
                title_widget.style().polish(title_widget)


        if self._highlighted_widget:
            self._highlighted_widget.setProperty("active_input", True)
            self._highlighted_widget.style().unpolish(self._highlighted_widget)
            self._highlighted_widget.style().polish(self._highlighted_widget)

    def _setup_input_area(self, stage):
        """Configures the input/action area by showing/hiding groups based on the stage."""
        self._current_stage = stage
        logger.debug(f"UI Stage: {stage} (Current Port: {self._current_test_port}, Order: {self._current_order_number})")
        self._hide_all_input_groups() # Hide everything first
        self._set_active_input_highlight(None, None) # <--- CLEAR HIGHLIGHTS FIRST ---
        # self.abort_button.setEnabled(False) # REMOVED: Abort button managed by page visibility

        # Enable/Disable Next Action Buttons (default: disabled)
        self.test_next_port_button.setEnabled(False)
        self.test_next_order_button.setEnabled(False)
        self.finish_measurements_button.setEnabled(False)

        # --- Show relevant group, set focus, AND HIGHLIGHT ---
        if stage == "SelectOrientation":
            self.orientation_group.setVisible(True)
            self.update_status("Select antenna orientation and confirm", "info")
            # Highlight the confirmation button as the primary action
            confirm_orient_button = self.orientation_group.findChild(QPushButton)
            self._set_active_input_highlight(self.orientation_group, confirm_orient_button)
            self.rb_horizontal.setFocus() # Focus remains on radio

        elif stage == "SelectStartPort":
            if not self._ports_to_test:
                 QMessageBox.critical(self, "Error", "No ports selected for testing. Cannot proceed.")
                 self.go_to_state("SelectOrientation")
                 return
            self.select_start_port_group.setVisible(True)
            self.start_port_combo.clear()
            self.start_port_combo.addItems(self._ports_to_test)
            self.update_status(f"Select which port to start testing with ({len(self._ports_to_test)} total selected)", "info")
            self._set_active_input_highlight(self.select_start_port_group, self.start_port_combo)
            self.start_port_combo.setFocus()

        elif stage == "RequestGoldenCal": # This stage is mostly internal now due to recalibration logic
             self.update_status(f"Preparing calibration for port {self._current_test_port}...", "info")
             # No user input directly, main app/request_calibration_for_port decides what to do

        elif stage == "ScanGolden":
            if not self._current_test_port: return
            self.golden_scan_group.setTitle(f"3. Calibrate {self._current_test_port}: Scan GOLDEN")
            self.golden_scan_group.setVisible(True)
            self.update_status(f"Scan Golden Sample SN for port {self._current_test_port}", "info")
            self.sn_input_golden.clear()
            self._set_active_input_highlight(self.golden_scan_group, self.sn_input_golden)
            self.sn_input_golden.setFocus()

        elif stage == "VerifyGolden":
            self.update_status(f"Verifying Golden SN for port {self._current_test_port}...", "info")

        elif stage == "StartGoldenMeasurement":
            if not self._current_test_port: return
            self.start_golden_group.setTitle(f"4. Calibrate {self._current_test_port}: Start GOLDEN Meas.")
            self.start_golden_group.setVisible(True)
            self.update_status(f"Ready to measure Golden Sample for port {self._current_test_port}", "good")
            self.start_golden_button.setEnabled(True)
            self._set_active_input_highlight(self.start_golden_group, self.start_golden_button)
            self.start_golden_button.setFocus()

        elif stage == "MeasureGolden":
            if not self._current_test_port: return
            self.update_status(f"Measuring Golden Sample for port {self._current_test_port}...", "info")
            self.progress_bar.setRange(0, 11)
            self.progress_bar.setValue(0)
            # self.abort_button.setEnabled(True) # REMOVED

        elif stage == "RequestSilverCal": # Mostly internal
             self.update_status(f"Preparing Silver calibration for port {self._current_test_port}...", "info")

        elif stage == "ScanSilver":
            if not self._current_test_port: return
            self.silver_scan_group.setTitle(f"5. Calibrate {self._current_test_port}: Scan SILVER")
            self.silver_scan_group.setVisible(True)
            self.update_status(f"Scan Silver Sample SN for port {self._current_test_port}", "info")
            self.sn_input_silver.clear()
            self._set_active_input_highlight(self.silver_scan_group, self.sn_input_silver)
            self.sn_input_silver.setFocus()

        elif stage == "VerifySilver":
            self.update_status(f"Verifying Silver SN for port {self._current_test_port}...", "info")

        elif stage == "StartSilverMeasurement":
            if not self._current_test_port: return
            self.start_silver_group.setTitle(f"6. Calibrate {self._current_test_port}: Start SILVER Meas.")
            self.start_silver_group.setVisible(True)
            self.update_status(f"Ready to measure Silver Sample for port {self._current_test_port}", "good")
            self.start_silver_button.setEnabled(True)
            self._set_active_input_highlight(self.start_silver_group, self.start_silver_button)
            self.start_silver_button.setFocus()

        elif stage == "MeasureSilver":
            if not self._current_test_port: return
            self.update_status(f"Measuring Silver Sample for port {self._current_test_port}...", "info")
            self.progress_bar.setRange(0, 11)
            self.progress_bar.setValue(0)
            # self.abort_button.setEnabled(True) # REMOVED

        elif stage == "EnterOrderInfo":
            # This stage is reached if calibration is valid OR after calibration completes
            # and no order is active.
            if not self._current_order_number:
                 self.order_info_group.setVisible(True)
                 self.update_status("Enter Production Order Details", "info")
                 self.order_number_input.setEnabled(True)
                 self.charge_number_input.setEnabled(True) 
                 self.order_quantity_input.setEnabled(True)
                 self.confirm_order_button.setEnabled(True)
                 self.order_number_input.clear()
                 self.charge_number_input.clear() 
                 self.order_quantity_input.clear()
                 self._set_active_input_highlight(self.order_info_group, self.order_number_input)
                 self.order_number_input.setFocus()
            else:
                 # Order info already exists (e.g. from a previous session for this antenna).
                 # The main app logic (via load_and_apply_order_history) will have requested
                 # calibration check. If cal is valid, we land here directly.
                 logger.info(f"UI: Order info ({self._current_order_number}) already exists, proceeding to ScanAntennaSN.")
                 self._setup_input_area("ScanAntennaSN")

        elif stage == "ScanAntennaSN":
            if not self._current_test_port: return
            # Default title and label, might be overridden by setup_for_retest_scan
            self.antenna_scan_group.setTitle(f"8. Test {self._current_test_port}: Scan Antenna")
            count_label = f"Scan Antenna SN ({self._tested_in_current_port_batch + 1} of {self._current_order_quantity}):"
            self.antenna_scan_label.setText(count_label)
            
            self.antenna_scan_group.setVisible(True)
            self.update_status(f"Ready for next Antenna SN for port {self._current_test_port}", "info")
            self.sn_input_antenna.clear() # Cleared here, setup_for_retest_scan might pre-fill it after
            self._set_active_input_highlight(self.antenna_scan_group, self.sn_input_antenna)
            self.sn_input_antenna.setFocus()

        elif stage == "VerifyAntennaSN":
            self.update_status(f"Checking SN for port {self._current_test_port} test...", "info")

        elif stage == "StartAntennaTest":
            if not self._current_test_port or not self._current_antenna_sn_under_test: return
            self.start_antenna_test_group.setTitle(f"9. Test {self._current_test_port}: Start Test")
            self.start_antenna_test_group.setVisible(True)
            sn = self._current_antenna_sn_under_test
            self.start_antenna_test_button.setText(f"Start Test ({self._current_test_port}) for SN: {sn}")
            self.start_antenna_test_button.setEnabled(True)
            self.update_status(f"Ready to test Port {self._current_test_port} on antenna {sn}", "good")
            self._set_active_input_highlight(self.start_antenna_test_group, self.start_antenna_test_button)
            self.start_antenna_test_button.setFocus()

        elif stage == "MeasureAntenna":
            if not self._current_test_port or not self._current_antenna_sn_under_test: return
            sn = self._current_antenna_sn_under_test
            self.update_status(f"TESTING Port {self._current_test_port} on SN: {sn}...", "info")
            self.progress_bar.setRange(0, 11)
            self.progress_bar.setValue(0)
            # self.abort_button.setEnabled(True) # REMOVED
            self.update_port_status(self._current_test_port, status="Testing")

        elif stage == "AntennaPortTestComplete":
             self.update_status(f"Antenna test complete for Port {self._current_test_port}. Waiting...", "info")
             # self.abort_button.setEnabled(False) # REMOVED

        elif stage == "NextAction":
            self.next_action_group.setVisible(True)
            # Determine which button gets focus based on availability
            if self.test_next_port_button.isEnabled():
                self.test_next_port_button.setFocus()
            elif self.test_next_order_button.isEnabled():
                self.test_next_order_button.setFocus()
            else:
                self.finish_measurements_button.setFocus()


        else: # Idle state
             self.update_status("Idle. Waiting for next action.", "info")

    @Slot(int, int)
    def _save_test_page_splitter_state(self, pos, index):
        """Saves the state of the splitter on the main testing page."""
        if hasattr(self, 'bottom_splitter') and self.bottom_splitter is not None:
            current_state = self.bottom_splitter.saveState()
            self.settings.setValue(TEST_PAGE_SPLITTER_STATE_KEY, current_state)
            # logger.debug(f"UI: Test page splitter state saved (pos: {pos}, index: {index}).")
        else:
            logger.warning("UI: Attempted to save splitter state, but bottom_splitter not found or not initialized.")

    # --- Event Handlers and Internal Logic ---
    # ... (show_login_dialog, _handle_login_success, _on_login_as_different_user_clicked, go_fullscreen, _on_antenna_selected, _on_orientation_confirmed, _on_ports_confirmed, _on_start_port_selected, _on_golden_sn_entered, _on_silver_sn_entered, _on_antenna_sn_entered, _on_start_golden_measurement, _on_start_silver_measurement, _on_start_antenna_test, _on_order_info_entered, _update_antenna_order_status, _on_retry_confirmed, _on_abort_clicked, _on_test_next_port_clicked, _on_test_next_order_clicked, _on_test_finish_measurements_clicked remain the same)
    # Event Handlers and Internal Logic
    def show_login_dialog(self, changing_user=False): # Add flag
        # self._initial_theme_setup() # Theme is applied once at startup or on manual change
        current = self._current_user if changing_user else None
        # Use the imported LoginDialog
        dialog = LoginDialog(self._users, current_user=current, parent=self) # Pass current user if changing
        dialog.login_successful.connect(self._handle_login_success)
        if not dialog.exec():
             if not self._current_user: # If login cancelled and NO user logged in yet
                 logger.info("Initial login cancelled or failed. Exiting.")
                 QTimer.singleShot(0, self.close) # Close gracefully
             # If changing user was cancelled, do nothing, keep old user

    def _handle_login_success(self, username, is_admin):
        was_already_logged_in = bool(self._current_user) # Check if this is initial login or change
        logger.info(f"Login successful: User={username}, Admin={is_admin} (WasLoggedIn: {was_already_logged_in})")
        self._current_user = username
        self._is_admin = is_admin
        self.detail_user_label.setText(self._current_user) # Update detail panel
        self.status_bar_label.setText(f"User: {self._current_user}{' (Admin)' if is_admin else ''}")
        self.manage_users_action.setEnabled(self._is_admin) # Enable user management for admin
        self.login_change_action.setEnabled(True) # Always enable change option after login
        self.status_bar.showMessage(f"User changed to {self._current_user}!" if was_already_logged_in else f"Welcome, {self._current_user}!", 5000)

        if not was_already_logged_in:
            # Transition to antenna selection page ONLY on initial login
            self.stacked_widget.setCurrentWidget(self.antenna_page)
            self.request_antenna_configs.emit() # Ask main app for configs

    def _on_login_as_different_user_clicked(self):
        """Handles the 'Login As Different User...' menu action."""
        logger.info("UI: Requesting to change user.")
        self.show_login_dialog(changing_user=True)

    def go_fullscreen(self):
        logger.info("UI: Going Fullscreen")
        self.showFullScreen()

    def _on_antenna_selected(self):
        selected_items = self.antenna_list_widget.selectedItems()
        if selected_items:
            antenna_name = selected_items[0].text()
            logger.info(f"UI: Antenna selected: {antenna_name}")
            self.status_bar.showMessage(f"Antenna '{antenna_name}' selected. Loading config...", 3000)
            self.antenna_selected.emit(antenna_name)

    def _on_orientation_confirmed(self):
        if self.rb_horizontal.isChecked(): self._selected_orientation = "Horizontal"
        elif self.rb_vertical.isChecked(): self._selected_orientation = "Vertical"
        else: return
        logger.info(f"UI: Orientation confirmed: {self._selected_orientation}")
        self.detail_orientation_label.setText(self._selected_orientation)
        self.status_bar.showMessage(f"{self._selected_orientation} orientation selected. Requesting ports...", 3000)
        self.orientation_selected.emit(self._selected_orientation)

    def _on_ports_confirmed(self, selected_ports):
        """Called after PortSelectionDialog closes with OK."""
        if not selected_ports:
             logger.warning("UI: _on_ports_confirmed called with empty list.")
             self.go_to_state("SelectOrientation")
             return
        logger.info(f"UI: Ports confirmed for testing: {selected_ports}")
        self._ports_to_test = selected_ports
        self.status_bar.showMessage(f"Active ports selected: {len(selected_ports)}. Select starting port.", 5000)
        self._update_port_selection_status()
        self.ports_selected_for_test.emit(self._ports_to_test)
        self._setup_input_area("SelectStartPort")

    def _on_start_port_selected(self):
        """Called when user confirms the starting port from the combo box."""
        start_port = self.start_port_combo.currentText()
        if not start_port:
            QMessageBox.warning(self, "Selection Error", "Please select a port to start testing.")
            self._set_active_input_highlight(self.select_start_port_group, self.start_port_combo)
            self.start_port_combo.setFocus()
            return
        logger.info(f"UI: Starting test sequence with port: {start_port}")
        self._current_test_port = start_port
        try:
            self._current_overall_port_index = self._ports_to_test.index(start_port)
        except ValueError:
             logger.error(f"Error: Selected start port '{start_port}' not found in the list of ports to test: {self._ports_to_test}")
             self._current_overall_port_index = -1
        self.status_bar.showMessage(f"Starting sequence with port {start_port}. Requesting calibration.", 5000)
        self.start_port_selected_for_testing.emit(start_port) # Main app handles next step (order info or cal)

    # SN Handlers
    def _on_golden_sn_entered(self):
        sn = self.sn_input_golden.text().strip().upper()
        if sn and self._current_test_port:
            self.sn_input_golden.setEnabled(False)
            self.golden_sample_scan_received.emit(sn, self._current_test_port)
            self._setup_input_area("VerifyGolden")
        elif not self._current_test_port:
             QMessageBox.critical(self, "Error", "Cannot verify Golden SN: No current test port selected.")
             self.go_to_state("SelectStartPort")
        else:
             self._set_active_input_highlight(self.golden_scan_group, self.sn_input_golden)
             self.sn_input_golden.setFocus()

    def _on_silver_sn_entered(self):
        sn = self.sn_input_silver.text().strip().upper()
        if sn and self._current_test_port:
            self.sn_input_silver.setEnabled(False)
            self.silver_sample_scan_received.emit(sn, self._current_test_port)
            self._setup_input_area("VerifySilver")
        elif not self._current_test_port:
             QMessageBox.critical(self, "Error", "Cannot verify Silver SN: No current test port selected.")
             self.go_to_state("SelectStartPort")
        else:
             self._set_active_input_highlight(self.silver_scan_group, self.sn_input_silver)
             self.sn_input_silver.setFocus()

    def _on_antenna_sn_entered(self):
        sn = self.sn_input_antenna.text().strip().upper()
        if sn and self._current_test_port:
            self.sn_input_antenna.setEnabled(False)
            self._current_antenna_sn_under_test = sn
            self.detail_sn_label.setText(sn)
            self.antenna_sn_scan_received.emit(sn, self._current_test_port)
            self._setup_input_area("VerifyAntennaSN")
        elif not self._current_test_port:
            QMessageBox.critical(self, "Error", "Cannot verify Antenna SN: No current test port selected.")
            self.go_to_state("SelectStartPort")
        else:
            self._set_active_input_highlight(self.antenna_scan_group, self.sn_input_antenna)
            self.sn_input_antenna.setFocus()

    # Measurement start handlers
    def _on_start_golden_measurement(self):
        if self._current_test_port:
            self.start_golden_button.setEnabled(False)
            self.start_golden_measurement.emit(self._current_test_port)
            self._setup_input_area("MeasureGolden")

    def _on_start_silver_measurement(self):
        if self._current_test_port:
            self.start_silver_button.setEnabled(False)
            self.start_silver_measurement.emit(self._current_test_port)
            self._setup_input_area("MeasureSilver")

    def _on_start_antenna_test(self):
        """Starts the measurement for the current antenna/port."""
        if self._current_test_port and self._current_antenna_sn_under_test:
             self.start_antenna_test_button.setEnabled(False)
             self.start_antenna_test_for_port.emit(self._current_test_port)
             self._setup_input_area("MeasureAntenna")

    def _on_order_info_entered(self):
        order_num = self.order_number_input.text().strip()
        charge_num = self.charge_number_input.text().strip() 
        quantity_str = self.order_quantity_input.text().strip()

        if not order_num:
             QMessageBox.warning(self, "Input Error", "Order Number cannot be empty.")
             self._set_active_input_highlight(self.order_info_group, self.order_number_input)
             self.order_number_input.setFocus()
             return
        
        if not charge_num:
             QMessageBox.warning(self, "Input Error", "Charge Number cannot be empty.")
             self._set_active_input_highlight(self.order_info_group, self.charge_number_input)
             self.charge_number_input.setFocus()
             return

        try:
            quantity = int(quantity_str)
            if quantity <= 0:
                raise ValueError("Quantity must be positive.")
        except ValueError:
             QMessageBox.warning(self, "Input Error", "Invalid quantity. Please enter a positive whole number.")
             self._set_active_input_highlight(self.order_info_group, self.order_quantity_input)
             self.order_quantity_input.selectAll()
             self.order_quantity_input.setFocus()
             return

        logger.info(f"UI: Order info confirmed: Order={order_num}, Charge={charge_num}, Qty={quantity}")
        if self._current_order_number != order_num:
             logger.info("UI: New Order Number detected, clearing results table and resetting antenna status.")
             self.clear_results_table()
             self._tested_in_current_order = 0
             self._passed_in_current_order = 0
             self._antenna_status_this_order = {}
             self._passed_antennas_in_order = 0
             self._failed_antennas_in_order = 0
             self.update_statistics()

        self._current_order_number = order_num
        self._current_charge_number = charge_num
        self._current_order_quantity = quantity
        self.detail_order_label.setText(order_num)
        self.detail_charge_label.setText(charge_num)

        self._tested_in_current_port_batch = 0
        self._passed_in_current_port_batch = 0
        self._completed_ports_in_run = 0
        self.update_statistics()

        self.order_number_input.setEnabled(False)
        self.charge_number_input.setEnabled(False)
        self.order_quantity_input.setEnabled(False)
        self.confirm_order_button.setEnabled(False)

        self.order_info_received.emit(order_num, charge_num, quantity)
        self.request_load_order_history.emit(order_num)


    def _update_antenna_order_status(self, serial_number, port_name, overall_port_status):
        if not serial_number or not self._ports_to_test:
            logger.warning("Cannot track antenna status - missing SN or selected ports.")
            return

        required_ports = set(self._ports_to_test)
        if not required_ports:
            logger.warning("Cannot track antenna status - no ports selected for test.")
            return

        if serial_number not in self._antenna_status_this_order:
            self._antenna_status_this_order[serial_number] = {
                "status": "IN_PROGRESS",
                "ports_tested": set(),
                "ports_passed": set()
            }
            logger.info(f"UI: Initializing status tracking for new SN: {serial_number}")

        ant_stat = self._antenna_status_this_order[serial_number]
        previous_overall_status = ant_stat["status"]

        ant_stat["ports_tested"].add(port_name)
        if overall_port_status == "PASS":
            ant_stat["ports_passed"].add(port_name)
            logger.debug(f"UI Trace: SN {serial_number} - Port {port_name} PASSED. Passed ports: {ant_stat['ports_passed']}")
        else:
            ant_stat["ports_passed"].discard(port_name) # Ensure it's removed if it was previously passed then failed on retest
            logger.debug(f"UI Trace: SN {serial_number} - Port {port_name} FAILED. Passed ports: {ant_stat['ports_passed']}")


        has_failed_port_among_tested = False
        for p_tested in ant_stat["ports_tested"]:
            if p_tested not in ant_stat["ports_passed"]:
                has_failed_port_among_tested = True
                break
        
        all_required_ports_tested = required_ports.issubset(ant_stat["ports_tested"])

        new_overall_status = "IN_PROGRESS"

        if has_failed_port_among_tested:
            new_overall_status = "FAIL"
        elif all_required_ports_tested: # And no fails (implicit from above)
            new_overall_status = "PASS"
        # Otherwise, it remains IN_PROGRESS

        # Update counts ONLY IF the overall status *changed* from PASS/FAIL to something else, or vice-versa
        if new_overall_status != previous_overall_status:
            logger.info(f"UI: Antenna '{serial_number}' overall order status changed from {previous_overall_status} to {new_overall_status}")

            # Decrement count for the old status (if it was a completed PASS or FAIL)
            if previous_overall_status == "PASS":
                self._passed_antennas_in_order -= 1
            elif previous_overall_status == "FAIL":
                self._failed_antennas_in_order -= 1

            # Increment count for the new status (if it is a completed PASS or FAIL)
            if new_overall_status == "PASS":
                self._passed_antennas_in_order += 1
            elif new_overall_status == "FAIL":
                self._failed_antennas_in_order += 1

            # Store the new status
            ant_stat["status"] = new_overall_status

            # Ensure counts don't go negative (safety)
            self._passed_antennas_in_order = max(0, self._passed_antennas_in_order)
            self._failed_antennas_in_order = max(0, self._failed_antennas_in_order)
            logger.info(f"UI: Updated Antenna Counts - Passed: {self._passed_antennas_in_order}, Failed: {self._failed_antennas_in_order}")

        else:
             logger.info(f"UI: Antenna '{serial_number}' overall order status remains {new_overall_status}")

    def _on_retry_confirmed(self, retry):
        """Handles user response to testing an already tested SN (from the warning dialog)."""
        sn = self._current_antenna_sn_under_test # This SN was from _on_antenna_sn_entered
        self.sn_input_antenna.setEnabled(True)

        self.retry_test_confirmed.emit(retry, sn)

        if retry:
            logger.info(f"UI: User chose to retry SN {sn} (after already-tested warning). Main app handles logic.")
            # Main app will receive retry_test_confirmed(True, sn) and should set up for a normal test.
            # UI should then be driven to StartAntennaTest by main_app.
            self._setup_input_area("StartAntennaTest")
        else:
            logger.info(f"UI: User chose not to retry SN {sn} (after already-tested warning). Scanning next.")
            self._current_antenna_sn_under_test = None # Clear the SN
            self.detail_sn_label.setText("-")
            self._setup_input_area("ScanAntennaSN")


    def _on_abort_clicked(self):
        reply = QMessageBox.question(self, "Confirm Abort",
                                     "Are you sure you want to abort all current operations and return to Antenna Selection?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
             logger.info("UI: Abort requested by user. Returning to Antenna Selection.")
             self._test_running = False # Stop any UI-side measurement progress updates
             self.abort_test_requested.emit() # Signal main application to stop hardware/long processes
             self.go_to_antenna_selection() # This will reset state and navigate


    # --- NEW Button Handlers for Next Action ---
    def _on_test_next_port_clicked(self):
        logger.info("UI: 'TEST NEXT PORT' button clicked.")
        self.request_test_next_port.emit()

    def _on_test_next_order_clicked(self):
        logger.info("UI: 'TEST NEXT ORDER' button clicked.")
        self.request_test_next_order.emit()

    def _on_test_finish_measurements_clicked(self):
        logger.info("UI: 'FINISH MEASUREMENTS' button clicked.")
        self.request_finish_measurements.emit()
    # --- Public Methods for Main Application Control ---

    def display_antenna_configs(self, antenna_names):
        """Populates the antenna selection list."""
        logger.info(f"UI: Displaying antenna configs: {antenna_names}")
        self.antenna_list_widget.clear()
        self.antenna_list_widget.addItems(sorted(antenna_names))
        self.select_antenna_button.setEnabled(False)
        self.stacked_widget.setCurrentWidget(self.antenna_page)
        self.update_status("Please select an antenna configuration.", "info")
        self.antenna_list_widget.setFocus()

    def set_antenna_details(self, name, part_number):
        """Called by main app after successfully loading config."""
        logger.info(f"UI: Setting antenna details - Name: {name}, PN: {part_number}")
        self._selected_antenna_name = name
        self._selected_antenna_pn = part_number
        self.detail_antenna_label.setText(name)
        self.detail_pn_label.setText(part_number or "-")

    def show_orientation_selection(self):
        """Transitions to the main test page, showing orientation selection first."""
        logger.info("UI: Showing orientation selection.")
        
        # Maximize the window when transitioning to the main test page ---
        if not self.isMaximized(): # Maximize only if not already maximized
            logger.info("UI: Maximizing window for main testing page.")
            self.showMaximized() 

        # Reset state variables related to a previous run
        self._selected_orientation = None
        self._ports_for_current_orientation = []
        self._ports_to_test = []
        self._current_test_port = None
        self._current_overall_port_index = -1
        self._current_order_number = ""
        self._current_charge_number = ""
        self._current_order_quantity = 0
        self._tested_in_current_port_batch = 0
        self._passed_in_current_port_batch = 0
        self._tested_in_current_order = 0
        self._passed_in_current_order = 0
        self._completed_ports_in_run = 0
        self._current_antenna_sn_under_test = None
        self._test_running = False
        self._port_status_data = {}
        self._port_calibration_timestamps = {} # Reset timestamps for new antenna config

        self._antenna_status_this_order = {}
        self._passed_antennas_in_order = 0
        self._failed_antennas_in_order = 0

        self.update_active_details()
        self.port_status_table.setRowCount(0)
        self.clear_graph()
        self.clear_results_table()
        self.update_statistics()
        self.progress_bar.setValue(0)

        self.stacked_widget.setCurrentWidget(self.test_page)
        self.abort_button.setEnabled(True) # Enable Abort button as test page is now active
        self._setup_input_area("SelectOrientation")
        self.rb_horizontal.setChecked(True)

    def populate_port_status_display(self, ports_for_orientation):
        """Populates the port status table initially."""
        logger.info(f"UI: Populating port status table with: {ports_for_orientation}")
        self._ports_for_current_orientation = ports_for_orientation
        self.port_status_table.setRowCount(0)
        self._port_status_data = {} # Reset status data
        # self._port_calibration_timestamps = {} # Timestamps reset in show_orientation_selection

        if not ports_for_orientation:
            logger.warning("UI: No ports provided to populate status table.")
            return

        self.port_status_table.setRowCount(len(ports_for_orientation))
        for i, port_name in enumerate(ports_for_orientation):
            self._port_status_data[port_name] = {"selected": False, "status": "Inactive"}
            item_port = QTableWidgetItem(port_name)
            item_selected = QTableWidgetItem("No")
            item_status = QTableWidgetItem("Inactive")
            item_status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_selected.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            flags = Qt.ItemFlag.ItemIsEnabled
            item_port.setFlags(flags)
            item_selected.setFlags(flags)
            item_status.setFlags(flags)
            self.port_status_table.setItem(i, 0, item_port)
            self.port_status_table.setItem(i, 1, item_selected)
            self.port_status_table.setItem(i, 2, item_status)
            self.update_port_status(port_name, status="Inactive")

    def show_port_selection(self):
        """Shows the dialog for the user to check/uncheck ports."""
        if not self._ports_for_current_orientation:
             QMessageBox.warning(self, "Configuration Error", "No ports available for the selected orientation.")
             self.go_to_state("SelectOrientation")
             return
        logger.info("UI: Showing port selection dialog.")
        dialog = PortSelectionDialog(self._ports_for_current_orientation, self._selected_orientation, self)
        dialog.ports_confirmed.connect(self._on_ports_confirmed)
        if not dialog.exec():
             logger.info("UI: Port selection cancelled.")
             confirm_orient_button = self.orientation_group.findChild(QPushButton)
             self._set_active_input_highlight(self.orientation_group, confirm_orient_button)
             self.rb_horizontal.setFocus()

    def apply_loaded_order_status(self, order_status_map):
        """Updates the port status table based on loaded historical data for an order."""
        logger.info(f"UI: Applying loaded status for order {self._current_order_number}: {order_status_map}")
        if not order_status_map: # No history for this order
            # Set selected ports to "Pending" if their cal isn't "Calibrated and Verified"
            # or if it has expired. This might be redundant if request_calibration_for_port handles it.
            for port_name in self._ports_to_test:
                current_ui_status = self._port_status_data.get(port_name, {}).get("status", "Inactive")
                if current_ui_status not in ["Calibrated and Verified", "Inactive"]:
                    self.update_port_status(port_name, status="Pending")
            return

        for port_name, status_from_history in order_status_map.items():
            if port_name in self._port_status_data and self._port_status_data[port_name]["selected"]:
                # Port is part of the current test run.
                # Prioritize "Done" or "Skipped" from history.
                if status_from_history in ["Done", "Skipped"]:
                    self.update_port_status(port_name, status=status_from_history)
                else:
                    # If history says something else (e.g. Pending, Cal Failed),
                    # check current UI calibration state.
                    current_ui_status = self._port_status_data.get(port_name, {}).get("status")
                    if current_ui_status == "Calibrated and Verified":
                        # Check timestamp
                        if port_name in self._port_calibration_timestamps:
                            cal_age = datetime.now() - self._port_calibration_timestamps[port_name]
                            if cal_age.total_seconds() > self._RECALIBRATION_TIME_SECONDS:
                                self.update_port_status(port_name, status="Pending") # Expired
                                self._port_calibration_timestamps.pop(port_name, None)
                            # else: keep "Calibrated and Verified"
                        else: # No timestamp, so not really verified recently
                            self.update_port_status(port_name, status="Pending")
                    elif current_ui_status != "Inactive": # If not verified, and not inactive, set to Pending
                         self.update_port_status(port_name, status="Pending")

            elif port_name in self._port_status_data: # Port exists but not selected for this run
                 self.update_port_status(port_name, status="Inactive")


    def set_current_test_port(self, port_name):
        """Sets the UI's internal reference for the current test port."""
        logger.info(f"UI: Setting current test port context to: {port_name}")
        if self._current_test_port != port_name: # Only reset if port actually changes
            self._current_test_port = port_name
            self._tested_in_current_port_batch = 0
            self._passed_in_current_port_batch = 0
            self.update_statistics()

    def request_calibration_for_port(self, port_name):
        """
        Sets UI state ready for Golden Scan for the specified port,
        or proceeds if calibration is already valid.
        """
        logger.info(f"UI: Calibration requested for port {port_name}")
        if port_name not in self._ports_to_test:
            QMessageBox.critical(self, "Error", f"Port '{port_name}' is not selected for testing.")
            self.go_to_state("SelectStartPort") # Or appropriate recovery
            return

        self._current_test_port = port_name # Ensure current port is set

        is_cal_valid = False
        current_status = self._port_status_data.get(port_name, {}).get("status")
        cal_timestamp = self._port_calibration_timestamps.get(port_name)

        if current_status == "Calibrated and Verified" and cal_timestamp:
            cal_age = datetime.now() - cal_timestamp
            if cal_age.total_seconds() <= self._RECALIBRATION_TIME_SECONDS:
                is_cal_valid = True
                logger.info(f"UI: Calibration for port {port_name} is still valid (age: {cal_age.total_seconds():.0f}s).")
            else:
                logger.warning(f"UI: Calibration for port {port_name} has EXPIRED (age: {cal_age.total_seconds():.0f}s). Needs recalibration.")
                self._port_calibration_timestamps.pop(port_name, None) # Clear expired timestamp
                self._port_status_data[port_name]["status"] = "Pending" # Mark for recal
        elif current_status == "Calibrated and Verified" and not cal_timestamp:
             logger.warning(f"UI: Port {port_name} is 'Calibrated and Verified' but no timestamp. Needs recalibration.")
             self._port_status_data[port_name]["status"] = "Pending" # Mark for recal
        else:
            logger.info(f"UI: Port {port_name} status is '{current_status}'. Needs full calibration sequence.")

        if is_cal_valid:
            self.update_status(f"Port {port_name} calibration current. Ready for Order/Test.", "good")
            self.update_port_status(port_name, status="Calibrated and Verified") # Ensure visual consistency
            if not self._current_order_number:
                self._setup_input_area("EnterOrderInfo")
            else:
                self._setup_input_area("ScanAntennaSN")
        else:
            # Proceed with full calibration sequence
            self.update_status(f"Starting calibration sequence for port {port_name}.", "info")
            self.update_port_status(port_name, status="Calibrating") # Visual update
            self.clear_graph() # Clear graph for new calibration
            self._setup_input_area("ScanGolden") # Start full cal from Golden

    def report_golden_sn_validation(self, port_name, valid, expected_sn="", message=""):
        """Handles the result of Golden SN validation from main app."""
        self.sn_input_golden.setEnabled(True) # Re-enable input
        if port_name != self._current_test_port: return # Context check
        if valid:
            self.status_bar.showMessage(f"Golden SN for {port_name} Verified.", 3000)
            self._setup_input_area("StartGoldenMeasurement")
        else:
            QMessageBox.critical(self, f"Golden SN Error ({port_name})", f"{message}\nExpected: {expected_sn}")
            self._setup_input_area("ScanGolden")

    def report_golden_measurement_complete(self, port_name, success=True):
        """Handles the completion of the Golden measurement."""
        if port_name != self._current_test_port: return # Check context
        self._test_running = False
        # self.abort_button.setEnabled(False) # REMOVED
        self._set_active_input_highlight(None, None)
        if success:
            self.update_status(f"Golden measurement complete for {port_name}. Ready for Silver.", "good")
            self.progress_bar.setValue(self.progress_bar.maximum())
            self.update_port_status(port_name, status="Calibrated") # Golden part is done
            self._setup_input_area("ScanSilver")
        else:
            self.update_status(f"Golden measurement failed for {port_name}. Check instrument.", "bad")
            self.update_port_status(port_name, status="Cal Failed")
            self.progress_bar.setValue(0)
            self._setup_input_area("ScanGolden")

    def report_silver_sn_validation(self, port_name, valid, expected_sn="", message=""):
        """Handles the result of Silver SN validation."""
        self.sn_input_silver.setEnabled(True) # Re-enable input
        if port_name != self._current_test_port: return
        if valid:
            self.status_bar.showMessage(f"Silver SN for {port_name} Verified.", 3000)
            self._setup_input_area("StartSilverMeasurement")
        else:
            QMessageBox.critical(self, f"Silver SN Error ({port_name})", f"{message}\nExpected: {expected_sn}")
            self._setup_input_area("ScanSilver")

    @Slot(str, bool, str, str, int, list)
    def report_silver_measurement_complete(self, port_name, success=True, message="", silver_sn="", measurement_id=-1, silver_results=None):
        if port_name != self._current_test_port: return
        self._test_running = False
        # self.abort_button.setEnabled(False) # REMOVED
        self._set_active_input_highlight(None, None)

        if silver_results:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            order_display = self._current_order_number if self._current_order_number else "CAL"
            logger.info(f"UI: Adding Silver Sample results for SN '{silver_sn}' (Port: {port_name}, ID: {measurement_id}) to table...")

            final_silver_results_with_original_status = []
            if not success: # overall_silver_status was FAIL
                for original_res in silver_results:
                    modified_res = original_res.copy()
                    modified_res['Original_Pass_Status_For_Coloring'] = original_res.get('Pass', 'N/A')
                    modified_res['Pass'] = 'FAIL'
                    final_silver_results_with_original_status.append(modified_res)
            else:
                for original_res in silver_results:
                    modified_res = original_res.copy()
                    modified_res['Original_Pass_Status_For_Coloring'] = original_res.get('Pass', 'N/A')
                    # 'Pass' key is already correct
                    final_silver_results_with_original_status.append(modified_res)

            for result in final_silver_results_with_original_status:
                freq = result.get('Frequency_GHz')
                gain = result.get('Antenna_Gain')
                ll = result.get('Lower_Limit')
                ul = result.get('Upper_Limit')
                status_for_text_column = result.get('Pass', 'N/A')
                original_freq_status_for_coloring = result.get('Original_Pass_Status_For_Coloring', 'N/A')
                ant_meas = result.get('Antenna_Measurement')
                gld_meas = result.get('Golden_Measurement')
                spc_gain = result.get('Spec_Gain_Displayed') # Or 'Spec_Gain_Golden' if that was intended
                limit_str = f"{ll:.2f} / {ul:.2f}" if ll is not None and ul is not None else "N/A"

                self.add_table_row(timestamp, order_display, measurement_id,
                                   silver_sn, port_name, freq, gain, limit_str,
                                   ant_meas, gld_meas, spc_gain,
                                   status_for_text_column, original_freq_status_for_coloring,
                                   is_retry_no_count=False) # Silver cal is never a "no count retry"
        else:
             logger.info(f"UI: No detailed silver results provided for Port {port_name}. Not adding to table.")

        # --- Logic for updating status, port status, and next UI state ---
        if success:
            self.update_status(f"Verification complete for {port_name}. Ready for Order Info / Testing.", "good")
            self.update_port_status(port_name, status="Calibrated and Verified")
            self._port_calibration_timestamps[port_name] = datetime.now()
            logger.info(f"UI: Calibration timestamp for port {port_name} set to {self._port_calibration_timestamps[port_name]}")
            self.progress_bar.setValue(self.progress_bar.maximum())
            if not self._current_order_number:
                 self._setup_input_area("EnterOrderInfo")
            else:
                 self._setup_input_area("ScanAntennaSN")
        else:
            fail_msg = f"Silver Sample validation FAILED for port {port_name}."
            if message: # message now contains formatted failure details
                fail_msg_title = f"Silver Validation Failed ({port_name})"
                full_fail_msg = f"{fail_msg}\n\nDetails:\n{message}\n\nPlease check the Silver Sample and re-run the Silver measurement."
                QMessageBox.critical(self, fail_msg_title, full_fail_msg)
            else: # Fallback, should not happen if DummyApp provides details
                QMessageBox.critical(self, f"Silver Validation Failed ({port_name})",
                                     fail_msg + "\nPlease check the Silver Sample and re-run the Silver measurement.")


            self.update_status(f"Silver validation failed for {port_name}. Re-run needed.", "bad")
            self.update_port_status(port_name, status="Cal Failed")
            self._port_calibration_timestamps.pop(port_name, None)
            self.progress_bar.setValue(0)
            self._setup_input_area("ScanSilver")

    @Slot(bool, bool, str, bool) # Added is_retest_flow parameter
    def report_antenna_sn_validation(self, valid, already_tested_on_this_port=False, message="", is_retest_flow=False):
        """Handles the result of Antenna SN validation."""
        self.sn_input_antenna.setEnabled(True) # Re-enable input
        current_sn_from_ui_input = self.sn_input_antenna.text().strip().upper() # SN that was actually in the input field
        
        if valid:
            # If 'valid' is true, it means main_app accepted the SN.
            # self._current_antenna_sn_under_test should now reflect this accepted SN.
            self._current_antenna_sn_under_test = current_sn_from_ui_input
            self.detail_sn_label.setText(self._current_antenna_sn_under_test)

            if already_tested_on_this_port and not is_retest_flow:
                # Standard "SN already tested on this port" warning dialog
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle("Serial Number Previously Tested on Port")
                msg_text = (f"SN '{self._current_antenna_sn_under_test}' has already been tested on Port '{self._current_test_port}' "
                            f"(possibly in a previous session or order).\n\nTest it again on this port?")
                msg_box.setText(msg_text)
                msg_box.setIcon(QMessageBox.Icon.Warning)
                test_again_button = msg_box.addButton("Test Again", QMessageBox.ButtonRole.YesRole)
                scan_next_button = msg_box.addButton("Scan Next Unit", QMessageBox.ButtonRole.NoRole)
                msg_box.setDefaultButton(scan_next_button)
                msg_box.exec()

                if msg_box.clickedButton() == test_again_button:
                    self._on_retry_confirmed(True) # This will emit retry_test_confirmed
                else: # Scan Next Unit or closed
                    self._on_retry_confirmed(False)
            else:
                # SN is valid, and either not already_tested_on_this_port, 
                # OR it is already_tested_on_this_port but it's a retest_flow (so we skip the warning)
                self.status_bar.showMessage(f"Antenna SN {self._current_antenna_sn_under_test} OK for port {self._current_test_port}.", 3000)
                self._setup_input_area("StartAntennaTest")
        else:
            # SN validation failed (e.g., wrong SN scanned for retest, or bad format as per main_app)
            QMessageBox.critical(self, f"Antenna SN Error ({self._current_test_port})", message)
            # self.detail_sn_label.setText("-") # Clear if validation completely fails
            # self._current_antenna_sn_under_test = None
            # If it was a retest flow, we want to go back to re-scanning the *expected* SN
            if is_retest_flow and self._current_antenna_sn_under_test: # _current_antenna_sn_under_test would be the *expected* SN for retest
                 self.setup_for_retest_scan(self._current_test_port, self._current_antenna_sn_under_test)
            else: # General failure, go back to normal scan
                 self.detail_sn_label.setText("-") 
                 self._current_antenna_sn_under_test = None
                 self._setup_input_area("ScanAntennaSN")

    def update_measurement_progress(self, frequency_index, freq_value, gain_value, lower_limit, upper_limit):
        """Updates the graph and progress bar during measurement."""
        if not self._test_running: return
        self.progress_bar.setValue(frequency_index + 1)

        if PYQTGRAPH_AVAILABLE and hasattr(self, 'plot_widget') and self.plot_widget and self.plot_curve:
            try:
                if frequency_index == 0:
                    self._current_plot_x = []
                    self._current_plot_y = []
                    self._current_limit_x = []
                    self._current_limit_y_upper = []
                    self._current_limit_y_lower = []
                    if hasattr(self.plot_widget, 'enableAutoRange'):
                        self.plot_widget.enableAutoRange('xy', True)
                self._current_plot_x.append(freq_value)
                self._current_plot_y.append(gain_value if gain_value is not None else 0)
                self._current_limit_x.append(freq_value)
                self._current_limit_y_upper.append(upper_limit if upper_limit is not None else 0)
                self._current_limit_y_lower.append(lower_limit if lower_limit is not None else 0)
                self.plot_curve.setData(x=self._current_plot_x, y=self._current_plot_y)
                self.upper_limit_curve.setData(x=self._current_limit_x, y=self._current_limit_y_upper)
                self.lower_limit_curve.setData(x=self._current_limit_x, y=self._current_limit_y_lower)
            except Exception as e:
                logger.error(f"Error updating graph: {e}", exc_info=True)


    def report_port_test_complete_for_antenna(self, port_name, serial_number, results,
                                              overall_port_status, measurement_id,
                                              is_retry_no_count=False, failure_details_message=""):
        retry_display = "(No-Count Retry)" if is_retry_no_count else ""
        logger.info(f"UI: Reporting test complete for SN {serial_number}, Port {port_name}, Status: {overall_port_status}, ID: {measurement_id} {retry_display}")

        if port_name != self._current_test_port or serial_number != self._current_antenna_sn_under_test:
            logger.warning(f"UI: report_port_test_complete received for wrong context. UI: ({self._current_test_port}, {self._current_antenna_sn_under_test}), Report: ({port_name}, {serial_number})")
            # If context is wrong, this report might be stale or for a different UI flow.
            # We might not want to update counts or UI based on it directly,
            # but still log it if results are provided. For now, log and proceed with UI context.

        self._test_running = False
        self.progress_bar.setValue(self.progress_bar.maximum())
        self._set_active_input_highlight(None, None)

        status_text = f"Antenna {serial_number}, Port {port_name}: {overall_port_status} {retry_display}"
        self.update_status(status_text, "good" if overall_port_status == "PASS" else "bad")

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Update counts only if not a "no-count" retry AND context matches
        if not is_retry_no_count and port_name == self._current_test_port:
            self._tested_in_current_port_batch += 1
            self._tested_in_current_order += 1
            if overall_port_status == "PASS":
                self._passed_in_current_port_batch += 1
                self._passed_in_current_order += 1
            logger.debug(f"UI: Counts incremented for SN {serial_number}, Port {port_name}.")
        elif is_retry_no_count:
            logger.debug(f"UI: Counts NOT incremented for no-count retry of SN {serial_number}, Port {port_name}.")
        else: # Context mismatch, counts not for current UI display
            logger.debug(f"UI: Counts NOT incremented due to port context mismatch (UI: {self._current_test_port}, Report: {port_name}).")


        self._update_antenna_order_status(serial_number, port_name, overall_port_status)
        self.update_statistics() # This will update based on current UI's _tested_in_current_port_batch etc.

        final_results_with_original_status = []
        if overall_port_status == "FAIL":
            for original_result in results:
                modified_result = original_result.copy()
                modified_result['Original_Pass_Status_For_Coloring'] = original_result.get('Pass', 'N/A')
                modified_result['Pass'] = 'FAIL'
                final_results_with_original_status.append(modified_result)
        else:
            for original_result in results:
                modified_result = original_result.copy()
                modified_result['Original_Pass_Status_For_Coloring'] = original_result.get('Pass', 'N/A')
                final_results_with_original_status.append(modified_result)

        for result in final_results_with_original_status:
            freq = result.get('Frequency_GHz')
            gain = result.get('Antenna_Gain')
            ll = result.get('Lower_Limit')
            ul = result.get('Upper_Limit')
            status_for_text_column = result.get('Pass', 'N/A')
            original_freq_status_for_coloring = result.get('Original_Pass_Status_For_Coloring', 'N/A')
            ant_meas = result.get('Antenna_Measurement')
            gld_meas = result.get('Golden_Measurement')
            spc_gain = result.get('Spec_Gain_Golden')
            limit_str = f"{ll:.2f} / {ul:.2f}" if ll is not None and ul is not None else "N/A"

            self.add_table_row(timestamp, self._current_order_number, measurement_id,
                               serial_number, port_name, freq, gain, limit_str,
                               ant_meas, gld_meas, spc_gain,
                               status_for_text_column, original_freq_status_for_coloring,
                               is_retry_no_count) # Pass retry flag to table

        # Show failure pop-up (now with retest option) or proceed
        # This pop-up and decision logic only applies if the report is for the current UI context
        if overall_port_status == "FAIL" and port_name == self._current_test_port and serial_number == self._current_antenna_sn_under_test:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(f"Antenna Test Failed (Port: {port_name}, SN: {serial_number})")
            full_message = f"The antenna test for SN '{serial_number}' on port '{port_name}' FAILED.\n\n"
            if failure_details_message:
                full_message += f"Details:\n{failure_details_message}"
            else:
                full_message += "No specific frequency failure details were provided."
            msg_box.setText(full_message)
            msg_box.setIcon(QMessageBox.Icon.Critical)

            retest_button = msg_box.addButton("Retest Failed Unit", QMessageBox.ButtonRole.ActionRole)
            continue_button = msg_box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
            msg_box.setDefaultButton(continue_button)

            msg_box.exec()

            if msg_box.clickedButton() == retest_button:
                logger.info(f"UI: User chose to retest SN {serial_number} on port {port_name}.")
                # Main app will be signalled, it will then call setup_for_retest_scan
                self.request_retest_failed_unit.emit(port_name, serial_number)
                return # Main app will drive UI to retest state (ScanAntennaSN for retest)
            else: # Continue button or closed
                logger.info(f"UI: User chose to continue after failure of SN {serial_number} on port {port_name}.")
                # Fall through to normal "next step" logic below
        
        # Determine next step if not retesting or if context was mismatched
        is_port_batch_complete = False
        if port_name == self._current_test_port: # Only consider batch complete for the port currently in UI focus
            # Check against order quantity. _tested_in_current_port_batch was NOT incremented for a retry.
            if self._tested_in_current_port_batch >= self._current_order_quantity:
                 is_port_batch_complete = True

        if is_port_batch_complete:
            logger.info(f"UI: Batch for port {port_name} is complete ({self._tested_in_current_port_batch}/{self._current_order_quantity}). Signaling main app.")
            self.update_port_status(port_name, status="Done")
            self._completed_ports_in_run += 1
            self.go_to_state("AntennaPortTestComplete") # UI state transition
            self.port_batch_run_complete.emit(port_name) # Signal main app
        elif port_name == self._current_test_port: # More antennas needed for the current port
            if self._tested_in_current_port_batch < self._current_order_quantity:
                logger.info(f"UI: More antennas needed for port {port_name} ({self._tested_in_current_port_batch}/{self._current_order_quantity}).")
                self._setup_input_area("ScanAntennaSN")
            else: # Should not happen if is_port_batch_complete logic is correct
                 logger.warning(f"UI: Port batch logic error? ({self._tested_in_current_port_batch}/{self._current_order_quantity}). Fallback to ScanAntennaSN.")
                 self._setup_input_area("ScanAntennaSN")
        else: # Report was for a different port than current UI context (e.g., stale)
            logger.info(f"UI: Report context mismatch ({port_name} vs {self._current_test_port}) handled. UI remains in current state or ScanAntennaSN for {self._current_test_port}.")
            # If UI is waiting for a scan, ensure it's reset for current context
            if self._current_stage in ["MeasureAntenna", "AntennaPortTestComplete"] and self._current_test_port:
                 self._setup_input_area("ScanAntennaSN")


        if PYQTGRAPH_AVAILABLE and self.plot_widget:
            if hasattr(self.plot_widget, 'autoRange'):
                if port_name == self._current_test_port: # Only auto-range if graph is for current context
                    logger.debug("Graph: Forcing final autoRange on test complete.")
                    QTimer.singleShot(50, lambda: self.plot_widget.autoRange())

    @Slot(str, str)
    def setup_for_retest_scan(self, port_name, serial_number_to_retest):
        """Sets up the UI to re-scan a specific SN for retest after failure."""
        logger.info(f"UI: Setting up for re-scan of failed SN {serial_number_to_retest} on Port {port_name}.")
        self._current_test_port = port_name
        # Store the SN we expect for retest. _on_antenna_sn_entered will use the text field's content.
        # self._current_antenna_sn_under_test is updated in _on_antenna_sn_entered from the input field.
        # The main app will validate if the scanned SN matches serial_number_to_retest.
        self.detail_sn_label.setText(f"{serial_number_to_retest} (Retest)") # Indicate retest in details
        self.clear_graph()

        # Call the generic setup for ScanAntennaSN first
        self._setup_input_area("ScanAntennaSN") # This clears sn_input_antenna

        # Now, customize titles and pre-fill for retest
        self.antenna_scan_group.setTitle(f"RETEST Port {port_name}: Re-Scan FAILED Antenna")
        self.antenna_scan_label.setText(f"Re-scan '{serial_number_to_retest}' for Port {port_name}:")
        self._set_active_input_highlight(self.antenna_scan_group, self.sn_input_antenna) # Re-apply highlight
        self.sn_input_antenna.setFocus()


    def update_next_action_state(self, completed_port, can_test_next_port, can_test_next_order):
        """Sets up the 'Next Action' group based on main app logic."""
        logger.info(f"UI: Updating Next Action state. CanNextPort: {can_test_next_port}, CanNextOrder: {can_test_next_order}")

        # 1. Transition the UI state FIRST
        self.go_to_state("NextAction")

        # 2. NOW update the label and button states within the active group
        self.next_action_label.setText(f"Testing for Port '{completed_port}' is complete.\nChoose the next action:")
        self.test_next_port_button.setEnabled(can_test_next_port)
        self.test_next_order_button.setEnabled(can_test_next_order)
        self.finish_measurements_button.setEnabled(True) # Always enabled on this screen


    def proceed_to_next_port(self, next_port_name):
        """
        Called by main app after user selects a port via "TEST NEXT PORT".
        Sets UI state to start calibration for the next port.
        """
        logger.info(f"UI: Proceeding to next port via user selection: {next_port_name}")
        # self._current_test_port is set by set_current_test_port called from main app
        try:
            self._current_overall_port_index = self._ports_to_test.index(next_port_name)
        except ValueError:
            logger.warning(f"UI: Next port {next_port_name} not found in UI's _ports_to_test list.")
            self._current_overall_port_index = -1

        # UI counts for the new port's batch are reset by set_current_test_port if port changes
        self._current_antenna_sn_under_test = None
        self.detail_sn_label.setText("-")
        # self.update_statistics() # Already called by set_current_test_port

        logger.info(f"UI: Triggering calibration flow for selected next port {next_port_name}")
        self.request_calibration_for_port(next_port_name) # This checks timestamp and decides flow

    def finish_order_testing(self):
        """Called by main app when FINISH MEASUREMENTS is chosen."""
        logger.info("UI: Finishing measurements for this antenna/orientation.")
        self.go_to_antenna_selection()

    def go_to_antenna_selection(self):
        """Resets state and returns to the antenna selection page."""
        logger.info("UI: Returning to Antenna Selection.")
        self._reset_test_state()
        self.stacked_widget.setCurrentWidget(self.antenna_page)
        self.request_antenna_configs.emit()
        self.update_status("Select a new antenna to test.", "info")

    def go_to_state(self, state_name):
        """Utility function to directly set the UI input state."""
        logger.debug(f"UI: Explicitly going to state: {state_name}")
        if hasattr(self, '_setup_input_area'):
            self._setup_input_area(state_name)
        else:
            logger.warning(f"UI: Cannot go to state '{state_name}' - UI not fully initialized.")

    # --- UI Update and Helper Methods ---
    def _create_status_icon(self, color):
        """Creates a small, circular QPixmap icon of a given color."""
        pixmap = QPixmap(15, 12)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.GlobalColor.transparent)
        painter.drawEllipse(0, 0, 11, 11)
        painter.end()
        return pixmap

    def set_database_status(self, is_connected, message):
        """
        Updates the database status indicator in the status bar.
        
        :param is_connected: bool (True for connected, False for error), or None for intermediate state.
        :param message: The status message string to display.
        """
        icon_color = "#f39c12" # Yellow/Orange for connecting/initializing (None)
        if is_connected is True:
            icon_color = "#2ecc71" # Green for connected
        elif is_connected is False:
            icon_color = "#e74c3c" # Red for error/failed

        icon_pixmap = self._create_status_icon(icon_color)
        full_tooltip = f"Database Status: {message}"

        # Set the pixmap on the icon label
        self.db_status_icon_label.setPixmap(icon_pixmap)
        self.db_status_icon_label.setToolTip(full_tooltip)

        # Set the text on the text label
        self.db_status_text_label.setText(f" DB: {message}")
        self.db_status_text_label.setToolTip(full_tooltip)

    def update_status(self, message, level="info"):
        """Updates the main status label and status bar message."""
        self.status_display_label.setText(f"STATUS: {message}")
        if level == "good": self.status_display_label.setObjectName("StatusLabelGood")
        elif level == "bad": self.status_display_label.setObjectName("StatusLabelBad")
        else: self.status_display_label.setObjectName("StatusLabelInfo")
        self.status_display_label.style().unpolish(self.status_display_label)
        self.status_display_label.style().polish(self.status_display_label)
        self.status_bar.showMessage(message, 5000)

    def clear_graph(self):
        """Clears all data from the pyqtgraph plot."""
        if PYQTGRAPH_AVAILABLE and hasattr(self, 'plot_widget') and self.plot_widget:
            if self.plot_curve: self.plot_curve.clear()
            if self.upper_limit_curve: self.upper_limit_curve.clear()
            if self.lower_limit_curve: self.lower_limit_curve.clear()
            self._current_plot_x = []
            self._current_plot_y = []
            self._current_limit_x = []
            self._current_limit_y_upper = []
            self._current_limit_y_lower = []
            if hasattr(self.plot_widget, 'enableAutoRange'):
                self.plot_widget.enableAutoRange('xy', True)

    def clear_results_table(self):
        """Clears all rows from the results history table."""
        self.results_table.setRowCount(0)

    def add_table_row(self, timestamp, order_num, measurement_id, sn, port, freq, gain, limits,
                      ant_meas, gld_meas, spc_gain,
                      status_for_text_column, original_freq_status_for_coloring,
                      is_retry_no_count): # Added retry flag
        """Adds a row of results to the history table, with differentiated coloring."""
        row_position = self.results_table.rowCount()
        self.results_table.insertRow(row_position)

        def format_num(value, precision=3):
            if isinstance(value, (float, int)):
                return f"{value:.{precision}f}"
            return "N/A"

        sn_display = sn

        # Order: Timestamp, Order Number, ID, SN, Port, Freq, Gain, Limits, AntMeas, GldMeas, SpecGain, Status
        items_data = [
            timestamp,
            order_num,
            str(measurement_id),
            sn_display, port, # Use sn_display
            format_num(freq, 1), format_num(gain, 3), limits,
            format_num(ant_meas, 4), format_num(gld_meas, 4), format_num(spc_gain, 3),
            status_for_text_column # Use the (potentially overridden) status for the text in Status column
        ]

        items = [QTableWidgetItem(str(data)) for data in items_data]

        for i in [2, 5, 6, 7, 8, 9, 10, 11]:
            if i < len(items):
                items[i].setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        for col, item in enumerate(items):
            self.results_table.setItem(row_position, col, item)

        current_dark_mode = get_effective_theme_is_dark(QApplication.instance())
        pass_row_bg_hex = "#27ae60" if current_dark_mode else "#a5d6a7"
        fail_row_bg_hex = "#c0392b" if current_dark_mode else "#ef9a9a"

        pass_fg_hex = "#ecf0f1" if current_dark_mode else "#2c3e50"
        fail_fg_hex = "#ffffff" if current_dark_mode else "#943126"

        pass_row_bg_color = QColor(pass_row_bg_hex)
        fail_row_bg_color = QColor(fail_row_bg_hex)
        pass_fg_color = QColor(pass_fg_hex)
        fail_fg_color = QColor(fail_fg_hex)

        # Determine colors for 'other' columns based on original_freq_status_for_coloring
        other_cols_bg_color = None
        other_cols_fg_color = None
        if original_freq_status_for_coloring == "PASS":
            other_cols_bg_color = pass_row_bg_color
            other_cols_fg_color = pass_fg_color
        elif original_freq_status_for_coloring == "FAIL":
            other_cols_bg_color = fail_row_bg_color
            other_cols_fg_color = fail_fg_color

        # Determine colors for the 'Status' column based on status_for_text_column
        status_col_bg_color = None
        status_col_fg_color = None
        if status_for_text_column == "PASS":
            status_col_bg_color = pass_row_bg_color
            status_col_fg_color = pass_fg_color
        elif status_for_text_column == "FAIL":
            status_col_bg_color = fail_row_bg_color
            status_col_fg_color = fail_fg_color

        status_column_index = 11 # Index of the "Status" column

        for col in range(self.results_table.columnCount()):
            table_item = self.results_table.item(row_position, col)
            if table_item:
                if col == status_column_index:
                    if status_col_bg_color:
                        table_item.setBackground(status_col_bg_color)
                    if status_col_fg_color:
                        table_item.setForeground(status_col_fg_color)
                else: # Other columns
                    if other_cols_bg_color:
                        table_item.setBackground(other_cols_bg_color)
                    if other_cols_fg_color: # Ensure text color is set for these too
                        table_item.setForeground(other_cols_fg_color)

        self.results_table.scrollToBottom()

    def update_statistics(self):
        """Updates FPY and Tested Counts labels for the CURRENT port AND the overall order Pass/Fail."""
        port_display = f" ({self._current_test_port or 'Port'})"
        if self._current_order_quantity > 0:
            # _tested_in_current_port_batch correctly reflects non-retried tests
            tested_port_text = f"Tested{port_display}: {self._tested_in_current_port_batch} / {self._current_order_quantity}"
            if self._tested_in_current_port_batch > 0:
                fpy_port = (self._passed_in_current_port_batch / self._tested_in_current_port_batch) * 100
                fpy_port_text = f"FPY{port_display}: {fpy_port:.1f}%"
            else:
                fpy_port_text = f"FPY{port_display}: N/A"
        else:
            tested_port_text = f"Tested{port_display}: N/A"
            fpy_port_text = f"FPY{port_display}: N/A"
        self.tested_port_label.setText(tested_port_text)
        self.fpy_port_label.setText(fpy_port_text)

        passed_order_text = f"Order Passed: {self._passed_antennas_in_order}"
        failed_order_text = f"Order Failed: {self._failed_antennas_in_order}"
        self.detail_passed_order_label.setText(passed_order_text)
        self.detail_failed_order_label.setText(failed_order_text)

    def update_active_details(self):
         """Updates all labels in the 'Active Test Details' panel based on internal state."""
         self.detail_user_label.setText(self._current_user or "-")
         self.detail_antenna_label.setText(self._selected_antenna_name or "-")
         self.detail_pn_label.setText(self._selected_antenna_pn or "-")
         self.detail_order_label.setText(self._current_order_number or "-")
         self.detail_charge_label.setText(self._current_charge_number or "-")
         self.detail_orientation_label.setText(self._selected_orientation or "-")
         self.detail_sn_label.setText(self._current_antenna_sn_under_test or "-")
         self.update_statistics()

    def _update_port_selection_status(self):
        """Updates the 'Selected' and initial 'Status' column after user confirms port selection."""
        for i in range(self.port_status_table.rowCount()):
            port_item = self.port_status_table.item(i, 0)
            selected_item = self.port_status_table.item(i, 1)
            status_item = self.port_status_table.item(i, 2)
            if not port_item or not selected_item or not status_item: continue

            port_name = port_item.text()
            is_selected = port_name in self._ports_to_test
            self._port_status_data[port_name]["selected"] = is_selected

            status = "Pending" if is_selected else "Inactive"
            self._port_status_data[port_name]["status"] = status

            selected_item.setText("Yes" if is_selected else "No")
            status_item.setText(status)
            self.update_port_status(port_name, status=status)


    def update_port_status(self, port_name, status="Pending"):
        """Updates the status and visual style of a specific port row in the table."""
        if port_name not in self._port_status_data:
            return

        self._port_status_data[port_name]["status"] = status
        target_row = -1
        for i in range(self.port_status_table.rowCount()):
             row_port_item = self.port_status_table.item(i, 0)
             if row_port_item and row_port_item.text() == port_name:
                 target_row = i
                 break
        if target_row == -1: return

        current_dark_mode = get_effective_theme_is_dark(QApplication.instance())
        default_fg_color = QColor(self.port_status_table.palette().color(QPalette.ColorRole.Text))

        # Pass/Fail colors are now directly from stylesheet for consistency
        pass_row_bg_hex = "#27ae60" if current_dark_mode else "#a5d6a7"
        fail_row_bg_hex = "#c0392b" if current_dark_mode else "#ef9a9a"

        # Map status to colors (Hex BG, Hex/QColor FG)
        color_map = {
             "Testing": ("#f39c12" if current_dark_mode else "#fef9e7", "#ffffff" if current_dark_mode else "#a0522d"),
             "Done": (pass_row_bg_hex, "#ffffff" if current_dark_mode else "#145a32"),
             "Calibrating": ("#8e44ad" if current_dark_mode else "#f4ecf7", "#ffffff" if current_dark_mode else "#5b2c6f"),
             "Calibrated": ("#8e44ad" if current_dark_mode else "#f4ecf7", "#ffffff" if current_dark_mode else "#5b2c6f"),
             "Calibrated and Verified": ("#1abc9c" if current_dark_mode else "#d1f2eb", "#ffffff" if current_dark_mode else "#0e6655"),
             "Inactive": ("#7f8c8d" if current_dark_mode else "#f2f3f4", "#bdc3c7" if current_dark_mode else "#707b7c"),
             "Skipped": ("#7f8c8d" if current_dark_mode else "#f2f3f4", "#bdc3c7" if current_dark_mode else "#707b7c"),
             "Pending": (Qt.GlobalColor.transparent, default_fg_color),
             "Cal Failed": (fail_row_bg_hex, "#ffffff" if current_dark_mode else "#943126"),
             "Aborted": (fail_row_bg_hex, "#ffffff" if current_dark_mode else "#943126"),
             "Cal Aborted": (fail_row_bg_hex, "#ffffff" if current_dark_mode else "#943126"),
        }

        bg_hex_or_qcolor_val, fg_hex_or_qcolor = color_map.get(status, color_map["Pending"])

        bg_color_to_set = QColor(bg_hex_or_qcolor_val) if isinstance(bg_hex_or_qcolor_val, str) else bg_hex_or_qcolor_val
        fg_color_to_set = QColor(fg_hex_or_qcolor) if isinstance(fg_hex_or_qcolor, str) else fg_hex_or_qcolor


        status_item = self.port_status_table.item(target_row, 2)
        if status_item: status_item.setText(status)
        else:
             status_item = QTableWidgetItem(status)
             status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
             self.port_status_table.setItem(target_row, 2, status_item)

        for col in range(self.port_status_table.columnCount()):
            item = self.port_status_table.item(target_row, col)
            if item:
                item.setBackground(bg_color_to_set)
                item.setForeground(fg_color_to_set)


    def reset_for_new_order_same_antenna(self, port_that_just_finished_batch):
        """
        Resets state for a new order using the same antenna/ports.
        Only the port_that_just_finished_batch will retain "Calibrated and Verified"
        if its calibration is still valid. Other selected ports become "Pending".
        """
        logger.info(f"UI: Resetting for new order. Port '{port_that_just_finished_batch}' just finished its previous batch.")
        self._current_order_number = ""
        self._current_charge_number = ""
        self._current_order_quantity = 0
        self._tested_in_current_port_batch = 0 # Will be reset again if current_test_port changes
        self._passed_in_current_port_batch = 0 # Will be reset again if current_test_port changes
        self._current_antenna_sn_under_test = None
        self._completed_ports_in_run = 0 # Reset for the new order's run of ports

        self.detail_order_label.setText("-")
        self.detail_charge_label.setText("-")
        self.detail_sn_label.setText("-")
        self.clear_results_table() # Clear table for new order
        self.progress_bar.setValue(0)
        self._antenna_status_this_order = {} # Reset antenna pass/fail tracking for new order
        self._passed_antennas_in_order = 0
        self._failed_antennas_in_order = 0
        self.update_statistics() # Update stats display

        for i in range(self.port_status_table.rowCount()):
            port_item = self.port_status_table.item(i, 0)
            if port_item:
                port_name = port_item.text()

                if port_name not in self._ports_to_test: # Port not selected for this test run
                    self.update_port_status(port_name, status="Inactive")
                    continue

                # Port IS selected for this test run
                if port_name == port_that_just_finished_batch:
                    # This is the port that just completed its batch. Check its cal.
                    cal_timestamp = self._port_calibration_timestamps.get(port_name)
                    if cal_timestamp:
                        cal_age = datetime.now() - cal_timestamp
                        if cal_age.total_seconds() <= self._RECALIBRATION_TIME_SECONDS:
                            self.update_port_status(port_name, status="Calibrated and Verified")
                            logger.info(f"UI Reset (New Order): Port {port_name} (just finished) calibration remains valid.")
                        else:
                            self.update_port_status(port_name, status="Pending")
                            self._port_calibration_timestamps.pop(port_name, None) # Remove expired timestamp
                            logger.info(f"UI Reset (New Order): Port {port_name} (just finished) calibration EXPIRED. Set to Pending.")
                    else: # No timestamp (e.g. Silver cal did not complete successfully)
                        original_status_in_data = self._port_status_data.get(port_name, {}).get("status")
                        if original_status_in_data == "Calibrated": # Only Golden was done
                            self.update_port_status(port_name, status="Calibrated")
                            logger.info(f"UI Reset (New Order): Port {port_name} (just finished) was '{original_status_in_data}'. Retaining.")
                        else: # Was e.g. "Cal Failed" or something else, needs full re-evaluation
                            self.update_port_status(port_name, status="Pending")
                            logger.info(f"UI Reset (New Order): Port {port_name} (just finished, no timestamp, original: '{original_status_in_data}') set to Pending.")
                else:
                    # This is a port selected for testing, but NOT the one that just finished.
                    # Set its status to "Pending". Its timestamp (if any) is preserved.
                    # request_calibration_for_port will re-evaluate it when this port becomes active.
                    self.update_port_status(port_name, status="Pending")
                    logger.info(f"UI Reset (New Order): Port {port_name} (not the last tested) set to Pending.")

    def _reset_test_state(self):
        """Resets most internal state variables for a completely new antenna selection."""
        logger.info("UI: Performing full state reset.")
        self._antenna_configs = {}
        self._selected_antenna_name = None
        self._selected_antenna_pn = None
        self._selected_orientation = None
        self._ports_for_current_orientation = []
        self._ports_to_test = []
        self._current_test_port = None
        self._current_overall_port_index = -1
        self._current_order_number = ""
        self._current_charge_number = ""
        self._current_order_quantity = 0
        self._tested_in_current_port_batch = 0
        self._passed_in_current_port_batch = 0
        self._tested_in_current_order = 0
        self._passed_in_current_order = 0
        self._completed_ports_in_run = 0
        self._current_antenna_sn_under_test = None
        self._test_running = False
        self._port_status_data = {}
        self._port_calibration_timestamps = {}
        self._antenna_status_this_order = {}
        self._passed_antennas_in_order = 0
        self._failed_antennas_in_order = 0
        self._highlighted_group = None
        self._highlighted_widget = None

        self.update_active_details()
        self.port_status_table.setRowCount(0)
        self.clear_graph()
        self.clear_results_table()
        self.update_statistics()
        self.progress_bar.setValue(0)
        self.update_status("Idle", "info")
        self.abort_button.setEnabled(False) # Disable abort button as we are leaving test page
        self._setup_input_area("Idle")

    def _handle_users_updated(self):
        """Called when user management dialog signals changes."""
        logger.info("UI: User list potentially updated by UserManagementDialog.")
        # The dialog modifies self._users (passed by reference) and saves it.
        # We should reload from disk to ensure consistency and pick up any direct file edits (though not expected).
        self._users = load_users()
        self.request_user_list_update.emit() # Signal the main application controller if it cares

    def show_user_management_dialog(self):
        """Shows the user management dialog."""
        if not self._is_admin:
             QMessageBox.warning(self, "Access Denied", "Only Administrators can manage users.")
             return
        # Use the imported UserManagementDialog
        dialog = UserManagementDialog(self._users, self)
        dialog.users_updated.connect(self._handle_users_updated)
        dialog.exec()

    def show_about_dialog(self):
        """Shows the About dialog."""
        dialog = AboutDialog(self)
        dialog.exec()

    def closeEvent(self, event):
        """Handles the main window close event."""
        reply = QMessageBox.question(self, "Confirm Exit", "Are you sure you want to exit the Antenna Tester?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            logger.info("UI: Exit confirmed.")
            self.exit_application.emit()
            event.accept()
        else:
            logger.info("UI: Exit cancelled.")
            event.ignore()
# --- Example Usage / Dummy Main App ---
if __name__ == '__main__':
    # Basic logging configuration for standalone execution
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    app = QApplication(sys.argv)
    # QSettings needs organization and application name to be set for it to work reliably on all platforms
    app.setOrganizationName(COMPANY_NAME)
    app.setApplicationName(APP_NAME_FOR_SETTINGS)
    app.setApplicationVersion(APP_VERSION)


    class DummyMainApp(QObject):
        """Simulates the main application logic interacting with the UI."""
        def __init__(self, ui):
            super().__init__()
            self.ui = ui
            self.antenna_data = {}
            self.current_measurement_timer = None
            self.freq_index = 0
            self._simulated_results = []

            self.ports_available_for_orientation = []
            self.ports_selected_by_user = []
            self.ports_remaining_in_order = set()
            self.current_processing_port = None
            self.current_antenna_sn = None
            self.order_number = None
            self.charge_number = None
            self.order_quantity = 0
            self.current_antenna_key = None
            self.measurement_id_counter = 1
            self.is_current_test_a_no_count_retry = False # For retest logic
            self.current_silver_sn_validated = None

            # Recalibration time (Main app would load this from config)
            self.RECALIBRATION_TIME_CONFIG = timedelta(seconds=ui._RECALIBRATION_TIME_SECONDS) # Use UI's dummy
            # Main app does not need to store timestamps if UI handles it.

            self.tested_sns_persistent = {}
            self.order_history_status = {}
            # self.load_persistent_data() # for now i don't want to load the data

            self.dummy_antenna_configs = {
                 "ARS620 B3": {
                    "PN_H+S": "85224121", "PN_CUSTOMER": "787273", "PART_NUMBER": "787273",
                    "SN_GOLDEN_SAMPLE": "11",
                    "SN_SILVER_SAMPLE": "22",
                    "PORT_HORIZONTAL": ["TX1", "TX2", "RX1", "RX2"],
                    "PORT_VERTICAL": ["TX3", "TX4", "RX3", "RX4"],
                    "limits": {
                        "TX1": [(76.0+i*0.5, 10.0, 12.0, 11.45+i*0.01, 11.35+i*0.01, 0.5) for i in range(11)],
                        "TX2": [(76.0+i*0.5, 10.0, 12.0, 11.25+i*0.01, 11.15+i*0.01, 0.5) for i in range(11)],
                        "RX1": [(76.0+i*0.5, 10.0, 12.0, 11.45+i*0.01, 11.35+i*0.01, 0.5) for i in range(11)],
                        "RX2": [(76.0+i*0.5, 10.0, 12.0, 11.25+i*0.01, 11.15+i*0.01, 0.5) for i in range(11)],
                        "TX3": [(76.0+i*0.5, 10.4, 12.0, 11.45+i*0.01, 11.35+i*0.01, 0.5) for i in range(11)],
                        "TX4": [(76.0+i*0.5, 10.0, 12.0, 11.25+i*0.01, 11.15+i*0.01, 0.5) for i in range(11)],
                        "RX3": [(76.0+i*0.5, 10.0, 12.0, 11.45+i*0.01, 11.35+i*0.01, 0.5) for i in range(11)],
                        "RX4": [(76.0+i*0.5, 10.0, 12.0, 11.25+i*0.01, 11.15+i*0.01, 0.5) for i in range(11)],
                    },
                    "golden_measurements": { port: [] for port in ["TX1","TX2","RX1","RX2","TX3","TX4","RX3","RX4"]},
                },
                 "Test Antenna V1": {
                    "PART_NUMBER": "TEST-ANT-001",
                    "SN_GOLDEN_SAMPLE": "GOLD-TEST",
                    "SN_SILVER_SAMPLE": "SILVER-TEST",
                    "PORT_HORIZONTAL": ["H1", "H2"],
                    "PORT_VERTICAL": ["V1", "V2"],
                     "limits": {
                        "H1": [(80.0+i*0.2, 8.0, 10.0, 9.0+i*0.02, 8.9+i*0.02, 0.4) for i in range(11)],
                        "H2": [(80.0+i*0.2, 8.5, 10.5, 9.5-i*0.01, 9.4-i*0.01, 0.4) for i in range(11)],
                        "V1": [(80.0+i*0.2, 8.0, 10.0, 9.1+i*0.01, 9.0+i*0.01, 0.4) for i in range(11)],
                        "V2": [(80.0+i*0.2, 8.5, 10.5, 9.4-i*0.02, 9.3-i*0.02, 0.4) for i in range(11)],
                    },
                    "golden_measurements": { port: [] for port in ["H1", "H2", "V1", "V2"]},
                 }
            }
            self._connect_signals()

            # --- Simulate DB connection status updates ---
            QTimer.singleShot(500, lambda: self.ui.set_database_status(None, "Connecting..."))
            QTimer.singleShot(2500, lambda: self.ui.set_database_status(True, "Connected"))
            # Example of a failure after some time, uncomment to test
            # QTimer.singleShot(10000, lambda: self.ui.set_database_status(False, "Connection Lost"))
            # --- END DB Sim ---

        def _connect_signals(self):
            self.ui.request_antenna_configs.connect(self.provide_antenna_configs)
            self.ui.antenna_selected.connect(self.load_antenna_config)
            self.ui.orientation_selected.connect(self.handle_orientation_selection)
            self.ui.ports_selected_for_test.connect(self.handle_ports_selected)
            self.ui.start_port_selected_for_testing.connect(self.handle_start_port_selected)
            self.ui.golden_sample_scan_received.connect(self.validate_golden_sn)
            self.ui.start_golden_measurement.connect(self.do_golden_measurement)
            self.ui.silver_sample_scan_received.connect(self.validate_silver_sn)
            self.ui.start_silver_measurement.connect(self.do_silver_measurement)
            self.ui.order_info_received.connect(self.handle_order_info)
            self.ui.antenna_sn_scan_received.connect(self.validate_antenna_sn)
            self.ui.retry_test_confirmed.connect(self.handle_retry_test) # For SN already tested warning
            self.ui.request_retest_failed_unit.connect(self.handle_request_retest_failed_unit) # NEW for failure retest
            self.ui.start_antenna_test_for_port.connect(self.do_antenna_measurement)
            self.ui.port_batch_run_complete.connect(self.handle_port_batch_complete)
            self.ui.request_test_next_port.connect(self.handle_request_test_next_port)
            self.ui.request_test_next_order.connect(self.handle_request_test_next_order)
            self.ui.request_finish_measurements.connect(self.handle_request_finish_measurements)
            self.ui.abort_test_requested.connect(self.abort_current_action)
            self.ui.exit_application.connect(self.cleanup_and_exit)
            self.ui.request_user_list_update.connect(self.reload_users_maybe)
            self.ui.request_load_order_history.connect(self.load_and_apply_order_history)

        @Slot()
        def provide_antenna_configs(self):
            logger.info("DummyApp: Providing antenna configs")
            antenna_names = list(self.dummy_antenna_configs.keys())
            self.ui.display_antenna_configs(antenna_names)

        @Slot(str)
        def load_antenna_config(self, antenna_name):
            logger.info(f"DummyApp: Loading config for {antenna_name}")
            if antenna_name in self.dummy_antenna_configs:
                self.antenna_data = self.dummy_antenna_configs[antenna_name]
                pn = self.antenna_data.get("PART_NUMBER", "N/A")
                self.antenna_data["name"] = antenna_name
                self.ui.set_antenna_details(antenna_name, pn)
                self.order_number = None
                self.charge_number = None
                self.order_quantity = 0
                self.ui.show_orientation_selection()
            else:
                 QMessageBox.critical(self.ui, "Error", f"Antenna configuration not found: {antenna_name}")
                 self.ui.go_to_antenna_selection()

        @Slot(str)
        def handle_orientation_selection(self, orientation):
            logger.info(f"DummyApp: Orientation selected: {orientation}")
            self.current_antenna_key = f"{self.antenna_data['name']}_{orientation}"
            key = f"PORT_{orientation.upper()}"
            ports = self.antenna_data.get(key, [])
            if not ports:
                 QMessageBox.warning(self.ui, "Config Warning", f"No ports defined for {orientation}.")
                 self.ui.go_to_state("SelectOrientation")
                 return
            self.ports_available_for_orientation = ports
            self.ui.populate_port_status_display(self.ports_available_for_orientation)
            self.ui.show_port_selection()

        @Slot(list)
        def handle_ports_selected(self, selected_ports):
            logger.info(f"DummyApp: Ports selected by user: {selected_ports}")
            self.ports_selected_by_user = selected_ports

        @Slot(str)
        def handle_start_port_selected(self, start_port):
            logger.info(f"DummyApp: User selected starting port: {start_port}")
            if not self.ports_selected_by_user or start_port not in self.ports_selected_by_user:
                logger.error(f"DummyApp: Invalid start port '{start_port}' or no ports selected.")
                self.ui.go_to_state("SelectStartPort")
                return

            self.current_processing_port = start_port
            self.ui.set_current_test_port(start_port)

            self.ports_remaining_in_order = set(self.ports_selected_by_user)

            if self.order_number:
                logger.info(f"DummyApp: Order number {self.order_number} known, requesting history load.")
                self.ui.request_load_order_history.emit(self.order_number)
            else:
                logger.info("DummyApp: No order active. UI will go to EnterOrderInfo.")
                self.ui.go_to_state("EnterOrderInfo")


        @Slot(str, str)
        def validate_golden_sn(self, scanned_sn, port_name):
            logger.info(f"DummyApp: Validating Golden SN '{scanned_sn}' for Port '{port_name}'")
            if port_name != self.current_processing_port: return
            expected = self.antenna_data.get("SN_GOLDEN_SAMPLE", "N/A")
            is_valid = (scanned_sn == expected)
            msg = f"Golden SN mismatch." if not is_valid else ""
            QTimer.singleShot(150, lambda p=port_name, v=is_valid, e=expected, m=msg: self.ui.report_golden_sn_validation(p, v, e, m))

        @Slot(str)
        def do_golden_measurement(self, port_name):
            logger.info(f"DummyApp: Starting Golden Measurement Sim for Port {port_name}")
            if port_name != self.current_processing_port: return
            self.freq_index = 0
            self._simulated_results = []
            self.ui._test_running = True
            self.current_measurement_timer = QTimer(self)
            self.current_measurement_timer.timeout.connect(self._simulate_golden_measurement_step)
            self.current_measurement_timer.start(50)

        def _simulate_golden_measurement_step(self):
            port_name = self.current_processing_port
            if self.freq_index < 11:
                limits_for_port = self.antenna_data.get("limits", {}).get(port_name, [])
                freq, ll, ul, spec_gain, _, _ = (76.0 + self.freq_index * 0.5, 10, 12, 11, 11, 0.5)
                if self.freq_index < len(limits_for_port):
                   try:
                       freq, ll, ul, spec_gain, _, _ = limits_for_port[self.freq_index]
                   except (IndexError, ValueError): pass

                sim_meas_dbm = -1.5 + random.uniform(-0.2, 0.2) - self.freq_index * 0.05
                self._simulated_results.append({"Antenna_Measurement": sim_meas_dbm})

                if self.ui.stacked_widget.currentWidget() == self.ui.test_page:
                     self.ui.progress_bar.setValue(self.freq_index + 1)
                self.freq_index += 1
            else:
                if self.current_measurement_timer: self.current_measurement_timer.stop(); self.current_measurement_timer = None
                self.ui._test_running = False
                logger.info(f"DummyApp: Golden measurement complete for Port {port_name}")

                if port_name not in self.antenna_data.get("golden_measurements", {}):
                    if "golden_measurements" not in self.antenna_data:
                        self.antenna_data["golden_measurements"] = {}
                    self.antenna_data["golden_measurements"][port_name] = []

                self.antenna_data["golden_measurements"][port_name] = [res["Antenna_Measurement"] for res in self._simulated_results]
                logger.info(f"DummyApp: Stored Golden dBm values for {port_name}")
                self.ui.report_golden_measurement_complete(port_name, success=True)


        @Slot(str, str)
        def validate_silver_sn(self, scanned_sn, port_name):
            logger.info(f"DummyApp: Validating Silver SN '{scanned_sn}' for Port '{port_name}'")
            if port_name != self.current_processing_port: return
            expected = self.antenna_data.get("SN_SILVER_SAMPLE", "N/A")
            is_valid = (scanned_sn == expected)
            msg = f"Silver SN mismatch." if not is_valid else ""
            if is_valid:
                self.current_silver_sn_validated = scanned_sn
            else:
                self.current_silver_sn_validated = None
            QTimer.singleShot(150, lambda p=port_name, v=is_valid, e=expected, m=msg: self.ui.report_silver_sn_validation(p, v, e, m))


        @Slot(str)
        def do_silver_measurement(self, port_name):
            logger.info(f"DummyApp: Starting Silver Measurement Sim for Port {port_name}")
            if port_name != self.current_processing_port: return
            self.freq_index = 0
            self._simulated_results = []
            self.ui._test_running = True
            self.current_measurement_timer = QTimer(self)
            self.current_measurement_timer.timeout.connect(self._simulate_silver_measurement_step)
            self.current_measurement_timer.start(50)


        def _simulate_silver_measurement_step(self):
            port_name = self.current_processing_port
            if not self.ui._test_running or not port_name:
                logger.error(f"DummyApp: Silver measurement step called in invalid state (Running: {self.ui._test_running}, Port: {port_name}). Aborting step.")
                if self.current_measurement_timer:
                    self.current_measurement_timer.stop()
                    self.current_measurement_timer = None
                self.ui._test_running = False
                return

            if self.freq_index < 11:
                limits_for_port = self.antenna_data.get("limits", {}).get(port_name, [])
                golden_meas_list = self.antenna_data.get("golden_measurements", {}).get(port_name)

                # Default values in case config is missing/incomplete
                default_freq = 76.0 + self.freq_index * 0.5
                default_spec_gain_golden = 11.0  # Default Golden Horn Spec Gain
                default_silver_gain_horn = 10.8  # Default Silver Horn Actual Spec Gain
                default_silver_spec_limit = 0.5  # Default +/- limit for Silver Horn validation
                default_golden_meas_dbm = -1.0   # Default Golden Horn measured power

                freq = default_freq
                spec_gain_golden = default_spec_gain_golden # This is the Golden Horn's spec gain
                silver_gain_horn = default_silver_gain_horn # This is the Silver Horn's actual spec gain
                silver_spec_limit = default_silver_spec_limit # This is the +/- tolerance for Silver Horn
                golden_meas_dbm = default_golden_meas_dbm

                config_found = False
                if limits_for_port and self.freq_index < len(limits_for_port):
                    try:
                        config_tuple = limits_for_port[self.freq_index]
                        if len(config_tuple) >= 6:
                            freq = config_tuple[0]                # Frequency
                            spec_gain_golden = config_tuple[3]    # Golden Horn Spec Gain
                            silver_gain_horn = config_tuple[4]    # Silver Horn Actual Spec Gain
                            silver_spec_limit = config_tuple[5]   # Silver Horn Validation Limit (+/- dBi)
                            config_found = True
                        else:
                            logger.warning(f"DummyApp: Incomplete limit tuple at index {self.freq_index} for port {port_name}. Len={len(config_tuple)}. Using defaults for Silver.")
                    except (IndexError, TypeError, ValueError) as e:
                        logger.warning(f"DummyApp: Error accessing limit data (for Silver) at index {self.freq_index} for port {port_name}: {e}. Using defaults.")
                else:
                    logger.warning(f"DummyApp: Frequency index {self.freq_index} out of bounds for limits config (len={len(limits_for_port if limits_for_port else [])}) for port {port_name} (Silver). Using defaults.")

                if not config_found:
                    logger.debug(f"DummyApp: Using default limit/gain values for Silver Sim - Freq Index {self.freq_index}, Port {port_name}")

                if golden_meas_list and self.freq_index < len(golden_meas_list):
                    try:
                        golden_meas_dbm = golden_meas_list[self.freq_index]
                    except (IndexError, TypeError, ValueError) as e:
                        logger.warning(f"DummyApp: Error accessing golden measurement data at index {self.freq_index} for port {port_name}: {e}. Using default ({default_golden_meas_dbm}).")
                        golden_meas_dbm = default_golden_meas_dbm
                else:
                    logger.warning(f"DummyApp: Golden measurement data missing or index {self.freq_index} out of bounds for port {port_name} (len={len(golden_meas_list if golden_meas_list else [])}). Using default ({default_golden_meas_dbm}).")

                noise_factor = 0.3
                random_deviation = random.uniform(-silver_spec_limit * noise_factor, silver_spec_limit * noise_factor)

                # This is the "effective measured gain" of the silver sample we are simulating
                calculated_gain_silver = silver_gain_horn + random_deviation

                # Now, derive the sim_silver_meas_dbm that would produce this calculated_gain_silver,
                # given the known golden_meas_dbm and spec_gain_golden (Golden Horn's spec gain).
                # Formula: Antenna_Gain = Golden_Horn_Spec_Gain - Antenna_Measured_Power_dBm + Golden_Horn_Measured_Power_dBm
                # So, for Silver:
                # calculated_gain_silver = spec_gain_golden - sim_silver_meas_dbm + golden_meas_dbm
                # Rearranging for sim_silver_meas_dbm:
                # sim_silver_meas_dbm = spec_gain_golden + golden_meas_dbm - calculated_gain_silver
                sim_silver_meas_dbm = spec_gain_golden + golden_meas_dbm - calculated_gain_silver

                silver_validation_ll = silver_gain_horn - silver_spec_limit
                silver_validation_ul = silver_gain_horn + silver_spec_limit

                status = "PASS" if silver_validation_ll <= calculated_gain_silver <= silver_validation_ul else "FAIL"

                self._simulated_results.append({
                    "Frequency_GHz": freq,
                    "Antenna_Gain": calculated_gain_silver,
                    "Lower_Limit": silver_validation_ll,
                    "Upper_Limit": silver_validation_ul,
                    "Pass": status,
                    "Antenna_Measurement": sim_silver_meas_dbm,
                    "Golden_Measurement": golden_meas_dbm,
                    "Spec_Gain_Displayed": silver_gain_horn
                })

                if self.ui.stacked_widget.currentWidget() == self.ui.test_page:
                    self.ui.update_measurement_progress(self.freq_index, freq, calculated_gain_silver, silver_validation_ll, silver_validation_ul)
                self.freq_index += 1
            else:
                if self.current_measurement_timer:
                    self.current_measurement_timer.stop()
                    self.current_measurement_timer = None
                self.ui._test_running = False
                logger.info(f"DummyApp: Silver measurement simulation complete for Port {port_name}")

                overall_silver_status = "PASS"
                fail_details = []
                for res in self._simulated_results:
                    if res.get("Pass") == "FAIL":
                        overall_silver_status = "FAIL"
                        fail_details.append(
                            f"  Freq {res.get('Frequency_GHz', 'N/A')} GHz: "
                            f"Measured {res.get('Antenna_Gain', float('nan')):.2f} dBi "
                            f"(Validation Limits: {res.get('Lower_Limit', float('nan')):.2f} / {res.get('Upper_Limit', float('nan')):.2f})"
                        )

                success = (overall_silver_status == "PASS")
                message = "\n".join(fail_details) if not success else "Silver Sample calibration passed."

                # Pass the full list of original _simulated_results to the UI
                # The UI will now handle creating the list with 'Original_Pass_Status_For_Coloring'
                silver_sn_to_report = self.current_silver_sn_validated or "UNKNOWN_SILVER_SN"
                current_measurement_id = self.measurement_id_counter
                self.measurement_id_counter += 1

                self.ui.report_silver_measurement_complete(
                    port_name,
                    success=success, # This is the overall_silver_status boolean
                    message=message,
                    silver_sn=silver_sn_to_report,
                    measurement_id=current_measurement_id,
                    silver_results=self._simulated_results # Pass the original detailed results
                )

        @Slot(str, str, int)
        def handle_order_info(self, order_num, charge_num, quantity):
            logger.info(f"DummyApp: Received order info: Order='{order_num}', Charge='{charge_num}', Quantity={quantity}")
            if self.order_number != order_num:
                 logger.info("DummyApp: New order number detected.")
                 self.ports_remaining_in_order = set(self.ports_selected_by_user)

            self.order_number = order_num
            self.charge_number = charge_num
            self.order_quantity = quantity

        @Slot(str)
        def load_and_apply_order_history(self, order_num):
            logger.info(f"DummyApp: Checking history for Order '{order_num}'")
            initial_start_port = self.current_processing_port
            if not initial_start_port:
                logger.error("DummyApp: Cannot load history - no initial start port selected by user or logic.")
                self.ui.go_to_state("SelectStartPort")
                return

            history_found = False
            statuses_from_history = {}
            if order_num in self.order_history_status:
                history_found = True
                logger.info("DummyApp: Found history, applying to UI.")
                statuses_from_history = self.order_history_status[order_num]

                current_run_selected_ports = set(self.ports_selected_by_user)
                ports_still_needed_for_this_order = set()
                for port in current_run_selected_ports:
                    if statuses_from_history.get(port) not in ["Done", "Skipped"]:
                        ports_still_needed_for_this_order.add(port)
                self.ports_remaining_in_order = ports_still_needed_for_this_order
                logger.info(f"DummyApp: Ports remaining for order '{order_num}' after loading history: {self.ports_remaining_in_order}")
            else:
                logger.info("DummyApp: No history found for this order.")
                self.ports_remaining_in_order = set(self.ports_selected_by_user)
                logger.info(f"DummyApp: Ports remaining for new order '{order_num}': {self.ports_remaining_in_order}")

            self.ui.apply_loaded_order_status(statuses_from_history)

            effective_start_port_status = self.ui._port_status_data.get(initial_start_port, {}).get("status", "Pending")
            if statuses_from_history.get(initial_start_port) in ["Done", "Skipped"]:
                effective_start_port_status = statuses_from_history.get(initial_start_port)

            logger.info(f"DummyApp: Status of intended start port '{initial_start_port}' is '{effective_start_port_status}' after history and UI cal check.")

            if effective_start_port_status in ["Done", "Skipped"]:
                logger.info(f"DummyApp: Intended start port '{initial_start_port}' is already completed for order '{order_num}'.")

                msg_box = QMessageBox(self.ui)
                msg_box.setWindowTitle("Port Already Tested")
                msg_text = (f"The initially selected port '{initial_start_port}' is already marked as "
                            f"'{effective_start_port_status}' for order '{order_num}'.\n\nWhat would you like to do?")
                
                test_again_button = msg_box.addButton("Test Again", QMessageBox.ButtonRole.ActionRole)
                select_different_button = None
                
                if self.ports_remaining_in_order: 
                    select_different_button = msg_box.addButton("Select Different Port", QMessageBox.ButtonRole.ActionRole)
                else: 
                    msg_text = (f"The initially selected port '{initial_start_port}' is already marked as "
                                f"'{effective_start_port_status}' for order '{order_num}'.\n"
                                "There are no other selected ports pending for this order.\n\n"
                                f"Would you like to test '{initial_start_port}' again?")

                msg_box.setText(msg_text)
                msg_box.setIcon(QMessageBox.Icon.Question)
                cancel_button = msg_box.addButton(QMessageBox.StandardButton.Cancel)
                msg_box.setDefaultButton(cancel_button if not select_different_button else select_different_button)

                msg_box.exec()
                clicked_button = msg_box.clickedButton()

                if clicked_button == test_again_button:
                    logger.info(f"DummyApp: User chose to test port '{initial_start_port}' again.")
                    
                    persistence_key_to_clear = (self.current_antenna_key, initial_start_port)
                    if persistence_key_to_clear in self.tested_sns_persistent:
                        logger.info(f"DummyApp: Clearing previously tested SNs for {persistence_key_to_clear} due to 'Test Again' on order port.")
                        self.tested_sns_persistent[persistence_key_to_clear].clear()
                    else:
                        logger.info(f"DummyApp: No SNs to clear for {persistence_key_to_clear} (key not found or port never tested under this antenna config).")

                    if self.order_number in self.order_history_status and initial_start_port in self.order_history_status[self.order_number]:
                        self.order_history_status[self.order_number][initial_start_port] = "Pending (Re-test)"
                        logger.info(f"DummyApp: Updated in-memory history for {initial_start_port} to 'Pending (Re-test)' for order {self.order_number}.")
                    
                    self.ports_remaining_in_order.add(initial_start_port) 

                    self.current_processing_port = initial_start_port
                    self.ui.set_current_test_port(initial_start_port)
                    self.ui.update_port_status(initial_start_port, status="Pending")
                    self.ui.request_calibration_for_port(initial_start_port)
                    return

                elif select_different_button and clicked_button == select_different_button:
                    logger.info(f"DummyApp: User chose to select a different port.")
                    remaining_list_for_selection = sorted(list(self.ports_remaining_in_order))
                    
                    if not remaining_list_for_selection: 
                         QMessageBox.information(self.ui, "No Other Ports", "There are no other available ports to select for this order run.")
                         self.save_persistent_data()
                         self.ui.go_to_antenna_selection()
                         self._reset_main_app_state()
                         return

                    chosen_port, ok = QInputDialog.getItem(self.ui, "Select Different Starting Port",
                                                        "Please choose a different port to start with from the remaining available ports for this test run:",
                                                        remaining_list_for_selection, 0, False)
                    if ok and chosen_port:
                        logger.info(f"DummyApp: User selected new starting port: {chosen_port}")
                        self.current_processing_port = chosen_port
                        self.ui.set_current_test_port(chosen_port)
                        self.ui.request_calibration_for_port(chosen_port)
                    else:
                        logger.info("DummyApp: User cancelled selecting a different starting port.")
                        QMessageBox.warning(self.ui, "Operation Cancelled", "You chose not to select a different starting port.\nReturning to antenna selection.")
                        self.save_persistent_data()
                        self.ui.go_to_antenna_selection()
                        self._reset_main_app_state()
                    return

                elif clicked_button == cancel_button or msg_box.clickedButton() is None:
                    logger.info("DummyApp: User cancelled the choice. Returning to antenna selection.")
                    QMessageBox.information(self.ui, "Operation Cancelled", "Operation cancelled. Returning to antenna selection.")
                    self.save_persistent_data()
                    self.ui.go_to_antenna_selection()
                    self._reset_main_app_state()
                    return
                
                if not self.ports_remaining_in_order and clicked_button != test_again_button :
                    QMessageBox.information(self.ui, "Order Section Complete",
                                            f"All selected ports ({', '.join(self.ports_selected_by_user)}) "
                                            f"are already completed for order '{order_num}'.\n"
                                            "Proceeding to 'Next Action' screen.")
                    last_completed_port_display = initial_start_port
                    if self.ports_selected_by_user: last_completed_port_display = self.ports_selected_by_user[-1]
                    
                    self.ui.update_next_action_state(
                        completed_port=last_completed_port_display,
                        can_test_next_port=False,
                        can_test_next_order=True
                    )
                    return

            else: 
                logger.info(f"DummyApp: Proceeding with port: {initial_start_port}. Requesting UI to manage its calibration.")
                self.ui.request_calibration_for_port(initial_start_port)


        @Slot(str, str)
        def validate_antenna_sn(self, scanned_sn, port_name):
            logger.info(f"DummyApp: Validating SN '{scanned_sn}' for Port '{port_name}' (Order: '{self.order_number}', Retest-No-Count-Pending: {self.is_current_test_a_no_count_retry})")
            if port_name != self.current_processing_port: return

            expected_sn_for_retest = None
            if self.is_current_test_a_no_count_retry: # If we are in a retest-due-to-failure flow
                expected_sn_for_retest = self.current_antenna_sn # This was set in handle_request_retest_failed_unit
                logger.info(f"DummyApp: Retest flow, expecting SN: {expected_sn_for_retest}")

            valid_format = bool(scanned_sn)
            message = ""
            is_valid_for_proceeding = False
            # report_as_already_tested controls if UI shows the "SN previously tested on this port" popup.
            # This should be false if we are in the retest-due-to-failure flow (is_current_test_a_no_count_retry is true)
            # because the user *explicitly* chose to retest.
            report_as_already_tested_for_ui_dialog = False

            if not valid_format:
                message = "Antenna Serial Number cannot be empty."
                is_valid_for_proceeding = False
            elif self.is_current_test_a_no_count_retry: # In retest-due-to-failure flow
                if scanned_sn == expected_sn_for_retest:
                    logger.info(f"DummyApp: SN {scanned_sn} matches expected SN {expected_sn_for_retest} for retest.")
                    is_valid_for_proceeding = True
                    # self.current_antenna_sn is already correct (the one that failed and is being retested)
                else:
                    message = f"Incorrect Serial Number for retest. Expected '{expected_sn_for_retest}', scanned '{scanned_sn}'."
                    is_valid_for_proceeding = False
            else: # Normal scan flow (not a retest-due-to-failure)
                self.current_antenna_sn = scanned_sn # Update current_antenna_sn with the newly scanned one
                persistence_key = (self.current_antenna_key, port_name)
                sns_tested_for_this_port = self.tested_sns_persistent.get(persistence_key, set())
                report_as_already_tested_for_ui_dialog = scanned_sn in sns_tested_for_this_port
                is_valid_for_proceeding = True # Format is good, it's a valid SN to consider

            # Determine the `is_retest_flow` flag for the UI's report_antenna_sn_validation method.
            # This flag tells the UI to bypass its own "already tested" dialog logic if we are in main_app's retest flow.
            ui_is_retest_flow_flag = self.is_current_test_a_no_count_retry and is_valid_for_proceeding

            QTimer.singleShot(100, lambda: \
                self.ui.report_antenna_sn_validation(
                    is_valid_for_proceeding,
                    report_as_already_tested_for_ui_dialog, # For UI's own dialog logic
                    message,
                    is_retest_flow=ui_is_retest_flow_flag # To bypass UI dialog if main app is handling retest
                )
            )

        @Slot(bool, str)
        def handle_retry_test(self, retry, serial_number): # This is for SN-already-tested warning from UI
            port_name = self.current_processing_port
            logger.info(f"DummyApp: Retry decision for SN-already-tested (UI warning): {retry} for SN '{serial_number}' on Port '{port_name}'")
            if retry: # User clicked "Test Again" on the UI's warning
                logger.info(f"DummyApp: Marking upcoming test for SN {serial_number} on Port {port_name} as a NO-COUNT retry.")
                self.is_current_test_a_no_count_retry = True # This test will not increment the counter
                self.current_antenna_sn = serial_number # Ensure main app knows this is the SN to test
                # UI is already in "StartAntennaTest"
            else: # User clicked "Scan Next Unit" on the UI's warning
                logger.info(f"DummyApp: User chose not to re-test SN {serial_number} on Port {port_name}. Scanning next.")
                self.is_current_test_a_no_count_retry = False
                self.current_antenna_sn = None # Clear SN as we are scanning next
                # UI is already in "ScanAntennaSN"

        @Slot(str, str) # NEW: Handles request from UI after a test failure
        def handle_request_retest_failed_unit(self, port_name, serial_number):
            logger.info(f"DummyApp: Retest requested by UI for failed SN {serial_number} on Port {port_name}")
            self.is_current_test_a_no_count_retry = True # This IS a "no-count" retry
            self.current_processing_port = port_name
            self.current_antenna_sn = serial_number # This is the SN we EXPECT to be re-scanned

            self.ui.set_current_test_port(port_name) # Ensure UI context matches
            # Instruct UI to prepare for re-scanning this specific SN
            self.ui.setup_for_retest_scan(port_name, serial_number)


        @Slot(str)
        def do_antenna_measurement(self, port_name):
            # self.current_antenna_sn should be correctly set by now, either from a normal scan
            # or from the retest flow (where it's the SN that failed).
            logger.info(f"DummyApp: Starting DUT Measurement Sim for SN '{self.current_antenna_sn}' Port '{port_name}' (Retry-No-Count: {self.is_current_test_a_no_count_retry})")
            if port_name != self.current_processing_port or not self.current_antenna_sn:
                 logger.error("DummyApp: Measurement start context invalid.")
                 # If it's a retest flow and SN somehow got cleared, might need to go back to re-scan
                 if self.is_current_test_a_no_count_retry and self.current_antenna_sn:
                     self.ui.setup_for_retest_scan(port_name, self.current_antenna_sn)
                 else:
                     self.ui.go_to_state("ScanAntennaSN")
                 return

            self.freq_index = 0
            self._simulated_results = []
            self.ui._test_running = True
            self.current_measurement_timer = QTimer(self)
            self.current_measurement_timer.timeout.connect(self._simulate_antenna_measurement_step)
            self.current_measurement_timer.start(75)


        def _simulate_antenna_measurement_step(self):
            port_name = self.current_processing_port
            serial_number = self.current_antenna_sn

            if not self.ui._test_running or not port_name or not serial_number:
                 logger.error(f"DummyApp: Antenna measurement step called in invalid state (Running: {self.ui._test_running}, Port: {port_name}, SN: {serial_number}). Aborting step.")
                 if self.current_measurement_timer:
                     self.current_measurement_timer.stop()
                     self.current_measurement_timer = None
                 self.ui._test_running = False
                 return

            if self.freq_index < 11:
                limits_for_port = self.antenna_data.get("limits", {}).get(port_name, [])
                golden_meas_list = self.antenna_data.get("golden_measurements", {}).get(port_name)

                default_freq = 76.0 + self.freq_index * 0.5
                default_ll = 9.0
                default_ul = 13.0
                default_spec_gain_golden = 11.5
                default_golden_meas_dbm = -1.0

                freq = default_freq
                ll = default_ll
                ul = default_ul
                spec_gain_golden = default_spec_gain_golden
                golden_meas_dbm = default_golden_meas_dbm

                config_found = False
                if limits_for_port and self.freq_index < len(limits_for_port):
                    try:
                        config_tuple = limits_for_port[self.freq_index]
                        if len(config_tuple) >= 4:
                            freq = config_tuple[0]
                            ll = config_tuple[1]
                            ul = config_tuple[2]
                            spec_gain_golden = config_tuple[3]
                            config_found = True
                        else:
                            logger.warning(f"DummyApp: Incomplete limit tuple (DUT) at index {self.freq_index} for port {port_name}. Len={len(config_tuple)}. Using defaults.")
                    except (IndexError, TypeError, ValueError) as e:
                        logger.warning(f"DummyApp: Error accessing limit data (DUT) at index {self.freq_index} for port {port_name}: {e}. Using defaults.")
                else:
                    logger.warning(f"DummyApp: Frequency index {self.freq_index} out of bounds for DUT limits config (len={len(limits_for_port if limits_for_port else [])}) for port {port_name}. Using defaults.")

                if not config_found:
                    logger.debug(f"DummyApp: Using default DUT limit/gain values for Freq Index {self.freq_index}, Port {port_name}")

                if golden_meas_list and self.freq_index < len(golden_meas_list):
                    try:
                        golden_meas_dbm = golden_meas_list[self.freq_index]
                    except (IndexError, TypeError, ValueError) as e:
                        logger.warning(f"DummyApp: Error accessing golden measurement data (DUT) at index {self.freq_index} for port {port_name}: {e}. Using default ({default_golden_meas_dbm}).")
                        golden_meas_dbm = default_golden_meas_dbm
                else:
                    logger.warning(f"DummyApp: Golden measurement data missing or index {self.freq_index} out of bounds for port {port_name} (len={len(golden_meas_list if golden_meas_list else [])}) (DUT). Using default ({default_golden_meas_dbm}).")

                FAIL_PROBABILITY_PER_POINT = 0.05
                is_this_point_failing = random.random() < FAIL_PROBABILITY_PER_POINT
                calculated_gain_dut = 0.0

                if is_this_point_failing:
                    spec_width = ul - ll
                    failure_offset_value = 0.0
                    if spec_width > 0:
                        failure_offset_value = spec_width * random.uniform(0.1, 0.5)
                    else:
                        failure_offset_value = random.uniform(0.2, 1.0)
                    if random.random() < 0.5:
                        calculated_gain_dut = ll - failure_offset_value
                    else:
                        calculated_gain_dut = ul + failure_offset_value
                    logger.warning(f"*** DummyApp: Simulating FAIL for DUT {serial_number}/{port_name} @ FreqIndex {self.freq_index}. Gain: {calculated_gain_dut:.3f}, Limits: {ll:.2f}/{ul:.2f} ***")
                else:
                    if ul > ll:
                        target_gain_center = (ll + ul) / 2.0
                        spec_half_width = (ul - ll) / 2.0
                        # noise_factor_pass determines how far from center the value can be,
                        # 0.0 = always at center, 1.0 = can reach spec limits.
                        noise_factor_pass = 0.90 # Allow up to 90% of half-width deviation from center
                        random_deviation_from_center = random.uniform(
                            -spec_half_width * noise_factor_pass,
                             spec_half_width * noise_factor_pass
                        )
                        calculated_gain_dut = target_gain_center + random_deviation_from_center
                    elif ul == ll:
                        calculated_gain_dut = ll
                    else:
                        logger.warning(f"DummyApp: Invalid spec ul < ll ({ul} < {ll}) for DUT {serial_number}/{port_name}. Simulating pass near 'll'.")
                        calculated_gain_dut = ll + random.uniform(-0.05, 0.05)

                sim_ant_meas_dbm = spec_gain_golden + golden_meas_dbm - calculated_gain_dut
                status = "PASS" if ll <= calculated_gain_dut <= ul else "FAIL"

                self._simulated_results.append({
                    "Frequency_GHz": freq,
                    "Antenna_Gain": calculated_gain_dut, # This is the "measured" gain of the DUT
                    "Lower_Limit": ll,                   # DUT Lower Limit
                    "Upper_Limit": ul,                   # DUT Upper Limit
                    "Pass": status,
                    "Antenna_Measurement": sim_ant_meas_dbm,   # Power measured from DUT
                    "Golden_Measurement": golden_meas_dbm,     # Power measured from Golden (reference)
                    "Spec_Gain_Golden": spec_gain_golden       # Golden Horn Spec Gain (reference for calculation)
                })

                if self.ui.stacked_widget.currentWidget() == self.ui.test_page:
                    self.ui.update_measurement_progress(self.freq_index, freq, calculated_gain_dut, ll, ul)
                self.freq_index += 1
            else: # Measurement steps complete
                if self.current_measurement_timer:
                    self.current_measurement_timer.stop()
                    self.current_measurement_timer = None
                self.ui._test_running = False
                logger.info(f"DummyApp: Measurement complete for SN {serial_number}, Port {port_name}")

                overall_port_status = "PASS" if all(res["Pass"] == "PASS" for res in self._simulated_results) else "FAIL"

                # Use and then reset the retry flag
                retry_flag_value = self.is_current_test_a_no_count_retry
                # IMPORTANT: Reset the flag *after* using its value for report_port_test_complete_for_antenna
                # and *before* any logic that might set up the next scan.
                if self.is_current_test_a_no_count_retry:
                    logger.info(f"DummyApp: Resetting is_current_test_a_no_count_retry flag from True to False after retest of {serial_number}.")
                    self.is_current_test_a_no_count_retry = False


                # Persist that this SN was tested on this port for this antenna type/orientation
                # This happens regardless of retry, as it's a record of a test attempt.
                persistence_key = (self.current_antenna_key, port_name)
                if persistence_key not in self.tested_sns_persistent:
                    self.tested_sns_persistent[persistence_key] = set()
                self.tested_sns_persistent[persistence_key].add(serial_number)
                logger.info(f"DummyApp: Added SN {serial_number} to persistent set for {persistence_key}. Current set: {self.tested_sns_persistent[persistence_key]}")

                current_measurement_id = self.measurement_id_counter
                self.measurement_id_counter += 1

                failure_details_msg = ""
                if overall_port_status == "FAIL":
                    fail_details = []
                    for res_idx, res_item in enumerate(self._simulated_results):
                        if res_item.get("Pass") == "FAIL":
                            fail_details.append(
                                f"  Freq {res_item.get('Frequency_GHz', 'N/A')} GHz: "
                                f"Measured Gain {res_item.get('Antenna_Gain', float('nan')):.2f} dBi "
                                f"(Limits: {res_item.get('Lower_Limit', float('nan')):.2f} / {res_item.get('Upper_Limit', float('nan')):.2f} dBi)"
                            )
                    failure_details_msg = "\n".join(fail_details)


                self.ui.report_port_test_complete_for_antenna(
                    port_name,
                    serial_number,
                    self._simulated_results, # Pass original detailed results
                    overall_port_status,
                    current_measurement_id,
                    is_retry_no_count=retry_flag_value, # Pass the flag
                    failure_details_message=failure_details_msg
                )

        @Slot(str)
        def handle_port_batch_complete(self, completed_port_name):
            logger.info(f"DummyApp: Received port_batch_run_complete for: {completed_port_name}")

            if not self.current_processing_port or completed_port_name != self.current_processing_port:
                 logger.warning(f"DummyApp: Batch complete signal context mismatch. UI Port: {completed_port_name}, App Port: {self.current_processing_port}")
                 self.ui.update_next_action_state(completed_port_name, can_test_next_port=False, can_test_next_order=True)
                 return

            if self.order_number:
                if self.order_number not in self.order_history_status:
                     self.order_history_status[self.order_number] = {}
                self.order_history_status[self.order_number][completed_port_name] = "Done"
                self.save_persistent_data()

            self.ports_remaining_in_order.discard(completed_port_name)
            logger.info(f"DummyApp: Ports remaining for order '{self.order_number}': {self.ports_remaining_in_order}")

            can_test_next_port = bool(self.ports_remaining_in_order)
            can_test_next_order = True

            self.ui.update_next_action_state(completed_port_name, can_test_next_port, can_test_next_order)


        @Slot()
        def handle_request_test_next_port(self):
            logger.info("DummyApp: Handling request to test next port.")
            if not self.ports_remaining_in_order:
                 QMessageBox.warning(self.ui, "No Ports Left", "All selected ports have been tested for this order.")
                 self.ui.update_next_action_state(self.current_processing_port, can_test_next_port=False, can_test_next_order=True)
                 return

            remaining_list = sorted(list(self.ports_remaining_in_order))
            chosen_port, ok = QInputDialog.getItem(self.ui, "Select Next Port",
                                                   "Choose the next port to test:",
                                                   remaining_list, 0, False)
            if ok and chosen_port:
                logger.info(f"DummyApp: User selected next port: {chosen_port}")
                self.current_processing_port = chosen_port
                self.ui.set_current_test_port(chosen_port)
                self.ui.proceed_to_next_port(chosen_port)
            else:
                logger.info("DummyApp: User cancelled next port selection.")
                self.ui.update_next_action_state(self.current_processing_port, can_test_next_port=True, can_test_next_order=True)

        @Slot()
        def handle_request_test_next_order(self):
            logger.info("DummyApp: Handling request to test next order (same antenna).")

            port_to_continue_with = self.current_processing_port
            if not port_to_continue_with:
                logger.error("DummyApp: No current port context to continue next order with. Aborting.")
                self.ui.go_to_antenna_selection()
                return

            self.order_number = None
            self.charge_number = None
            self.order_quantity = 0

            self.current_processing_port = port_to_continue_with
            logger.info(f"DummyApp: New order will potentially start with port {self.current_processing_port}.")
            
            self.ui.reset_for_new_order_same_antenna(port_to_continue_with)
            self.ui.set_current_test_port(self.current_processing_port)
            self.ui.go_to_state("EnterOrderInfo")


        @Slot()
        def handle_request_finish_measurements(self):
            logger.info("DummyApp: Handling request to finish measurements.")
            self.save_persistent_data()
            self.ui.finish_order_testing()
            self._reset_main_app_state()

        @Slot()
        def abort_current_action(self):
            logger.info("DummyApp: Abort signal received by main app.")
            if self.current_measurement_timer:
                logger.info("DummyApp: Stopping measurement timer due to abort.")
                self.current_measurement_timer.stop()
                self.current_measurement_timer = None

            if self.current_processing_port and self.current_antenna_key:
                persistence_key = (self.current_antenna_key, self.current_processing_port)
                if persistence_key in self.tested_sns_persistent:
                    logger.warning(f"ABORT: Clearing all previously tested SNs for port '{self.current_processing_port}' on antenna config '{self.current_antenna_key}'.")
                    self.tested_sns_persistent[persistence_key].clear()
                else:
                    logger.info(f"ABORT: No SNs to clear for port '{self.current_processing_port}' (key not found or port never tested).")
            else:
                logger.info("ABORT: No current port/antenna context, cannot clear specific SNs.")

            logger.info("DummyApp: Resetting main application state due to abort.")
            self._reset_main_app_state()

        @Slot()
        def cleanup_and_exit(self):
            logger.info("DummyApp: Cleaning up and exiting.")
            self.save_persistent_data()
            app.quit()

        @Slot()
        def reload_users_maybe(self):
            logger.info("DummyApp: Notified users might have been updated.")

        def _reset_main_app_state(self):
             logger.info("DummyApp: Resetting internal state for new antenna.")
             self.antenna_data = {}
             self.ports_available_for_orientation = []
             self.ports_selected_by_user = []
             self.ports_remaining_in_order = set()
             self.current_processing_port = None
             self.current_antenna_sn = None
             self.order_number = None
             self.charge_number = None
             self.order_quantity = 0
             self.current_antenna_key = None
             self.is_current_test_a_no_count_retry = False 
             self.current_silver_sn_validated = None
             if self.current_measurement_timer:
                 self.current_measurement_timer.stop()
                 self.current_measurement_timer = None

        def save_persistent_data(self):
            logger.info("DummyApp: Saving persistent data...")
            try:
                import pickle
                data_dir = "assets/app_data"
                os.makedirs(data_dir, exist_ok=True)

                with open(os.path.join(data_dir,"tested_sns_persistent.pkl"), "wb") as f_sn:
                    pickle.dump(self.tested_sns_persistent, f_sn)
                with open(os.path.join(data_dir,"order_history_status.pkl"), "wb") as f_hist:
                    pickle.dump(self.order_history_status, f_hist)
                logger.info("DummyApp: Persistent data saved.")
            except Exception as e:
                logger.error(f"Error saving persistent data: {e}", exc_info=True)

        def load_persistent_data(self):
            logger.info("DummyApp: Loading persistent data...")
            data_dir = "assets/app_data"
            try:
                import pickle
                sn_path = os.path.join(data_dir, "tested_sns_persistent.pkl")
                hist_path = os.path.join(data_dir, "order_history_status.pkl")

                if os.path.exists(sn_path):
                    with open(sn_path, "rb") as f_sn:
                        self.tested_sns_persistent = pickle.load(f_sn)
                        logger.info(f"DummyApp: Loaded {len(self.tested_sns_persistent)} persistent SN entries.")
                else:
                    logger.info(f"DummyApp: No persistent SN file found at {sn_path}.")
                    self.tested_sns_persistent = {}

                if os.path.exists(hist_path):
                    with open(hist_path, "rb") as f_hist:
                        self.order_history_status = pickle.load(f_hist)
                        logger.info(f"DummyApp: Loaded {len(self.order_history_status)} order history entries.")
                else:
                    logger.info(f"DummyApp: No order history file found at {hist_path}.")
                    self.order_history_status = {}

            except Exception as e:
                logger.error(f"Error loading persistent data: {e}", exc_info=True)
                self.tested_sns_persistent = {}
                self.order_history_status = {}


    main_window = UiMainWindow()
    main_window.resize(1600, 900)
    dummy_app_logic = DummyMainApp(main_window)
    main_window.show()
    sys.exit(app.exec())