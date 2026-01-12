"""
LMS-163 Digital Signal Generator Controller

This module provides a clean, object-oriented interface for controlling
Vaunix LMS-163 Digital Signal Generator devices.

Usage:
    from lms163_controller import LMS163Controller
    
    # Create a controller instance
    controller = LMS163Controller()
    
    # List available devices
    devices = controller.get_available_devices()
    
    # Connect to a specific device (first one by default)
    signal_gen = controller.connect_device()
    
    # Configure and use the device
    signal_gen.set_frequency(2400)  # 2400 MHz
    signal_gen.set_power(-10)       # -10 dBm
    signal_gen.rf_on()              # Turn on RF output
    
    # When finished
    signal_gen.close()
"""

from ctypes import cdll, c_int
import logging
import os
import platform

# Set up logging
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )
logger = logging.getLogger("LMS163Controller")


class LMSError(Exception):
    """Custom exception for LMS device errors"""
    ERROR_CODES = {
        0: "No error",
        1: "Device not initialized",
        2: "Device already initialized",
        3: "Device not present",
        4: "Device not open",
        5: "Invalid parameter",
        6: "Invalid device",
        7: "Invalid device driver",
        8: "Operation not supported",
        9: "Device failed",
        10: "Device in use",
        11: "Device not found",
        12: "Device not available",
        13: "Device not responding",
        14: "Device not ready",
        15: "Device not programmed",
        16: "Device not enabled",
        17: "Device busy",
        18: "Device not connected",
        19: "Device not calibrated",
        20: "Device not licensed",
        21: "Device not authorized"
    }
    
    def __init__(self, code, function_name):
        self.code = code
        self.function_name = function_name
        message = f"{function_name} returned error {code}"
        if code in self.ERROR_CODES:
            message += f": {self.ERROR_CODES[code]}"
        super().__init__(message)


