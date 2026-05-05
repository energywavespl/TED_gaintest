"""
MeasurementWorker — Background worker for hardware measurement loops.

This worker runs in a QThread to prevent blocking the main GUI thread
during time.sleep() and synchronous VISA I/O operations.
"""

import time
import random
import logging
import threading
from typing import Optional, List, Dict, Any

from PySide6.QtCore import QObject, Signal

from src.instruments.Vaunix_LMS163_DSG import LMSTimeoutError

logger = logging.getLogger("MeasurementWorker")

MAX_HW_RETRIES = 2  # Number of reconnect attempts before giving up


class MeasurementWorker(QObject):
    """
    Executes measurement loops (Golden, Silver, Antenna/DUT) in a background thread.
    
    Communicates results back to the main thread via Qt signals.
    Abort is handled via a threading.Event for thread-safe cancellation.
    """

    # --- Signals ---
    # Emitted for each frequency point completed
    progress_updated = Signal(int, object)  # (freq_index, step_data_dict)
    # Emitted when the entire measurement loop finishes successfully
    measurement_completed = Signal(str, object)  # (measurement_type, results_list)
    # Emitted on hardware/measurement error
    error_occurred = Signal(str, str)  # (operation_description, error_message)
    # Emitted when the worker is fully done (for thread cleanup)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._abort_event = threading.Event()

        # Hardware references (set before starting)
        self.signal_generator_device = None
        self.power_meter = None

        # Configuration (set before starting)
        self.hardware_ready: bool = False
        self.hardware_demo_mode: bool = True
        self.instrument_settling_time_s: float = 1.0
        self.transmitter_power: float = -20.0
        self.multiplexing_factor: int = 1

        # Measurement parameters (set before starting via configure_* methods)
        self._measurement_type: str = ""  # "golden", "silver", "antenna"
        self._port_name: str = ""
        self._serial_number: str = ""
        self._limits_for_port: List = []
        self._golden_meas_list: List = []

    def request_abort(self):
        """Thread-safe abort request. Can be called from the main thread."""
        logger.info("MeasurementWorker: Abort requested.")
        self._abort_event.set()

    def _is_aborted(self) -> bool:
        return self._abort_event.is_set()

    def _ensure_rf_off(self):
        """Safely turn off RF output."""
        try:
            if (self.signal_generator_device and 
                    hasattr(self.signal_generator_device, 'is_rf_on') and
                    self.signal_generator_device.is_rf_on):
                self.signal_generator_device.rf_off()
                logger.info("  Gen RF OFF (worker)")
        except Exception as e:
            logger.error(f"Error turning RF off in worker: {e}")

    def _do_hardware_step(self, generator_freq_mhz: float, target_freq_ghz: float) -> float:
        """Execute one hardware measurement cycle (set freq/power, RF on, measure, RF off).

        Automatically retries up to MAX_HW_RETRIES times on LMSTimeoutError
        by reconnecting the signal generator.

        Returns the measured power in dBm.
        Raises Exception if all retries are exhausted or a non-timeout error occurs.
        """
        last_error = None
        for attempt in range(1 + MAX_HW_RETRIES):
            try:
                if attempt > 0:
                    logger.warning(f"  Retry attempt {attempt}/{MAX_HW_RETRIES} after reconnect")

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

                measured = self.power_meter.measure_power(wait_time=0.5)
                return measured

            except LMSTimeoutError as e:
                last_error = e
                self._ensure_rf_off()
                logger.error(f"  Hardware timeout: {e}")
                if attempt < MAX_HW_RETRIES:
                    logger.info("  Attempting signal generator reconnect...")
                    if self.signal_generator_device.reconnect():
                        logger.info("  Reconnect successful, retrying measurement step")
                        continue
                    else:
                        raise Exception(f"Signal generator reconnect failed after timeout: {e}")
                else:
                    raise Exception(
                        f"Signal generator not responding after {MAX_HW_RETRIES} reconnect attempts: {e}"
                    )
            finally:
                self._ensure_rf_off()

    # --- Configuration methods (call from main thread BEFORE starting) ---

    def configure_golden(self, port_name: str, limits_for_port: List,
                         signal_generator, power_meter,
                         hardware_ready: bool, hardware_demo_mode: bool,
                         instrument_settling_time_s: float,
                         transmitter_power: float, multiplexing_factor: int):
        self._measurement_type = "golden"
        self._port_name = port_name
        self._limits_for_port = limits_for_port
        self.signal_generator_device = signal_generator
        self.power_meter = power_meter
        self.hardware_ready = hardware_ready
        self.hardware_demo_mode = hardware_demo_mode
        self.instrument_settling_time_s = instrument_settling_time_s
        self.transmitter_power = transmitter_power
        self.multiplexing_factor = multiplexing_factor

    def configure_silver(self, port_name: str, limits_for_port: List,
                         golden_meas_list: List,
                         signal_generator, power_meter,
                         hardware_ready: bool, hardware_demo_mode: bool,
                         instrument_settling_time_s: float,
                         transmitter_power: float, multiplexing_factor: int):
        self._measurement_type = "silver"
        self._port_name = port_name
        self._limits_for_port = limits_for_port
        self._golden_meas_list = golden_meas_list
        self.signal_generator_device = signal_generator
        self.power_meter = power_meter
        self.hardware_ready = hardware_ready
        self.hardware_demo_mode = hardware_demo_mode
        self.instrument_settling_time_s = instrument_settling_time_s
        self.transmitter_power = transmitter_power
        self.multiplexing_factor = multiplexing_factor

    def configure_antenna(self, port_name: str, serial_number: str,
                          limits_for_port: List, golden_meas_list: List,
                          signal_generator, power_meter,
                          hardware_ready: bool, hardware_demo_mode: bool,
                          instrument_settling_time_s: float,
                          transmitter_power: float, multiplexing_factor: int):
        self._measurement_type = "antenna"
        self._port_name = port_name
        self._serial_number = serial_number
        self._limits_for_port = limits_for_port
        self._golden_meas_list = golden_meas_list
        self.signal_generator_device = signal_generator
        self.power_meter = power_meter
        self.hardware_ready = hardware_ready
        self.hardware_demo_mode = hardware_demo_mode
        self.instrument_settling_time_s = instrument_settling_time_s
        self.transmitter_power = transmitter_power
        self.multiplexing_factor = multiplexing_factor

    # --- Main entry point (connected to QThread.started) ---

    def run(self):
        """Dispatches to the correct measurement loop based on configured type."""
        self._abort_event.clear()
        try:
            if self._measurement_type == "golden":
                self._run_golden()
            elif self._measurement_type == "silver":
                self._run_silver()
            elif self._measurement_type == "antenna":
                self._run_antenna()
            else:
                logger.error(f"MeasurementWorker: Unknown measurement type '{self._measurement_type}'")
                self.error_occurred.emit("Configuration", f"Unknown measurement type: {self._measurement_type}")
        except Exception as e:
            logger.error(f"MeasurementWorker: Unhandled exception in run(): {e}", exc_info=True)
            self.error_occurred.emit("Measurement Loop", str(e))
        finally:
            self._ensure_rf_off()
            self.finished.emit()

    # --- Golden Measurement Loop ---

    def _run_golden(self):
        port_name = self._port_name
        limits = self._limits_for_port
        num_points = len(limits)
        results = []

        for idx in range(num_points):
            if self._is_aborted():
                logger.info(f"Golden measurement aborted at index {idx}/{num_points}")
                return

            target_freq_ghz = limits[idx][0]
            measured_power_dbm: Optional[float] = None

            if not self.hardware_ready:
                # Simulation
                logger.debug(f"Golden (Sim) Freq Idx: {idx}, Target Freq: {target_freq_ghz} GHz")
                measured_power_dbm = -1.5 + random.uniform(-0.2, 0.2) - (idx * (0.5 / max(1, num_points)))
                time.sleep(0.05)  # Pace simulation for visual progress updates
            else:
                # Real hardware
                logger.debug(f"Golden (HW) Freq Idx: {idx}, Target Freq: {target_freq_ghz} GHz")
                try:
                    generator_freq_mhz = (target_freq_ghz * 1000) / self.multiplexing_factor
                    measured_power_dbm = self._do_hardware_step(generator_freq_mhz, target_freq_ghz)
                except Exception as e:
                    self.error_occurred.emit("Golden Measurement Step", str(e))
                    return

                if measured_power_dbm is None:
                    self.error_occurred.emit("Golden Measurement (No PM Value)", "Power Meter returned no value")
                    return

            step_data = {"Antenna_Measurement": measured_power_dbm}
            results.append(step_data)

            self.progress_updated.emit(idx, step_data)

        # All points done
        self.measurement_completed.emit("golden", results)

    # --- Silver Measurement Loop ---

    def _run_silver(self):
        port_name = self._port_name
        limits = self._limits_for_port
        golden_meas = self._golden_meas_list
        num_points = len(limits)
        results = []

        for idx in range(num_points):
            if self._is_aborted():
                logger.info(f"Silver measurement aborted at index {idx}/{num_points}")
                return

            current_limit_data = limits[idx]
            target_freq_ghz = current_limit_data[0]
            spec_gain_golden_val = current_limit_data[3]  # Spec_Gain_Horn
            silver_gain_horn_target = current_limit_data[4]  # Target gain for Silver sample
            silver_tolerance_pm = current_limit_data[5]  # Tolerance

            golden_meas_dbm_val = golden_meas[idx]
            if golden_meas_dbm_val is None:
                self.error_occurred.emit(
                    "Silver Measurement (Missing Golden Data)",
                    f"Missing Golden measurement data point at Freq Index {idx}"
                )
                return

            instrument_reading_for_silver_dbm: Optional[float] = None
            actual_measured_silver_gain: Optional[float] = None

            if not self.hardware_ready:
                # Simulation
                logger.debug(f"Silver (Sim) Freq Idx: {idx}, Target Freq: {target_freq_ghz} GHz")
                fail_silver_point_prob = 0.02
                simulated_silver_deviation = random.uniform(-silver_tolerance_pm * 0.8, silver_tolerance_pm * 0.8)
                if random.random() < fail_silver_point_prob:
                    simulated_silver_deviation = silver_tolerance_pm * random.choice([-1.2, 1.2])
                actual_measured_silver_gain = silver_gain_horn_target + simulated_silver_deviation
                instrument_reading_for_silver_dbm = golden_meas_dbm_val + (actual_measured_silver_gain - spec_gain_golden_val)
                time.sleep(0.05)  # Pace simulation for visual progress updates
            else:
                # Real hardware
                logger.debug(f"Silver (HW) Freq Idx: {idx}, Target Freq: {target_freq_ghz} GHz")
                try:
                    generator_freq_mhz = (target_freq_ghz * 1000) / self.multiplexing_factor
                    instrument_reading_for_silver_dbm = self._do_hardware_step(generator_freq_mhz, target_freq_ghz)

                    if instrument_reading_for_silver_dbm is None:
                        raise Exception("Power meter returned None for Silver measurement.")

                    actual_measured_silver_gain = spec_gain_golden_val + (instrument_reading_for_silver_dbm - golden_meas_dbm_val)

                except Exception as e:
                    self.error_occurred.emit("Silver Measurement Step", str(e))
                    return

            # Compute pass/fail for silver
            silver_gain_validation_ll = silver_gain_horn_target - silver_tolerance_pm
            silver_gain_validation_ul = silver_gain_horn_target + silver_tolerance_pm
            pass_status = "FAIL"
            if actual_measured_silver_gain is not None:
                pass_status = "PASS" if silver_gain_validation_ll <= actual_measured_silver_gain <= silver_gain_validation_ul else "FAIL"
                # Anomaly detection: warn if silver gain is negative (unexpected)
                if actual_measured_silver_gain < 0:
                    logger.warning(
                        f"ANOMALY: Negative Silver gain {actual_measured_silver_gain:.2f} dBi at {target_freq_ghz} GHz. "
                        f"P_silver={instrument_reading_for_silver_dbm:.2f} dBm, P_golden={golden_meas_dbm_val:.2f} dBm, "
                        f"Spec_Gain_Golden={spec_gain_golden_val:.2f} dBi, "
                        f"Delta={instrument_reading_for_silver_dbm - golden_meas_dbm_val:.2f} dB"
                    )

            step_data = {
                "Frequency_GHz": target_freq_ghz,
                "Antenna_Gain": actual_measured_silver_gain if actual_measured_silver_gain is not None else float('nan'),
                "Lower_Limit": silver_gain_validation_ll,
                "Upper_Limit": silver_gain_validation_ul,
                "Pass": pass_status,
                "Antenna_Measurement": instrument_reading_for_silver_dbm if instrument_reading_for_silver_dbm is not None else float('nan'),
                "Golden_Measurement": golden_meas_dbm_val,
                "Spec_Gain_Displayed": silver_gain_horn_target
            }
            results.append(step_data)

            self.progress_updated.emit(idx, step_data)

        # All points done
        self.measurement_completed.emit("silver", results)

    # --- Antenna (DUT) Measurement Loop ---

    def _run_antenna(self):
        port_name = self._port_name
        serial_number = self._serial_number
        limits = self._limits_for_port
        golden_meas = self._golden_meas_list
        num_points = len(limits)
        results = []

        for idx in range(num_points):
            if self._is_aborted():
                logger.info(f"DUT measurement aborted at index {idx}/{num_points}")
                return

            current_limit_data = limits[idx]
            target_freq_ghz_val = current_limit_data[0]
            dut_lower_limit = current_limit_data[1]
            dut_upper_limit = current_limit_data[2]
            spec_gain_golden_sample = current_limit_data[3]

            golden_sample_power_reading_dbm = golden_meas[idx]
            if golden_sample_power_reading_dbm is None:
                self.error_occurred.emit(
                    "DUT Measurement (Missing Golden Data)",
                    f"Missing Golden measurement data point at Freq Index {idx}, SN {serial_number}"
                )
                return

            instrument_reading_dut_dbm: Optional[float] = None
            actual_dut_gain_dbi: Optional[float] = None

            if not self.hardware_ready:
                # Simulation
                logger.debug(f"DUT (Sim) SN {serial_number}, Port {port_name}, Freq Idx: {idx}, Target Freq: {target_freq_ghz_val} GHz")
                FAIL_PROBABILITY_PER_TEST_POINT = 0.05
                is_this_freq_point_failing = random.random() < FAIL_PROBABILITY_PER_TEST_POINT

                sim_actual_dut_gain_dbi = 0.0
                if is_this_freq_point_failing:
                    spec_range_width = dut_upper_limit - dut_lower_limit
                    failure_magnitude_offset = 0.0
                    if spec_range_width > 0.1:
                        failure_magnitude_offset = spec_range_width * random.uniform(0.1, 0.5)
                    else:
                        failure_magnitude_offset = random.uniform(0.2, 1.0)
                    if random.random() < 0.5:
                        sim_actual_dut_gain_dbi = dut_lower_limit - failure_magnitude_offset
                    else:
                        sim_actual_dut_gain_dbi = dut_upper_limit + failure_magnitude_offset
                else:
                    if dut_upper_limit > dut_lower_limit:
                        target_gain_center = (dut_lower_limit + dut_upper_limit) / 2.0
                        spec_half_width = (dut_upper_limit - dut_lower_limit) / 2.0
                        noise_factor_for_pass = 0.90
                        random_deviation = random.uniform(-spec_half_width * noise_factor_for_pass,
                                                          spec_half_width * noise_factor_for_pass)
                        sim_actual_dut_gain_dbi = target_gain_center + random_deviation
                    elif dut_upper_limit == dut_lower_limit:
                        sim_actual_dut_gain_dbi = dut_lower_limit
                    else:
                        sim_actual_dut_gain_dbi = dut_lower_limit + random.uniform(-0.05, 0.05)

                actual_dut_gain_dbi = sim_actual_dut_gain_dbi
                instrument_reading_dut_dbm = golden_sample_power_reading_dbm + (actual_dut_gain_dbi - spec_gain_golden_sample)
                time.sleep(0.075)  # Pace simulation for visual progress updates

            else:
                # Real hardware
                logger.debug(f"DUT (HW) SN {serial_number}, Port {port_name}, Freq Idx: {idx}, Target Freq: {target_freq_ghz_val} GHz")
                try:
                    generator_freq_mhz = (target_freq_ghz_val * 1000) / self.multiplexing_factor
                    instrument_reading_dut_dbm = self._do_hardware_step(generator_freq_mhz, target_freq_ghz_val)

                    if instrument_reading_dut_dbm is None:
                        raise Exception("Power meter returned None for DUT measurement.")

                    actual_dut_gain_dbi = spec_gain_golden_sample + (instrument_reading_dut_dbm - golden_sample_power_reading_dbm)

                except Exception as e:
                    self.error_occurred.emit("DUT Measurement Step", str(e))
                    return

            # Compute pass/fail
            pass_status_for_point = "FAIL (Error)"
            if actual_dut_gain_dbi is not None and instrument_reading_dut_dbm is not None:
                pass_status_for_point = "PASS" if dut_lower_limit <= actual_dut_gain_dbi <= dut_upper_limit else "FAIL"
                # Anomaly detection: warn if DUT gain is negative (unexpected for antenna measurements)
                if actual_dut_gain_dbi < 0:
                    logger.warning(
                        f"ANOMALY: Negative DUT gain {actual_dut_gain_dbi:.2f} dBi at {target_freq_ghz_val} GHz "
                        f"for SN '{serial_number}' on port '{port_name}'. "
                        f"P_dut={instrument_reading_dut_dbm:.2f} dBm, P_golden={golden_sample_power_reading_dbm:.2f} dBm, "
                        f"Spec_Gain_Golden={spec_gain_golden_sample:.2f} dBi, "
                        f"Delta(P_dut-P_golden)={instrument_reading_dut_dbm - golden_sample_power_reading_dbm:.2f} dB"
                    )

            step_data = {
                "Frequency_GHz": target_freq_ghz_val,
                "Antenna_Gain": actual_dut_gain_dbi if actual_dut_gain_dbi is not None else float('nan'),
                "Lower_Limit": dut_lower_limit,
                "Upper_Limit": dut_upper_limit,
                "Pass": pass_status_for_point,
                "Antenna_Measurement": instrument_reading_dut_dbm if instrument_reading_dut_dbm is not None else float('nan'),
                "Golden_Measurement": golden_sample_power_reading_dbm,
                "Spec_Gain_Golden": spec_gain_golden_sample
            }
            results.append(step_data)

            self.progress_updated.emit(idx, step_data)

        # All points done
        self.measurement_completed.emit("antenna", results)
