import sys
import os
import random
import pickle
from datetime import datetime, timedelta, timezone 
from pathlib import Path
import logging
from typing import Optional, Dict, List, Any, Set
import pandas as pd
import time # Added for hardware settling time

from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog
from PySide6.QtCore import QObject, Slot, QTimer, Signal

# Import the main UI window class from your ui_module
# Assuming ui_module.py is in src/ui/
from src.ui.ui_module import UiMainWindow

# Import configuration loaders
from src.loaders.software_config_loader import SoftwareConfigLoader, SoftwareConfigError, ConfigFileNotFoundError, SheetNotFoundError
from src.loaders.antenna_config_loader import ExcelConfigLoader, ConfigDataError, find_excel_files, create_config_loader

# Import Instrument Controllers
from src.instruments.Vaunix_LMS163_DSG import LMS163Controller, LMS163Device, LMSError
from src.instruments.Anritsu_MA24510A import MA24510A

# Import the database service and data classes
from src.database.database_handling import (
    AntennaDataService,
    CompositeAntennaTestData,
    GainTestHeader,
    GainTestValue,
    pyodbc # Import for exception handling
)

# These constants are used by QApplication.setOrganizationName and setApplicationName.
COMPANY_NAME = "Energy Waves"
APP_NAME_FOR_SETTINGS = "AntennaTesterApp"
APP_VERSION = "1.8" 
 
# --- Path Definitions ---
PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_ROOT / "config"
# The software config file is now determined dynamically in _load_software_config
ANTENNA_CONFIG_FILES_DIR = CONFIG_DIR / "antenna_config_files"
PERSISTENT_DATA_DIR = PROJECT_ROOT / "assets" / "app_data"

  

# --- Logging Setup ---
log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.DEBUG, format=log_format) # Sets up console logging INFO or DEBUG


# --- Setup File Logging ---
try:
    PERSISTENT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_file_path = PERSISTENT_DATA_DIR / "app_session.log"
    
    file_handler = logging.FileHandler(log_file_path, mode='w') # 'w' to overwrite
    formatter = logging.Formatter(log_format) # Use global log_format
    file_handler.setFormatter(formatter)
    
    # Add handler to the "MainApp" logger instance
    root_logger = logging.getLogger() # Get the root logger
    root_logger.addHandler(file_handler)
    logger = logging.getLogger("MainApp") # Specific logger for the application
    logger.info(f"File logging initialized. Log file: {log_file_path}")
except Exception as e:
    # Log to console if file logging setup fails
    logging.error(f"CRITICAL: Failed to set up file logging to {PERSISTENT_DATA_DIR / 'app_session.log'}: {e}", exc_info=True)
    logging.warning("Application will continue with console-only logging.")



class ConfigNotLoadedError(Exception):
    """Custom exception for when a config is accessed before loaded or if loader has issues."""
    pass

def _parse_boolean_config_value(value_str: Any, default_value: bool = False, param_name: str = "Parameter") -> bool:
    """
    Parses a string value (typically from config) into a boolean.
    Handles "TRUE"/"FALSE" case-insensitively, and also '1'/'0'.
    Logs warnings for None or invalid values and returns default.
    """
    if value_str is None or pd.isna(value_str):
        logger.warning(f"'{param_name}' not found in config or its value is empty/None. Defaulting to {default_value}.")
        return default_value
    
    val_str = str(value_str).strip().upper()

    if val_str in ("TRUE", "1"):
        return True
    elif val_str in ("FALSE", "0"):
        return False
    else:
        logger.warning(f"Invalid value for '{param_name}': '{value_str}'. Expected 'TRUE'/'FALSE' or '1'/'0'. Defaulting to {default_value}.")
        return default_value