class LMS163Device:
    """Class representing a single LMS-163 device"""
    
    def __init__(self, device_id, dll):
        """Initialize a device with the given ID and DLL reference"""
        self.device_id = device_id
        self.dll = dll
        self.is_initialized = False
        self.is_rf_on = False
        self._init_device()
        
        # Cache device capabilities
        self._min_freq_mhz = self._get_min_freq_mhz()
        self._max_freq_mhz = self._get_max_freq_mhz()
        self._min_power_dbm = self._get_min_power_dbm()
        self._max_power_dbm = self._get_max_power_dbm()
        
        logger.info(f"Device ID: {self.device_id}, " +
                   f"Frequency range: {self._min_freq_mhz}-{self._max_freq_mhz} MHz, " +
                   f"Power range: {self._min_power_dbm}-{self._max_power_dbm} dBm")
    
    def _init_device(self):
        """Initialize the device for operation"""
        result = self.dll.fnLMS_InitDevice(self.device_id)
        if result != 0:
            raise LMSError(result, "InitDevice")
        self.is_initialized = True
        logger.info(f"Device {self.device_id} initialized")
    
    def _get_min_freq_mhz(self):
        """Get the minimum frequency in MHz"""
        min_freq = self.dll.fnLMS_GetMinFreq(self.device_id)
        return min_freq / 100000  # Convert to MHz
    
    def _get_max_freq_mhz(self):
        """Get the maximum frequency in MHz"""
        max_freq = self.dll.fnLMS_GetMaxFreq(self.device_id)
        return max_freq / 100000  # Convert to MHz
    
    def _get_min_power_dbm(self):
        """Get the minimum power in dBm"""
        min_power = self.dll.fnLMS_GetMinPwr(self.device_id)
        return min_power / 4  # Convert to dBm
    
    def _get_max_power_dbm(self):
        """Get the maximum power in dBm"""
        max_power = self.dll.fnLMS_GetMaxPwr(self.device_id)
        return max_power / 4  # Convert to dBm
    
    def get_serial_number(self):
        """Get the device serial number"""
        return self.dll.fnLMS_GetSerialNumber(self.device_id)
    
    def set_frequency(self, frequency_mhz):
        """
        Set the output frequency in MHz
        
        Args:
            frequency_mhz (float): Desired frequency in MHz
        
        Returns:
            float: The actual set frequency in MHz
        
        Raises:
            ValueError: If frequency is outside the valid range
            LMSError: If the device operation fails
        """
        if not self.is_initialized:
            raise LMSError(1, "Device not initialized")
            
        if frequency_mhz < self._min_freq_mhz or frequency_mhz > self._max_freq_mhz:
            raise ValueError(f"Frequency must be between {self._min_freq_mhz} and {self._max_freq_mhz} MHz")
        
        # Convert MHz to device units (0.01 Hz)
        frequency_device_units = int(frequency_mhz * 1000000 / 10)
        
        result = self.dll.fnLMS_SetFrequency(self.device_id, frequency_device_units)
        if result != 0:
            raise LMSError(result, "SetFrequency")
        
        # Read back the actual frequency set
        actual_freq_mhz = self.get_frequency()
        logger.info(f"Frequency set to {actual_freq_mhz} MHz")
        return actual_freq_mhz
    
    def get_frequency(self):
        """
        Get the current output frequency in MHz
        
        Returns:
            float: The current frequency in MHz
        """
        if not self.is_initialized:
            raise LMSError(1, "Device not initialized")
            
        result = self.dll.fnLMS_GetFrequency(self.device_id)
        # Convert from device units (0.01 Hz) to MHz
        return (result * 10) / 1000000
    
    def set_power(self, power_dbm):
        """
        Set the output power level in dBm
        
        Args:
            power_dbm (float): Desired power in dBm
        
        Returns:
            float: The actual set power in dBm
        
        Raises:
            ValueError: If power is outside the valid range
            LMSError: If the device operation fails
        """
        if not self.is_initialized:
            raise LMSError(1, "Device not initialized")
            
        if power_dbm < self._min_power_dbm or power_dbm > self._max_power_dbm:
            raise ValueError(f"Power must be between {self._min_power_dbm} and {self._max_power_dbm} dBm")
        
        # Convert dBm to device units (0.25 dBm steps)
        power_device_units = int(power_dbm / 0.25)
        
        result = self.dll.fnLMS_SetPowerLevel(self.device_id, power_device_units)
        if result != 0:
            raise LMSError(result, "SetPowerLevel")
        
        # Read back the actual power set
        actual_power_dbm = self.get_power()
        logger.info(f"Power set to {actual_power_dbm} dBm")
        return actual_power_dbm
    
      
    def get_power(self):
        """
        Get the current output power level in dBm
        
        Returns:
            float: The current power in dBm
        """
        if not self.is_initialized:
            raise LMSError(1, "Device not initialized")
            
        # Use fnLMS_GetAbsPowerLevel to get absolute power in 0.25 dB units
        result = self.dll.fnLMS_GetAbsPowerLevel(self.device_id)
        # Convert from device units (0.25 dBm steps) to dBm
        return result * 0.25
      
    # Alternative get_power() if fnLMS_GetAbsPowerLevel is not used/available
    # def get_power(self):
    #     """
    #     Get the current output power level in dBm
        
    #     Returns:
    #         float: The current power in dBm
    #     """
    #     if not self.is_initialized:
    #         raise LMSError(1, "Device not initialized")
            
    #     # fnLMS_GetPowerLevel returns power relative to max power, in 0.25 dB units
    #     # (MaxPower_dBm - ActualPower_dBm) / 0.25 = result_from_dll
    #     # MaxPower_dBm - ActualPower_dBm = result_from_dll * 0.25
    #     # ActualPower_dBm = MaxPower_dBm - (result_from_dll * 0.25)
    #     result_from_dll = self.dll.fnLMS_GetPowerLevel(self.device_id)
    #     power_offset_from_max_db = result_from_dll * 0.25
    #     actual_power_dbm = self._max_power_dbm - power_offset_from_max_db
    #     return actual_power_dbm

    
    
    
    def rf_on(self):
        """Turn on the RF output"""
        if not self.is_initialized:
            raise LMSError(1, "Device not initialized")
            
        result = self.dll.fnLMS_SetRFOn(self.device_id, 1)
        if result != 0:
            raise LMSError(result, "SetRFOn")
        self.is_rf_on = True
        logger.info("RF output enabled")
    
    def rf_off(self):
        """Turn off the RF output"""
        if not self.is_initialized:
            raise LMSError(1, "Device not initialized")
            
        result = self.dll.fnLMS_SetRFOn(self.device_id, 0)
        if result != 0:
            raise LMSError(result, "SetRFOn")
        self.is_rf_on = False
        logger.info("RF output disabled")
    
    def close(self):
        """Close the device when finished"""
        if self.is_initialized:
            result = self.dll.fnLMS_CloseDevice(self.device_id)
            if result != 0:
                raise LMSError(result, "CloseDevice")
            self.is_initialized = False
            logger.info(f"Device {self.device_id} closed")
    
    def __del__(self):
        """Destructor to ensure device is closed"""
        try:
            self.close()
        except:
            pass


