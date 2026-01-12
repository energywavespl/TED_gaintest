import pyodbc
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple # Added Tuple
from dataclasses import dataclass, field
import uuid # Kept for other potential uses, but not for Meas_ID generation

# Version 0.5

# Configure logging
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
#     handlers=[
#         logging.FileHandler("antenna_data_service.log"),
#         logging.StreamHandler()
#     ]
# )
logger = logging.getLogger("AntennaDataService")

@dataclass
class GainTestValue:
    """Data class for storing individual frequency measurement values."""
    frequency_ghz: Optional[float] = None
    measurement_antenna: Optional[float] = None
    measurement_golden: Optional[float] = None
    gain_antenna: Optional[float] = None
    gain_golden: Optional[float] = None       # Gain of the golden sample (from setup file)
    lower_limit: Optional[float] = None
    upper_limit: Optional[float] = None

@dataclass
class GainTestHeader:
    """Data class for storing header information for a set of gain test measurements."""
    # meas_id is now a manually assigned integer, based on MAX(Meas_ID) + 1 from the Headers table.
    # It will be None until assigned during the insertion process.
    meas_id: Optional[int] = None
    port: Optional[str] = None
    antenna_id: Optional[str] = None         # Serial number of the antenna
    order_number: Optional[str] = None
    article_number: Optional[str] = None     # Article number of the antenna
    charge_number: Optional[str] = None      # Charge number of the antenna
    product_name: Optional[str] = None
    setup_file: Optional[str] = None         # Setup file used for the measurement
    timestamp_utc: Optional[datetime] = None # Timestamp of the measurement (UTC)
    reference: Optional[str] = None          # Measurement type (e.g., "Empty" for standard, "Silver" for silver sample)
    operator: Optional[str] = None
    result: Optional[str] = None             # Overall result ("PASS"/"FAIL")
    soft_version: Optional[str] = None       # Software version used for the test
    comment: Optional[str] = None
    hardware_id_gen: Optional[str] = None
    hardware_id_power_meter: Optional[str] = None
    hardware_id_extension_module: Optional[str] = None
    label_1: Optional[str] = None
    label_2: Optional[str] = None
    inactive: int = 0                        # Default to 0, compatible with DB (int, null)

@dataclass
class CompositeAntennaTestData:
    """Represents a complete test session: one header and multiple value readings."""
    header: GainTestHeader
    values: List[GainTestValue] = field(default_factory=list)


class BatchTestCollector:
    """Collector for gathering composite test data in memory before batch submission."""
    
    def __init__(self):
        """Initialize an empty batch collector."""
        self.records: List[CompositeAntennaTestData] = []
        self.batch_id_str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        logger.info(f"Initialized BatchTestCollector with batch_id_str: {self.batch_id_str}")
        
    def add_record(self, record: CompositeAntennaTestData):
        """
        Add a composite test record (header + values) to the batch.
        The record's header.meas_id will be None at this stage; it's assigned by the service on commit.
        
        Args:
            record: CompositeAntennaTestData object to add to the batch.
        """
        self.records.append(record)
        logger.debug(f"Added record (Antenna: {record.header.antenna_id}, Port: {record.header.port}; "
                     f"Manual Meas_ID will be assigned on commit) to batch {self.batch_id_str}. "
                     f"Total records in batch: {len(self.records)}")
        
    def clear(self):
        """Clear all records from the batch."""
        record_count = len(self.records)
        self.records = []
        logger.info(f"Cleared {record_count} records from batch {self.batch_id_str}")
        
    def get_records(self) -> List[CompositeAntennaTestData]:
        """
        Get all records in the batch.
        
        Returns:
            A copy of the list of CompositeAntennaTestData objects in the batch.
        """
        return self.records.copy()
    
    def get_record_count(self) -> int:
        """
        Get the number of records (composite tests) in the batch.
        
        Returns:
            Count of CompositeAntennaTestData objects in the batch.
        """
        return len(self.records)


