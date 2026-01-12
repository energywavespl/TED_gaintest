import pyvisa
import time

def connect_ma24510a(visa_resource_name=None):
    """
    Connects to the Anritsu MA24510A Power Master via VISA.

    Args:
        visa_resource_name (str, optional): VISA resource string for the MA24510A.
                                             If None, it will try to find a suitable resource automatically.
                                             Defaults to None.

    Returns:
        pyvisa.resources.MessageBasedResource: VISA instrument object if connection is successful,
                                                None otherwise.
    """
    rm = pyvisa.ResourceManager()
    try:
        if visa_resource_name:
            instrument = rm.open_resource(visa_resource_name)
            print(f"Connected to instrument at {visa_resource_name}")
        else:
            resources = rm.list_resources()
            ma24510a_resource = None
            for resource in resources:
                if "TCPIP" in resource and "INSTR" in resource: # Heuristic to find network instruments, may need adjustment
                    try:
                        instrument_probe = rm.open_resource(resource)
                        idn_response = instrument_probe.query("*IDN?\n")
                        if "Anritsu" in idn_response and "MA245" in idn_response:  # Check for Anritsu and MA245 series
                            ma24510a_resource = resource
                            instrument_probe.close()
                            break
                        instrument_probe.close()
                    except Exception:
                        continue  # Ignore resources that fail to identify

            if ma24510a_resource:
                instrument = rm.open_resource(ma24510a_resource)
                print(f"Auto-connected to instrument at {ma24510a_resource}")
            else:
                print("MA24510A not found automatically. Please provide VISA resource name.")
                return None
        instrument.timeout = 5000  # Set timeout to 5 seconds
        instrument.clear() # Clear any existing status
        return instrument
    except pyvisa.VisaIOError as e:
        print(f"Error connecting to MA24510A: {e}")
        return None

def configure_measurement(instrument, frequency_ghz=1.0):
    """
    Configures the MA24510A for basic power measurement in Continuous Average mode.

    Args:
        instrument (pyvisa.resources.MessageBasedResource): VISA instrument object.
        frequency_ghz (float, optional): Measurement frequency in GHz. Defaults to 1.0 GHz.
    """
    try:
        instrument.read_termination = "\n"
        
        IDNw = instrument.query("*IDN?")
        print(f"IDN: {IDNw} ")
        instrument.write(":INITiate:CONTinuous ON\n") # Ensure continuous mode is on
        instrument.write(f":SENSe:FREQuency:CENTer {frequency_ghz}GHZ\n") # Set frequency
        instrument.write(":SENSe:AVERage:STATe OFF\n") # Disable auto averaging for simplicity in example, enable if needed
        instrument.write(":SENSe:CHPower:STATe ON\n") # Enable Channel Power Measurement (can be CW Max as well)
        print(f"Measurement configured for {frequency_ghz} GHz.")
    except pyvisa.VisaIOError as e:
        print(f"Error configuring instrument: {e}")


def measure_power(instrument):
    """
    Measures power using the configured settings on the MA24510A.

    Args:
        instrument (pyvisa.resources.MessageBasedResource): VISA instrument object.

    Returns:
        float: Power reading in dBm if successful, None otherwise.
    """
    try:
        power_str = instrument.query(":FETCh:POWer?")
        power_value = float(power_str.strip()) # Remove whitespace and convert to float
        return power_value
    except pyvisa.VisaIOError as e:
        print(f"Error during measurement: {e}")
        return None
    except ValueError:
        print(f"Error: Could not convert power reading to float. Raw response: {power_str}")
        return None


def disconnect_ma24510a(instrument):
    """
    Disconnects from the MA24510A Power Master.

    Args:
        instrument (pyvisa.resources.MessageBasedResource): VISA instrument object.
    """
    if instrument:
        instrument.close()
        print("Disconnected from MA24510A.")


if __name__ == "__main__":
    # --- Example Usage ---
    visa_address = None # Replace with your instrument's VISA resource string if auto-detection fails, e.g., "TCPIP0::192.168.1.100::INSTR"
    visa_address = "TCPIP0::127.0.0.1::59001::SOCKET"

    ma24510a = connect_ma24510a(visa_address)

    if ma24510a:
        configure_measurement(ma24510a, frequency_ghz=2.4) # Configure for 2.4 GHz measurement


        time.sleep(1) # Allow time for configuration to take effect and reading to stabilize

        power_dbm = measure_power(ma24510a)

        if power_dbm is not None:
            print(f"Measured Power: {power_dbm:.2f} dBm") # Print power reading with 2 decimal places

        disconnect_ma24510a(ma24510a)
    else:
        print("Failed to connect to MA24510A. Please check connection and VISA resource name.")