class LMS163Controller:
    """Controller class for managing LMS-163 devices"""
    
    def __init__(self, test_mode=False):
        """
        Initialize the controller
        
        Args:
            test_mode (bool): If True, use test mode instead of actual devices
        """
        self.dll = self._load_library()
        self.dll.fnLMS_SetTestMode(test_mode)
        self.test_mode = test_mode
        logger.info(f"LMS163Controller initialized (test mode: {test_mode})")
    
    def _load_library(self):
        """Load the appropriate DLL based on the operating system"""
        system = platform.system()
        
        if system == "Windows":
            try:
                return cdll.vnx_fmsynth
            except OSError:

                # Get the path to the folder containing the running script
                script_dir = os.path.dirname(os.path.abspath(__file__))
                local_dll_path = os.path.join(script_dir, "vnx_fmsynth.dll")
                # Try common installation paths
                paths = [
                    local_dll_path,
                    "C:\\Program Files\\Vaunix\\LMS\\vnx_fmsynth.dll",
                    "C:\\Program Files (x86)\\Vaunix\\LMS\\vnx_fmsynth.dll"
                ]
                for path in paths:
                    if os.path.exists(path):
                        return cdll.LoadLibrary(path)
                raise ImportError("Could not find vnx_fmsynth.dll. Please install the Vaunix LMS driver.")
        
        elif system == "Linux":
            try:
                return cdll.LoadLibrary("libvnx_fmsynth.so")
            except OSError:
                raise ImportError("Could not find libvnx_fmsynth.so. Please install the Vaunix LMS driver.")
        
        else:
            raise ImportError(f"Unsupported operating system: {system}")
    
    def get_available_devices(self):
        """
        Get a list of available device IDs
        
        Returns:
            list: List of device IDs
        """
        # This array will hold the list of device handles
        device_id_array = c_int * 20
        devices = device_id_array()
        
        # GetNumDevices will determine how many LMS devices are available
        num_devices = self.dll.fnLMS_GetNumDevices()
        logger.info(f"Found {num_devices} device(s)")
        
        if num_devices == 0:
            return []
        
        # GetDevInfo generates a list, stored in the devices array, of
        # every available LMS device attached to the system
        dev_info = self.dll.fnLMS_GetDevInfo(devices)
        logger.info(f"GetDevInfo returned {dev_info} device(s)")
        
        # Convert to a Python list
        return [devices[i] for i in range(dev_info)]
    
    def connect_device(self, device_index=0):
        """
        Connect to a specific device by index
        
        Args:
            device_index (int): Index of the device to connect to (default: 0, first device)
        
        Returns:
            LMS163Device: Connected device object
        
        Raises:
            IndexError: If no devices are available or the index is out of range
        """
        devices = self.get_available_devices()
        
        if not devices:
            raise IndexError("No LMS devices found")
        
        if device_index >= len(devices):
            raise IndexError(f"Device index {device_index} out of range. Only {len(devices)} devices available.")
        
        device_id = devices[device_index]
        return LMS163Device(device_id, self.dll)


# Example usage
def example_usage():
    """Example of how to use the LMS163Controller"""
    try:
        # Create a controller instance
        controller = LMS163Controller()
        
        # List available devices
        devices = controller.get_available_devices()
        if not devices:
            print("No LMS devices found.")
            return
        
        # Connect to the first device
        signal_gen = controller.connect_device()
        
        # Print device information
        serial_number = signal_gen.get_serial_number()
        print(f"Connected to device with serial number: {serial_number}")
        print(f"Frequency range: {signal_gen._min_freq_mhz}-{signal_gen._max_freq_mhz} MHz")
        print(f"Power range: {signal_gen._min_power_dbm}-{signal_gen._max_power_dbm} dBm")
        
        # Set frequency to 2400 MHz (2.4 GHz)
        freq = 8400.0
        actual_freq = signal_gen.set_frequency(freq)
        print(f"Set frequency to {actual_freq} MHz")
        
        # Set power to -10 dBm
        power = -10.0
        actual_power = signal_gen.set_power(power)
        print(f"Set power to {actual_power} dBm")
        
        # Turn on RF output
        signal_gen.rf_on()
        print("RF output enabled")
        
        # Read current settings
        current_freq = signal_gen.get_frequency()
        current_power = signal_gen.get_power()
        print(f"Current frequency: {current_freq} MHz")
        print(f"Current power: {current_power} dBm")
        
        # Turn off RF output
        signal_gen.rf_off()
        print("RF output disabled")
        
        # Close the device when finished
        signal_gen.close()
        print("Device closed")
        
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    example_usage()
