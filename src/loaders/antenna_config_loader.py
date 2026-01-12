      
# --- START OF FILE antenna_config_loader.py ---

import pandas as pd
import os
from typing import Dict, Optional, Any, Union, List, Tuple
import logging
import glob
from pathlib import Path

# Set up logging
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )
logger = logging.getLogger('ConfigLoader')


class ConfigDataError(Exception):
    """Custom exception for configuration data errors."""
    pass


class ExcelConfigLoader:
    """
    Class to load and handle configuration data from Excel files (.xlsx, .xls).
    Supports multiple tabs ('LIMITS', 'CONFIGURATION') and provides structured access to the data.
    """

    # Define expected columns and keys for validation
    EXPECTED_LIMITS_COLUMNS = [
        'Port', 'Frequency_GHz', 'Spec_Gain_Horn', 'Lower_Limit', 'Upper_Limit',
        'Silver_Gain_Horn', 'Silver_Spec_Limit', 'Comment'
    ]
    EXPECTED_CONFIG_KEYS = [
        'ANTENNA_NAME', 'PN_H+S', 'PART_NUMBER', 'PART_NUMBER_DECODING',
        'REV_FROM_SN_DECODING', 'SN_GOLDEN_SAMPLE', 'SN_SILVER_SAMPLE',
        'PORT_HORIZONTAL', 'PORT_VERTICAL'
    ]
    # Assuming the config sheet uses first col for key, second for value
    EXPECTED_CONFIG_COLUMNS = 2 # Expect at least Key and Value columns

    def __init__(self, file_path: Optional[str] = None):
        """
        Initialize the config loader.

        Args:
            file_path: Path to the Excel file containing configuration data.
        """
        self.file_path = file_path
        self._limits_data: Optional[pd.DataFrame] = None
        self._config_data: Optional[pd.DataFrame] = None

        # If file path is provided during initialization, load the data
        if file_path:
            self.load_config(file_path)

    def load_config(self, file_path: str) -> bool:
        """
        Load configuration data from the specified Excel file.
        Requires 'LIMITS' and 'CONFIGURATION' sheets.

        Args:
            file_path: Path to the Excel file containing configuration data.

        Returns:
            bool: True if data was loaded successfully, False otherwise.
        """
        if not os.path.exists(file_path):
            logger.error(f"Configuration file not found: {file_path}")
            return False

        try:
            # Check file extension
            _, ext = os.path.splitext(file_path)
            if ext.lower() not in ['.xlsx', '.xls']:
                logger.error(f"Unsupported file format: {ext}. Only .xlsx and .xls are supported.")
                return False

            # Store file path
            self.file_path = file_path

            # Read the Excel file
            excel_file = pd.ExcelFile(file_path)
            available_sheets = excel_file.sheet_names

            loaded_limits = False
            loaded_config = False

            # Check for required sheets and load data
            if 'LIMITS' in available_sheets:
                # Try loading with comma decimal first, fallback to dot if error
                try:
                    self._limits_data = excel_file.parse('LIMITS', decimal=',')
                    logger.info("Loaded LIMITS sheet (using ',' as decimal separator)")
                except ValueError:
                     logger.warning("Could not parse LIMITS sheet with ',' as decimal separator. Trying '.'")
                     try:
                         self._limits_data = excel_file.parse('LIMITS') # Default decimal is '.'
                         logger.info("Loaded LIMITS sheet (using '.' as decimal separator)")
                     except Exception as parse_e:
                         logger.error(f"Failed to parse LIMITS sheet even with '.' decimal: {parse_e}")
                         self._limits_data = None # Ensure it's None if parsing fails
                         return False # Cannot proceed without limits

                # Ensure _limits_data is not None before accessing it
                if self._limits_data is not None:
                    # Convert numeric columns explicitly after loading, handling potential errors
                    # Ensure these column names match EXACTLY with Excel headers (and EXPECTED_LIMITS_COLUMNS)
                    numeric_cols = ['Frequency_GHz', 'Spec_Gain_Horn', 'Lower_Limit', 'Upper_Limit',
                                    'Silver_Gain_Horn', 'Silver_Spec_Limit'] # Corrected 'Silver_Gain_Horn [dBi]'
                    for col in numeric_cols:
                        if col in self._limits_data.columns:
                            # If parsing with comma decimal worked, replace comma with dot for consistency before to_numeric
                            if isinstance(self._limits_data[col].iloc[0], str) and ',' in self._limits_data[col].iloc[0]:
                                self._limits_data[col] = self._limits_data[col].astype(str).str.replace(',', '.', regex=False)
                            self._limits_data[col] = pd.to_numeric(self._limits_data[col], errors='coerce')
                            if self._limits_data[col].isnull().any():
                                logger.warning(f"Column '{col}' in LIMITS sheet contains non-numeric values after conversion.")
                    loaded_limits = True
                else: # Parsing failed completely
                     loaded_limits = False


            else:
                logger.error("Required sheet 'LIMITS' not found in Excel file.")
                self._limits_data = None
                self._config_data = None
                return False # Fail if LIMITS is missing

            if 'CONFIGURATION' in available_sheets:
                try:
                    self._config_data = excel_file.parse('CONFIGURATION', header=None)
                    logger.info("Loaded CONFIGURATION sheet (assuming no header row)")
                    if len(self._config_data.columns) >= 2:
                         self._config_data.columns = range(len(self._config_data.columns))
                         logger.debug(f"Assigned default column names: {self._config_data.columns.tolist()}")
                    loaded_config = True
                except Exception as parse_e:
                    logger.error(f"Failed to parse CONFIGURATION sheet: {parse_e}")
                    loaded_config = False
                    self._config_data = None
            else:
                logger.error("Required sheet 'CONFIGURATION' not found in Excel file.")
                self._limits_data = None
                self._config_data = None
                return False

            if loaded_limits and loaded_config:
                logger.info(f"Configuration loaded successfully from {file_path}")
                if not self.validate_config():
                    logger.error(f"Loaded configuration from {file_path} failed validation. Check previous logs.")
                    # return False # Stricter: fail load if validation fails
                return True
            else:
                logger.error("Failed to load required sheets or parse data correctly from Excel file.")
                self._limits_data = None
                self._config_data = None
                return False

        except Exception as e:
            logger.error(f"Error loading configuration from {file_path}: {str(e)}")
            self._limits_data = None
            self._config_data = None
            return False

    @property
    def limits_data(self) -> Optional[pd.DataFrame]:
        """Get the limits data as a pandas DataFrame."""
        if self._limits_data is None:
            logger.warning("Attempted to access limits_data before loading or after failed load.")
        return self._limits_data

    @property
    def config_data(self) -> Optional[pd.DataFrame]:
        """Get the configuration data as a pandas DataFrame."""
        if self._config_data is None:
            logger.warning("Attempted to access config_data before loading or after failed load.")
        return self._config_data

    def get_port_data(self, port_name: str) -> pd.DataFrame:
        """
        Get all data for a specific port from the limits data.

        Args:
            port_name: The name of the port (e.g., 'RX01', 'TX02').

        Returns:
            DataFrame containing data for the specified port.

        Raises:
            ConfigDataError: If the port is not found or limits data is not loaded or valid.
        """
        if self._limits_data is None:
            raise ConfigDataError("Limits data not loaded or invalid.")

        if 'Port' not in self._limits_data.columns:
            raise ConfigDataError("'Port' column not found in limits data")

        port_data = self._limits_data[self._limits_data['Port'].astype(str) == str(port_name)]

        if port_data.empty:
            raise ConfigDataError(f"Port '{port_name}' not found in limits data")

        return port_data.copy()

    def get_config_value(self, key: str, default: Any = pd.NA) -> Any:
        """
        Get a specific configuration value from the 'CONFIGURATION' sheet.
        Assumes the first column contains keys and the second column contains values.

        Args:
            key: The configuration key to look up in the first column.
            default: Value to return if key not found. pd.NA is used to distinguish from None if None is a valid value.


        Returns:
            The value associated with the key from the second column.

        Raises:
            ConfigDataError: If configuration data is not loaded, or data format is invalid (e.g. not enough columns).
                             Does not raise if key is not found but default is provided.
        """
        if self._config_data is None:
            raise ConfigDataError("Configuration data not loaded or invalid.")

        if len(self._config_data.columns) < self.EXPECTED_CONFIG_COLUMNS:
            raise ConfigDataError(f"Configuration data sheet must have at least "
                                  f"{self.EXPECTED_CONFIG_COLUMNS} columns (Key, Value). "
                                  f"Found: {len(self._config_data.columns)}")

        key_col = self._config_data.columns[0]
        val_col = self._config_data.columns[1]

        key_row = self._config_data[self._config_data[key_col].astype(str) == str(key)]

        if key_row.empty:
            if default is not pd.NA:
                return default
            raise ConfigDataError(f"Key '{key}' not found in configuration data (column '{key_col}') and no default provided.")

        value = key_row.iloc[0][val_col]

        if pd.isna(value):
            logger.warning(f"Key '{key}' found, but its value is missing/NaN in the configuration sheet.")
            return None 

        return value


    def get_ports_by_orientation(self, orientation: str) -> list:
        """
        Get list of ports by orientation (horizontal/vertical) from config data.

        Args:
            orientation: 'horizontal' or 'vertical'.

        Returns:
            List of port names for the specified orientation.

        Raises:
            ConfigDataError: If the orientation info is not found or config data is invalid.
        """
        if self._config_data is None:
            raise ConfigDataError("Configuration data not loaded or invalid.")

        try:
            orientation_lower = orientation.lower()
            if orientation_lower == 'horizontal':
                port_key = 'PORT_HORIZONTAL'
            elif orientation_lower == 'vertical':
                port_key = 'PORT_VERTICAL'
            else:
                raise ConfigDataError(f"Invalid orientation '{orientation}', must be 'horizontal' or 'vertical'")

            port_str = self.get_config_value(port_key)

            if pd.isna(port_str) or port_str is None:
                 raise ConfigDataError(f"Value for key '{port_key}' is missing or not found.")
            if not isinstance(port_str, str):
                 raise ConfigDataError(f"Value for key '{port_key}' is not a string (found type: {type(port_str)}): {port_str}")

            ports = [port.strip() for port in port_str.split(',') if port.strip()]
            if not ports:
                 logger.warning(f"No valid ports found for key '{port_key}' after splitting and stripping value: '{port_str}'")

            return ports

        except ConfigDataError as e: 
             raise ConfigDataError(f"Error getting ports for orientation '{orientation}': {str(e)}")
        except Exception as e:
            raise ConfigDataError(f"Unexpected error getting ports for orientation '{orientation}': {str(e)}")

    def get_frequency_data(self, frequency: Union[float, int]) -> pd.DataFrame:
        """
        Get all port data for a specific frequency from the limits data.

        Args:
            frequency: The frequency value (in GHz) to filter by.

        Returns:
            DataFrame containing data for all ports at the specified frequency.

        Raises:
            ConfigDataError: If the frequency is not found or limits data is not loaded or valid.
        """
        if self._limits_data is None:
            raise ConfigDataError("Limits data not loaded or invalid.")

        freq_col_name = 'Frequency_GHz'
        if freq_col_name not in self._limits_data.columns:
            raise ConfigDataError(f"'{freq_col_name}' column not found in limits data")

        if not pd.api.types.is_numeric_dtype(self._limits_data[freq_col_name]):
             logger.warning(f"'{freq_col_name}' column is not numeric. Attempting conversion again.")
             self._limits_data[freq_col_name] = pd.to_numeric(self._limits_data[freq_col_name], errors='coerce')
             if self._limits_data[freq_col_name].isnull().all():
                  raise ConfigDataError(f"'{freq_col_name}' column contains no valid numeric data.")

        try:
            target_frequency = float(frequency)
        except (ValueError, TypeError):
             raise ConfigDataError(f"Invalid frequency value provided: {frequency}. Must be convertible to a number.")

        try:
            import numpy as np
            freq_data = self._limits_data[np.isclose(self._limits_data[freq_col_name].astype(float), target_frequency)]
        except ImportError:
            logger.warning("numpy not available. Using basic equality for frequency comparison (may be sensitive to float precision).")
            freq_data = self._limits_data[self._limits_data[freq_col_name] == target_frequency]


        if freq_data.empty:
            all_freqs = self._limits_data[freq_col_name].dropna().unique()
            try:
                import numpy as np
                exists = any(np.isclose(f, target_frequency) for f in all_freqs)
            except ImportError:
                exists = target_frequency in all_freqs

            if not exists:
                raise ConfigDataError(f"Frequency {target_frequency} GHz not found in limits data")
            else:
                 logger.warning(f"Frequency {target_frequency} GHz exists, but no matching rows found after filtering (unexpected).")

        return freq_data.copy()

    def get_all_ports(self) -> list:
        """
        Get a list of all unique ports in the limits data.

        Returns:
            List of unique port names, sorted alphabetically.

        Raises:
            ConfigDataError: If limits data is not loaded or 'Port' column is missing.
        """
        if self._limits_data is None:
            raise ConfigDataError("Limits data not loaded or invalid.")

        if 'Port' not in self._limits_data.columns:
            raise ConfigDataError("'Port' column not found in limits data")

        ports = self._limits_data['Port'].dropna().astype(str).unique()
        return sorted(ports.tolist())

    def get_all_frequencies(self) -> list:
        """
        Get a list of all unique frequencies in the limits data.

        Returns:
            List of unique frequency values (as floats), sorted numerically.

        Raises:
            ConfigDataError: If limits data is not loaded or 'Frequency_GHz' column is missing or non-numeric.
        """
        if self._limits_data is None:
            raise ConfigDataError("Limits data not loaded or invalid.")

        freq_col_name = 'Frequency_GHz'
        if freq_col_name not in self._limits_data.columns:
            raise ConfigDataError(f"'{freq_col_name}' column not found in limits data")

        if not pd.api.types.is_numeric_dtype(self._limits_data[freq_col_name]):
            raise ConfigDataError(f"'{freq_col_name}' column is not numeric. Cannot extract frequencies.")

        frequencies = self._limits_data[freq_col_name].dropna().unique()
        return sorted(frequencies.tolist())

    def validate_config(self) -> bool:
        """
        Validate that the loaded configuration data meets expected structure and content.
        Checks for required sheets, columns within sheets, and specific keys.
        This method is automatically called after a successful load in `load_config`.

        Returns:
            bool: True if valid, False otherwise. Logs errors for specific issues.
        """
        is_valid = True
        validation_errors = []

        if self._limits_data is None:
            validation_errors.append("Limits data frame is missing.")
            is_valid = False
        if self._config_data is None:
            validation_errors.append("Configuration data frame is missing.")
            is_valid = False

        if not is_valid:
            logger.error(f"Validation Failed: Basic data structures not loaded. Errors: {'; '.join(validation_errors)}")
            return False

        limits_cols = self._limits_data.columns.tolist()
        missing_limits_cols = [col for col in self.EXPECTED_LIMITS_COLUMNS if col not in limits_cols]
        # extra_limits_cols = [col for col in limits_cols if col not in self.EXPECTED_LIMITS_COLUMNS] # Not needed for this check

        if missing_limits_cols:
            # Check if missing columns are among the non-comment ones, as Comment might be optional in some interpretations
            critical_missing_cols = [
                col for col in self.EXPECTED_LIMITS_COLUMNS 
                if col != 'Comment' and col not in limits_cols
            ]
            if critical_missing_cols:
                validation_errors.append(f"LIMITS Sheet: Missing required columns: {', '.join(critical_missing_cols)}")
                is_valid = False
            elif 'Comment' not in limits_cols:
                 logger.warning("Validation Info (LIMITS Sheet): 'Comment' column is missing, but considered optional.")


        if len(self._config_data.columns) < self.EXPECTED_CONFIG_COLUMNS:
             validation_errors.append(f"CONFIGURATION Sheet: Expected at least {self.EXPECTED_CONFIG_COLUMNS} columns (Key, Value), "
                                      f"but found {len(self._config_data.columns)}.")
             is_valid = False
        else:
             key_col_name = self._config_data.columns[0]
             # val_col_name = self._config_data.columns[1] # Not used in this check

             if is_valid and len(self._config_data.columns) >= 1 :
                key_col = self._config_data.columns[0]
                config_keys_present = self._config_data[key_col].dropna().astype(str).tolist()
                missing_config_keys = [str(key) for key in self.EXPECTED_CONFIG_KEYS if str(key) not in config_keys_present]

                if missing_config_keys:
                    validation_errors.append(f"CONFIGURATION Sheet: Missing required keys in column '{key_col_name}': {', '.join(missing_config_keys)}")
                    is_valid = False

        if is_valid:
            logger.info(f"Configuration validation successful for {self.file_path}.")
        else:
             logger.error(f"Configuration validation failed for {self.file_path}. Issues found:")
             for error in validation_errors:
                 logger.error(f"  - {error}")
        return is_valid


