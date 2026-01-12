# --- START OF FILE Anritsu_MA24510A_V4.py ---

"""
Anritsu MA24510A Power Master Analyzer Interface

This module provides a comprehensive interface for controlling and retrieving
measurements from the Anritsu MA24510A mmWave Power Master Analyzer.
"""

import pyvisa
import time
import logging
from typing import Optional, Union, Dict, Any, Tuple
import re
import contextlib # Added for suppress

# Set up logging
# logging.basicConfig(
#     level=logging.DEBUG,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )
logger = logging.getLogger('anritsu_ma24510a')


class MA24510A:
    """
    Class for controlling the Anritsu MA24510A Power Master Analyzer.

    This class provides methods for connecting to the instrument, configuring
    measurements, and retrieving power readings.
    """

    # Constants for frequency ranges and other parameters
    FREQ_MIN_GHZ = 9e-3  # 9 kHz
    FREQ_MAX_GHZ = 110.0  # 110 GHz
    POWER_MIN_DBM = -90.0
    POWER_MAX_DBM = 20.0

    # Command templates
    COMMANDS = {
        'idn': '*IDN?',
        'reset': '*RST',
        'clear': '*CLS',
        'opc': '*OPC?', # Added for checking operation complete
        'wait': '*WAI', # Added for waiting
        'continuous_mode': ':INITiate:CONTinuous {state}',
        'frequency': ':SENSe:FREQuency:CENTer {freq_ghz}GHZ',
        'set_averaging': ':SENSe:AVERage:STATe {state}',
        'set_averaging_count': ':SENSe:AVERage:COUNt {count}',
        'set_chpower': ':SENSe:CHPower:STATe {state}',
        # Corrected command for channel power bandwidth based on manual and error message
        'set_chpower_bandwidth': ':SENSe:FREQuency:CHWidth {bandwidth_mhz}MHZ',
        'fetch_power': ':FETCh:POWer?',
        'fetch_chpower': ':FETCh:CHPower?',
        'fetch_max_power': ':FETCh:MAXimum?',
        'trigger_mode': ':TRIGger:SOURce {source}', # Note: Check manual if this is the correct trigger command structure
        'zero_sensor': ':CALibration:ZERO:AUTO ONCE', # Note: Power Master may not need zeroing like sensors
        'check_zero_status': ':CALibration:ZERO:STATe?', # Note: Check if applicable to Power Master
        'set_units': ':UNIT:POWer {units}',
        'get_units': ':UNIT:POWer?',
        'set_offset': ':CALCulate:OFFSet {offset_db}',
        'get_offset': ':CALCulate:OFFSet?',
        'system_errors': ':SYSTem:ERRor?',
    }

    # Increased default timeout to 30 seconds (30000 ms)
    def __init__(self, visa_timeout: int = 30000, auto_connect: bool = False,
                 visa_resource_name: Optional[str] = None):
        """
        Initialize the MA24510A controller.

        Args:
            visa_timeout (int): VISA timeout in milliseconds
            auto_connect (bool): If True, attempts to automatically connect to the instrument
            visa_resource_name (str, optional): VISA resource name for the instrument
        """
        self.instrument = None
        self.visa_timeout = visa_timeout
        self.rm = None
        self.connected = False
        self.instrument_idn_string: Optional[str] = None # To store IDN after successful connection
        self.measurement_config = {
            'frequency_ghz': 1.0,
            'averaging': False,
            'averaging_count': 16,
            'chpower': False,
            'chpower_bandwidth_mhz': 100.0,
            'units': 'DBM',
            'offset_db': 0.0,
        }

        if auto_connect:
            self.connect(visa_resource_name)

    def connect(self, visa_resource_name: Optional[str] = None) -> bool:
        """
        Connect to the MA24510A instrument.

        Args:
            visa_resource_name (str, optional): VISA resource name for the instrument.
                If None, attempts to auto-detect the instrument.

        Returns:
            bool: True if connection was successful, False otherwise.
        """
        try:
            self.rm = pyvisa.ResourceManager()
            logger.info(f"Attempting to connect to instrument {visa_resource_name or 'auto-detect'}...") # Corrected Log

            if visa_resource_name:
                # Ensure connection resource string format is correct for pyvisa
                # Example: "TCPIP0::127.0.0.1::59001::SOCKET" is generally correct for sockets
                self.instrument = self.rm.open_resource(visa_resource_name)
                logger.info(f"Opened resource at {visa_resource_name}")
            else:
                logger.info("Attempting to auto-detect MA24510A...")
                resources = self.rm.list_resources()
                ma24510a_resource = None

                for resource in resources:
                    # Look for TCPIP or USB resources compatible with MA24510A
                    # Power Masters often use TCPIP sockets or USBTMC
                    if ("TCPIP" in resource or "USB" in resource) and "INSTR" not in resource.upper(): # Power Master might not be INSTR
                        if "SOCKET" in resource.upper():
                             # Socket connections might need special handling or might not respond to IDN quickly
                             logger.debug(f"Skipping socket resource {resource} for auto-detect IDN probe, connect directly if needed.")
                             continue # Skip sockets for generic IDN probing unless specifically targeted
                        elif "USB" in resource:
                            # Only probe USB resources that look like instruments
                            if "::INSTR" not in resource.upper():
                                logger.debug(f"Skipping non-INSTR USB resource {resource}")
                                continue

                    logger.debug(f"Probing resource: {resource}")
                    try:
                        # Use context manager for safe resource opening/closing during probe
                        with self.rm.open_resource(resource, open_timeout=2000) as instrument_probe:
                            instrument_probe.timeout = 2000  # Short timeout for probing IDN
                            try:
                                idn_response = instrument_probe.query(self.COMMANDS['idn'])
                                logger.debug(f"IDN Response from {resource}: {idn_response}")
                                # Check if it's an Anritsu MA24510A
                                if "Anritsu" in idn_response and "MA24510A" in idn_response:
                                    ma24510a_resource = resource
                                    logger.info(f"Found MA24510A at {resource}")
                                    break # Stop searching once found
                            except pyvisa.errors.VisaIOError as e_idn:
                                # Timeouts are common during probing, log as debug
                                if hasattr(e_idn, 'error_code') and e_idn.error_code == pyvisa.constants.VI_ERROR_TMO:
                                    logger.debug(f"Timeout probing {resource}: {e_idn}")
                                else:
                                    logger.warning(f"VISA error probing {resource}: {e_idn}")
                            except Exception as e_probe:
                                logger.warning(f"Unexpected error probing {resource}: {e_probe}")

                    except pyvisa.errors.VisaIOError as e_open:
                         logger.debug(f"Could not open resource {resource} for probing: {e_open}")
                    except Exception as e:
                        logger.warning(f"Failed to probe {resource}: {e}")
                    time.sleep(0.1) # Small delay between probes

                if ma24510a_resource:
                    self.instrument = self.rm.open_resource(ma24510a_resource)
                    logger.info(f"Auto-connected to instrument at {ma24510a_resource}")
                else:
                    logger.error("MA24510A not found automatically. Please provide VISA resource name.")
                    if self.rm:
                         with contextlib.suppress(Exception): self.rm.close()
                    return False

            # Configure the instrument connection
            self.instrument.timeout = self.visa_timeout
            # Set termination characters - important for sockets
            if "SOCKET" in self.instrument.resource_name.upper():
                 self.instrument.read_termination = "\n"
                 self.instrument.write_termination = "\n"
            else:
                # Use default terminations for USBTMC/GPIB etc.
                # Resetting termination might be needed if defaults are wrong
                 pass

            # Clear buffer before sending commands
            self.instrument.clear()
            # Optional: Short sleep after clear
            # time.sleep(0.1)

            # Verify connection with IDN query
            idn = self.query(self.COMMANDS['idn'])
            if not idn:
                logger.error(f"Failed to get IDN response from {self.instrument.resource_name}")
                with contextlib.suppress(Exception): self.instrument.close()
                self.instrument = None
                if self.rm:
                    with contextlib.suppress(Exception): self.rm.close()
                return False
            elif "Anritsu" not in idn or "MA24510A" not in idn:
                 logger.error(f"Connected to unexpected instrument: {idn}")
                 with contextlib.suppress(Exception): self.instrument.close()
                 self.instrument = None
                 if self.rm:
                     with contextlib.suppress(Exception): self.rm.close()
                 return False

            logger.info(f"Successfully connected to: {idn}")
            self.instrument_idn_string = idn # Store IDN
            self.connected = True

            # Clear status and check for initial errors
            self.clear_status()
            initial_errors = self.check_errors()
            if initial_errors:
                logger.warning(f"Instrument reported errors on connection: {initial_errors}")

            return True

        except pyvisa.errors.VisaIOError as e:
            logger.error(f"VISA Error connecting to MA24510A: {e}")
            if self.instrument:
                with contextlib.suppress(Exception): self.instrument.close()
                self.instrument = None
            if self.rm:
                with contextlib.suppress(Exception): self.rm.close()
            return False
        except Exception as e:
            logger.error(f"Unexpected error during connection: {e}")
            if self.instrument:
                with contextlib.suppress(Exception): self.instrument.close()
                self.instrument = None
            if self.rm:
                with contextlib.suppress(Exception): self.rm.close()
            return False


    def disconnect(self) -> None:
        """
        Disconnect from the MA24510A instrument.
        """
        if self.instrument:
            logger.info(f"Disconnecting from {self.instrument.resource_name}.")
            # Use suppress to avoid errors if closing fails (e.g., already closed)
            with contextlib.suppress(pyvisa.errors.VisaIOError, Exception):
                 self.instrument.clear() # Try to clear before closing
                 self.instrument.close()
            self.instrument = None
        if self.rm:
             with contextlib.suppress(Exception): self.rm.close()
             self.rm = None
        self.connected = False
        self.instrument_idn_string = None # Clear stored IDN
        logger.info("Disconnected.")

    def __enter__(self):
        """
        Context manager entry point.
        """
        # Connection should happen in __init__ or connect() before entering context
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Context manager exit point. Ensures disconnection.
        """
        self.disconnect()


    def write(self, command: str) -> bool:
        """
        Send a command to the instrument.

        Args:
            command (str): Command to send

        Returns:
            bool: True if successful, False otherwise
        """
        # if not self.connected or not self.instrument:
        #     logger.error("Not connected to instrument. Cannot write command.")
        #     return False

        try:
            logger.debug(f"Writing command: {command}")
            self.instrument.write(command)
            # Optional: Check for errors after writing non-query commands
            # errors = self.check_errors()
            # if errors:
            #     logger.warning(f"Instrument reported errors after writing '{command}': {errors}")
            #     # Decide if this should return False based on errors
            return True
        except pyvisa.errors.VisaIOError as e:
            logger.error(f"Error writing command '{command}': {e}")
            # Consider attempting to reconnect or marking as disconnected
            # self.connected = False
            return False
        except Exception as e:
            logger.error(f"Unexpected error writing command '{command}': {e}")
            return False


    def query(self, command: str, delay: float = 0.0) -> Optional[str]:
        """
        Send a query to the instrument and return the response.

        Args:
            command (str): Query command to send
            delay (float): Optional delay in seconds before reading response

        Returns:
            str: Response from the instrument, or None if an error occurred
        """
        # if not self.connected or not self.instrument:
        #     logger.error("Not connected to instrument. Cannot query command.")
        #     return None

        try:
            logger.debug(f"Querying command: {command}")
            response = self.instrument.query(command, delay=delay)
            logger.debug(f"Response: {response.strip()}")
            return response.strip()
        except pyvisa.errors.VisaIOError as e:
            # Specifically log timeout errors which might indicate needed delays or longer timeouts
            if hasattr(e, 'error_code') and e.error_code == pyvisa.constants.VI_ERROR_TMO:
                logger.error(f"Timeout querying command '{command}': {e}")
            else:
                logger.error(f"VISA Error querying command '{command}': {e}")
            # Consider attempting to reconnect or marking as disconnected
            # self.connected = False
            return None
        except Exception as e:
            logger.error(f"Unexpected error querying command '{command}': {e}")
            return None


    def reset(self) -> bool:
        """
        Reset the instrument to default settings.

        Returns:
            bool: True if successful, False otherwise
        """
        logger.info("Resetting instrument...")
        success = self.write(self.COMMANDS['reset'])
        if success:
             # Wait for reset to complete. *OPC? might work after reset, or a fixed delay is needed.
             # A simple sleep is often used, but can be unreliable.
             time.sleep(5) # Increased sleep after reset
             logger.info("Reset command sent. Waiting for instrument to stabilize...")
             # Clear status after reset
             self.clear_status()
            # Re-fetch IDN after reset if it was previously fetched
             if self.instrument_idn_string is not None:
                 self.instrument_idn_string = self.query(self.COMMANDS['idn'])
             # Querying *OPC? ensures command completion
             # opc = self.query(self.COMMANDS['opc'])
             # if opc == '1':
             #     logger.info("Instrument reset complete (OPC confirmed).")
             #     return True
             # else:
             #     logger.warning(f"Instrument reset *OPC? returned unexpected value: {opc}")
             #     return False # Or maybe still true, depending on required strictness
        return success

    def clear_status(self) -> bool:
        """
        Clear the instrument status registers.

        Returns:
            bool: True if successful, False otherwise
        """
        return self.write(self.COMMANDS['clear'])

    def check_errors(self) -> list:
        """
        Check for and return any errors reported by the instrument.

        Returns:
            list: List of error messages (strings)
        """
        errors = []
        if not self.connected or not self.instrument:
            logger.error("Cannot check errors: Not connected.")
            return ["Driver Error: Not Connected"]

        try:
            while True:
                # Add a small delay before querying error queue, sometimes helps
                # time.sleep(0.1)
                error_str = self.instrument.query(self.COMMANDS['system_errors'])
                # error_str = self.query(self.COMMANDS['system_errors']) # Use self.query for unified logging/error handling
                if error_str is None:
                    # Query failed, stop checking
                    logger.error("Failed to query system errors.")
                    errors.append("VISA Query Error during error check")
                    break

                error_str = error_str.strip()
                logger.debug(f"System error query response: {error_str}")

                # Check if the error string indicates "No error"
                # Format is usually like: 0,"No error"
                if error_str.startswith('0,') or "No error" in error_str:
                    break
                else:
                    errors.append(error_str)
                    # Limit loop to prevent infinite loops in case of instrument malfunction
                    if len(errors) > 20:
                         logger.error("Stopped checking errors after 20 errors, queue might be stuck.")
                         errors.append("Error Check Limit Reached")
                         break
            if errors:
                logger.warning(f"Instrument reported errors: {errors}")
            else:
                 logger.debug("No system errors reported by instrument.")
        except pyvisa.errors.VisaIOError as e:
            logger.error(f"VISA Error checking system errors: {e}")
            errors.append(f"VISA Error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error checking system errors: {e}")
            errors.append(f"Unexpected Error: {e}")
        return errors


    def set_frequency(self, frequency_ghz: float) -> bool:
        """
        Set the measurement frequency.

        Args:
            frequency_ghz (float): Frequency in GHz

        Returns:
            bool: True if successful, False otherwise
        """
        if not self.FREQ_MIN_GHZ <= frequency_ghz <= self.FREQ_MAX_GHZ:
            logger.error(f"Frequency {frequency_ghz} GHz out of range ({self.FREQ_MIN_GHZ}-{self.FREQ_MAX_GHZ} GHz)")
            return False

        success = self.write(self.COMMANDS['frequency'].format(freq_ghz=frequency_ghz))
        if success:
            logger.info(f"Frequency set to {frequency_ghz} GHz")
            self.measurement_config['frequency_ghz'] = frequency_ghz
            # Optional: Wait for operation complete
            # self.query(self.COMMANDS['opc'])
        return success

    def set_continuous_mode(self, enabled: bool = True) -> bool:
        """
        Set continuous measurement mode.

        Args:
            enabled (bool): True to enable continuous mode, False for single mode

        Returns:
            bool: True if successful, False otherwise
        """
        state = "ON" if enabled else "OFF"
        success = self.write(self.COMMANDS['continuous_mode'].format(state=state))
        if success:
             logger.info(f"Continuous mode set to {state}")
             # Optional: Wait for operation complete
             # self.query(self.COMMANDS['opc'])
        return success

    def set_averaging(self, enabled: bool = True, count: int = 16) -> bool:
        """
        Configure averaging for measurements.

        Args:
            enabled (bool): True to enable averaging, False to disable
            count (int): Number of samples to average (1-1024, check manual for exact range)

        Returns:
            bool: True if successful, False otherwise
        """
        state = "ON" if enabled else "OFF"
        # Check manual for valid averaging count range
        if not (1 <= count <= 1024): # Assuming 1-1024 is correct
            logger.error(f"Invalid averaging count: {count}. Must be between 1 and 1024.")
            return False

        success_state = self.write(self.COMMANDS['set_averaging'].format(state=state))
        if not success_state:
            logger.error(f"Failed to set averaging state to {state}")
            return False

        success_count = True
        if enabled:
            success_count = self.write(self.COMMANDS['set_averaging_count'].format(count=count))
            if not success_count:
                 logger.error(f"Failed to set averaging count to {count}")
                 # Rollback state? Or just report failure? Reporting failure seems reasonable.
                 return False

        if success_state and success_count:
            logger.info(f"Averaging set to {state}, count {count if enabled else 'N/A'}")
            self.measurement_config['averaging'] = enabled
            self.measurement_config['averaging_count'] = count if enabled else self.measurement_config['averaging_count'] # Keep old count if disabled
            # Optional: Wait for operation complete
            # self.query(self.COMMANDS['opc'])
            return True
        else:
             # Should have returned earlier on failure
             return False

    def set_channel_power(self, enabled: bool = True, bandwidth_mhz: float = 1.0) -> bool:
        """
        Configure channel power measurement.

        Args:
            enabled (bool): True to enable channel power measurement, False for CW measurement
            bandwidth_mhz (float): Channel bandwidth in MHz (check manual for valid range)

        Returns:
            bool: True if successful, False otherwise
        """
        # Check manual for valid bandwidth range
        if bandwidth_mhz <= 0:
             logger.error(f"Invalid channel power bandwidth: {bandwidth_mhz} MHz. Must be positive.")
             return False

        state = "ON" if enabled else "OFF"
        success_state = self.write(self.COMMANDS['set_chpower'].format(state=state))
        if not success_state:
             logger.error(f"Failed to set channel power state to {state}")
             return False

        success_bw = True
        if enabled:
            success_bw = self.write(self.COMMANDS['set_chpower_bandwidth'].format(bandwidth_mhz=bandwidth_mhz))
            if not success_bw:
                logger.error(f"Failed to set channel power bandwidth to {bandwidth_mhz} MHz")
                return False

        if success_state and success_bw:
             logger.info(f"Channel Power set to {state}, bandwidth {bandwidth_mhz if enabled else 'N/A'} MHz")
             self.measurement_config['chpower'] = enabled
             self.measurement_config['chpower_bandwidth_mhz'] = bandwidth_mhz if enabled else self.measurement_config['chpower_bandwidth_mhz']
             # Optional: Wait for operation complete
             # self.query(self.COMMANDS['opc'])
             return True
        else:
             return False

    def set_units(self, units: str = "DBM") -> bool:
        """
        Set the power measurement units.

        Args:
            units (str): Power units ("DBM", "W", "DBMV", "DBUV", "V" - check manual for exact valid units)

        Returns:
            bool: True if successful, False otherwise
        """
        valid_units = ["DBM", "W", "DBMV", "DBUV", "V"] # Confirm these are correct for MA24510A
        units_upper = units.upper()
        if units_upper not in valid_units:
            logger.error(f"Invalid units: {units}. Valid units are {valid_units}")
            return False

        success = self.write(self.COMMANDS['set_units'].format(units=units_upper))
        if success:
            logger.info(f"Power units set to {units_upper}")
            self.measurement_config['units'] = units_upper
            # Optional: Wait for operation complete
            # self.query(self.COMMANDS['opc'])
        return success

    def set_offset(self, offset_db: float) -> bool:
        """
        Set a power offset in dB.

        Args:
            offset_db (float): Offset value in dB (check manual for valid range)

        Returns:
            bool: True if successful, False otherwise
        """
        # Add range check if known from manual
        success = self.write(self.COMMANDS['set_offset'].format(offset_db=offset_db))
        if success:
            logger.info(f"Power offset set to {offset_db} dB")
            self.measurement_config['offset_db'] = offset_db
            # Optional: Wait for operation complete
            # self.query(self.COMMANDS['opc'])
        return success

    def zero_sensor(self) -> bool:
        """
        Perform a zero calibration on the sensor.
        NOTE: This might not be applicable or necessary for the Power Master itself,
              but could be relevant if controlling external sensors via it.
              Check the MA24510A manual for zeroing procedures. Assuming it's not needed for now.

        Returns:
            bool: True if successful (or not needed), False otherwise
        """
        logger.warning("Zeroing command called, but may not be applicable to MA24510A Power Master. Check manual.")
        # If zeroing is needed, uncomment and adapt the following:
        # logger.info("Performing zero calibration...")
        # if not self.write(self.COMMANDS['zero_sensor']):
        #     return False

        # # Wait for zero calibration to complete (adjust timeout as needed)
        # timeout_seconds = 30
        # start_time = time.time()
        # while time.time() - start_time < timeout_seconds:
        #     time.sleep(1)
        #     status = self.query(self.COMMANDS['check_zero_status'])
        #     logger.debug(f"Zero status check: {status}")
        #     if status == "0":  # 0 means zeroing is complete (confirm this code)
        #         logger.info("Zero calibration completed successfully")
        #         return True
        #     elif status is None:
        #          logger.error("Failed to query zero status during zeroing.")
        #          return False
        #     # Add checks for error status codes if they exist

        # logger.error(f"Zero calibration timed out after {timeout_seconds} seconds.")
        # return False
        return True # Returning True assuming it's not needed/applicable

    def measure_power(self, wait_time: float = 0.5) -> Optional[float]:
        """
        Measure power using the configured settings.

        Args:
            wait_time (float): Time to wait before querying for measurement in seconds.
                               This allows the instrument to acquire/average data.

        Returns:
            float: Power reading in configured units, or None if measurement failed
        """
        if not self.connected:
            logger.error("Not connected to instrument")
            return None

        try:
            # Allow time for measurement acquisition/averaging before fetching
            if wait_time > 0:
                 logger.debug(f"Waiting {wait_time}s before fetching power...")
                 time.sleep(wait_time)

            # Use the appropriate fetch command based on measurement mode
            if self.measurement_config['chpower']:
                fetch_cmd = self.COMMANDS['fetch_chpower']
                logger.debug(f"Fetching Channel Power using {fetch_cmd}")
                power_str = self.query(fetch_cmd)
                if power_str is None:
                    logger.error("Failed to fetch channel power.")
                    return None

                # Handle comma-separated response: take the first value
                try:
                    power_value_str = power_str.split(',')[0]
                    power_value = float(power_value_str)
                    logger.debug(f"Raw CHPower string: '{power_str}', Parsed value: {power_value}")
                except (IndexError, ValueError) as e_parse:
                    logger.error(f"Error parsing channel power reading '{power_str}': {e_parse}")
                    return None

            else:
                fetch_cmd = self.COMMANDS['fetch_power']
                logger.debug(f"Fetching CW Power using {fetch_cmd}")
                power_str = self.query(fetch_cmd)
                if power_str is None:
                    logger.error("Failed to fetch CW power.")
                    return None
                # Assume CW power returns a single value
                try:
                    power_value = float(power_str)
                    logger.debug(f"Raw CW Power string: '{power_str}', Parsed value: {power_value}")
                except ValueError as e_parse:
                     logger.error(f"Error converting power reading '{power_str}' to float: {e_parse}")
                     return None

            # Optional: Check for extremely large/small numbers which might indicate errors
            # (e.g., 9.9e37 is often an error code)
            if abs(power_value) > 1e30:
                 logger.warning(f"Measured power value {power_value} seems unrealistic, might indicate an error.")
                 # Decide whether to return None or the value

            return power_value

        except (ValueError, TypeError) as e: # Should be caught by inner try-except now
            logger.error(f"Unexpected error processing power reading: {e}")
            return None
        except Exception as e: # Catch any other unexpected errors
             logger.error(f"Unexpected error during power measurement: {e}")
             return None


    def measure_max_power(self, wait_time: float = 0.5) -> Optional[float]:
        """
        Measure maximum power using the configured settings.
        Note: Ensure ':FETCh:MAXimum?' is the correct command and check its return format.

        Args:
            wait_time (float): Time to wait for measurement to stabilize in seconds

        Returns:
            float: Maximum power reading in configured units, or None if measurement failed
        """
        if not self.connected:
            logger.error("Not connected to instrument")
            return None

        try:
            # Allow time for measurement acquisition before fetching
            if wait_time > 0:
                logger.debug(f"Waiting {wait_time}s before fetching max power...")
                time.sleep(wait_time)

            fetch_cmd = self.COMMANDS['fetch_max_power']
            logger.debug(f"Fetching Max Power using {fetch_cmd}")
            power_str = self.query(fetch_cmd)

            if power_str is None:
                logger.error("Failed to fetch max power.")
                return None

            # Assuming MAX returns a single value. Adjust if it returns multiple (e.g., power, freq)
            try:
                power_value = float(power_str)
                logger.debug(f"Raw Max Power string: '{power_str}', Parsed value: {power_value}")
                return power_value
            except ValueError as e_parse:
                logger.error(f"Error converting max power reading '{power_str}' to float: {e_parse}")
                return None

        except Exception as e: # Catch any other unexpected errors
             logger.error(f"Unexpected error during max power measurement: {e}")
             return None

    def get_current_config(self) -> Dict[str, Any]:
        """
        Get the current measurement configuration stored in the driver.
        Note: This does NOT query the instrument for its current settings.

        Returns:
            dict: Current measurement configuration stored by the driver
        """
        return self.measurement_config.copy()

    def configure_measurement(self, **kwargs) -> bool:
        """
        Configure multiple measurement parameters at once.

        Args:
            **kwargs: Configuration parameters to set
                - frequency_ghz (float): Measurement frequency in GHz
                - averaging (bool): Enable/disable averaging
                - averaging_count (int): Number of samples to average
                - chpower (bool): Enable/disable channel power measurement
                - chpower_bandwidth_mhz (float): Channel bandwidth in MHz
                - units (str): Power units
                - offset_db (float): Power offset in dB

        Returns:
            bool: True if all configurations were successful, False otherwise
        """
        logger.info("Configuring measurement...")
        success = True
        config_changed = False

        if 'frequency_ghz' in kwargs and kwargs['frequency_ghz'] != self.measurement_config['frequency_ghz']:
            if not self.set_frequency(kwargs['frequency_ghz']): success = False; logger.error("Failed during frequency set.")
            else: config_changed = True

        # Handle averaging enable/disable and count together
        avg_enabled = kwargs.get('averaging', self.measurement_config['averaging'])
        avg_count = kwargs.get('averaging_count', self.measurement_config['averaging_count'])
        if 'averaging' in kwargs or ('averaging_count' in kwargs and avg_enabled): # Only set count if enabled or being enabled
             if (self.measurement_config['averaging'] != avg_enabled or
                 (avg_enabled and self.measurement_config['averaging_count'] != avg_count)):
                  if not self.set_averaging(avg_enabled, avg_count): success = False; logger.error("Failed during averaging set.")
                  else: config_changed = True

        # Handle channel power enable/disable and bandwidth together
        chp_enabled = kwargs.get('chpower', self.measurement_config['chpower'])
        chp_bw = kwargs.get('chpower_bandwidth_mhz', self.measurement_config['chpower_bandwidth_mhz'])
        if 'chpower' in kwargs or ('chpower_bandwidth_mhz' in kwargs and chp_enabled):
            if (self.measurement_config['chpower'] != chp_enabled or
                (chp_enabled and self.measurement_config['chpower_bandwidth_mhz'] != chp_bw)):
                 if not self.set_channel_power(chp_enabled, chp_bw): success = False; logger.error("Failed during channel power set.")
                 else: config_changed = True

        if 'units' in kwargs and kwargs['units'].upper() != self.measurement_config['units']:
            if not self.set_units(kwargs['units']): success = False; logger.error("Failed during units set.")
            else: config_changed = True

        if 'offset_db' in kwargs and kwargs['offset_db'] != self.measurement_config['offset_db']:
            if not self.set_offset(kwargs['offset_db']): success = False; logger.error("Failed during offset set.")
            else: config_changed = True

        if config_changed and success:
             logger.info("Measurement configuration applied successfully.")
             # Optional: Wait for all operations to complete if needed
             # self.query(self.COMMANDS['opc'])
        elif not success:
             logger.error("One or more configuration steps failed.")
        else:
             logger.info("No configuration changes detected.")

        return success

    def get_instrument_info(self) -> Dict[str, str]:
        """
        Get information about the connected instrument by parsing the *IDN? response.

        Returns:
            dict: Information about the instrument (manufacturer, model, serial, firmware)
                  or {"error": ...} if failed.
        """
        if not self.connected:
            return {"error": "Not connected to instrument"}

        idn_to_parse = self.instrument_idn_string # Use stored IDN first
        if not idn_to_parse: # Fallback if not stored (e.g. reset cleared it and wasn't re-queried)
            logger.debug("Stored IDN not available, querying instrument for IDN again.")
            idn_to_parse = self.query(self.COMMANDS['idn'])

        if not idn_to_parse:
            return {"error": "Failed to get instrument identification", "idn": "N/A"}
        try:
            parts = idn_to_parse.split(',', 3)
            if len(parts) == 4:
                return {
                    "manufacturer": parts[0].strip(),
                    "model": parts[1].strip(),
                    "serial": parts[2].strip(),
                    "firmware": parts[3].strip(),
                    "idn": idn_to_parse # Include the full IDN string for reference
                }
            else:
                 logger.warning(f"Could not parse IDN string '{idn_to_parse}' into 4 parts.")
                 return {"idn": idn_to_parse, "error": "Could not parse IDN"}
        except Exception as e: # Catch any parsing error
            logger.error(f"Error parsing IDN string '{idn_to_parse}': {e}", exc_info=True)
            return {"idn": idn_to_parse, "error": f"Parsing failed: {e}"}

    def measure_power_statistics(self, num_samples: int = 10,
                                sample_interval: float = 0.1) -> Dict[str, Any]:
        """
        Measure power statistics over multiple samples.

        Args:
            num_samples (int): Number of samples to take
            sample_interval (float): Approximate time between start of samples in seconds.

        Returns:
            dict: Power statistics including min, max, mean, and all samples,
                  or {"error": ...} if failed.
        """
        if not self.connected:
            logger.error("Not connected to instrument for statistics measurement")
            return {"error": "Not connected to instrument"}

        samples = []
        logger.info(f"Starting power statistics measurement: {num_samples} samples, ~{sample_interval}s interval.")
        for i in range(num_samples):
            logger.debug(f"Taking sample {i+1}/{num_samples}")
            # Pass sample_interval as wait_time to ensure instrument has time before query
            power = self.measure_power(wait_time=sample_interval)
            if power is not None:
                samples.append(power)
                logger.debug(f"Sample {i+1} value: {power:.4f} {self.measurement_config['units']}")
            else:
                logger.warning(f"Sample {i+1}/{num_samples} failed.")
            # Note: The actual time between samples will be sample_interval + query_time + processing_time
            # If precise timing is needed, a different approach (e.g., instrument internal triggering/logging) is required.

        if not samples:
            logger.error("Failed to collect any valid samples for statistics.")
            return {"error": "Failed to collect any valid samples"}

        # Calculate statistics
        try:
            min_val = min(samples)
            max_val = max(samples)
            mean_val = sum(samples) / len(samples)
            stats_result = {
                "samples": samples,
                "min": min_val,
                "max": max_val,
                "mean": mean_val,
                "count": len(samples),
                "units": self.measurement_config['units']
            }
            logger.info(f"Statistics complete: Count={len(samples)}, Min={min_val:.3f}, Max={max_val:.3f}, Mean={mean_val:.3f} {self.measurement_config['units']}")
            return stats_result
        except Exception as e_stat:
             logger.error(f"Error calculating statistics: {e_stat}")
             return {"error": f"Statistics calculation failed: {e_stat}", "samples": samples}


# Factory function to create an instance of the MA24510A class
def create_power_master(visa_resource_name: Optional[str] = None,
                        auto_connect: bool = True, visa_timeout: int = 30000) -> MA24510A: # Added timeout pass-through
    """
    Create and optionally connect to an MA24510A Power Master.

    Args:
        visa_resource_name (str, optional): VISA resource name for the instrument
        auto_connect (bool): If True, attempts to automatically connect to the instrument
        visa_timeout (int): VISA timeout in milliseconds

    Returns:
        MA24510A: An instance of the MA24510A class
    """
    return MA24510A(auto_connect=auto_connect, visa_resource_name=visa_resource_name, visa_timeout=visa_timeout)


# Example usage
if __name__ == "__main__":
    # Enable more verbose logging for debugging if needed
    logger.setLevel(logging.DEBUG)

    # --- IMPORTANT ---
    # Replace with your actual VISA resource name if auto-detect fails or is not desired.
    # Format for TCPIP Socket is usually 'TCPIP0::[IP_Address]::[Port]::SOCKET'
    # Check Anritsu documentation or connection utility for the correct port (59001 seems plausible)
    # Example: visa_resource_name = "TCPIP0::192.168.1.100::59001::SOCKET"
    # Or for USB: visa_resource_name = "USB0::0x0B5B::0x001F::123456::INSTR" (VendorID, ProductID, Serial - find using VISA utility)
    visa_resource_name = "TCPIP0::127.0.0.1::59001::SOCKET" # Using loopback for simulation/testing if applicable
    # visa_resource_name = None # To attempt auto-detection

    print("\n--- Example 1: Basic Measurement ---")
    # Use default timeout (now 30s)
    with create_power_master(visa_resource_name=visa_resource_name) as power_master:

        if power_master.connected:
            # Configure for 28 GHz measurement with channel power
            # --- Note: Make sure MA24510A supports channel power mode ---
            # Consulting the OCR'd manual index (page 9):
            # 12-8 Continuous Mode Settings -> Measurement – CW/Channel Power -> Yes
            # 12-12 Channel Monitor Mode Settings -> Measurement – CW/Channel Mode -> Yes
            # It seems Channel Power is supported.
            print("Configuring for 28 GHz Channel Power...")
            config_ok = power_master.configure_measurement(
                frequency_ghz=28.0,
                averaging=True,        # Enable averaging
                averaging_count=32,    # Set average count
                chpower=True,          # Enable Channel Power mode
                chpower_bandwidth_mhz=100.0, # Set bandwidth
                units="DBM"            # Set units
            )

            if config_ok:
                print("Configuration successful.")
                # Take a measurement
                power_dbm = power_master.measure_power(wait_time=1.0) # Increased wait time after config+avg
                if power_dbm is not None:
                    print(f"Measured Power: {power_dbm:.2f} dBm")
                else:
                    print("Failed to measure power.")
            else:
                print("Failed to configure measurement.")

            # Check for errors after operation
            final_errors = power_master.check_errors()
            if final_errors:
                 print(f"Instrument Errors (Example 1): {final_errors}")
        else:
            print("Failed to connect in Example 1.")

    print("\n--- Example 2: Advanced Measurement ---")
    # Increase timeout specifically for this potentially long test
    power_master = create_power_master(visa_resource_name=visa_resource_name, visa_timeout=45000)

    if power_master.connected:
        try:
            # Print instrument info
            info = power_master.get_instrument_info()
            print(f"Connected to: {info.get('model', 'Unknown')} - SN: {info.get('serial', 'Unknown')}")

            # Reset the instrument
            print("Resetting instrument...")
            if not power_master.reset():
                 print("WARNING: Reset command failed to send.")
            else:
                 print("Instrument reset. Waiting...")
                 # Already includes a wait in reset()

            print("Configuring for 3.5 GHz, 100MHz BW Channel Power with Averaging...")
            # Configure for 5G NR measurement example
            config_ok = power_master.configure_measurement(
                frequency_ghz=3.5,  # 3.5 GHz (mid-band 5G)
                averaging=True,
                averaging_count=64, # Increased averaging
                chpower=True,
                chpower_bandwidth_mhz=100.0,  # 100 MHz bandwidth
                units="DBM",
                offset_db=0.0  # Compensate for cable loss if needed
            )

            # Check errors after configuration
            config_errors = power_master.check_errors()
            if config_errors:
                 print(f"Instrument Errors after config (Example 2): {config_errors}")


            if config_ok:
                print("Configuration successful.")
                # Take multiple measurements and calculate statistics
                print("Measuring power statistics...")
                # Use a longer sample interval due to averaging
                stats = power_master.measure_power_statistics(num_samples=5, sample_interval=1.5)

                # Check if statistics calculation was successful
                if 'error' in stats:
                     print(f"Error during statistics measurement: {stats['error']}")
                else:
                     # Safely print stats
                     print(f"Min Power: {stats.get('min', float('nan')):.2f} dBm")
                     print(f"Max Power: {stats.get('max', float('nan')):.2f} dBm")
                     print(f"Mean Power: {stats.get('mean', float('nan')):.2f} dBm")
                     print(f"Samples Collected: {stats.get('count', 0)}")
                     print(f"Units: {stats.get('units', 'N/A')}")
                     # print(f"Raw Samples: {stats.get('samples', [])}") # Optional: print raw data
            else:
                 print("Failed to configure measurement for statistics.")

            # Check for any final errors
            final_errors = power_master.check_errors()
            if final_errors:
                print("Instrument reported errors at end of Example 2:")
                for error in final_errors:
                    print(f"  {error}")

        except Exception as e:
             logger.exception("An unexpected error occurred in Example 2") # Log full traceback
             print(f"An unexpected error occurred: {e}")
        finally:
            # Disconnect is handled by __exit__ if using 'with', but good practice here too
            power_master.disconnect()
    else:
        print("Failed to connect to MA24510A for Example 2.")
        print("Please check connection and VISA resource name.")

# --- END OF FILE Anritsu_MA24510A_V4.py ---