class AntennaDataService:
    """Service for interacting with the antenna test database."""
    
    def __init__(self, connection_string: str):
        """
        Initialize the data service with a database connection string.
        
        Args:
            connection_string: ODBC connection string for the database.
        """
        self.connection_string = connection_string
        self.conn: Optional[pyodbc.Connection] = None
        self.batch_collector = BatchTestCollector()
        logger.warning("MANUAL Meas_ID GENERATION (MAX+1): This method can have concurrency issues in high-traffic environments "
                       "leading to potential duplicate Meas_ID errors if not handled carefully (e.g., with unique constraints and retries, or by ensuring serial access).")

    def __enter__(self):
        """Context manager entry point to establish a database connection."""
        try:
            self.conn = pyodbc.connect(self.connection_string)
            logger.info("Database connection established.")
            return self
        except pyodbc.Error as e:
            logger.error(f"Database connection error: {e}")
            raise
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit point to close the database connection."""
        if self.conn:
            try:
                self.conn.close()
                logger.info("Database connection closed.")
            except pyodbc.Error as e:
                logger.error(f"Error closing database connection: {e}")
                
    def _get_connection(self) -> pyodbc.Connection:
        """
        Get the current connection. If called outside of a 'with' block
        or if connection is closed, it will attempt to establish a new one.
        It's recommended to use the service as a context manager.
        """
        if self.conn is None or (hasattr(self.conn, 'closed') and self.conn.closed):
            is_closed_or_none = True
            if self.conn:
                try:
                    # Test connection usability (pyodbc.Connection doesn't have a .closed reliable attribute for all drivers)
                    self.conn.cursor().execute("SELECT 1")
                    is_closed_or_none = False
                except pyodbc.Error:
                    logger.warning("Connection check failed. Assuming closed/invalid.")
                    self.conn = None
                    is_closed_or_none = True
            
            if is_closed_or_none:
                logger.warning("Connection is None or closed/invalid. Attempting to establish a new connection. "
                               "Consider using AntennaDataService as a context manager ('with' statement).")
                self.conn = pyodbc.connect(self.connection_string)
                logger.info("Database re-connection successful.")

        if self.conn is None:
             raise ConnectionError("Failed to establish database connection.")
        return self.conn
    
    def add_measurement_to_batch(self, data: CompositeAntennaTestData):
        """
        Add a single composite test data record to the in-memory batch.
        
        Args:
            data: CompositeAntennaTestData object to add to the batch.
        """
        self.batch_collector.add_record(data)
        logger.info(f"Added composite record (Antenna: {data.header.antenna_id}, Port: {data.header.port}; "
                    f"Manual Meas_ID will be assigned on commit) to batch. "
                    f"Current batch size: {self.batch_collector.get_record_count()}")

    def _get_current_max_manual_meas_id(self, cursor: pyodbc.Cursor) -> int:
        """
        Fetches the maximum Meas_ID from Gain_Test_Measurements_Headers.
        Returns 0 if table is empty or all Meas_IDs are NULL.
        WARNING: Prone to race conditions in concurrent environments.
        """
        cursor.execute("SELECT MAX(Meas_ID) FROM Gain_Test_Measurements_Headers")
        row = cursor.fetchone()
        if row and row[0] is not None:
            return int(row[0])
        return 0 # Start from 1 if table is empty or no Meas_ID set

    def commit_measurements_batch(self) -> List[int]:
        """
        Commit all composite test records in the current batch to the database.
        Manually assigned Meas_IDs are generated sequentially for the batch.
        The entire batch is committed as one transaction.
        
        Returns:
            List of manually assigned integer Meas_IDs for the inserted header records.
        Raises:
            ConnectionError: If the database connection is not available.
            pyodbc.Error: For database-related errors during commit.
        """
        records_to_commit = self.batch_collector.get_records()
        if not records_to_commit:
            logger.info("No records to commit in batch.")
            return []
            
        assigned_manual_meas_ids: List[int] = []
        
        current_db_conn = self._get_connection()

        try:
            current_db_conn.autocommit = False # Start transaction for the entire batch
            cursor = current_db_conn.cursor()
            
            current_max_meas_id = self._get_current_max_manual_meas_id(cursor)
            next_manual_meas_id_to_assign = current_max_meas_id + 1
            
            for composite_data in records_to_commit:
                # _insert_single_composite_test_data will use and return the assigned manual_meas_id
                # It also updates composite_data.header.meas_id
                assigned_id = self._insert_single_composite_test_data(
                    composite_data, 
                    cursor, 
                    next_manual_meas_id_to_assign
                )
                assigned_manual_meas_ids.append(assigned_id)
                next_manual_meas_id_to_assign += 1 # Increment for the next record in this batch
            
            current_db_conn.commit()
            logger.info(f"Successfully committed batch with {len(assigned_manual_meas_ids)} composite records. "
                        f"Manually assigned Meas_IDs: {assigned_manual_meas_ids}")
            self.batch_collector.clear() # Clear batch only on successful commit
            return assigned_manual_meas_ids
        except pyodbc.Error as e:
            logger.error(f"Error committing batch of measurements: {e}")
            if current_db_conn:
                try:
                    current_db_conn.rollback()
                    logger.info("Batch commit rolled back due to pyodbc.Error.")
                except pyodbc.Error as rb_e:
                    logger.error(f"Error during rollback: {rb_e}")
            raise
        except Exception as e: 
            logger.error(f"An unexpected error occurred during batch commit: {e}")
            if current_db_conn and current_db_conn.autocommit is False:
                 try:
                    current_db_conn.rollback()
                    logger.info("Batch commit rolled back due to unexpected error.")
                 except pyodbc.Error as rb_e:
                    logger.error(f"Error during rollback after unexpected error: {rb_e}")
            raise
        finally:
            if current_db_conn:
                try:
                    current_db_conn.autocommit = True # Reset autocommit state
                except pyodbc.Error as final_e:
                    logger.warning(f"Could not reset autocommit after batch commit: {final_e}")

    def get_batch_size(self) -> int:
        """Get the current size of the uncommitted batch."""
        return self.batch_collector.get_record_count()
    
    def clear_batch(self):
        """Clear all records from the current batch without committing."""
        self.batch_collector.clear()
        logger.info("Cleared current batch without committing.")

    def _insert_single_composite_test_data(self, data: CompositeAntennaTestData, cursor: pyodbc.Cursor, manual_meas_id_to_use: int) -> int:
        """
        Helper method to insert a single composite test data (header and its values).
        Assumes it's called within an existing transaction and with an active cursor.
        Assigns the provided manual_meas_id_to_use to data.header.meas_id and uses it for insertion.
        The auto-generated PK `ID` for the Headers table is also handled but not the primary focus for this method's return.
        
        Args:
            data: CompositeAntennaTestData object. Its header.meas_id will be updated.
            cursor: Active pyodbc cursor.
            manual_meas_id_to_use: The manually determined Meas_ID to use for this record.
            
        Returns:
            The manually assigned integer Meas_ID used for the inserted header record.
        """
        header = data.header
        header.meas_id = manual_meas_id_to_use # Assign the manual Meas_ID

        if header.timestamp_utc is None:
            header.timestamp_utc = datetime.now(timezone.utc)
            logger.debug(f"Timestamp_UTC was None for Antenna {header.antenna_id}, Port {header.port}. Set to current UTC time.")

        # Meas_ID is NOW included in the INSERT statement's column list and VALUES.
        # The `ID` column (PK) is still expected to be an IDENTITY column generated by the database.
        header_query = """
        INSERT INTO Gain_Test_Measurements_Headers (
            Meas_ID, Port, Antenna_ID, Order_Number, Article_Number, Charge_Number,
            Product_Name, Setup_File, Timestamp_UTC, Reference, Operator, Result,
            Soft_Version, Label_1, Label_2, Inactive, Comment, HardwareID_Gen,
            HardwareID_Power_Meter, HardwareID_Extension_Module
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        # Parameters list now has 20 items, matching the 20 columns and '?'
        header_params = (
            header.meas_id, # The manually assigned Meas_ID
            header.port, header.antenna_id, header.order_number, header.article_number,
            header.charge_number, header.product_name, header.setup_file, header.timestamp_utc,
            header.reference, header.operator, header.result, header.soft_version,
            header.label_1, header.label_2, header.inactive, header.comment,
            header.hardware_id_gen, header.hardware_id_power_meter, header.hardware_id_extension_module
        )
        
        cursor.execute(header_query, header_params)
        
        # Optionally, retrieve the auto-generated PK 'ID' if needed for logging or other purposes,
        # but it's not the 'Meas_ID' we are primarily concerned with for linking or returning.
        cursor.execute("SELECT SCOPE_IDENTITY() AS auto_pk_id;")
        header_auto_pk_id_row = cursor.fetchone()
        if header_auto_pk_id_row and header_auto_pk_id_row[0] is not None:
            auto_generated_header_table_pk = int(header_auto_pk_id_row[0])
            logger.debug(f"Inserted header with manual Meas_ID: {header.meas_id} "
                         f"(Antenna_ID: {header.antenna_id}, Port: {header.port}). "
                         f"Auto-generated PK for Headers table (ID column): {auto_generated_header_table_pk}.")
        else:
            logger.warning(f"Could not retrieve SCOPE_IDENTITY() for inserted header with manual Meas_ID: {header.meas_id}. "
                           "This is unexpected if 'ID' is an IDENTITY column.")
            # This doesn't stop the process if Meas_ID was main concern.
        
        if data.values:
            value_query = """
            INSERT INTO Gain_Test_Measurements_Values (
                Meas_ID, Freq_GHz, Measurement_Antenna, Measurement_Golden,
                Gain_Antenna, Gain_Golden, Lower_Limit, Upper_Limit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            value_params_list = []
            for value_item in data.values:
                value_params_list.append((
                    header.meas_id, # FK is now the manually assigned Meas_ID from the header
                    value_item.frequency_ghz,
                    value_item.measurement_antenna,
                    value_item.measurement_golden,
                    value_item.gain_antenna,
                    value_item.gain_golden,
                    value_item.lower_limit,
                    value_item.upper_limit
                ))
            
            if value_params_list:
                if hasattr(cursor, 'fast_executemany') and cursor.fast_executemany is not None:
                    cursor.fast_executemany = True
                cursor.executemany(value_query, value_params_list)
                logger.debug(f"Inserted {len(value_params_list)} value records for manual Meas_ID {header.meas_id}.")
        
        return header.meas_id # Return the manually assigned Meas_ID

    def insert_measurement(self, data: CompositeAntennaTestData) -> int:
        """
        Insert a single composite antenna test data (header and its values) into the database.
        A manual Meas_ID is generated (MAX(existing Meas_ID) + 1).
        This operation is performed in a single transaction. Updates data.header.meas_id.
        
        Args:
            data: CompositeAntennaTestData object. Its header.meas_id will be updated.
            
        Returns:
            The manually assigned integer Meas_ID of the inserted header record.
        """
        current_db_conn = self._get_connection()
        
        try:
            if data.header.timestamp_utc is None:
                data.header.timestamp_utc = datetime.now(timezone.utc)

            current_db_conn.autocommit = False # Start transaction
            cursor = current_db_conn.cursor()
            
            current_max_meas_id = self._get_current_max_manual_meas_id(cursor)
            manual_meas_id_to_assign = current_max_meas_id + 1
            
            # _insert_single_composite_test_data will assign manual_meas_id_to_assign to data.header.meas_id
            # and use it for insertion.
            assigned_id = self._insert_single_composite_test_data(data, cursor, manual_meas_id_to_assign)
            
            current_db_conn.commit()
            logger.info(f"Successfully inserted composite measurement (Manually assigned Meas_ID: {assigned_id})")
            return assigned_id
            
        except pyodbc.Error as e:
            if current_db_conn:
                try:
                    current_db_conn.rollback()
                    logger.info(f"Transaction rolled back for Antenna {data.header.antenna_id}, Port {data.header.port} due to pyodbc.Error.")
                except pyodbc.Error as rb_e:
                    logger.error(f"Error during rollback for Antenna {data.header.antenna_id}, Port {data.header.port}: {rb_e}")
            logger.error(f"Error inserting composite measurement (Antenna: {data.header.antenna_id}, Port: {data.header.port}, "
                         f"Attempted manual Meas_ID for this record: {data.header.meas_id}): {e}")
            raise
        except Exception as e:
            if current_db_conn and current_db_conn.autocommit is False:
                 try:
                    current_db_conn.rollback()
                    logger.info(f"Transaction rolled back due to unexpected error for Antenna: {data.header.antenna_id}, Port: {data.header.port}")
                 except pyodbc.Error as rb_e:
                    logger.error(f"Error during rollback after unexpected error: {rb_e}")
            logger.error(f"An unexpected error occurred during single insert (Antenna: {data.header.antenna_id}, Port: {data.header.port}, "
                         f"Attempted manual Meas_ID for this record: {data.header.meas_id}): {e}")
            raise
        finally:
            if current_db_conn:
                try:
                    current_db_conn.autocommit = True # Reset autocommit state
                except pyodbc.Error as final_e:
                    logger.warning(f"Could not reset autocommit after single insert: {final_e}")


def example_usage():
    """Example of using the AntennaDataService class with manually assigned Meas_ID."""
    
    logger.info("SCHEMA NOTE: 'Meas_ID' for Gain_Test_Measurements_Headers is now manually assigned "
                "based on MAX(existing Meas_ID) + 1. The 'ID' column in Headers is still the auto-generated PK. "
                "The 'Meas_ID' in Gain_Test_Measurements_Values is the foreign key to Headers.Meas_ID (manual).")

    # IMPORTANT: Replace with your actual connection string
    connection_string = (
        "DRIVER={ODBC Driver 18 for SQL Server};"  # Or your specific driver
        "SERVER=your_server_name\\your_instance_name;" 
        "DATABASE=PL_MP_gaintest_dev;" # Your database name
        "Trusted_Connection=yes;" # Use yes for Windows Authentication
        # "UID=your_username;"      # Or UID/PWD for SQL Server Authentication
        # "PWD=your_password;"
        "TrustServerCertificate=yes;" # Often needed for local/dev instances or newer drivers
    )
    
    try:
        with AntennaDataService(connection_string) as service:
            print("--- Example: Batch inserting multiple measurement sessions (manual Meas_ID) ---")
            
            # Note: meas_id is initially None, will be assigned by the service.
            header_data1 = GainTestHeader(
                port="TX03", 
                antenna_id="SN-ANT001-DBGEN", 
                order_number="PO-12345",
                article_number="PN-XYZ-001-R01", 
                charge_number="BATCH-202401DB",
                product_name="ARS620 B3", 
                setup_file="ARS620 B3.xlsx",
                timestamp_utc=datetime.now(timezone.utc), 
                reference=None, 
                operator="Dawid",
                result="PENDING", 
                oft_version="TesterSW_1",
                comment="Initial test run for SN-ANT001-DBGEN, Port TX03. DB-generated Meas_ID.",
                hardware_id_gen="SIGGEN-001", 
                hardware_id_power_meter="PWMR-002",
                hardware_id_extension_module="EXTMOD-003"
            )
            
            values_list1: List[GainTestValue] = []
            frequencies1 = [76.1, 77.1, 78.1, 79.1, 80.1, 81.1]
            session1_overall_result = "PASS"

            for freq in frequencies1:
                ant_meas = -2.1 + (freq - 76.0) * 0.05
                gold_meas = -1.9 + (freq - 76.0) * 0.04
                ant_gain = 12.6 - (freq - 76.0) * 0.1
                gold_gain = 12.1
                ll, ul = 10.0, 14.0
                if not (ll <= ant_gain <= ul): session1_overall_result = "FAIL"
                values_list1.append(GainTestValue(
                    frequency_ghz=freq, measurement_antenna=ant_meas, measurement_golden=gold_meas,
                    gain_antenna=ant_gain, gain_golden=gold_gain, lower_limit=ll, upper_limit=ul
                ))
            header_data1.result = session1_overall_result
            composite_test1 = CompositeAntennaTestData(header=header_data1, values=values_list1)
            service.add_measurement_to_batch(composite_test1)
            print(f"Added composite test (Antenna: {header_data1.antenna_id}, Port: {header_data1.port}) to batch. "
                  f"Manual Meas_ID will be assigned on commit. Current header.meas_id: {header_data1.meas_id}")

            header_data2 = GainTestHeader(
                port="RX01", 
                antenna_id="SN-SILVER001", 
                order_number="CAL-001",
                article_number="PN-REF-00S", 
                charge_number="CAL-BATCH-A",
                product_name="ARS620 B3", 
                setup_file="ARS620 B3.xlsx",
                timestamp_utc=datetime.now(timezone.utc), 
                reference="Silver", # Indicates a silver sample measurement
                operator="Dawid",
                result="PASS", # Assuming silver sample always passes or result determined differently
                soft_version="TesterSW_1.0", 
                comment="Silver sample calibration run.",
                hardware_id_gen="SIGGEN-001", 
                hardware_id_power_meter="PWMR-002", 
                hardware_id_extension_module="EXTMOD-003"
            )
            values_list2 = [
                GainTestValue(frequency_ghz=77.6, measurement_antenna=-1.1, measurement_golden=-0.8,
                              gain_antenna=11.1, gain_golden=11.2, lower_limit=10.5, upper_limit=11.5)
            ]
            composite_test2 = CompositeAntennaTestData(header=header_data2, values=values_list2)
            service.add_measurement_to_batch(composite_test2)
            print(f"Added composite test (Antenna: {header_data2.antenna_id}, Port: {header_data2.port}) to batch. "
                  f"Manual Meas_ID will be assigned on commit. Current header.meas_id: {header_data2.meas_id}")

            try:
                assigned_manual_ids = service.commit_measurements_batch()
                print(f"Successfully committed batch. Manually assigned Meas_IDs: {assigned_manual_ids}")
                # The original objects' headers in the batch are updated with their assigned Meas_ID.
                print(f"After batch commit, composite_test1.header.meas_id is now: {composite_test1.header.meas_id}")
                print(f"After batch commit, composite_test2.header.meas_id is now: {composite_test2.header.meas_id}")

            except Exception as e:
                print(f"Error committing batch: {e}")
            
            print("\n--- Example: Single measurement insertion ---")
            header_data_single = GainTestHeader(
                port="TX01", 
                antenna_id="0787273000C110024649L200001", 
                order_number="PO-12346",
                article_number="PN-XYZ-002-R00", 
                charge_number="BATCH-202402",
                product_name="ARS620 B3", 
                setup_file="ARS620 B3.xlsx",
                timestamp_utc=datetime.now(timezone.utc), 
                reference=None, 
                operator="Dawid",
                result="FAIL", # Overall result for this test
                soft_version="TesterSW_1.0", 
                comment="Single test for 0787273000C110024649L200001. Antenna Rev: 00."
            )
            values_single = [
                GainTestValue(frequency_ghz=76.2, measurement_antenna=-5.2, measurement_golden=-2.2,
                              gain_antenna=7.8, gain_golden=11.3, lower_limit=9.0, upper_limit=12.0), # Fails
                GainTestValue(frequency_ghz=78.2, measurement_antenna=-2.7, measurement_golden=-2.3,
                              gain_antenna=10.3, gain_golden=11.2, lower_limit=9.0, upper_limit=12.0)
            ]
            composite_test_single = CompositeAntennaTestData(header=header_data_single, values=values_single)
            
            try:
                single_manual_id = service.insert_measurement(composite_test_single)
                print(f"Successfully inserted single measurement. Manually assigned Meas_ID: {single_manual_id}. "
                      f"Object updated: composite_test_single.header.meas_id = {composite_test_single.header.meas_id}")
            except Exception as e:
                print(f"Error inserting single measurement: {e}")

    except pyodbc.Error as db_conn_err:
        print(f"Fatal Database Connection/Setup Error: {db_conn_err}")
        print("Please check the following:")
        print("1. Database server is running and accessible.")
        print("2. Connection string details (DRIVER, SERVER, DATABASE, UID/PWD or Trusted_Connection) are correct.")
        print("3. The specified ODBC driver is installed on your system.")
        print("4. The database and tables (Gain_Test_Measurements_Headers, Gain_Test_Measurements_Values) exist "
              "and their schemas match the expected structure (Headers.ID as PK/Identity, Headers.Meas_ID for manual ID).")
        print("5. Ensure the user has permissions to SELECT MAX(Meas_ID) and INSERT into the tables.")
    except Exception as general_err:
        print(f"An unexpected error occurred in example_usage: {general_err}")

if __name__ == "__main__":
    print("Running AntennaDataService example usage (Manually Assigned Meas_ID).")
    print("Ensure your database is set up and the connection string in 'example_usage' is correctly configured.")
    print("Output will be logged to 'antenna_data_service.log' and to the console.")
    print("WARNING: The manual Meas_ID generation (MAX+1) can have issues in high-concurrency scenarios.")
    example_usage()