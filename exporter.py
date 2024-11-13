import yaml
import snap7
from snap7.util import get_int, get_real, get_bool
from prometheus_client import start_http_server, Gauge
import time
import logging
import string

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_config(config_path='./targets.yaml'):
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

class S7Exporter:
    def __init__(self, config):
        self.config = config
        self.gauges = {}
        self.alphabet_index = {char: idx + 1 for idx, char in enumerate(string.ascii_uppercase)}  # A=1, B=2, ..., Z=26

    def connect_to_plc(self, target):
        client = snap7.client.Client()
        try:
            client.connect(target['ip'], target['rack'], target['slot'], target['port'])
            if client.get_connected():
                logger.info(f"Connected to PLC at {target['ip']}")
            return client
        except Exception as e:
            logger.error(f"Failed to connect to PLC at {target['ip']}: {e}")
            return None

    def read_data_from_plc(self, client, db, metric):
        try:
            # Define bytes to read based on the metric type
            if metric['type'] == 'int':
                bytes_to_read = 2
                offset = int(metric['offset'])
            elif metric['type'] == 'float':
                bytes_to_read = 4
                offset = int(metric['offset'])
            elif metric['type'] == 'bool':
                bytes_to_read = 1
                offset_str = str(metric['offset'])
                if '.' in offset_str:
                    offset, bit_index = map(int, offset_str.split('.'))
                else:
                    offset = int(offset_str)
                    bit_index = 0  # Default to first bit if no specific bit is specified
            elif metric['type'] == 'string':
                # Specify bytes_to_read explicitly in the metric for strings
                bytes_to_read = metric.get('bytes_to_read', 10)  # Default to 10 bytes if not specified
                offset = int(metric['offset'])
            else:
                logger.warning(f"Unsupported data type '{metric['type']}' for {metric['name']}")
                return None

            # Read from the specified DB, offset, and bytes_to_read
            data = client.db_read(db['number'], offset, bytes_to_read)
            
            # Extract value based on the data type
            if metric['type'] == 'int':
                return get_int(data, 0)
            elif metric['type'] == 'float':
                return get_real(data, 0)
            elif metric['type'] == 'bool':
                return get_bool(data, 0, bit_index)
            elif metric['type'] == 'string':
                # Decode string, filter out non-printable characters, and strip padding
                decoded_str = data[:bytes_to_read].decode('iso-8859-1', errors='ignore')
                filtered_str = ''.join([ch for ch in decoded_str if ch.isprintable()]).strip()

                # Cut the first character if the metric is "Recepi"
                if metric['name'] == 'Recepi':
                    filtered_str = filtered_str[1:]  # Remove the first character

                return filtered_str
        except Exception as e:
            logger.error(f"Error reading data from DB {db['number']} at offset {metric['offset']}: {e}")
            return None

    def initialize_metrics(self):
        for target in self.config:
            for db in target.get('db', []):
                for metric in db.get('metrics', []):
                    key = f"{target['ip']}_{metric['name']}"
                    if metric['name'] == 'Recepi':
                        # Initialize separate metrics for alphabet and number parts
                        self.gauges[key + "_alphabet"] = Gauge(metric['name'] + "_alphabet", "Alphabet part of Recepi", ['target'])
                        self.gauges[key + "_number"] = Gauge(metric['name'] + "_number", "Numeric part of Recepi", ['target'])
                    else:
                        # Initialize regular metric
                        self.gauges[key] = Gauge(metric['name'], metric['help'], ['target'])
                    logger.info(f"Initialized gauge for {metric['name']}")

    def update_metrics(self):
        for target in self.config:
            client = self.connect_to_plc(target)
            if not client:
                continue  # Skip this target if connection failed
            for db in target.get('db', []):
                for metric in db.get('metrics', []):
                    key = f"{target['ip']}_{metric['name']}"
                    value = self.read_data_from_plc(client, db, metric)
                    if value is not None:
                        if metric['name'] == 'Recepi' and isinstance(value, str):
                            # Parse Recepi into alphabetic and numeric parts
                            alphabet_part = value[0]
                            numeric_part = int(value[1:]) if value[1:].isdigit() else 0

                            # Convert alphabet part to its position in the alphabet
                            alphabet_value = self.alphabet_index.get(alphabet_part.upper(), 0)

                            # Update Prometheus metrics for both parts
                            self.gauges[key + "_alphabet"].labels(target=target['label']).set(alphabet_value)
                            self.gauges[key + "_number"].labels(target=target['label']).set(numeric_part)
                            logger.info(f"Updated {metric['name']} to alphabet={alphabet_part} ({alphabet_value}), number={numeric_part}")
                        else:
                            # For non-Recepi metrics, update Prometheus normally
                            self.gauges[key].labels(target=target['label']).set(value)
                            logger.info(f"Updated {metric['name']} to {value}")
            client.disconnect()

if __name__ == '__main__':
    config = load_config()
    exporter = S7Exporter(config)
    exporter.initialize_metrics()
    start_http_server(9712)

    # Set update frequency from configuration, defaulting to 15 seconds if not specified
    update_interval = config[0].get('cycle-runtime', '15000ms')
    if isinstance(update_interval, str) and update_interval.endswith('ms'):
        update_interval = int(update_interval.replace('ms', '')) / 1000
    else:
        update_interval = int(update_interval)  # Assume seconds if no 'ms' suffix

    while True:
        exporter.update_metrics()
        time.sleep(update_interval)
