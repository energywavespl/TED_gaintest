# loaders/software_config_loader.py

import pandas as pd
import os
import logging
from typing import Dict, Optional, Any, Union

# --- Configuration ---
# You can change the expected filename here if needed
DEFAULT_CONFIG_FILENAME = "software_config.xlsx"
HARDWARE_SHEET_NAME = "Hardware"
DATABASE_SHEET_NAME = "Database"

# --- Logging Setup ---
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )
logger = logging.getLogger('SoftwareConfigLoader')

# --- Custom Exceptions ---
class SoftwareConfigError(Exception):
    """Base exception for software configuration errors."""
    pass

class ConfigFileNotFoundError(SoftwareConfigError):
    """Exception raised when the config file is not found."""
    pass

class SheetNotFoundError(SoftwareConfigError):
    """Exception raised when a required sheet is missing."""
    pass

class ConfigNotLoadedError(SoftwareConfigError):
    """Exception raised when trying to access config data before loading."""
    pass

class KeyNotFoundError(SoftwareConfigError):
    """Exception raised when a specific key is not found in the config."""
    pass


class SoftwareConfigLoader:
    """
    Loads and provides access to software configuration settings
    from an Excel file with 'Hardware' and 'Database' sheets.

    Expects sheets to have a Key-Value structure in the first two columns.
    """

    def __init__(self, config_directory: str, filename: str = DEFAULT_CONFIG_FILENAME):
        """
        Initializes the loader with the path to the configuration directory.

        Args:
            config_directory (str): The path to the folder containing the config file.
            filename (str, optional): The name of the Excel config file.
                                      Defaults to DEFAULT_CONFIG_FILENAME.
        """
        if not os.path.isdir(config_directory):
            raise FileNotFoundError(f"Configuration directory not found: {config_directory}")

        self.config_directory = config_directory
        self.filename = filename
        self.file_path = os.path.join(self.config_directory, self.filename)
        self._hardware_config: Optional[Dict[str, Any]] = None
        self._database_config: Optional[Dict[str, Any]] = None
        self._loaded = False

    def _read_sheet_to_dict(self, excel_file: pd.ExcelFile, sheet_name: str) -> Dict[str, Any]:
        """Helper to read a sheet and convert it to a Key-Value dictionary."""
        logger.debug(f"Attempting to parse sheet: '{sheet_name}'")
        try:
            # Read sheet, assume no header, use first two columns
            df = excel_file.parse(sheet_name, header=None, usecols=[0, 1])

            # Convert to dictionary: Column 0 as key, Column 1 as value
            config_dict = {}
            for index, row in df.iterrows():
                key = row.iloc[0]
                value = row.iloc[1]

                # Handle potential empty cells read as NaN or None
                if pd.isna(key):
                    logger.warning(f"Skipping row {index+1} in sheet '{sheet_name}' due to missing key.")
                    continue
                if pd.isna(value):
                     logger.warning(f"Key '{key}' in sheet '{sheet_name}' has a missing/empty value. Setting to None.")
                     value = None # Represent empty Excel cells as None

                # Convert key to string for consistent access
                key_str = str(key).strip()
                if not key_str:
                    logger.warning(f"Skipping row {index+1} in sheet '{sheet_name}' due to empty key after stripping.")
                    continue

                # Handle potential numeric values correctly (don't force to string if not needed)
                # Pandas typically infers types well here. Value remains as read.
                config_dict[key_str] = value
                logger.debug(f"  Loaded: {key_str} = {value} (Type: {type(value).__name__})")

            if not config_dict:
                 logger.warning(f"Sheet '{sheet_name}' parsed, but resulted in an empty configuration dictionary.")

            return config_dict

        except ValueError as e:
            # More specific error for missing sheet
            if f"Worksheet named '{sheet_name}' not found" in str(e):
                 raise SheetNotFoundError(f"Required sheet '{sheet_name}' not found in {self.file_path}") from e
            else:
                 # Catch other potential parsing errors (e.g., file corruption)
                 raise SoftwareConfigError(f"Error parsing sheet '{sheet_name}' in {self.file_path}: {e}") from e
        except IndexError as e:
            # Catch error if sheet exists but has fewer than 2 columns
            raise SoftwareConfigError(f"Sheet '{sheet_name}' in {self.file_path} must have at least two columns (Key, Value). Error: {e}") from e
        except Exception as e:
             # Catch unexpected errors during parsing
             raise SoftwareConfigError(f"Unexpected error reading sheet '{sheet_name}' from {self.file_path}: {e}") from e

    def load(self) -> bool:
        """
        Loads the configuration data from the Excel file.

        Returns:
            bool: True if loading was successful, False otherwise.

        Raises:
            ConfigFileNotFoundError: If the specified Excel file does not exist.
            SheetNotFoundError: If required 'Hardware' or 'Database' sheets are missing.
            SoftwareConfigError: For other parsing or file access errors.
        """
        self._loaded = False # Reset load status
        self._hardware_config = None
        self._database_config = None

        logger.info(f"Attempting to load software configuration from: {self.file_path}")
        if not os.path.exists(self.file_path):
            logger.error(f"Configuration file not found: {self.file_path}")
            raise ConfigFileNotFoundError(f"Configuration file not found: {self.file_path}")

        try:
            # Check file extension
            _, ext = os.path.splitext(self.file_path)
            if ext.lower() not in ['.xlsx', '.xls']:
                logger.error(f"Unsupported file format: {ext}. Only .xlsx and .xls are supported.")
                return False

            excel_file = pd.ExcelFile(self.file_path)
            available_sheets = excel_file.sheet_names
            logger.debug(f"Found sheets: {available_sheets}")

            # Check if required sheets exist before trying to parse
            if HARDWARE_SHEET_NAME not in available_sheets:
                 raise SheetNotFoundError(f"Required sheet '{HARDWARE_SHEET_NAME}' not found in {self.file_path}")
            if DATABASE_SHEET_NAME not in available_sheets:
                 raise SheetNotFoundError(f"Required sheet '{DATABASE_SHEET_NAME}' not found in {self.file_path}")

            # Load sheets into dictionaries
            self._hardware_config = self._read_sheet_to_dict(excel_file, HARDWARE_SHEET_NAME)
            self._database_config = self._read_sheet_to_dict(excel_file, DATABASE_SHEET_NAME)

            self._loaded = True
            logger.info(f"Successfully loaded configuration from {self.file_path}")
            return True

        except (ConfigFileNotFoundError, SheetNotFoundError) as e:
            logger.error(f"Configuration load failed: {e}")
            raise # Re-raise specific errors for caller handling
        except SoftwareConfigError as e: # Catch parsing errors from helper
             logger.error(f"Configuration load failed due to parsing error: {e}")
             # Optionally re-raise or return False depending on desired strictness
             # raise e # Re-raise if parsing errors should halt execution
             return False # Return False if main app might handle missing data gracefully
        except Exception as e:
            logger.exception(f"An unexpected error occurred loading configuration from {self.file_path}: {e}")
            # raise SoftwareConfigError(f"Unexpected error loading config: {e}") from e
            return False # Return False for unexpected errors

    def is_loaded(self) -> bool:
        """Checks if the configuration has been successfully loaded."""
        return self._loaded

    @property
    def hardware(self) -> Dict[str, Any]:
        """
        Returns the hardware configuration dictionary.

        Raises:
            ConfigNotLoadedError: If config hasn't been loaded successfully.
        """
        if not self._loaded or self._hardware_config is None:
            raise ConfigNotLoadedError("Hardware configuration accessed before successful load.")
        return self._hardware_config

    @property
    def database(self) -> Dict[str, Any]:
        """
        Returns the database configuration dictionary.

        Raises:
            ConfigNotLoadedError: If config hasn't been loaded successfully.
        """
        if not self._loaded or self._database_config is None:
            raise ConfigNotLoadedError("Database configuration accessed before successful load.")
        return self._database_config

    def get_value(self, section: str, key: str, default: Any = None) -> Any:
        """
        Gets a specific value from the specified config section (Hardware or Database).

        Args:
            section (str): The configuration section ('Hardware' or 'Database', case-insensitive).
            key (str): The configuration key to retrieve.
            default (Any, optional): The value to return if the key is not found. Defaults to None.

        Returns:
            Any: The configuration value, or the default value if the key is not found.

        Raises:
            ConfigNotLoadedError: If config hasn't been loaded successfully.
            ValueError: If the section name is invalid.
        """
        if not self._loaded:
            raise ConfigNotLoadedError("Configuration accessed before successful load.")

        section_lower = section.lower()
        target_dict: Optional[Dict[str, Any]] = None

        if section_lower == 'hardware':
            target_dict = self._hardware_config
        elif section_lower == 'database':
            target_dict = self._database_config
        else:
            raise ValueError(f"Invalid configuration section '{section}'. Use 'Hardware' or 'Database'.")

        if target_dict is None:
            # This should theoretically not happen if _loaded is True, but safety check
            raise ConfigNotLoadedError(f"Internal error: Section '{section}' dictionary is None despite loaded=True.")

        value = target_dict.get(key, default) # Use dict.get for safe access

        # Optional: Log if key was not found and default is used
        if key not in target_dict:
             logger.debug(f"Key '{key}' not found in section '{section}'. Returning default value: {default}")
        # Optional: Handle type conversion here if desired, e.g., get_int_value, get_float_value
        # Example:
        # if isinstance(value, (int, float, str)) and isinstance(default, type):
        #    try: return default(value) except (ValueError, TypeError): pass

        return value

    def get_hardware_value(self, key: str, default: Any = None) -> Any:
        """Convenience method to get a value from the Hardware section."""
        return self.get_value('Hardware', key, default)

    def get_database_value(self, key: str, default: Any = None) -> Any:
        """Convenience method to get a value from the Database section."""
        return self.get_value('Database', key, default)

    def __str__(self) -> str:
        """String representation for easy printing."""
        if not self._loaded:
            return f"SoftwareConfigLoader(file='{self.file_path}', status=Not Loaded)"
        return (
            f"SoftwareConfigLoader(file='{self.file_path}', status=Loaded)\n"
            f"  Hardware Settings: {len(self._hardware_config or {})} items\n"
            f"  Database Settings: {len(self._database_config or {})} items"
        )

# Example of how to add simple validation (optional but recommended)
# Ti could expand this validation logic significantly
# EXPECTED_HARDWARE_KEYS = {
#     'Serial_Number_Extension', 'Multiplexing_Factor',
#     'Transmitter_Power', 'Calibration_Valid_Time'
# }
# EXPECTED_DATABASE_KEYS = {
#     'Server_Name', 'Database_Name', 'User_ID', 'Database_Password'
# }
#
# def validate_config(self):
#     if not self._loaded: return False # Cannot validate if not loaded
#     valid = True
#     # Check Hardware Keys
#     missing_hw = EXPECTED_HARDWARE_KEYS - set(self._hardware_config.keys())
#     if missing_hw:
#         logger.error(f"Validation Error: Missing required Hardware keys: {missing_hw}")
#         valid = False
#     # Check Database Keys
#     missing_db = EXPECTED_DATABASE_KEYS - set(self._database_config.keys())
#     if missing_db:
#         logger.error(f"Validation Error: Missing required Database keys: {missing_db}")
#         valid = False
#     # Add more checks (e.g., type checks, value ranges) if needed
#     if valid:
#         logger.info("Configuration validation passed.")
#     return valid
#
# # Remember to call self.validate_config() at the end of a successful load() if you implement it.