def find_excel_files(directory_path: Union[str, Path]) -> List[Tuple[str, str]]:
    """
    Find all Excel files (.xlsx, .xls) in the specified directory.

    Args:
        directory_path: Path to the directory to search for Excel files.

    Returns:
        List of tuples containing (file_name, full_path) for each Excel file found,
        sorted alphabetically by file name. Returns empty list on error or if not found.
    """
    # Convert to string if Path object is passed, for os.path.isdir
    dir_path_str = str(directory_path)
    if not os.path.isdir(dir_path_str): 
        logger.error(f"Directory not found or is not a directory: {dir_path_str}")
        return []

    try:
        excel_extensions = ['*.xlsx', '*.xls']
        excel_files = []

        for ext in excel_extensions:
            pattern = os.path.join(dir_path_str, ext)
            files = glob.glob(pattern)
            for file_path in files:
                if os.path.isfile(file_path) and not os.path.basename(file_path).startswith('~$'):
                    file_name = os.path.basename(file_path)
                    excel_files.append((file_name, file_path))

        if not excel_files:
            logger.warning(f"No suitable Excel files (.xlsx, .xls) found in directory: {dir_path_str}")
        else:
            logger.info(f"Found {len(excel_files)} Excel file(s) in {dir_path_str}")

        excel_files.sort(key=lambda x: x[0])
        return excel_files

    except Exception as e:
        logger.error(f"Error while searching for Excel files in {dir_path_str}: {str(e)}")
        return []