class DummyMainApp(QObject):
    """Simulates the main application logic interacting with the UI."""
    _critical_hardware_failure: bool = False # Class attribute to signal fatal hardware error

    def __init__(self, ui: UiMainWindow):
        super().__init__()
        self.ui = ui
        self.antenna_data: Dict = {}
        self.current_measurement_timer: Optional[QTimer] = None
        self.freq_index: int = 0
        self._simulated_results: List[Dict] = [] # Used for both simulated and real measurement results storage

        self.ports_available_for_orientation: List[str] = []
        self.ports_selected_by_user: List[str] = []
        self.ports_remaining_in_order: Set[str] = set()
        self.current_processing_port: Optional[str] = None
        self.current_antenna_sn: Optional[str] = None # Will be set by SN scan or retest flow
        self.order_number: Optional[str] = None
        self.charge_number: Optional[str] = None
        self.order_quantity: int = 0
        self.current_antenna_key: Optional[str] = None
        self.measurement_id_counter: int = 1
        self.is_current_test_a_no_count_retry: bool = False
        self.current_silver_sn_validated: Optional[str] = None
        self.current_antenna_config_filename: Optional[str] = None 

        self.software_config_loader: Optional[SoftwareConfigLoader] = None
        self.available_antenna_config_files: Dict[str, Path] = {}

        # --- New Software Config Parameters ---
        # Hardware Sheet
        self.hardware_id_gen: Optional[str] = None
        self.hardware_id_power_meter: Optional[str] = None
        self.power_meter_visa_name: Optional[str] = None
        self.hardware_id_extension_module: Optional[str] = None
        self.multiplexing_factor: Optional[int] = 1 # Default to 1 (no multiplication)
        self.transmitter_power: Optional[float] = -20.0 # Default power in dBm
        self.anritsu_bandwidth_mhz: float = 100.0 # Default bandwidth in MHz
        self.anritsu_averaging_count: int = 0 # Default to 0 (OFF)
        self.hardware_demo_mode: bool = True # Default to True (safer)

        # Database Sheet
        self.obdc_driver: Optional[str] = None
        self.server_name_db: Optional[str] = None 
        self.database_name_db: Optional[str] = None 
        self.user_id_db: Optional[str] = None 
        self.database_password_db: Optional[str] = None
        self.optional_db_parameters: Optional[str] = None
        self.database_demo_mode: bool = False 
        # --- End New Software Config Parameters ---

        self._load_software_config() # Loads demo mode, transmitter power etc.

        # Initialize Database Service if not in demo mode
        self.db_service: Optional[AntennaDataService] = None
        self._initialize_database_service()

        self.persistent_memory_enabled: bool = False 
        if self.software_config_loader and self.software_config_loader.is_loaded():
            try:
                persistent_setting_str = self.software_config_loader.get_database_value("Persistent_Memory")
                self.persistent_memory_enabled = _parse_boolean_config_value(
                    persistent_setting_str, 
                    default_value=False, 
                    param_name="Persistent_Memory"
                )
            except ConfigNotLoadedError:
                 logger.error(f"Failed to access 'Database' configuration for 'Persistent_Memory', possibly not loaded. Defaulting to FALSE.")
            except Exception as e:
                logger.error(f"Error reading 'Persistent_Memory' from software config: {e}. Defaulting to FALSE.")
        else:
             logger.warning(f"Software config not loaded. Cannot read 'Persistent_Memory'. Defaulting to FALSE.")
        logger.info(f"Persistent Memory Enabled: {self.persistent_memory_enabled}")

        default_recal_time = timedelta(seconds=ui._RECALIBRATION_TIME_SECONDS)
        self.RECALIBRATION_TIME_CONFIG: timedelta = default_recal_time
        if self.software_config_loader and self.software_config_loader.is_loaded():
            try:
                recal_minutes = self.software_config_loader.get_hardware_value("Recalibration_Time")
                if recal_minutes is not None:
                    self.RECALIBRATION_TIME_CONFIG = timedelta(minutes=float(recal_minutes))
                    logger.info(f"Recalibration time set from software config: {self.RECALIBRATION_TIME_CONFIG}")
                else:
                    logger.warning(f"Recalibration_Time not found in software config hardware sheet. Using default: {default_recal_time}")
            except (ValueError, TypeError) as e:
                logger.error(f"Error parsing Recalibration_Time from software config: {e}. Using default: {default_recal_time}")
            except ConfigNotLoadedError: 
                logger.error(f"Hardware config sheet not loaded in software_config_loader. Cannot get Recalibration_Time. Using default: {default_recal_time}")
            except Exception as e:
                logger.error(f"Error getting Recalibration_Time from software_config_loader: {e}. Using default: {default_recal_time}")
        else:
             logger.warning(f"Software config not loaded or 'Recalibration_Time' key missing. Using default recalibration time: {default_recal_time}")

        # --- Hardware Initialization ---
        self.signal_generator_controller: Optional[LMS163Controller] = None
        self.signal_generator_device: Optional[LMS163Device] = None
        self.power_meter: Optional[MA24510A] = None
        self.hardware_initialized_successfully: bool = False
        self.instrument_settling_time_s: float = 1.0 # General settling time for instruments
        
        DummyMainApp._critical_hardware_failure = False # Reset flag at start of instance

        # Show message if Hardware Demo Mode is ON (from config)
        if self.hardware_demo_mode:
            logger.info("Hardware Demo Mode is ON as per configuration. Measurements will be simulated.")
            QTimer.singleShot(0, lambda: QMessageBox.information(
                self.ui,
                "Hardware Demo Mode Active",
                "Hardware Demo Mode is currently ENABLED\n\n"
                "Measurements will be simulated, and no real hardware will be controlled.\n"
                "This mode is NOT for production use.\n\n"
                "To use real hardware, ensure 'software_config.xlsx' is present and valid, "
                "then set 'Hardware_Demo' to FALSE in the 'Hardware' sheet and restart the application."
            ))
            # No hardware initialization attempt if configured for demo mode
        else: # hardware_demo_mode is FALSE (configured for real hardware)
            logger.info("Hardware Demo Mode is configured as OFF. Attempting to initialize real instruments.")
            self._initialize_hardware() # This sets self.hardware_initialized_successfully
            
            if not self.hardware_initialized_successfully:
                logger.critical("Hardware initialization failed. Application configured for production mode cannot continue.")
                QMessageBox.critical(self.ui, "Hardware Initialization Error",
                                     "Failed to initialize one or more hardware instruments.\n\n"
                                     "The application is configured for production use (Hardware_Demo = FALSE in software_config.xlsx) "
                                     "but cannot connect to the required hardware.\n\n"
                                     "Please check instrument connections and configurations. "
                                     "If you intend to run in demo mode, ensure 'Hardware_Demo' is set to 'TRUE' "
                                     "in the 'Hardware' sheet of 'software_config.xlsx'.\n\n"
                                     "The application will now close.")
                DummyMainApp._critical_hardware_failure = True
                return # Exit constructor early
            else:
                logger.info("Hardware instruments initialized successfully.")

        # Show message if Database Demo Mode is ON
        if self.database_demo_mode: # This reflects the value from software_config.xlsx or fallback
            logger.info("Database Demo Mode is ON as per configuration/fallback.")
            QTimer.singleShot(0, lambda: QMessageBox.information(
                self.ui,
                "Database Demo Mode Active",
                "Database Demo Mode is currently ENABLED.\n\n"
                "No data will be saved to or retrieved from a real database.\n"
                "This mode is NOT for production use.\n\n"
                "To use a real database, ensure 'software_config.xlsx' is present and valid, "
                "then set 'Database_Demo' to FALSE in the 'Database' sheet, "
                "provide valid connection details, and restart the application."
            ))
        self.tested_sns_persistent: Dict[tuple[str,str], set[str]] = {}
        self.order_history_status: Dict[str, Dict[str,str]] = {}

        if self.persistent_memory_enabled:
            self.load_persistent_data()
        else:
            logger.info("Persistent memory is disabled by configuration. Skipping load of persistent data.")
            self.tested_sns_persistent = {}
            self.order_history_status = {}

        self._connect_signals()

    def _build_connection_string(self) -> Optional[str]:
        """Constructs the ODBC connection string from loaded config values."""
        if not all([self.obdc_driver, self.server_name_db, self.database_name_db]):
            logger.error("Cannot build connection string: Driver, Server, or Database name is missing from config.")
            return None
        
        parts = [
            f"DRIVER={self.obdc_driver}",
            f"SERVER={self.server_name_db}",
            f"DATABASE={self.database_name_db}"
        ]
        
        # Handle authentication method
        if self.user_id_db and self.database_password_db:
            logger.info("Building connection string with User ID/Password authentication.")
            parts.append(f"UID={self.user_id_db}")
            parts.append(f"PWD={self.database_password_db}")
        else:
            logger.info("Building connection string with Trusted Connection (Windows Authentication).")
            parts.append("Trusted_Connection=yes")
            
        # Add optional parameters
        if self.optional_db_parameters:
            parts.append(self.optional_db_parameters)
            
        conn_str = ";".join(parts)
        logger.info(f"Constructed DB connection string.")
        return conn_str

    def _initialize_database_service(self):
        """Initializes the AntennaDataService if not in demo mode."""
        if self.database_demo_mode:
            logger.info("Database Demo Mode is ON. Skipping database service initialization.")
            QTimer.singleShot(100, lambda: self.ui.set_database_status(True, "Demo"))
            return

        logger.info("Database Demo Mode is OFF. Initializing database service...")
        connection_string = self._build_connection_string()

        if not connection_string:
            logger.error("Failed to initialize database service: Connection string could not be built.")
            QMessageBox.warning(self.ui, "Database Config Error",
                                "Database connection string could not be built from software_config.xlsx.\n\n"
                                "Please check the 'Database' sheet for complete and valid entries.\n\n"
                                "Application will continue in a mode with NO database connectivity.")
            return

        try:
            self.db_service = AntennaDataService(connection_string)
            # Test the connection to provide immediate feedback
            with self.db_service as service:
                 logger.info("Successfully created and tested connection for AntennaDataService.")
            QTimer.singleShot(100, lambda: self.ui.set_database_status(True, "Connected"))
            logger.info("Database service initialized and connection verified successfully.")

        except pyodbc.Error as e:
            logger.critical(f"Failed to initialize or connect to the database: {e}", exc_info=True)
            self.db_service = None # Ensure service is None on failure
            QMessageBox.critical(self.ui, "Database Connection Failed",
                                 f"Could not connect to the database.\n\nDetails: {e}\n\n"
                                 "Please verify the connection details in software_config.xlsx, check network/VPN, "
                                 "and ensure the database server is running.\n\n"
                                 "Application will continue with NO database connectivity.")
            QTimer.singleShot(100, lambda: self.ui.set_database_status(False, "Connection Failed"))
        except Exception as e:
            logger.critical(f"An unexpected error occurred during database initialization: {e}", exc_info=True)
            self.db_service = None
            QMessageBox.critical(self.ui, "Database Initialization Error",
                                 f"An unexpected error occurred while setting up the database connection.\n\nDetails: {e}\n\n"
                                 "Application will continue with NO database connectivity.")
            QTimer.singleShot(100, lambda: self.ui.set_database_status(False, "Error"))

    def _load_software_config(self):
        # 1. Define the possible paths for the config file
        xlsx_path = CONFIG_DIR / "software_config.xlsx"
        xls_path = CONFIG_DIR / "software_config.xls"
        found_config_path = None

        # 2. Check for the .xlsx version first, then the .xls version
        if xlsx_path.exists():
            found_config_path = xlsx_path
        elif xls_path.exists():
            found_config_path = xls_path

        # 3. Handle the case where neither file is found
        if not found_config_path:
            logger.error(f"Software config file not found. Looked for '{xlsx_path.name}' and '{xls_path.name}' in {CONFIG_DIR}")
            self.software_config_loader = None
            self.hardware_demo_mode = True
            logger.warning("Software config not found. Forcing Hardware Demo Mode = TRUE.")
            return

        # 4. Proceed with loading the file that was found
        logger.info(f"Found software configuration file: {found_config_path}")
        try:
            # Use the name of the file we actually found
            self.software_config_loader = SoftwareConfigLoader(config_directory=str(CONFIG_DIR), filename=found_config_path.name)
            if self.software_config_loader.load():
                logger.info("Software configuration loaded successfully.")
                # Load additional configs immediately after successful load
                self._load_additional_software_configs()
            else:
                logger.error(f"Failed to load software configuration from {found_config_path} (load returned False).")
                self.software_config_loader = None
                self.hardware_demo_mode = True
                logger.warning("Software config load failed. Forcing Hardware Demo Mode = TRUE.")
        except ConfigFileNotFoundError as e: # This exception is now less likely to be the primary one caught here
            logger.error(f"Software configuration file load error: {e}")
            self.software_config_loader = None
            self.hardware_demo_mode = True
            logger.warning("Software config file not found. Forcing Hardware Demo Mode = TRUE.")
        except SheetNotFoundError as e:
            logger.warning(f"Sheet not found in software configuration: {e}. This may affect some settings.")
        except SoftwareConfigError as e:
            logger.error(f"Error loading software configuration: {e}")
            self.software_config_loader = None
            self.hardware_demo_mode = True
            logger.warning("Software config error. Forcing Hardware Demo Mode = TRUE.")
        except Exception as e:
            logger.error(f"Unexpected error during software configuration loading: {e}", exc_info=True)
            self.software_config_loader = None
            self.hardware_demo_mode = True
            logger.warning("Unexpected software config error. Forcing Hardware Demo Mode = TRUE.")

    def _load_additional_software_configs(self):
        if not self.software_config_loader or not self.software_config_loader.is_loaded():
            logger.warning("Software config not loaded or loader unavailable. Cannot load additional parameters. Using defaults.")
            # Defaults are already set at class level, including hardware_demo_mode = True
            return

        logger.info("Loading additional parameters from software configuration...")

        # --- Hardware Parameters ---
        try:
            hw_val = self.software_config_loader.get_hardware_value("HardwareID_Gen")
            self.hardware_id_gen = str(hw_val) if hw_val is not None else None
            logger.info(f"  HardwareID_Gen: {self.hardware_id_gen}")

            hw_val = self.software_config_loader.get_hardware_value("HardwareID_Power_Meter")
            self.hardware_id_power_meter = str(hw_val) if hw_val is not None else None
            logger.info(f"  HardwareID_Power_Meter: {self.hardware_id_power_meter}")

            hw_val = self.software_config_loader.get_hardware_value("Power_Meter_Visa_Name")
            self.power_meter_visa_name = str(hw_val) if hw_val is not None else None
            logger.info(f"  Power_Meter_Visa_Name: {self.power_meter_visa_name}")

            hw_val = self.software_config_loader.get_hardware_value("HardwareID_Extension_Module")
            self.hardware_id_extension_module = str(hw_val) if hw_val is not None else None
            logger.info(f"  HardwareID_Extension_Module: {self.hardware_id_extension_module}")

            multiplexing_factor_str = self.software_config_loader.get_hardware_value("Multiplexing_Factor")
            if multiplexing_factor_str is not None:
                try:
                    val = int(multiplexing_factor_str)
                    if val == 0:
                        logger.error("  Multiplexing_Factor cannot be 0. Using default (1).")
                        self.multiplexing_factor = 1
                    else:
                        self.multiplexing_factor = val
                    logger.info(f"  Multiplexing_Factor: {self.multiplexing_factor}")
                except ValueError:
                    logger.error(f"  Invalid value for Multiplexing_Factor: '{multiplexing_factor_str}'. Must be an integer. Using default (1).")
                    self.multiplexing_factor = 1
            else:
                logger.warning("  Multiplexing_Factor not found in Hardware config. Using default (1).")
                self.multiplexing_factor = 1
            
            transmitter_power_str = self.software_config_loader.get_hardware_value("Transmitter_Power")
            if transmitter_power_str is not None:
                try:
                    self.transmitter_power = float(transmitter_power_str)
                    logger.info(f"  Transmitter_Power: {self.transmitter_power} dBm")
                except ValueError:
                    logger.error(f"  Invalid value for Transmitter_Power: '{transmitter_power_str}'. Must be a number. Using default (-20.0 dBm).")
                    self.transmitter_power = -20.0
            else:
                logger.warning("  Transmitter_Power not found in Hardware config. Using default (-20.0 dBm).")
                self.transmitter_power = -20.0
            
            settling_time_str = self.software_config_loader.get_hardware_value("Instrument_Settling_Time")
            if settling_time_str is not None:
                try:
                    val = float(settling_time_str)
                    if val < 0:
                        logger.error(f"  Instrument_Settling_Time cannot be negative: '{settling_time_str}'. Using default ({self.instrument_settling_time_s} s).")
                    else:
                        self.instrument_settling_time_s = val
                        logger.info(f"  Instrument_Settling_Time: {self.instrument_settling_time_s} s")
                except (ValueError, TypeError):
                    logger.error(f"  Invalid value for Instrument_Settling_Time: '{settling_time_str}'. Must be a number. Using default ({self.instrument_settling_time_s} s).")
            else:
                logger.warning(f"  Instrument_Settling_Time not found in Hardware config. Using default ({self.instrument_settling_time_s} s).")

            bandwidth_str = self.software_config_loader.get_hardware_value("Anritsu_bandwidth_mhz")
            if bandwidth_str is not None:
                try:
                    val = float(bandwidth_str)
                    if val <= 0:
                        logger.error(f"  Anritsu_bandwidth_mhz cannot be zero or negative: '{bandwidth_str}'. Using default ({self.anritsu_bandwidth_mhz} MHz).")
                    else:
                        self.anritsu_bandwidth_mhz = val
                        logger.info(f"  Anritsu_bandwidth_mhz: {self.anritsu_bandwidth_mhz} MHz")
                except (ValueError, TypeError):
                    logger.error(f"  Invalid value for Anritsu_bandwidth_mhz: '{bandwidth_str}'. Must be a number. Using default ({self.anritsu_bandwidth_mhz} MHz).")
            else:
                logger.warning(f"  Anritsu_bandwidth_mhz not found in Hardware config. Using default ({self.anritsu_bandwidth_mhz} MHz).")

            averaging_str = self.software_config_loader.get_hardware_value("Anritsu_averaging")
            if averaging_str is not None:
                try:
                    val = int(averaging_str)
                    if 1 <= val <= 1024:
                        self.anritsu_averaging_count = val
                        logger.info(f"  Anritsu_averaging: {self.anritsu_averaging_count} (Enabled)")
                    elif val <= 0:
                        self.anritsu_averaging_count = 0
                        logger.info(f"  Anritsu_averaging: {val} (Disabled)")
                    else:
                        logger.error(f"  Invalid value for Anritsu_averaging: '{averaging_str}'. Must be between 1 and 1024. Defaulting to OFF (0).")
                        self.anritsu_averaging_count = 0
                except (ValueError, TypeError):
                    logger.error(f"  Invalid value for Anritsu_averaging: '{averaging_str}'. Must be an integer. Defaulting to OFF (0).")
                    self.anritsu_averaging_count = 0
            else:
                logger.warning(f"  Anritsu_averaging not found in Hardware config. Defaulting to OFF (0).")
                self.anritsu_averaging_count = 0

            # Hardware_Demo is critical, ensure it's read correctly
            hw_demo_str = self.software_config_loader.get_hardware_value("Hardware_Demo")
            # Default to True if not found or invalid, as it's safer
            self.hardware_demo_mode = _parse_boolean_config_value(hw_demo_str, True, "Hardware_Demo (Hardware sheet)")
            logger.info(f"  Hardware_Demo (Hardware sheet): {self.hardware_demo_mode}")

        except ConfigNotLoadedError:
            logger.error("Hardware config sheet not loaded. Cannot get additional hardware parameters. Using defaults (Demo Mode ON).")
            self.hardware_demo_mode = True # Critical fallback
        except Exception as e:
            logger.error(f"Error reading additional hardware parameters from software config: {e}. Using defaults (Demo Mode ON).")
            self.hardware_demo_mode = True # Critical fallback

        # --- Database Parameters ---
        try:
            db_val = self.software_config_loader.get_database_value("OBDC_Driver")
            self.obdc_driver = str(db_val) if db_val is not None else None
            logger.info(f"  OBDC_Driver: {self.obdc_driver}")

            db_val = self.software_config_loader.get_database_value("Server_Name")
            self.server_name_db = str(db_val) if db_val is not None else None
            logger.info(f"  Server_Name (Database): {self.server_name_db}")

            db_val = self.software_config_loader.get_database_value("Database_Name")
            self.database_name_db = str(db_val) if db_val is not None else None
            logger.info(f"  Database_Name (Database): {self.database_name_db}")

            db_val = self.software_config_loader.get_database_value("User_ID")
            self.user_id_db = str(db_val) if db_val is not None else None
            logger.info(f"  User_ID (Database): {self.user_id_db}")

            db_val = self.software_config_loader.get_database_value("Database_Password")
            self.database_password_db = str(db_val) if db_val is not None else None
            logger.info(f"  Database_Password (Database): {'Loaded' if self.database_password_db is not None and self.database_password_db != '' else 'Not found/Empty'}")


            db_val = self.software_config_loader.get_database_value("Optional_Parameters") 
            self.optional_db_parameters = str(db_val) if db_val is not None else None
            logger.info(f"  Optional_Parameters (Database): {self.optional_db_parameters}")

            db_demo_str = self.software_config_loader.get_database_value("Database_Demo")
            self.database_demo_mode = _parse_boolean_config_value(db_demo_str, False, "Database_Demo (Database sheet)")
            logger.info(f"  Database_Demo (Database sheet): {self.database_demo_mode}")

        except ConfigNotLoadedError:
            logger.error("Database config sheet not loaded. Cannot get additional database parameters.")
        except Exception as e:
            logger.error(f"Error reading additional database parameters from software config: {e}")

    def _is_hardware_ready(self) -> bool:
        """Checks if hardware is initialized and ready for use (not in demo mode)."""
        return (not self.hardware_demo_mode and
                self.hardware_initialized_successfully and
                self.signal_generator_device is not None and
                self.power_meter is not None)

    def _handle_hardware_error(self, operation: str, error: Exception, port_name: Optional[str] = None, sn: Optional[str] = None):
        """Handles common hardware error reporting and test abortion."""
        log_msg = f"Hardware error during '{operation}'"
        if port_name: log_msg += f" for Port '{port_name}'"
        if sn: log_msg += f", SN '{sn}'"
        log_msg += f": {error}"
        logger.error(log_msg, exc_info=True)

        if self.current_measurement_timer and self.current_measurement_timer.isActive():
            self.current_measurement_timer.stop()
        self.ui._test_running = False
        
        QMessageBox.critical(self.ui, "Hardware Communication Error",
                             f"An error occurred while communicating with the hardware during '{operation}'.\n"
                             f"Details: {error}\n\n"
                             "The current test will be aborted. Please check instrument status and logs.")
        # Go to a safe state, e.g., where user can decide next action or re-select antenna
        # For now, use the abort_current_action logic which resets state.
        # self.abort_current_action() # This might be too drastic, let the UI guide from here or show next action
        # A more targeted state change might be better:
        if self.ui.stacked_widget.currentWidget() == self.ui.test_page:
            # If test was running, offer to go to next action or abort
            # For now, let's assume the measurement step itself will return and the UI will transition based on that failure.
            # The cleanup (RF off) should happen in a finally block if possible.
            logger.warning("Hardware error occurred during active test. UI should handle transition.")
            # We can emit a specific signal if UI needs to react immediately beyond current flow
            # self.ui.measurement_hardware_error.emit(str(error))


    def _initialize_hardware(self):
        """Initializes Signal Generator and Power Meter."""
        logger.info("Initializing hardware instruments...")
        self.hardware_initialized_successfully = False # Assume failure until all succeed

        # Initialize Signal Generator (Vaunix LMS163)
        try:
            logger.info("Initializing Signal Generator (Vaunix LMS163)...")
            self.signal_generator_controller = LMS163Controller(test_mode=False) # test_mode=True for Vaunix own sim
            devices = self.signal_generator_controller.get_available_devices()
            if not devices:
                logger.error("No Vaunix LMS signal generator devices found.")
                return 
            
            self.signal_generator_device = self.signal_generator_controller.connect_device(0) # Connect to the device at index 0
            logger.info(f"Connected to Signal Generator: ID {self.signal_generator_device.device_id}, "
                        f"SN: {self.signal_generator_device.get_serial_number()}")
            logger.info(f"  Generator Freq Range: {self.signal_generator_device._min_freq_mhz} - {self.signal_generator_device._max_freq_mhz} MHz")
            logger.info(f"  Generator Power Range: {self.signal_generator_device._min_power_dbm} - {self.signal_generator_device._max_power_dbm} dBm")

            if self.transmitter_power is not None:
                if not (self.signal_generator_device._min_power_dbm <= self.transmitter_power <= self.signal_generator_device._max_power_dbm):
                    logger.error(f"Configured Transmitter_Power ({self.transmitter_power} dBm) is outside Signal Generator's "
                                 f"capabilities ({self.signal_generator_device._min_power_dbm} to {self.signal_generator_device._max_power_dbm} dBm). "
                                 f"Please adjust software_config.xlsx.")
                    self.signal_generator_device.close()
                    self.signal_generator_device = None
                    return
            else:
                logger.error("Transmitter_Power is not configured. Cannot initialize signal generator power.")
                self.signal_generator_device.close()
                self.signal_generator_device = None
                return

        except LMSError as e:
            logger.error(f"Vaunix LMS Signal Generator LMSError: {e}")
            if self.signal_generator_device: self.signal_generator_device = None
            return
        except Exception as e:
            logger.error(f"Failed to initialize Vaunix LMS Signal Generator: {e}", exc_info=True)
            if self.signal_generator_device: self.signal_generator_device = None
            return

        # Initialize Power Meter (Anritsu MA24510A)
        try:
            logger.info("Initializing Power Meter (Anritsu MA24510A)...")
            if not self.power_meter_visa_name:
                logger.error("Power_Meter_Visa_Name not configured in software_config.xlsx. Cannot initialize Power Meter.")
                self._shutdown_hardware() 
                return

            self.power_meter = MA24510A(visa_resource_name=self.power_meter_visa_name, auto_connect=True)
            if not (self.power_meter and self.power_meter.connected): # Check both instance and connected flag
                logger.error(f"Failed to connect to Power Meter at {self.power_meter_visa_name} (auto_connect failed).")
                self.power_meter = None
                self._shutdown_hardware()
                return
            
            logger.info(f"Connected to Power Meter: {self.power_meter.get_instrument_info().get('idn', 'N/A')}")
            
            # self.power_meter.reset() 
            # time.sleep(1) 
            # self.power_meter.clear_status()
            # errors = self.power_meter.check_errors()
            # if errors: logger.warning(f"Power Meter errors after reset: {errors}")

            if not self.power_meter.set_units("DBM"):
                logger.error("Failed to set Power Meter units to DBM.")
                self._shutdown_hardware()
                return
            if not self.power_meter.set_continuous_mode(True):
                 logger.warning("Failed to set Power Meter to continuous mode.")

            self.power_meter.set_channel_power(True, self.anritsu_bandwidth_mhz)
            logger.info(f"Power Meter channel bandwidth set to {self.anritsu_bandwidth_mhz} MHz.")
            
            if self.anritsu_averaging_count > 0:
                logger.info(f"Configuring Power Meter averaging ON with count: {self.anritsu_averaging_count}")
                if not self.power_meter.set_averaging(enabled=True, count=self.anritsu_averaging_count):
                    logger.error(f"Failed to set Power Meter averaging with count {self.anritsu_averaging_count}.")
            else:
                logger.info("Configuring Power Meter averaging OFF.")
                if not self.power_meter.set_averaging(enabled=False):
                    logger.warning("Failed to disable Power Meter averaging.")
            
            logger.info("Power Meter initialized and configured.")

        except Exception as e:
            logger.error(f"Failed to initialize Anritsu MA24510A Power Meter: {e}", exc_info=True)
            if self.power_meter: self.power_meter = None 
            self._shutdown_hardware() 
            return
        
        self.hardware_initialized_successfully = True
        logger.info("All hardware instruments initialized successfully.")

    def _shutdown_hardware(self):
        """Shuts down and disconnects hardware instruments."""
        logger.info("Shutting down hardware instruments...")
        if self.signal_generator_device:
            try:
                logger.info("Turning RF OFF and closing Signal Generator...")
                self.signal_generator_device.rf_off()
                self.signal_generator_device.close()
                logger.info("Signal Generator closed.")
            except Exception as e:
                logger.error(f"Error shutting down Signal Generator: {e}", exc_info=True)
            finally:
                self.signal_generator_device = None
                self.signal_generator_controller = None

        if self.power_meter:
            try:
                logger.info("Disconnecting Power Meter...")
                self.power_meter.disconnect()
                logger.info("Power Meter disconnected.")
            except Exception as e:
                logger.error(f"Error disconnecting Power Meter: {e}", exc_info=True)
            finally:
                self.power_meter = None
        
        self.hardware_initialized_successfully = False # Mark as not initialized
        logger.info("Hardware shutdown complete.")


    def _transform_excel_config_to_app_format(self, loader: ExcelConfigLoader, antenna_file_basename: str) -> Optional[dict]:
        try:
            config_dict: Dict[str, Any] = {}
            antenna_name_from_file = loader.get_config_value('ANTENNA_NAME')
            if pd.isna(antenna_name_from_file) or antenna_name_from_file is None or not str(antenna_name_from_file).strip():
                config_dict["name"] = Path(antenna_file_basename).stem
                logger.warning(f"ANTENNA_NAME not found or empty in {loader.file_path}, using filename stem: {config_dict['name']}")
            else:
                config_dict["name"] = str(antenna_name_from_file).strip()

            config_dict["PN_H+S"] = loader.get_config_value('PN_H+S')
            config_dict["PART_NUMBER"] = loader.get_config_value('PART_NUMBER')
            part_num_customer = loader.get_config_value('PART_NUMBER')
            config_dict["PART_NUMBER"] = str(part_num_customer) if not pd.isna(part_num_customer) else "N/A"

            config_dict["SN_GOLDEN_SAMPLE"] = loader.get_config_value('SN_GOLDEN_SAMPLE')
            config_dict["SN_SILVER_SAMPLE"] = loader.get_config_value('SN_SILVER_SAMPLE')

            critical_keys_check = ["PN_H+S", "PART_NUMBER", "SN_GOLDEN_SAMPLE", "SN_SILVER_SAMPLE"]
            for key in critical_keys_check:
                val = config_dict[key]
                if val is None or pd.isna(val) or (isinstance(val, str) and not val.strip()):
                    logger.error(f"Critical key '{key}' missing or empty in antenna config file: {loader.file_path}. Skipping this config transformation.")
                    return None
                config_dict[key] = str(val)

            h_ports_str = loader.get_config_value('PORT_HORIZONTAL')
            v_ports_str = loader.get_config_value('PORT_VERTICAL')

            if pd.isna(h_ports_str) or h_ports_str is None or not isinstance(h_ports_str, str) or not h_ports_str.strip():
                logger.error(f"'PORT_HORIZONTAL' key missing, invalid, or empty in {loader.file_path}. Skipping this config transformation.")
                return None
            if pd.isna(v_ports_str) or v_ports_str is None or not isinstance(v_ports_str, str) or not v_ports_str.strip():
                logger.error(f"'PORT_VERTICAL' key missing, invalid, or empty in {loader.file_path}. Skipping this config transformation.")
                return None

            config_dict["PORT_HORIZONTAL"] = [p.strip() for p in str(h_ports_str).split(',') if p.strip()]
            config_dict["PORT_VERTICAL"] = [p.strip() for p in str(v_ports_str).split(',') if p.strip()]

            if not config_dict["PORT_HORIZONTAL"] and not config_dict["PORT_VERTICAL"]:
                logger.error(f"Both PORT_HORIZONTAL and PORT_VERTICAL are empty or invalid in {loader.file_path}. Skipping this config transformation.")
                return None

            limits_data_transformed: Dict[str, List[tuple]] = {}
            all_ports_in_limits_sheet = loader.get_all_ports()

            if not all_ports_in_limits_sheet:
                logger.error(f"No ports found in LIMITS sheet of {loader.file_path}. Skipping this config transformation.")
                return None

            all_configured_ports = set(config_dict["PORT_HORIZONTAL"] + config_dict["PORT_VERTICAL"])

            for port_name in all_configured_ports:
                if port_name not in all_ports_in_limits_sheet:
                    logger.error(f"Port '{port_name}' defined in CONFIGURATION sheet but not found in LIMITS sheet of {loader.file_path}. Skipping config transformation.")
                    return None

                port_df = loader.get_port_data(port_name)
                if port_df.empty:
                    logger.error(f"No limit data rows found for port '{port_name}' in LIMITS sheet of {loader.file_path}, though port was listed. Skipping config transformation.")
                    return None

                port_limits_list: List[tuple] = []
                required_limit_cols = ['Frequency_GHz', 'Lower_Limit', 'Upper_Limit',
                                       'Spec_Gain_Horn', 'Silver_Gain_Horn', 'Silver_Spec_Limit']

                missing_cols = [col for col in required_limit_cols if col not in port_df.columns]
                if missing_cols:
                    logger.error(f"Missing required columns in LIMITS data for port '{port_name}' in {loader.file_path}: {missing_cols}. Skipping transformation.")
                    return None

                for _, row in port_df.iterrows():
                    try:
                        freq = float(row['Frequency_GHz'])
                        ll = float(row['Lower_Limit'])
                        ul = float(row['Upper_Limit'])
                        spec_gain_golden = float(row['Spec_Gain_Horn'])
                        silver_gain_horn = float(row['Silver_Gain_Horn'])
                        silver_spec_limit = float(row['Silver_Spec_Limit'])

                        if any(pd.isna(v) for v in [freq, ll, ul, spec_gain_golden, silver_gain_horn, silver_spec_limit]):
                            logger.error(f"Invalid non-numeric data found in LIMITS for port '{port_name}' at Freq '{row.get('Frequency_GHz', 'N/A')}' "
                                         f"in {loader.file_path} after conversion. Skipping this frequency point.")
                            continue
                        port_limits_list.append((freq, ll, ul, spec_gain_golden, silver_gain_horn, silver_spec_limit))
                    except (ValueError, TypeError) as e:
                        logger.error(f"Error parsing numeric limit data for port '{port_name}' at Freq '{row.get('Frequency_GHz', 'N/A')}' "
                                     f"in {loader.file_path}: {e}. Skipping this frequency point.")
                        continue

                if not port_limits_list and not port_df.empty:
                     logger.warning(f"No valid frequency points could be parsed for port '{port_name}' in {loader.file_path}, though rows existed. This port will have no limits.")
                limits_data_transformed[port_name] = port_limits_list

            config_dict["limits"] = limits_data_transformed
            config_dict["golden_measurements"] = {port: [] for port in limits_data_transformed if limits_data_transformed[port]}

            for port_name in all_configured_ports:
                if port_name not in config_dict["limits"] or not config_dict["limits"][port_name]:
                    logger.error(f"Port '{port_name}' from CONFIGURATION sheet ended up with no valid limit data after processing {loader.file_path}. Skipping transformation.")
                    return None

            logger.info(f"Successfully transformed antenna configuration: {config_dict['name']} from {loader.file_path}")
            return config_dict

        except ConfigDataError as e:
            logger.error(f"Configuration data error while transforming {Path(loader.file_path).name}: {e}")
            return None
        except KeyError as e:
            logger.error(f"Missing expected data field during transformation of {Path(loader.file_path).name}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error transforming antenna config {Path(loader.file_path).name}: {e}", exc_info=True)
            return None

    def _discover_available_antenna_configs(self):
        logger.info(f"Discovering available antenna configurations in: {ANTENNA_CONFIG_FILES_DIR}")
        self.available_antenna_config_files.clear()

        if not ANTENNA_CONFIG_FILES_DIR.is_dir():
            logger.error(f"Antenna configuration directory does not exist: {ANTENNA_CONFIG_FILES_DIR}")
            return

        excel_files = find_excel_files(ANTENNA_CONFIG_FILES_DIR)
        if not excel_files:
            logger.warning(f"No antenna configuration files (.xlsx, .xls) found in {ANTENNA_CONFIG_FILES_DIR}.")
            return

        discovered_configs_temp: Dict[str, Path] = {}
        for file_basename, file_path_str in excel_files:
            file_path_obj = Path(file_path_str)
            logger.debug(f"Discovering: Checking antenna name from file: {file_basename}")

            loader = create_config_loader(str(file_path_obj))
            if loader:
                try:
                    antenna_name_from_file = loader.get_config_value('ANTENNA_NAME')
                    canonical_name: str

                    if pd.isna(antenna_name_from_file) or antenna_name_from_file is None or not str(antenna_name_from_file).strip():
                        canonical_name = file_path_obj.stem
                        logger.debug(f"ANTENNA_NAME not found or empty in {file_basename}. Using filename stem '{canonical_name}' as key for discovery.")
                    else:
                        canonical_name = str(antenna_name_from_file).strip()
                        logger.debug(f"Discovered ANTENNA_NAME '{canonical_name}' from {file_basename}.")

                    if canonical_name in discovered_configs_temp:
                        logger.warning(f"Duplicate antenna name '{canonical_name}' detected. File '{file_basename}' "
                                       f"conflicts with previously processed file '{discovered_configs_temp[canonical_name].name}'. Skipping '{file_basename}'.")
                    else:
                        discovered_configs_temp[canonical_name] = file_path_obj
                except ConfigDataError as e:
                    logger.error(f"ConfigDataError while trying to read ANTENNA_NAME from {file_basename} during discovery: {e}. "
                                 "Attempting to use filename stem as fallback key.")
                    canonical_name = file_path_obj.stem
                    if canonical_name in discovered_configs_temp:
                         logger.warning(f"Skipping {file_basename} due to error and name conflict on fallback name '{canonical_name}'.")
                    else:
                        discovered_configs_temp[canonical_name] = file_path_obj
                        logger.info(f"Used filename stem '{canonical_name}' for {file_basename} due to ConfigDataError during ANTENNA_NAME discovery.")
                except Exception as e:
                    logger.error(f"Unexpected error during discovery pre-check of {file_basename}: {e}. Skipping this file.", exc_info=True)
            else:
                logger.error(f"Failed to create config loader for discovery of file: {file_basename} (path: {file_path_obj})")

        self.available_antenna_config_files = discovered_configs_temp
        logger.info(f"Discovery complete. Found {len(self.available_antenna_config_files)} unique antenna configurations.")

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
        self.ui.retry_test_confirmed.connect(self.handle_retry_test) # For UI's "SN already tested" dialog
        self.ui.request_retest_failed_unit.connect(self.handle_request_retest_failed_unit) # For retesting a failed unit
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
        logger.info("App: Providing antenna configs (list of names) to UI.")
        if not self.available_antenna_config_files and ANTENNA_CONFIG_FILES_DIR.is_dir():
             logger.info("Antenna config list is empty. Re-attempting discovery.")
             self._discover_available_antenna_configs()

        antenna_display_names = sorted(list(self.available_antenna_config_files.keys()))

        if not antenna_display_names:
            logger.warning("No antenna configurations available to provide to UI after discovery attempt.")
            QMessageBox.warning(self.ui, "No Antennas Found",
                                "No valid antenna configuration files were found or could be processed in:\n"
                                f"{ANTENNA_CONFIG_FILES_DIR}\n\n"
                                "Please check the directory for valid .xlsx or .xls files, ensure they have unique "
                                "ANTENNA_NAME values (or unique filenames if ANTENNA_NAME is missing), "
                                "and then try refreshing or restarting the application.")

        self.ui.display_antenna_configs(antenna_display_names)

    @Slot(str)
    def load_antenna_config(self, selected_antenna_name: str):
        logger.info(f"App: Received request to load config for selected antenna name: '{selected_antenna_name}'")

        file_path_to_load = self.available_antenna_config_files.get(selected_antenna_name)

        if not file_path_to_load or not file_path_to_load.exists():
            logger.error(f"File path for antenna name '{selected_antenna_name}' not found in discovered list, or file does not exist. Path: {file_path_to_load}")
            QMessageBox.critical(self.ui, "Configuration Error",
                                 f"The configuration file for antenna '{selected_antenna_name}' could not be found or is missing.\n"
                                 "This might happen if the file was moved or deleted after discovery.\n"
                                 "Please try going back and re-selecting the antenna, or restart the application.")
            self.ui.go_to_antenna_selection()
            return

        logger.info(f"Attempting to load and transform full antenna configuration from file: {file_path_to_load.name} (Path: {file_path_to_load})")
        loader = create_config_loader(str(file_path_to_load))

        if not loader:
            logger.error(f"Failed to create a configuration loader for antenna file: {file_path_to_load.name}")
            QMessageBox.critical(self.ui, "Load Error", f"Could not initialize a loader for the antenna configuration file: {file_path_to_load.name}.\n"
                                                        "The file might be an unsupported type or corrupt.")
            self.ui.go_to_antenna_selection()
            return

        transformed_config = self._transform_excel_config_to_app_format(loader, file_path_to_load.name)

        if transformed_config:
            if transformed_config.get("name") != selected_antenna_name:
                logger.warning(f"Name mismatch: Selected name was '{selected_antenna_name}', but loaded config's internal name is '{transformed_config.get('name')}'. "
                               f"Proceeding with the name from the loaded file: '{transformed_config.get('name')}'.")

            self.antenna_data = transformed_config
            self._reset_for_new_antenna_selection()
            
            # Store the filename for database logging
            self.current_antenna_config_filename = file_path_to_load.name
            logger.info(f"Set current_antenna_config_filename to '{self.current_antenna_config_filename}' for DB logging.")


            actual_display_name_from_config = self.antenna_data.get("name", "N/A")
            part_number = self.antenna_data.get("PART_NUMBER", "N/A")

            self.ui.set_antenna_details(actual_display_name_from_config, part_number)
            self.ui.show_orientation_selection()
        else:
            logger.error(f"Failed to transform antenna configuration from file: {file_path_to_load.name} (Path: {file_path_to_load})")
            QMessageBox.critical(self.ui, "Load Error",
                                 f"Failed to load or parse critical data from the antenna configuration file: {file_path_to_load.name}.\n"
                                 "Please check the file's content and format against requirements, or view application logs for details.")
            self.ui.go_to_antenna_selection()

    def _reset_for_new_antenna_selection(self):
        logger.debug("Resetting state for new antenna type selection.")
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
        self.current_antenna_config_filename = None 

        if self.current_measurement_timer and self.current_measurement_timer.isActive():
            self.current_measurement_timer.stop()
        self.current_measurement_timer = None

    @Slot(str)
    def handle_orientation_selection(self, orientation: str):
        logger.info(f"App: Orientation selected: {orientation}")
        if not self.antenna_data:
            logger.error("Cannot handle orientation: No antenna data loaded.")
            QMessageBox.critical(self.ui, "Internal Error", "No antenna data loaded. Please re-select antenna.")
            self.ui.go_to_antenna_selection()
            return

        current_config_name = self.antenna_data.get("name", "UnknownAntenna")
        self.current_antenna_key = f"{current_config_name}_{orientation}" # Set the key here

        key_for_ports = f"PORT_{orientation.upper()}"
        ports_for_orientation = self.antenna_data.get(key_for_ports, [])

        if not ports_for_orientation:
             logger.warning(f"No ports defined for {key_for_ports} in config for {current_config_name}.")
             QMessageBox.warning(self.ui, "Config Warning", f"No ports defined for '{orientation}' orientation in the loaded configuration for '{current_config_name}'.")
             self.ui.go_to_state("SelectOrientation")
             return

        valid_ports_with_limits = []
        for port_name in ports_for_orientation:
            if port_name in self.antenna_data.get("limits", {}) and self.antenna_data["limits"][port_name]:
                valid_ports_with_limits.append(port_name)
            else:
                logger.warning(f"Port '{port_name}' for orientation '{orientation}' of antenna '{current_config_name}' "
                               f"is listed in {key_for_ports} but has no limit data. It will be excluded.")

        if not valid_ports_with_limits:
            logger.error(f"No ports with valid limit data for orientation '{orientation}' of antenna '{current_config_name}'.")
            QMessageBox.critical(self.ui, "Config Error",
                                 f"No ports with defined measurement limits found for orientation '{orientation}'.\n"
                                 "Please check the antenna configuration file.")
            self.ui.go_to_state("SelectOrientation")
            return

        self.ports_available_for_orientation = valid_ports_with_limits
        self.ui.populate_port_status_display(self.ports_available_for_orientation)
        self.ui.show_port_selection()

    @Slot(list)
    def handle_ports_selected(self, selected_ports: List[str]):
        logger.info(f"App: Ports selected by user for current run: {selected_ports}")
        self.ports_selected_by_user = selected_ports

    @Slot(str)
    def handle_start_port_selected(self, start_port: str):
        logger.info(f"App: User selected starting port: {start_port}")
        if not self.ports_selected_by_user:
            logger.error("Error: No ports were selected by the user prior to selecting a start port.")
            QMessageBox.critical(self.ui, "Selection Error", "No ports were selected for testing. Please go back and select ports.")
            self.ui.go_to_state("SelectPorts")
            return
        if start_port not in self.ports_selected_by_user:
            logger.error(f"Error: Invalid start port '{start_port}' - not in the list of user-selected ports.")
            QMessageBox.critical(self.ui, "Selection Error", f"The selected start port '{start_port}' is not among the ports you chose for testing. Please re-select the start port.")
            self.ui.go_to_state("SelectStartPort")
            return

        self.current_processing_port = start_port
        self.ui.set_current_test_port(start_port)
        self.ports_remaining_in_order = set(self.ports_selected_by_user)

        if self.order_number:
            logger.info(f"App: Order number '{self.order_number}' already known. Requesting load of its history.")
            self.ui.request_load_order_history.emit(self.order_number)
        else:
            logger.info("App: No active order number. UI should proceed to 'EnterOrderInfo'.")
            self.ui.go_to_state("EnterOrderInfo")

    @Slot(str, str)
    def validate_golden_sn(self, scanned_sn: str, port_name: str):
        logger.info(f"App: Validating Golden SN '{scanned_sn}' for Port '{port_name}'")
        if port_name != self.current_processing_port:
            logger.warning(f"Golden SN validation for wrong port. Expected {self.current_processing_port}, got {port_name}")
            return

        expected_golden_sn = self.antenna_data.get("SN_GOLDEN_SAMPLE", "N/A_GOLDEN_SN_IN_CONFIG")
        is_valid = (scanned_sn == expected_golden_sn)
        msg = ""
        if not is_valid:
            msg = f"Golden SN mismatch. Expected '{expected_golden_sn}', scanned '{scanned_sn}'."
        QTimer.singleShot(150, lambda p=port_name, v=is_valid, e=expected_golden_sn, m=msg: \
                                 self.ui.report_golden_sn_validation(p, v, e, m))

    @Slot(str)
    def do_golden_measurement(self, port_name: str):
        logger.info(f"App: Starting Golden Measurement for Port {port_name}")
        if port_name != self.current_processing_port:
            logger.warning(f"Golden measurement start for wrong port. Expected {self.current_processing_port}, got {port_name}")
            return

        limits_for_port = self.antenna_data.get("limits", {}).get(port_name, [])
        num_freq_points = len(limits_for_port)

        if num_freq_points == 0:
            logger.error(f"No limit data/frequency points defined for port '{port_name}' for Golden Measurement.")
            QMessageBox.critical(self.ui, "Configuration Error",
                                 f"No frequency points defined for port '{port_name}'. Cannot start Golden measurement.\n"
                                 "Check antenna configuration file.")
            self.ui.go_to_state("ScanGoldenSN")
            return
        
        if self._is_hardware_ready():
            min_req_gen_freq_mhz = float('inf')
            max_req_gen_freq_mhz = float('-inf')
            for freq_data in limits_for_port:
                target_freq_ghz = freq_data[0]
                gen_freq_mhz = (target_freq_ghz * 1000) / self.multiplexing_factor
                min_req_gen_freq_mhz = min(min_req_gen_freq_mhz, gen_freq_mhz)
                max_req_gen_freq_mhz = max(max_req_gen_freq_mhz, gen_freq_mhz)
            
            if not (self.signal_generator_device._min_freq_mhz <= min_req_gen_freq_mhz and 
                    self.signal_generator_device._max_freq_mhz >= max_req_gen_freq_mhz):
                msg = (f"Required generator frequency range ({min_req_gen_freq_mhz:.2f}-{max_req_gen_freq_mhz:.2f} MHz) "
                       f"for this antenna port (after multiplexing) is outside the Signal Generator's capabilities "
                       f"({self.signal_generator_device._min_freq_mhz}-{self.signal_generator_device._max_freq_mhz} MHz). "
                       f"Check antenna config or multiplexing factor.")
                logger.error(msg)
                QMessageBox.critical(self.ui, "Hardware Capability Error", msg)
                self.ui.go_to_state("ScanGoldenSN")
                return


        self.ui.progress_bar.setMaximum(num_freq_points)
        self.ui.progress_bar.setValue(0)
        self.freq_index = 0
        self._simulated_results = [] 
        self.ui._test_running = True

        if self.current_measurement_timer and self.current_measurement_timer.isActive():
            self.current_measurement_timer.stop()
        self.current_measurement_timer = QTimer(self)
        self.current_measurement_timer.timeout.connect(self._perform_golden_measurement_step)
        interval = 50 if self.hardware_demo_mode else 200 
        self.current_measurement_timer.start(interval)

    def _perform_golden_measurement_step(self):
        port_name = self.current_processing_port
        if not port_name or not self.antenna_data:
            if self.current_measurement_timer: self.current_measurement_timer.stop()
            self.ui._test_running = False
            logger.error("Golden measurement step: Port name or antenna data missing.")
            return

        limits_for_port = self.antenna_data.get("limits", {}).get(port_name, [])
        num_freq_points = len(limits_for_port)

        if self.freq_index < num_freq_points:
            target_freq_ghz = limits_for_port[self.freq_index][0]
            measured_power_dbm: Optional[float] = None

            if not self._is_hardware_ready(): 
                logger.debug(f"Golden (Sim) Freq Idx: {self.freq_index}, Target Freq: {target_freq_ghz} GHz")
                measured_power_dbm = -1.5 + random.uniform(-0.2, 0.2) - (self.freq_index * (0.5 / max(1, num_freq_points)))
            else: 
                logger.debug(f"Golden (HW) Freq Idx: {self.freq_index}, Target Freq: {target_freq_ghz} GHz")
                try:
                    generator_freq_mhz = (target_freq_ghz * 1000) / self.multiplexing_factor
                    
                    logger.info(f"  Setting Gen: Freq={generator_freq_mhz:.4f} MHz, Pwr={self.transmitter_power} dBm")
                    if not self.signal_generator_device.set_frequency(generator_freq_mhz):
                         raise Exception(f"Failed to set generator frequency to {generator_freq_mhz} MHz")
                    if not self.signal_generator_device.set_power(self.transmitter_power): 
                         raise Exception(f"Failed to set generator power to {self.transmitter_power} dBm")
                    
                    logger.info(f"  Setting PM: Freq={target_freq_ghz} GHz") 
                    if not self.power_meter.set_frequency(target_freq_ghz):
                        raise Exception(f"Failed to set power meter frequency to {target_freq_ghz} GHz")
                    
                    self.signal_generator_device.rf_on()
                    time.sleep(self.instrument_settling_time_s) 

                    measured_power_dbm = self.power_meter.measure_power(wait_time=0.5) 
                    
                except Exception as e:
                    self._handle_hardware_error("Golden Measurement Step", e, port_name=port_name)
                    return 
                finally:
                    if self.signal_generator_device and self.signal_generator_device.is_rf_on:
                        self.signal_generator_device.rf_off()
                        logger.info("  Gen RF OFF")
                
                if measured_power_dbm is None: 
                    logger.error(f"Power meter returned None for Golden measurement at {target_freq_ghz} GHz.")
                    self._handle_hardware_error("Golden Measurement (No PM Value)", Exception("Power Meter returned no value"), port_name=port_name)
                    return


            self._simulated_results.append({"Antenna_Measurement": measured_power_dbm}) 

            if self.ui.stacked_widget.currentWidget() == self.ui.test_page:
                 self.ui.progress_bar.setValue(self.freq_index + 1)

            self.freq_index += 1
        else: 
            if self.current_measurement_timer:
                self.current_measurement_timer.stop()
            self.current_measurement_timer = None
            self.ui._test_running = False
            logger.info(f"App: Golden measurement {'simulation' if self.hardware_demo_mode or not self.hardware_initialized_successfully else 'hardware test'} complete for Port {port_name}")

            if "golden_measurements" not in self.antenna_data:
                self.antenna_data["golden_measurements"] = {}

            self.antenna_data["golden_measurements"][port_name] = [res["Antenna_Measurement"] for res in self._simulated_results]
            logger.info(f"App: Stored {len(self._simulated_results)} Golden dBm values for {port_name}.")

            self.ui.report_golden_measurement_complete(port_name, success=True)


    @Slot(str, str)
    def validate_silver_sn(self, scanned_sn: str, port_name: str):
        logger.info(f"App: Validating Silver SN '{scanned_sn}' for Port '{port_name}'")
        if port_name != self.current_processing_port:
            logger.warning(f"Silver SN validation for wrong port. Expected {self.current_processing_port}, got {port_name}")
            return

        expected_silver_sn = self.antenna_data.get("SN_SILVER_SAMPLE", "N/A_SILVER_SN_IN_CONFIG")
        is_valid = (scanned_sn == expected_silver_sn)
        msg = ""
        if is_valid:
            self.current_silver_sn_validated = scanned_sn
        else:
            self.current_silver_sn_validated = None
            msg = f"Silver SN mismatch. Expected '{expected_silver_sn}', scanned '{scanned_sn}'."

        QTimer.singleShot(150, lambda p=port_name, v=is_valid, e=expected_silver_sn, m=msg: \
                                 self.ui.report_silver_sn_validation(p, v, e, m))

    @Slot(str)
    def do_silver_measurement(self, port_name: str):
        logger.info(f"App: Starting Silver Measurement for Port {port_name}")
        if port_name != self.current_processing_port:
            logger.warning(f"Silver measurement start for wrong port. Expected {self.current_processing_port}, got {port_name}")
            return

        limits_for_port = self.antenna_data.get("limits", {}).get(port_name, [])
        num_freq_points = len(limits_for_port)
        golden_meas_list = self.antenna_data.get("golden_measurements", {}).get(port_name, [])

        if num_freq_points == 0:
            logger.error(f"No limit data/frequency points defined for port '{port_name}' for Silver Measurement.")
            QMessageBox.critical(self.ui, "Configuration Error", f"No frequency points for port '{port_name}'. Cannot start Silver measurement.")
            self.ui.go_to_state("ScanSilverSN")
            return
        if not golden_meas_list or len(golden_meas_list) != num_freq_points:
            logger.error(f"Golden measurement data missing or incomplete for port '{port_name}' (Silver). "
                         f"Golden items: {len(golden_meas_list if golden_meas_list else [])}, Freq points: {num_freq_points}.")
            QMessageBox.critical(self.ui, "Data Error",
                                 "Golden measurement data is missing or incomplete for this port.\n"
                                 "Please re-run Golden Sample measurement first.")
            self.ui.go_to_state("ScanGoldenSN") 
            return
        if self._is_hardware_ready():
            min_req_gen_freq_mhz = float('inf')
            max_req_gen_freq_mhz = float('-inf')
            for freq_data in limits_for_port:
                target_freq_ghz = freq_data[0]
                gen_freq_mhz = (target_freq_ghz * 1000) / self.multiplexing_factor
                min_req_gen_freq_mhz = min(min_req_gen_freq_mhz, gen_freq_mhz)
                max_req_gen_freq_mhz = max(max_req_gen_freq_mhz, gen_freq_mhz)
            
            if not (self.signal_generator_device._min_freq_mhz <= min_req_gen_freq_mhz and 
                    self.signal_generator_device._max_freq_mhz >= max_req_gen_freq_mhz):
                msg = (f"Required generator frequency range ({min_req_gen_freq_mhz:.2f}-{max_req_gen_freq_mhz:.2f} MHz) "
                       f"for Silver sample on this port is outside Signal Generator's capabilities. Check config.")
                logger.error(msg)
                QMessageBox.critical(self.ui, "Hardware Capability Error", msg)
                self.ui.go_to_state("ScanSilverSN")
                return

        self.ui.progress_bar.setMaximum(num_freq_points)
        self.ui.progress_bar.setValue(0)
        self.freq_index = 0
        self._simulated_results = []
        self.ui._test_running = True

        if self.current_measurement_timer and self.current_measurement_timer.isActive():
            self.current_measurement_timer.stop()
        self.current_measurement_timer = QTimer(self)
        self.current_measurement_timer.timeout.connect(self._perform_silver_measurement_step)
        interval = 50 if self.hardware_demo_mode else 200
        self.current_measurement_timer.start(interval)

    def _perform_silver_measurement_step(self):
        port_name = self.current_processing_port
        if not self.ui._test_running or not port_name or not self.antenna_data:
            logger.warning(f"Silver measurement step called in invalid state (Running: {self.ui._test_running}, Port: {port_name}). Aborting step.")
            if self.current_measurement_timer: self.current_measurement_timer.stop()
            self.current_measurement_timer = None
            self.ui._test_running = False
            return

        limits_for_port = self.antenna_data.get("limits", {}).get(port_name, [])
        num_freq_points = len(limits_for_port)
        golden_meas_list = self.antenna_data.get("golden_measurements", {}).get(port_name, []) # These are actual (or sim) power readings

        if self.freq_index < num_freq_points:
            current_limit_data = limits_for_port[self.freq_index]
            target_freq_ghz = current_limit_data[0]
            spec_gain_golden_val = current_limit_data[3] # Spec_Gain_Horn
            silver_gain_horn_target = current_limit_data[4] # Target gain for Silver sample
            silver_tolerance_pm = current_limit_data[5] # Tolerance for Silver sample gain validation

            golden_meas_dbm_val = golden_meas_list[self.freq_index] # Actual power meter reading for golden sample setup
            if golden_meas_dbm_val is None: # Check if golden measurement was valid
                logger.error(f"Missing Golden measurement data point for Silver test at Freq Index {self.freq_index}, Port {port_name}. Aborting Silver test.")
                if self.current_measurement_timer: self.current_measurement_timer.stop()
                self.ui._test_running = False
                QMessageBox.critical(self.ui, "Data Error", "Golden measurement data point missing. Please re-run Golden Sample measurement.")
                self.ui.go_to_state("ScanGoldenSN")
                return

            instrument_reading_for_silver_dbm: Optional[float] = None
            actual_measured_silver_gain: Optional[float] = None

            if not self._is_hardware_ready(): # Simulation for Silver
                logger.debug(f"Silver (Sim) Freq Idx: {self.freq_index}, Target Freq: {target_freq_ghz} GHz")
                fail_silver_point_prob = 0.02 # Sim params
                simulated_silver_deviation_from_target = random.uniform(-silver_tolerance_pm * 0.8, silver_tolerance_pm * 0.8)
                if random.random() < fail_silver_point_prob:
                     simulated_silver_deviation_from_target = silver_tolerance_pm * random.choice([-1.2, 1.2])
                actual_measured_silver_gain = silver_gain_horn_target + simulated_silver_deviation_from_target
                # Back-calculate what the instrument would read for this simulated gain
                # CORRECTED CALCULATION (for simulation consistency, though the primary fix is below)
                instrument_reading_for_silver_dbm = golden_meas_dbm_val + (actual_measured_silver_gain - spec_gain_golden_val)
            else: # Real hardware for Silver
                logger.debug(f"Silver (HW) Freq Idx: {self.freq_index}, Target Freq: {target_freq_ghz} GHz")
                try:
                    generator_freq_mhz = (target_freq_ghz * 1000) / self.multiplexing_factor
                    
                    logger.info(f"  Setting Gen: Freq={generator_freq_mhz:.4f} MHz, Pwr={self.transmitter_power} dBm")
                    if not self.signal_generator_device.set_frequency(generator_freq_mhz):
                        raise Exception(f"Failed to set generator frequency to {generator_freq_mhz} MHz")
                    if not self.signal_generator_device.set_power(self.transmitter_power):
                        raise Exception(f"Failed to set generator power to {self.transmitter_power} dBm")

                    logger.info(f"  Setting PM: Freq={target_freq_ghz} GHz")
                    if not self.power_meter.set_frequency(target_freq_ghz):
                         raise Exception(f"Failed to set power meter frequency to {target_freq_ghz} GHz")
                    
                    self.signal_generator_device.rf_on()
                    time.sleep(self.instrument_settling_time_s)

                    instrument_reading_for_silver_dbm = self.power_meter.measure_power(wait_time=0.5)
                    
                    if instrument_reading_for_silver_dbm is None:
                        raise Exception("Power meter returned None for Silver measurement.")
                    
                    # Calculate actual Silver gain based on real readings
                    # --- THIS IS THE CORRECTED CALCULATION ---
                    actual_measured_silver_gain = spec_gain_golden_val + (instrument_reading_for_silver_dbm - golden_meas_dbm_val)

                except Exception as e:
                    self._handle_hardware_error("Silver Measurement Step", e, port_name=port_name)
                    return
                finally:
                    if self.signal_generator_device and self.signal_generator_device.is_rf_on:
                        self.signal_generator_device.rf_off()
                        logger.info("  Gen RF OFF")

            if instrument_reading_for_silver_dbm is None or actual_measured_silver_gain is None : # Should be caught by try-except for HW
                logger.error(f"Failed to get valid reading for Silver at {target_freq_ghz} GHz. Aborting point.")
                # This implies a logic error if not caught by hardware error handling, or sim issue
                pass_status = "FAIL (Error)"
            else:
                silver_gain_validation_ll = silver_gain_horn_target - silver_tolerance_pm
                silver_gain_validation_ul = silver_gain_horn_target + silver_tolerance_pm
                pass_status = "PASS" if silver_gain_validation_ll <= actual_measured_silver_gain <= silver_gain_validation_ul else "FAIL"

            self._simulated_results.append({
                "Frequency_GHz": target_freq_ghz,
                "Antenna_Gain": actual_measured_silver_gain if actual_measured_silver_gain is not None else float('nan'),
                "Lower_Limit": silver_gain_validation_ll,
                "Upper_Limit": silver_gain_validation_ul,
                "Pass": pass_status,
                "Antenna_Measurement": instrument_reading_for_silver_dbm if instrument_reading_for_silver_dbm is not None else float('nan'),
                "Golden_Measurement": golden_meas_dbm_val,
                "Spec_Gain_Displayed": silver_gain_horn_target 
            })

            if self.ui.stacked_widget.currentWidget() == self.ui.test_page:
                self.ui.update_measurement_progress(self.freq_index, target_freq_ghz, 
                                                    actual_measured_silver_gain if actual_measured_silver_gain is not None else float('nan'),
                                                    silver_gain_validation_ll, silver_gain_validation_ul)
            self.freq_index += 1
        else: # All frequency points processed
            if self.current_measurement_timer: self.current_measurement_timer.stop()
            self.current_measurement_timer = None
            self.ui._test_running = False
            logger.info(f"App: Silver measurement {'simulation' if self.hardware_demo_mode or not self.hardware_initialized_successfully else 'hardware test'} complete for Port {port_name}")

            overall_silver_status = "PASS"
            fail_details_text = []
            for res_item in self._simulated_results:
                if res_item.get("Pass") != "PASS": 
                    overall_silver_status = "FAIL"
                    fail_details_text.append(
                        f"  Freq {res_item.get('Frequency_GHz', 'N/A')} GHz: "
                        f"Measured Silver Gain {res_item.get('Antenna_Gain', float('nan')):.2f} dBi "
                        f"(Validation Limits: {res_item.get('Lower_Limit', float('nan')):.2f} / {res_item.get('Upper_Limit', float('nan')):.2f} dBi)"
                    )
            
            # Save results to database if not in demo mode
            silver_sn_for_report = self.current_silver_sn_validated if self.current_silver_sn_validated else "UNKNOWN_SILVER_SN"
            self._save_test_results_to_db(
                port_name=port_name,
                serial_number=silver_sn_for_report,
                results_list=self._simulated_results,
                overall_status=overall_silver_status,
                is_silver_test=True,
                is_retry_no_count=False # Silver test is never a retry
            )

            test_passed_successfully = (overall_silver_status == "PASS")
            message_to_ui = "\n".join(fail_details_text) if not test_passed_successfully else "Silver Sample calibration passed successfully."
            
            new_measurement_id = self.measurement_id_counter
            self.measurement_id_counter += 1

            self.ui.report_silver_measurement_complete(
                port_name=port_name,
                success=test_passed_successfully,
                message=message_to_ui,
                silver_sn=silver_sn_for_report,
                measurement_id=new_measurement_id,
                silver_results=self._simulated_results
            )

    # <-- MODIFIED
    @Slot(str, str, int)
    def handle_order_info(self, order_num: str, charge_num: str, quantity: int):
        logger.info(f"App: Received order info: Order='{order_num}', Charge='{charge_num}', Quantity={quantity}")
        if self.order_number != order_num:
             logger.info("App: New order number detected. Resetting ports remaining for this new order based on current selection.")
             self.ports_remaining_in_order = set(self.ports_selected_by_user)
        self.order_number = order_num
        self.charge_number = charge_num
        self.order_quantity = quantity

        if self.current_processing_port:
            logger.info(f"App: Order info set. Now checking/loading history for order '{order_num}' and port '{self.current_processing_port}'.")
            self.ui.request_load_order_history.emit(self.order_number)
        else:
            logger.error("CRITICAL: Order info received, but no current_processing_port is set. Cannot proceed.")
            QMessageBox.critical(self.ui, "Internal Error", "Order information received, but no processing port is active. Please restart antenna selection.")
            self.ui.go_to_antenna_selection()

    @Slot(str)
    def load_and_apply_order_history(self, order_num: str):
        logger.info(f"App: Attempting to load and apply history for Order '{order_num}'. Intended start port for this run: '{self.current_processing_port}'")

        initial_start_port = self.current_processing_port
        if not initial_start_port:
            logger.error("Error: Cannot load order history - no initial start port determined for this run.")
            QMessageBox.critical(self.ui, "Internal Error", "Cannot load order history: no start port context. Please restart selection.")
            self.ui.go_to_antenna_selection()
            return

        statuses_from_history_for_order = self.order_history_status.get(order_num, {})
        if statuses_from_history_for_order:
            logger.info(f"App: Found existing history for order '{order_num}': {statuses_from_history_for_order}")
        else:
            logger.info(f"App: No existing history found for order '{order_num}'. This is a new order or first time for this order.")

        current_session_selected_ports = set(self.ports_selected_by_user)
        ports_still_needed_for_this_order_run = set()
        for port in current_session_selected_ports:
            if statuses_from_history_for_order.get(port) not in ["Done", "Skipped"]:
                ports_still_needed_for_this_order_run.add(port)

        self.ports_remaining_in_order = ports_still_needed_for_this_order_run.copy()
        logger.info(f"App: Ports (potentially) remaining for order '{order_num}' after initial history check: {self.ports_remaining_in_order}")

        self.ui.apply_loaded_order_status(statuses_from_history_for_order)

        status_of_intended_start_port = statuses_from_history_for_order.get(initial_start_port)
        logger.info(f"App: Status of intended start port '{initial_start_port}' from history for order '{order_num}' is '{status_of_intended_start_port}'.")

        if status_of_intended_start_port in ["Done", "Skipped"]:
            logger.info(f"App: Intended start port '{initial_start_port}' is already Done/Skipped for order '{order_num}'.")

            msg_box = QMessageBox(self.ui)
            msg_box.setWindowTitle("Port Already Tested")
            msg_text_base = (f"The initially selected port '{initial_start_port}' is already marked as "
                             f"'{status_of_intended_start_port}' for order '{order_num}'.\n\nWhat would you like to do?")

            test_again_button = msg_box.addButton("Test Again", QMessageBox.ButtonRole.ActionRole)
            select_different_button = None

            ports_for_different_selection = self.ports_remaining_in_order - {initial_start_port}

            if ports_for_different_selection:
                select_different_button = msg_box.addButton("Select Different Port", QMessageBox.ButtonRole.ActionRole)
                msg_box.setText(msg_text_base)
            else:
                msg_box.setText(f"The initially selected port '{initial_start_port}' is already marked as "
                                f"'{status_of_intended_start_port}' for order '{order_num}'.\n"
                                "There are no other selected ports pending for this order.\n\n"
                                f"Would you like to test '{initial_start_port}' again?")

            cancel_button = msg_box.addButton(QMessageBox.StandardButton.Cancel)
            msg_box.setDefaultButton(cancel_button if not select_different_button else select_different_button)
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.exec()
            clicked_button = msg_box.clickedButton()

            if clicked_button == test_again_button:
                logger.info(f"App: User chose to test port '{initial_start_port}' again for order '{order_num}'.")

                if self.current_antenna_key:
                    persistence_key_to_clear = (self.current_antenna_key, initial_start_port)
                    if persistence_key_to_clear in self.tested_sns_persistent:
                        logger.info(f"App: Clearing previously tested SNs for {persistence_key_to_clear} due to 'Test Again' on order port.")
                        self.tested_sns_persistent[persistence_key_to_clear].clear()
                    else:
                        logger.info(f"App: No SNs to clear for {persistence_key_to_clear} (key not found or port never tested under this antenna config/orientation).")
                else:
                    logger.warning(f"App: Cannot clear SNs for port '{initial_start_port}' on 'Test Again' because current_antenna_key is not set.")

                if self.order_number in self.order_history_status and initial_start_port in self.order_history_status[self.order_number]:
                    self.order_history_status[self.order_number][initial_start_port] = "Pending (Re-test)"
                    logger.info(f"App: Updated in-memory history for {initial_start_port} to 'Pending (Re-test)'.")

                self.ports_remaining_in_order.add(initial_start_port)
                self.current_processing_port = initial_start_port
                self.ui.set_current_test_port(initial_start_port)
                self.ui.update_port_status(initial_start_port, status="Pending")
                self.ui.request_calibration_for_port(initial_start_port)
                return

            elif select_different_button and clicked_button == select_different_button:
                logger.info(f"App: User chose to select a different port for order '{order_num}'.")
                remaining_list_for_selection = sorted(list(ports_for_different_selection))

                if not remaining_list_for_selection:
                        QMessageBox.information(self.ui, "No Other Ports", "There are no other available ports to select.")
                        self.save_persistent_data(); self.ui.go_to_antenna_selection(); self._reset_main_app_state()
                        return

                chosen_port, ok = QInputDialog.getItem(self.ui, "Select Different Starting Port",
                                                    "Please choose a different port to start with from the remaining ports:",
                                                    remaining_list_for_selection, 0, False)
                if ok and chosen_port:
                    logger.info(f"App: User selected new starting port: {chosen_port}")
                    self.current_processing_port = chosen_port
                    self.ui.set_current_test_port(chosen_port)
                    self.ui.request_calibration_for_port(chosen_port)
                else:
                    logger.info("App: User cancelled selecting a different starting port.")
                    QMessageBox.warning(self.ui, "Operation Cancelled", "Selection cancelled. Returning to antenna selection.")
                    self.save_persistent_data(); self.ui.go_to_antenna_selection(); self._reset_main_app_state()
                return

            elif clicked_button == cancel_button or msg_box.clickedButton() is None:
                logger.info("App: User cancelled the choice. Returning to antenna selection.")
                QMessageBox.information(self.ui, "Operation Cancelled", "Operation cancelled. Returning to antenna selection.")
                self.save_persistent_data(); self.ui.go_to_antenna_selection(); self._reset_main_app_state()
                return

            if not ports_for_different_selection and clicked_button != test_again_button :
                QMessageBox.information(self.ui, "Order Section Complete",
                                        f"All selected ports for order '{order_num}' are completed.\n"
                                        "Proceeding to 'Next Action' screen.")
                last_port_disp = initial_start_port
                if self.ports_selected_by_user: last_port_disp = self.ports_selected_by_user[-1]
                self.ui.update_next_action_state(last_port_disp, False, True)
                return
        else:
            logger.info(f"App: Proceeding with port: {initial_start_port} for order '{order_num}'. Requesting UI calibration.")
            self.ui.request_calibration_for_port(initial_start_port)

    @Slot(str, str)
    def validate_antenna_sn(self, scanned_sn: str, port_name: str):
        logger.info(f"App: Validating SN '{scanned_sn}' for Port '{port_name}' (Order: '{self.order_number}', Retest-No-Count-Pending: {self.is_current_test_a_no_count_retry})")
        if port_name != self.current_processing_port:
            logger.warning(f"Antenna SN validation for wrong port. Expected {self.current_processing_port}, got {port_name}")
            return

        expected_sn_for_retest = None
        if self.is_current_test_a_no_count_retry: 
            expected_sn_for_retest = self.current_antenna_sn 
            logger.info(f"App: Retest flow active, expecting SN: {expected_sn_for_retest}")

        is_valid_for_proceeding = True 
        error_message = ""
        report_as_already_tested_for_ui_dialog = False

        if not (scanned_sn and scanned_sn.strip()):
            error_message = "Antenna Serial Number cannot be empty."
            is_valid_for_proceeding = False
        elif self.is_current_test_a_no_count_retry: 
            if scanned_sn == expected_sn_for_retest:
                logger.info(f"App: SN {scanned_sn} matches expected SN {expected_sn_for_retest} for retest.")
            else:
                error_message = f"Incorrect Serial Number for retest. Expected '{expected_sn_for_retest}', scanned '{scanned_sn}'."
                is_valid_for_proceeding = False
        else: 
            self.current_antenna_sn = scanned_sn 
            if self.current_antenna_key:
                persistence_key_tuple = (self.current_antenna_key, port_name)
                sns_tested_for_this_specific_config = self.tested_sns_persistent.get(persistence_key_tuple, set())
                if scanned_sn in sns_tested_for_this_specific_config:
                    report_as_already_tested_for_ui_dialog = True
                    logger.info(f"SN '{scanned_sn}' has already been marked as tested for {self.current_antenna_key} / {port_name}.")
            else:
                logger.error("Cannot check SN persistence: self.current_antenna_key is not set during normal scan. This is a bug.")

        ui_is_retest_flow_flag = self.is_current_test_a_no_count_retry and is_valid_for_proceeding

        QTimer.singleShot(100, lambda: \
            self.ui.report_antenna_sn_validation(
                is_valid_for_proceeding,
                report_as_already_tested_for_ui_dialog, 
                error_message,
                is_retest_flow=ui_is_retest_flow_flag 
            )
        )


    @Slot(bool, str) 
    def handle_retry_test(self, retry: bool, serial_number: str):
        port_name = self.current_processing_port
        logger.info(f"App: Retry decision from UI for SN-already-tested: {retry} for SN '{serial_number}' on Port '{port_name}'")

        if retry: 
            logger.info(f"App: User chose to re-test SN {serial_number}. Marking upcoming test as NOT-COUNTABLE test.")
            self.is_current_test_a_no_count_retry = True 
            self.current_antenna_sn = serial_number 
        else: 
            logger.info(f"App: User chose not to re-test SN {serial_number} on Port {port_name}. Will scan next unit.")
            self.is_current_test_a_no_count_retry = False 
            self.current_antenna_sn = None 


    @Slot(str, str) 
    def handle_request_retest_failed_unit(self, port_name: str, serial_number: str):
        logger.info(f"App: Retest requested by UI for failed SN {serial_number} on Port {port_name}")
        self.is_current_test_a_no_count_retry = True 
        self.current_processing_port = port_name
        self.current_antenna_sn = serial_number 

        self.ui.set_current_test_port(port_name) 

        if hasattr(self.ui, 'setup_for_retest_scan'):
            logger.info(f"Calling UI's setup_for_retest_scan for {port_name}, SN {serial_number}")
            self.ui.setup_for_retest_scan(port_name, serial_number) 
        elif hasattr(self.ui, 'prepare_for_retest'): 
            logger.warning(f"UI method 'setup_for_retest_scan' not found. Using 'prepare_for_retest' as fallback for {port_name}, SN {serial_number}. Ensure it goes to SN scan.")
            self.ui.prepare_for_retest(port_name, serial_number) 
        else:
            logger.error("UI is missing 'setup_for_retest_scan' or 'prepare_for_retest' method. Cannot properly prepare for retest of failed unit.")
            QMessageBox.warning(self.ui, "UI Error", "Cannot prepare for retest scan. UI component missing. Please scan the SN manually.")
            self.ui.go_to_state("ScanAntennaSN") 


    @Slot(str)
    def do_antenna_measurement(self, port_name: str):
        logger.info(f"App: Starting DUT Measurement for SN '{self.current_antenna_sn}' Port '{port_name}' (No-Count-Retry: {self.is_current_test_a_no_count_retry})")

        if port_name != self.current_processing_port:
             logger.error(f"DUT Measurement start for wrong port. Expected {self.current_processing_port}, got {port_name}.")
             if self.is_current_test_a_no_count_retry and self.current_antenna_sn:
                 logger.warning("Retest flow context mismatch. Attempting to re-setup retest scan.")
                 if hasattr(self.ui, 'setup_for_retest_scan'):
                     self.ui.setup_for_retest_scan(port_name, self.current_antenna_sn)
                 else: 
                     self.ui.go_to_state("ScanAntennaSN")
             else:
                 self.ui.go_to_state("ScanAntennaSN")
             return

        if not self.current_antenna_sn:
             logger.error("DUT Measurement start: No current_antenna_sn set.")
             QMessageBox.critical(self.ui, "Error", "No Antenna Serial Number available for test. Please scan SN first.")
             if self.is_current_test_a_no_count_retry: 
                 logger.warning("SN missing during retest flow. Attempting to re-setup retest scan.")
                 self.is_current_test_a_no_count_retry = False 
                 self.ui.go_to_state("ScanAntennaSN")
             else:
                 self.ui.go_to_state("ScanAntennaSN")
             return

        limits_for_port = self.antenna_data.get("limits", {}).get(port_name, [])
        num_freq_points = len(limits_for_port)
        golden_meas_list = self.antenna_data.get("golden_measurements", {}).get(port_name, [])

        if num_freq_points == 0:
            logger.error(f"No limit data/frequency points defined for port '{port_name}' for DUT Measurement.")
            QMessageBox.critical(self.ui, "Configuration Error", f"No frequency points for port '{port_name}'. Cannot start DUT measurement.")
            self.ui.go_to_state("ScanAntennaSN")
            return
        if not golden_meas_list or len(golden_meas_list) != num_freq_points:
            logger.error(f"Golden measurement data missing or incomplete for port '{port_name}' (DUT). "
                         f"Golden items: {len(golden_meas_list if golden_meas_list else [])}, Freq points: {num_freq_points}.")
            QMessageBox.critical(self.ui, "Data Error", "Golden measurement data is incomplete or missing for this port. Please re-run Golden Sample measurement.")
            self.ui.go_to_state("ScanGoldenSN")
            return
        
        # Hardware capability check for DUT measurement
        if self._is_hardware_ready():
            min_req_gen_freq_mhz = float('inf')
            max_req_gen_freq_mhz = float('-inf')
            for freq_data in limits_for_port:
                target_freq_ghz = freq_data[0]
                gen_freq_mhz = (target_freq_ghz * 1000) / self.multiplexing_factor
                min_req_gen_freq_mhz = min(min_req_gen_freq_mhz, gen_freq_mhz)
                max_req_gen_freq_mhz = max(max_req_gen_freq_mhz, gen_freq_mhz)
            
            if not (self.signal_generator_device._min_freq_mhz <= min_req_gen_freq_mhz and 
                    self.signal_generator_device._max_freq_mhz >= max_req_gen_freq_mhz):
                msg = (f"Required generator frequency range ({min_req_gen_freq_mhz:.2f}-{max_req_gen_freq_mhz:.2f} MHz) "
                       f"for DUT on this port is outside Signal Generator's capabilities. Check config.")
                logger.error(msg)
                QMessageBox.critical(self.ui, "Hardware Capability Error", msg)
                self.ui.go_to_state("ScanAntennaSN")
                return

        self.ui.progress_bar.setMaximum(num_freq_points)
        self.ui.progress_bar.setValue(0)
        self.freq_index = 0
        self._simulated_results = []
        self.ui._test_running = True

        if self.current_measurement_timer and self.current_measurement_timer.isActive():
            self.current_measurement_timer.stop()
        self.current_measurement_timer = QTimer(self)
        self.current_measurement_timer.timeout.connect(self._perform_antenna_measurement_step)
        interval = 75 if self.hardware_demo_mode else 250 
        self.current_measurement_timer.start(interval)

    def _perform_antenna_measurement_step(self): 
        port_name = self.current_processing_port
        serial_number = self.current_antenna_sn

        if not self.ui._test_running or not port_name or not serial_number or not self.antenna_data:
             logger.warning(f"Antenna measurement step called in invalid state (Running: {self.ui._test_running}, Port: {port_name}, SN: {serial_number}). Aborting step.")
             if self.current_measurement_timer: self.current_measurement_timer.stop()
             self.current_measurement_timer = None
             self.ui._test_running = False
             return

        limits_for_port = self.antenna_data.get("limits", {}).get(port_name, [])
        num_freq_points = len(limits_for_port)
        golden_meas_list = self.antenna_data.get("golden_measurements", {}).get(port_name, [])

        if self.freq_index < num_freq_points:
            current_limit_data = limits_for_port[self.freq_index]
            target_freq_ghz_val = current_limit_data[0]
            dut_lower_limit = current_limit_data[1]
            dut_upper_limit = current_limit_data[2]
            spec_gain_golden_sample = current_limit_data[3]

            golden_sample_power_reading_dbm = golden_meas_list[self.freq_index]
            if golden_sample_power_reading_dbm is None:
                logger.error(f"Missing Golden measurement data point for DUT test at Freq Index {self.freq_index}, Port {port_name}, SN {serial_number}. Aborting DUT test.")
                if self.current_measurement_timer: self.current_measurement_timer.stop()
                self.ui._test_running = False
                QMessageBox.critical(self.ui, "Data Error", "Golden measurement data point missing. Please re-run Golden Sample measurement.")
                self.ui.go_to_state("ScanGoldenSN")
                return

            instrument_reading_dut_dbm: Optional[float] = None
            actual_dut_gain_dbi: Optional[float] = None

            if not self._is_hardware_ready(): # Simulation for DUT
                logger.debug(f"DUT (Sim) SN {serial_number}, Port {port_name}, Freq Idx: {self.freq_index}, Target Freq: {target_freq_ghz_val} GHz")
                FAIL_PROBABILITY_PER_TEST_POINT = 0.05
                is_this_freq_point_failing = random.random() < FAIL_PROBABILITY_PER_TEST_POINT
                
                sim_actual_dut_gain_dbi = 0.0 # Placeholder for simulated gain
                if is_this_freq_point_failing:
                    # ... (simulation for failing point, sets sim_actual_dut_gain_dbi) ...
                    spec_range_width = dut_upper_limit - dut_lower_limit
                    failure_magnitude_offset = 0.0
                    if spec_range_width > 0.1: failure_magnitude_offset = spec_range_width * random.uniform(0.1, 0.5)
                    else: failure_magnitude_offset = random.uniform(0.2, 1.0)
                    if random.random() < 0.5: sim_actual_dut_gain_dbi = dut_lower_limit - failure_magnitude_offset
                    else: sim_actual_dut_gain_dbi = dut_upper_limit + failure_magnitude_offset
                else:
                    # ... (simulation for passing point, sets sim_actual_dut_gain_dbi) ...
                    if dut_upper_limit > dut_lower_limit:
                        target_gain_center = (dut_lower_limit + dut_upper_limit) / 2.0
                        spec_half_width = (dut_upper_limit - dut_lower_limit) / 2.0; noise_factor_for_pass = 0.90
                        random_deviation_from_center = random.uniform(-spec_half_width * noise_factor_for_pass, spec_half_width * noise_factor_for_pass)
                        sim_actual_dut_gain_dbi = target_gain_center + random_deviation_from_center
                    elif dut_upper_limit == dut_lower_limit: sim_actual_dut_gain_dbi = dut_lower_limit
                    else: sim_actual_dut_gain_dbi = dut_lower_limit + random.uniform(-0.05, 0.05)
                
                actual_dut_gain_dbi = sim_actual_dut_gain_dbi
                # Back-calculate what instrument would read for this simulated DUT gain
                # CORRECTED CALCULATION (for simulation consistency, though the primary fix is below)
                instrument_reading_dut_dbm = golden_sample_power_reading_dbm + (actual_dut_gain_dbi - spec_gain_golden_sample)

            else: # Real hardware for DUT
                logger.debug(f"DUT (HW) SN {serial_number}, Port {port_name}, Freq Idx: {self.freq_index}, Target Freq: {target_freq_ghz_val} GHz")
                try:
                    generator_freq_mhz = (target_freq_ghz_val * 1000) / self.multiplexing_factor
                    
                    logger.info(f"  Setting Gen: Freq={generator_freq_mhz:.4f} MHz, Pwr={self.transmitter_power} dBm")
                    if not self.signal_generator_device.set_frequency(generator_freq_mhz):
                        raise Exception(f"Failed to set generator frequency to {generator_freq_mhz} MHz")
                    if not self.signal_generator_device.set_power(self.transmitter_power):
                        raise Exception(f"Failed to set generator power to {self.transmitter_power} dBm")

                    logger.info(f"  Setting PM: Freq={target_freq_ghz_val} GHz")
                    if not self.power_meter.set_frequency(target_freq_ghz_val):
                        raise Exception(f"Failed to set power meter frequency to {target_freq_ghz_val} GHz")
                    
                    self.signal_generator_device.rf_on()
                    time.sleep(self.instrument_settling_time_s)

                    instrument_reading_dut_dbm = self.power_meter.measure_power(wait_time=0.5)
                    
                    if instrument_reading_dut_dbm is None:
                        raise Exception("Power meter returned None for DUT measurement.")
                    
                    # Calculate actual DUT gain based on real readings
                    # --- THIS IS THE CORRECTED CALCULATION ---
                    actual_dut_gain_dbi = spec_gain_golden_sample + (instrument_reading_dut_dbm - golden_sample_power_reading_dbm)

                except Exception as e:
                    self._handle_hardware_error("DUT Measurement Step", e, port_name=port_name, sn=serial_number)
                    return 
                finally:
                    if self.signal_generator_device and self.signal_generator_device.is_rf_on:
                        self.signal_generator_device.rf_off()
                        logger.info("  Gen RF OFF")
            
            pass_status_for_point = "FAIL (Error)" 
            if actual_dut_gain_dbi is not None and instrument_reading_dut_dbm is not None:
                 pass_status_for_point = "PASS" if dut_lower_limit <= actual_dut_gain_dbi <= dut_upper_limit else "FAIL"
            else: # Should have been caught by HW error handling
                 logger.error(f"DUT measurement resulted in None for gain or power reading for SN {serial_number} at {target_freq_ghz_val} GHz.")


            self._simulated_results.append({
                "Frequency_GHz": target_freq_ghz_val,
                "Antenna_Gain": actual_dut_gain_dbi if actual_dut_gain_dbi is not None else float('nan'),
                "Lower_Limit": dut_lower_limit,
                "Upper_Limit": dut_upper_limit,
                "Pass": pass_status_for_point,
                "Antenna_Measurement": instrument_reading_dut_dbm if instrument_reading_dut_dbm is not None else float('nan'),
                "Golden_Measurement": golden_sample_power_reading_dbm, 
                "Spec_Gain_Golden": spec_gain_golden_sample 
            })

            if self.ui.stacked_widget.currentWidget() == self.ui.test_page:
                self.ui.update_measurement_progress(self.freq_index, target_freq_ghz_val, 
                                                    actual_dut_gain_dbi if actual_dut_gain_dbi is not None else float('nan'),
                                                    dut_lower_limit, dut_upper_limit)
            self.freq_index += 1
        else: # All frequency points processed
            if self.current_measurement_timer: self.current_measurement_timer.stop()
            self.current_measurement_timer = None
            self.ui._test_running = False
            logger.info(f"App: DUT Measurement {'simulation' if self.hardware_demo_mode or not self.hardware_initialized_successfully else 'hardware test'} complete for SN '{serial_number}', Port '{port_name}'")

            overall_port_pass_status = "PASS" if all(res["Pass"] == "PASS" for res in self._simulated_results) else "FAIL"

            retry_flag_value_for_report = self.is_current_test_a_no_count_retry

            # Save results to database if not in demo mode
            self._save_test_results_to_db(
                port_name=port_name,
                serial_number=serial_number,
                results_list=self._simulated_results,
                overall_status=overall_port_pass_status,
                is_silver_test=False,
                is_retry_no_count=retry_flag_value_for_report
            )

            if self.is_current_test_a_no_count_retry:
                logger.info(f"App: Resetting is_current_test_a_no_count_retry flag from True to False after retest of {serial_number}.")
                self.is_current_test_a_no_count_retry = False

            if self.current_antenna_key and serial_number:
                persistence_key_tuple_for_sn = (self.current_antenna_key, port_name)
                if persistence_key_tuple_for_sn not in self.tested_sns_persistent:
                    self.tested_sns_persistent[persistence_key_tuple_for_sn] = set()

                if serial_number not in self.tested_sns_persistent[persistence_key_tuple_for_sn]:
                    self.tested_sns_persistent[persistence_key_tuple_for_sn].add(serial_number)
                    logger.info(f"App: Added SN '{serial_number}' to persistent set for {persistence_key_tuple_for_sn}. "
                               f"Total for this key: {len(self.tested_sns_persistent[persistence_key_tuple_for_sn])}")
                else:
                    logger.info(f"App: SN '{serial_number}' was already in persistent set for {persistence_key_tuple_for_sn} (or this was a no-count retry completion).")
            else:
                logger.warning("current_antenna_key or serial_number not set. Cannot update tested_sns_persistent for DUT.")


            new_measurement_id_for_dut = self.measurement_id_counter
            self.measurement_id_counter += 1

            failure_details_msg = ""
            if overall_port_pass_status == "FAIL":
                fail_details = []
                for res_idx, res_item in enumerate(self._simulated_results):
                    if res_item.get("Pass") != "PASS":
                        fail_details.append(
                            f"  Freq {res_item.get('Frequency_GHz', 'N/A')} GHz: "
                            f"Measured Gain {res_item.get('Antenna_Gain', float('nan')):.2f} dBi "
                            f"(Limits: {res_item.get('Lower_Limit', float('nan')):.2f} / {res_item.get('Upper_Limit', float('nan')):.2f} dBi)"
                        )
                failure_details_msg = "\n".join(fail_details)

            self.ui.report_port_test_complete_for_antenna(
                port_name=port_name,
                serial_number=serial_number,
                results=self._simulated_results, 
                overall_port_status=overall_port_pass_status,
                measurement_id=new_measurement_id_for_dut,
                is_retry_no_count=retry_flag_value_for_report, 
                failure_details_message=failure_details_msg
            )

    @Slot(str)
    def handle_port_batch_complete(self, completed_port_name: str):
        logger.info(f"App: UI signaled port_batch_run_complete for: {completed_port_name}")

        if not self.current_processing_port or completed_port_name != self.current_processing_port:
             logger.warning(f"Batch complete signal context mismatch. UI Port: '{completed_port_name}', App's current Port: '{self.current_processing_port}'. This might indicate an issue or an abort.")
             self.ports_remaining_in_order.discard(completed_port_name)
             can_still_test_next_port = bool(self.ports_remaining_in_order)
             self.ui.update_next_action_state(completed_port_name, can_still_test_next_port, can_test_next_order=True)
             return

        if self.order_number:
            if self.order_number not in self.order_history_status:
                 self.order_history_status[self.order_number] = {}
            self.order_history_status[self.order_number][completed_port_name] = "Done"
            self.save_persistent_data()
            logger.info(f"Order history for '{self.order_number}' updated: Port '{completed_port_name}' is now 'Done'.")
        else:
            logger.warning(f"Port batch complete for '{completed_port_name}', but no active order_number. History not updated.")

        self.ports_remaining_in_order.discard(completed_port_name)
        logger.info(f"App: Ports remaining for current order ('{self.order_number}'): {self.ports_remaining_in_order}")

        can_test_another_port_this_order = bool(self.ports_remaining_in_order)
        can_start_new_order_or_finish = True

        self.ui.update_next_action_state(completed_port_name,
                                         can_test_next_port=can_test_another_port_this_order,
                                         can_test_next_order=can_start_new_order_or_finish)

    @Slot()
    def handle_request_test_next_port(self):
        logger.info("App: Handling UI request to test next port for the current order.")

        if not self.ports_remaining_in_order:
             logger.warning("Request to test next port, but no ports are remaining for the current order.")
             QMessageBox.warning(self.ui, "No More Ports", "All selected ports for the current order have been processed.")
             self.ui.update_next_action_state(self.current_processing_port or "N/A",
                                             can_test_next_port=False,
                                             can_test_next_order=True)
             return

        remaining_ports_list_for_dialog = sorted(list(self.ports_remaining_in_order))
        default_selection_idx = 0 if remaining_ports_list_for_dialog else -1

        chosen_port, ok = QInputDialog.getItem(self.ui, "Select Next Port",
                                               "Choose the next port to test for the current order:",
                                               remaining_ports_list_for_dialog,
                                               current=default_selection_idx,
                                               editable=False)
        if ok and chosen_port:
            logger.info(f"App: User selected next port to test: {chosen_port}")
            self.current_processing_port = chosen_port
            self.ui.set_current_test_port(chosen_port)
            self.ui.proceed_to_next_port(chosen_port)
        else:
            logger.info("App: User cancelled next port selection. Staying on NextActionPage.")
            self.ui.update_next_action_state(self.current_processing_port or "N/A",
                                             can_test_next_port=True,
                                             can_test_next_order=True)

    @Slot()
    def handle_request_test_next_order(self):
        logger.info("App: Handling UI request to start a new order (using same antenna config and port selection).")

        if not self.ports_selected_by_user:
            logger.error("Cannot start next order: No ports were initially selected for this test session. Critical error.")
            QMessageBox.critical(self.ui, "Internal Error", "Cannot determine start port for new order as no ports were initially selected. Please restart antenna selection.")
            self.ui.go_to_antenna_selection()
            self._reset_main_app_state()
            return

        start_port_for_new_order = self.current_processing_port
        if not start_port_for_new_order or start_port_for_new_order not in self.ports_selected_by_user:
            logger.warning(f"Warning: Current processing port ('{start_port_for_new_order}') "
                           f"is invalid or not in the list of user-selected ports for this session: {self.ports_selected_by_user}. "
                           f"Defaulting to the first selected port as a safer fallback.")
            start_port_for_new_order = self.ports_selected_by_user[0]

        logger.info(f"App: Resetting for a new order. New order will begin with port: {start_port_for_new_order}.")

        self.order_number = None
        self.charge_number = None
        self.order_quantity = 0
        self.ports_remaining_in_order = set(self.ports_selected_by_user)
        self.current_processing_port = start_port_for_new_order

        self.ui.reset_for_new_order_same_antenna(start_port_for_new_order)
        self.ui.set_current_test_port(start_port_for_new_order)
        self.ui.go_to_state("EnterOrderInfo")

    @Slot()
    def handle_request_finish_measurements(self):
        logger.info("App: Handling UI request to finish measurements (current antenna/orders).")
        self.save_persistent_data()
        self.ui.finish_order_testing() 
        self._reset_main_app_state()

    @Slot()
    def abort_current_action(self):
        logger.info("App: Abort signal received from UI. Stopping any active measurement and resetting app state.")
        if self.current_measurement_timer and self.current_measurement_timer.isActive():
            logger.info("App: Stopping active measurement timer due to abort.")
            self.current_measurement_timer.stop()
        self.current_measurement_timer = None
        self.ui._test_running = False

        if self.current_processing_port and self.current_antenna_key:
            persistence_key = (self.current_antenna_key, self.current_processing_port)
            if persistence_key in self.tested_sns_persistent:
                logger.warning(f"ABORT: Clearing all previously tested SNs for port '{self.current_processing_port}' on antenna config '{self.current_antenna_key}'.")
                self.tested_sns_persistent[persistence_key].clear()
            else:
                logger.info(f"ABORT: No SNs to clear for port '{self.current_processing_port}' (key not found or port never tested).")
        else:
            logger.info("ABORT: No current port/antenna context, cannot clear specific SNs.")

        # Ensure RF is off if hardware was active
        if self.signal_generator_device and hasattr(self.signal_generator_device, 'is_rf_on') and self.signal_generator_device.is_rf_on:
            try:
                logger.info("Aborting: Turning RF OFF on signal generator.")
                self.signal_generator_device.rf_off()
            except Exception as e:
                logger.error(f"Error turning RF off during abort: {e}")

        logger.info("App: Resetting main application state due to abort.")
        self._reset_main_app_state()

    @Slot()
    def cleanup_and_exit(self):
        logger.info("App: Received request to cleanup and exit application.")
        self.save_persistent_data()
        self._shutdown_hardware() # Full hardware shutdown on application exit
        logger.info("Persistent data saved (if enabled). Hardware shutdown. Application will now quit.")

        q_app_instance = QApplication.instance()
        if q_app_instance:
            q_app_instance.quit()
        else:
            logger.warning("QApplication.instance() is None during exit. Forcing sys.exit().")
            sys.exit(0)

    @Slot()
    def reload_users_maybe(self):
        logger.info("App: UI signaled that user list might have been updated (e.g., User Management dialog closed).")

    def _reset_main_app_state(self):
         logger.info("App: Resetting internal application state for a new antenna selection or full restart.")
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
         self.current_antenna_config_filename = None 
         if self.current_measurement_timer and self.current_measurement_timer.isActive():
             self.current_measurement_timer.stop()
         self.current_measurement_timer = None

    def _save_test_results_to_db(self, port_name: str, serial_number: str, results_list: List[Dict], overall_status: str, is_silver_test: bool, is_retry_no_count: bool):
        """
        Prepares and saves a completed test (Silver or DUT) to the database.
        This method is skipped if in database_demo_mode or if the db_service is unavailable.
        """
        if self.database_demo_mode:
            logger.info(f"DB DEMO MODE: Skipping database save for SN '{serial_number}', Port '{port_name}'.")
            return
        if self.db_service is None:
            logger.error(f"Cannot save to DB for SN '{serial_number}', Port '{port_name}': Database service is not available.")
            return

        logger.info(f"Preparing to save test results to DB for SN '{serial_number}', Port '{port_name}'.")

        try:
            # --- 1. Prepare GainTestHeader ---
            comment = f"Test for Port {port_name}."
            if is_silver_test:
                comment = f"Silver sample calibration for Port {port_name}."
            elif is_retry_no_count:
                comment = f"Re-test of previously failed unit for Port {port_name} (no-count)."

            header = GainTestHeader(
                port=port_name,
                antenna_id=serial_number,
                order_number=self.order_number,
                article_number=self.antenna_data.get("PART_NUMBER"),
                charge_number=self.charge_number,
                product_name=self.antenna_data.get("name"),
                setup_file=self.current_antenna_config_filename,
                timestamp_utc=datetime.now(timezone.utc),
                reference="Silver" if is_silver_test else None,
                operator=self.ui.current_user,
                result=overall_status,
                soft_version=APP_VERSION,
                comment=comment,
                hardware_id_gen=self.hardware_id_gen,
                hardware_id_power_meter=self.hardware_id_power_meter,
                hardware_id_extension_module=self.hardware_id_extension_module,
                inactive=0 # Default to active
            )

            # --- 2. Prepare List of GainTestValue ---
            values: List[GainTestValue] = []
            for res_item in results_list:
                # For Silver test, 'Gain_Golden' is the target gain of the Silver sample.
                # For DUT test, 'Gain_Golden' is the spec gain of the Golden sample.
                if is_silver_test:
                    gain_golden_val = res_item.get('Spec_Gain_Displayed')
                else:
                    gain_golden_val = res_item.get('Spec_Gain_Golden')

                value_entry = GainTestValue(
                    frequency_ghz=res_item.get('Frequency_GHz'),
                    measurement_antenna=res_item.get('Antenna_Measurement'),
                    measurement_golden=res_item.get('Golden_Measurement'),
                    gain_antenna=res_item.get('Antenna_Gain'),
                    gain_golden=gain_golden_val,
                    lower_limit=res_item.get('Lower_Limit'),
                    upper_limit=res_item.get('Upper_Limit')
                )
                values.append(value_entry)
            
            # --- 3. Create Composite Data and Insert ---
            composite_data = CompositeAntennaTestData(header=header, values=values)
            
            logger.info(f"Attempting to insert composite measurement into DB for SN '{serial_number}'...")
            inserted_meas_id = self.db_service.insert_measurement(composite_data)
            logger.info(f"Successfully saved test to DB for SN '{serial_number}', Port '{port_name}'. Assigned Meas_ID: {inserted_meas_id}.")

        except pyodbc.Error as e:
            logger.error(f"DATABASE ERROR while saving results for SN '{serial_number}', Port '{port_name}': {e}", exc_info=True)
            QMessageBox.critical(self.ui, "Database Save Failed",
                                 f"Could not save test results to the database for SN '{serial_number}'.\n\n"
                                 f"Error: {e}\n\n"
                                 "The test result is NOT recorded. Please check database connectivity and logs. "
                                 "You may need to re-test this unit later.")
        except Exception as e:
            logger.error(f"UNEXPECTED ERROR while preparing or saving results for SN '{serial_number}', Port '{port_name}': {e}", exc_info=True)
            QMessageBox.critical(self.ui, "Application Error During Save",
                                 f"An unexpected application error occurred while trying to save test results for SN '{serial_number}'.\n\n"
                                 f"Error: {e}\n\n"
                                 "The test result may not be recorded. Please check logs.")


    def save_persistent_data(self):
        if not self.persistent_memory_enabled:
            logger.info("Persistent memory is disabled by configuration. Skipping save of persistent data.")
            return

        logger.info(f"App: Attempting to save persistent data to directory: {PERSISTENT_DATA_DIR}")
        try:
            PERSISTENT_DATA_DIR.mkdir(parents=True, exist_ok=True)
            sn_persistence_file = PERSISTENT_DATA_DIR / "tested_sns_persistent.pkl"
            order_history_file = PERSISTENT_DATA_DIR / "order_history_status.pkl"

            with open(sn_persistence_file, "wb") as f_sn:
                pickle.dump(self.tested_sns_persistent, f_sn)
                logger.debug(f"Saved tested_sns_persistent to {sn_persistence_file}")
            with open(order_history_file, "wb") as f_hist:
                pickle.dump(self.order_history_status, f_hist)
                logger.debug(f"Saved order_history_status to {order_history_file}")

            logger.info(f"App: Persistent data (SNs tested, order history) saved successfully.")
        except Exception as e:
            logger.error(f"CRITICAL ERROR saving persistent data: {e}", exc_info=True)
            if self.ui and hasattr(self.ui, 'isVisible') and self.ui.isVisible():
                QMessageBox.critical(self.ui, "Save Error",
                                     f"Could not save persistent application data to:\n{PERSISTENT_DATA_DIR}\n\n"
                                     f"Error: {e}\n\n"
                                     "Recent test history might be lost on exit if not saved previously.")

    def load_persistent_data(self):
        logger.info(f"App: Attempting to load persistent data from directory: {PERSISTENT_DATA_DIR}")

        if not PERSISTENT_DATA_DIR.exists():
            logger.info(f"Persistent data directory {PERSISTENT_DATA_DIR} does not exist. Initializing with empty data structures.")
            self.tested_sns_persistent = {}
            self.order_history_status = {}
            return

        sn_persistence_file = PERSISTENT_DATA_DIR / "tested_sns_persistent.pkl"
        order_history_file = PERSISTENT_DATA_DIR / "order_history_status.pkl"

        try:
            if sn_persistence_file.exists():
                with open(sn_persistence_file, "rb") as f_sn:
                    loaded_sns = pickle.load(f_sn)
                    if isinstance(loaded_sns, dict):
                        self.tested_sns_persistent = loaded_sns
                        logger.info(f"App: Loaded {len(self.tested_sns_persistent)} persistent SN entries from {sn_persistence_file}.")
                    else:
                        logger.error(f"Corrupt or incompatible data in {sn_persistence_file}. Expected dict, got {type(loaded_sns)}. Initializing empty SN persistence.")
                        self.tested_sns_persistent = {}
            else:
                logger.info(f"App: No persistent SN file found at {sn_persistence_file}. Initializing empty SN persistence.")
                self.tested_sns_persistent = {}

            if order_history_file.exists():
                with open(order_history_file, "rb") as f_hist:
                    loaded_history = pickle.load(f_hist)
                    if isinstance(loaded_history, dict):
                        self.order_history_status = loaded_history
                        logger.info(f"App: Loaded {len(self.order_history_status)} order history entries from {order_history_file}.")
                    else:
                        logger.error(f"Corrupt or incompatible data in {order_history_file}. Expected dict, got {type(loaded_history)}. Initializing empty order history.")
                        self.order_history_status = {}
            else:
                logger.info(f"App: No order history file found at {order_history_file}. Initializing empty order history.")
                self.order_history_status = {}

        except pickle.UnpicklingError as pe:
            logger.error(f"Error unpickling persistent data (file might be corrupt or incompatible): {pe}. Initializing with empty data.", exc_info=True)
            if self.ui and hasattr(self.ui, 'isVisible') and self.ui.isVisible():
                QMessageBox.warning(self.ui, "Load Warning",
                                    f"Could not load some persistent data files from:\n{PERSISTENT_DATA_DIR}\n"
                                    "Files might be corrupt. Starting with fresh history for affected items.\n"
                                    f"Error: {pe}")
            self.tested_sns_persistent = {}
            self.order_history_status = {}
        except Exception as e:
            logger.error(f"Error loading persistent data: {e}. Initializing with empty data.", exc_info=True)
            if self.ui and hasattr(self.ui, 'isVisible') and self.ui.isVisible():
                 QMessageBox.warning(self.ui, "Load Error",
                                    f"Could not load persistent application data from:\n{PERSISTENT_DATA_DIR}\n"
                                    f"Error: {e}\n\nStarting with fresh history.")
            self.tested_sns_persistent = {}
            self.order_history_status = {}

if __name__ == '__main__':


    app = QApplication(sys.argv)
    app.setOrganizationName(COMPANY_NAME)
    app.setApplicationName(APP_NAME_FOR_SETTINGS)
    app.setApplicationVersion(APP_VERSION)

    logger.info("Application starting...") # This will now go to console and file
    main_window = UiMainWindow()
    main_window.resize(1600, 900)

    dummy_app_logic = DummyMainApp(main_window)

    # Check if DummyMainApp constructor signaled a critical hardware failure
    if DummyMainApp._critical_hardware_failure:
        logger.critical("Exiting application due to critical hardware failure during initialization in production mode.")
        # main_window might not be visible yet, or QMessageBox handled UI interaction.
        # Ensure clean exit.
        sys.exit(1) # Exit with an error code

    main_window.show()
    logger.info("Main window shown.")

    exit_code = app.exec()
    
    if dummy_app_logic:
        logger.info("Ensuring hardware shutdown before final exit (if not already handled by cleanup_and_exit)...")
        dummy_app_logic._shutdown_hardware()

    logger.info(f"Application exiting with code {exit_code}.")
    sys.exit(exit_code)