def create_config_loader(file_path: Union[str, Path] = None) -> Optional[ExcelConfigLoader]:
    """
    Factory function to create and initialize an Excel config loader.
    Loads the specified file if provided and exists. Performs validation after loading.

    Args:
        file_path: Optional path to the Excel file (.xlsx, .xls) to load.

    Returns:
        Initialized ExcelConfigLoader instance if loading and validation are successful,
        otherwise returns None.
    """
    if not file_path:
        logger.error("No file path provided to create_config_loader.")
        return None
    
    # Convert to string if Path object is passed
    file_path_str = str(file_path)

    if not os.path.exists(file_path_str):
        logger.error(f"Provided file path does not exist: {file_path_str}.")
        return None

    logger.info(f"Attempting to load configuration from: {file_path_str}")
    loader = ExcelConfigLoader() 
    success = loader.load_config(file_path_str) 

    if success:
        # load_config now calls validate_config. If strict validation is needed for loader creation:
        # if not loader.validate_config(): # Re-check or rely on load_config's return for strictness
        #     logger.error("Configuration loaded but failed validation. Loader creation aborted.")
        #     return None
        logger.info(f"Successfully created config loader from {file_path_str}")
        return loader
    else:
        logger.error(f"Failed to load or an error occurred during validation for configuration from {file_path_str}. Loader creation aborted.")
        return None


if __name__ == "__main__":
    print("-" * 30)
    print("Config Loader Example Usage")
    print("-" * 30)

    config_loader = None 

    try:
        project_root = Path(__file__).resolve().parent.parent 
        config_dir = project_root / "config" / "antenna_config_files"
        print(f"\nLooking for Excel configuration files (.xlsx, .xls) in: '{os.path.abspath(config_dir)}'")

        if not os.path.isdir(config_dir):
            print(f"\nERROR: Configuration directory not found: '{config_dir}'")
            print("Please create the directory and place your Excel configuration file inside.")
            exit() 

        excel_files = find_excel_files(config_dir)

        if not excel_files:
            print(f"\nERROR: No Excel configuration files (.xlsx, .xls) found in '{config_dir}'.")
            print("Please ensure a valid configuration file exists in the directory.")
            exit()

        print(f"\nFound {len(excel_files)} Excel configuration file(s):")
        for idx, (name, path) in enumerate(excel_files, 1):
            print(f"  {idx}. {name}")

        selected_index = 0 
        selected_name, selected_path = excel_files[selected_index]
        print(f"\n--> Automatically selecting first file for example usage: {selected_name}")

        config_loader = create_config_loader(selected_path)

        if config_loader:
            print("\n--- Configuration Successfully Loaded (Validation result logged above) ---")

            print("\nFetching some data from configuration:")
            try:
                antenna_name = config_loader.get_config_value('ANTENNA_NAME')
                print(f"  Antenna Name: {antenna_name}")

                h_ports = config_loader.get_ports_by_orientation('horizontal')
                print(f"  Horizontal Ports: {h_ports}")

                v_ports = config_loader.get_ports_by_orientation('vertical')
                print(f"  Vertical Ports: {v_ports}")

                all_freqs = config_loader.get_all_frequencies()
                print(f"  All Frequencies (GHz): {all_freqs}")

                if all_freqs:
                     freq_to_get = all_freqs[0]
                     print(f"\n  Data for First Frequency ({freq_to_get} GHz):")
                     freq_data = config_loader.get_frequency_data(freq_to_get)
                     print(freq_data.to_string(index=False, max_cols=16))
                else:
                     print("\n  No frequencies found in the limits data.")


                all_ports = config_loader.get_all_ports()
                print(f"\n  All Ports Found: {all_ports}")
                if all_ports:
                     port_to_get = all_ports[0]
                     print(f"\n  Data for First Port ('{port_to_get}'):")
                     port_data = config_loader.get_port_data(port_to_get)
                     print(port_data.to_string(index=False, max_cols=16))
                else:
                     print("\n  No ports found in the limits data.")


            except ConfigDataError as e:
                print(f"\nERROR retrieving data: {e}")
            except Exception as e:
                print(f"\nAn unexpected error occurred during data retrieval: {e}")
                logging.exception("Unhandled exception during data retrieval:")

        else:
            print("\n--- Failed to Create Config Loader ---")
            print("Check log messages above for specific errors during loading or validation.")

    except Exception as e:
        print(f"\nAn unexpected error occurred in the main execution block: {str(e)}")
        logging.exception("Unhandled exception in main block:")

    print("-" * 30)
    print("Example Usage Finished")
    print("-" * 30)
# --- END OF FILE antenna_config_loader.py ---

    