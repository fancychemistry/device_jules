import json
import logging
import os
from typing import Optional, Dict, Any

class ExperimentConfigManager:
    def __init__(self):
        """
        Initializes the ExperimentConfigManager.
        """
        self.logger = logging.getLogger(__name__)

    def load_config(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Loads an experiment configuration from a JSON file.

        Args:
            file_path: The path to the JSON configuration file.

        Returns:
            A dictionary containing the configuration data if successful, None otherwise.
        """
        self.logger.debug(f"Attempting to load configuration from: {file_path}")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.logger.info(f"Configuration successfully loaded from {file_path}")
            return data
        except FileNotFoundError:
            self.logger.error(f"Configuration file not found: {file_path}")
            return None
        except json.JSONDecodeError as e:
            self.logger.error(f"Error decoding JSON from configuration file {file_path}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"An unexpected error occurred while loading configuration file {file_path}: {e}", exc_info=True)
            return None

    def save_config(self, data: Dict[str, Any], file_path: str) -> bool:
        """
        Saves the given configuration data to a JSON file.

        Args:
            data: A dictionary containing the configuration data to save.
            file_path: The path where the JSON configuration file will be saved.

        Returns:
            True if saving was successful, False otherwise.
        """
        self.logger.debug(f"Attempting to save configuration to: {file_path}")
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Configuration successfully saved to {file_path}")
            return True
        except IOError as e:
            self.logger.error(f"IOError saving configuration file {file_path}: {e}", exc_info=True)
            return False
        except Exception as e:
            self.logger.error(f"An unexpected error occurred while saving configuration file {file_path}: {e}", exc_info=True)
            return False

    def validate_config(self, data: Dict[str, Any]) -> bool:
        """
        Performs basic validation on the provided configuration data.

        Args:
            data: A dictionary containing the configuration data to validate.

        Returns:
            True if the basic validation passes, False otherwise.
        """
        self.logger.debug("Validating configuration data...")
        if not isinstance(data, dict):
            self.logger.error("Validation failed: Configuration data is not a dictionary.")
            return False

        if "experiment_sequence" not in data:
            self.logger.error("Validation failed: 'experiment_sequence' key is missing.")
            return False
        
        if not isinstance(data["experiment_sequence"], list):
            self.logger.error("Validation failed: 'experiment_sequence' is not a list.")
            return False
            
        if "project_name" not in data:
            self.logger.warning("Validation warning: 'project_name' key is missing (optional basic check).")
            # Depending on strictness, this could be an error too. For now, just a warning.

        # Example of further basic check: ensure all items in sequence are dicts with an 'id'
        for i, step in enumerate(data["experiment_sequence"]):
            if not isinstance(step, dict):
                self.logger.error(f"Validation failed: Step at index {i} in 'experiment_sequence' is not a dictionary.")
                return False
            if "id" not in step:
                self.logger.error(f"Validation failed: Step at index {i} in 'experiment_sequence' is missing an 'id'.")
                return False
            if "type" not in step:
                self.logger.error(f"Validation failed: Step at index {i} (id: {step.get('id')}) in 'experiment_sequence' is missing a 'type'.")
                return False


        self.logger.info("Configuration passed basic validation.")
        return True

if __name__ == '__main__':
    # Setup basic logging for the test
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger_main = logging.getLogger(__name__)

    manager = ExperimentConfigManager()

    # 1. Create a dummy valid config and save it
    dummy_valid_config_path = "temp_valid_config.json"
    valid_config_data = {
        "project_name": "Test Project",
        "description": "A test experiment configuration.",
        "global_variables": {"sample_volume_ml": 0.5},
        "default_wait_times": {"after_each_step": 0.1},
        "experiment_sequence": [
            {"id": "step1", "type": "printer_home", "description": "Home the printer", "enabled": True, "params": {}},
            {"id": "step2", "type": "move_printer_xyz", "description": "Move to position", "enabled": True, "params": {"x": 10, "y": 20, "z": 5}}
        ]
    }
    logger_main.info(f"\n--- Testing save_config with valid data to {dummy_valid_config_path} ---")
    save_success = manager.save_config(valid_config_data, dummy_valid_config_path)
    logger_main.info(f"Save success: {save_success}")
    assert save_success

    # 2. Load the saved config and print it
    logger_main.info(f"\n--- Testing load_config from {dummy_valid_config_path} ---")
    loaded_data = manager.load_config(dummy_valid_config_path)
    if loaded_data:
        logger_main.info(f"Loaded data: {json.dumps(loaded_data, indent=2)}")
        assert loaded_data["project_name"] == "Test Project"
    else:
        logger_main.error("Failed to load the saved config.")
        assert False

    # 3. Test loading a non-existent file
    logger_main.info("\n--- Testing load_config with non-existent file ---")
    non_existent_data = manager.load_config("non_existent_config.json")
    assert non_existent_data is None

    # 4. Test loading a malformed JSON file
    dummy_malformed_path = "temp_malformed_config.json"
    with open(dummy_malformed_path, 'w') as f:
        f.write("{'project_name': 'Test', 'sequence': [}") # Invalid JSON
    logger_main.info(f"\n--- Testing load_config with malformed JSON from {dummy_malformed_path} ---")
    malformed_data = manager.load_config(dummy_malformed_path)
    assert malformed_data is None


    # 5. Test validate_config with valid data
    logger_main.info("\n--- Testing validate_config with valid data ---")
    is_valid = manager.validate_config(valid_config_data)
    logger_main.info(f"Validation of valid_config_data: {is_valid}")
    assert is_valid

    # 6. Create a dummy invalid config and test validate_config
    logger_main.info("\n--- Testing validate_config with invalid data (experiment_sequence not a list) ---")
    invalid_config_data_seq_type = {
        "project_name": "Invalid Project",
        "experiment_sequence": "this should be a list"
    }
    is_invalid_seq_type = manager.validate_config(invalid_config_data_seq_type)
    logger_main.info(f"Validation of invalid_config_data_seq_type: {is_invalid_seq_type}")
    assert not is_invalid_seq_type

    logger_main.info("\n--- Testing validate_config with invalid data (missing experiment_sequence) ---")
    invalid_config_data_missing_seq = {
        "project_name": "Invalid Project 2"
    }
    is_invalid_missing_seq = manager.validate_config(invalid_config_data_missing_seq)
    logger_main.info(f"Validation of invalid_config_data_missing_seq: {is_invalid_missing_seq}")
    assert not is_invalid_missing_seq
    
    logger_main.info("\n--- Testing validate_config with invalid data (step not a dict) ---")
    invalid_config_step_not_dict = {
        "project_name": "Invalid Steps",
        "experiment_sequence": ["step1_as_string"]
    }
    is_invalid_step_type = manager.validate_config(invalid_config_step_not_dict)
    logger_main.info(f"Validation of invalid_config_step_not_dict: {is_invalid_step_type}")
    assert not is_invalid_step_type

    logger_main.info("\n--- Testing validate_config with invalid data (step missing id) ---")
    invalid_config_step_missing_id = {
        "project_name": "Invalid Steps",
        "experiment_sequence": [{"type": "printer_home"}]
    }
    is_invalid_step_id = manager.validate_config(invalid_config_step_missing_id)
    logger_main.info(f"Validation of invalid_config_step_missing_id: {is_invalid_step_id}")
    assert not is_invalid_step_id
    
    logger_main.info("\n--- Testing validate_config with invalid data (step missing type) ---")
    invalid_config_step_missing_type = {
        "project_name": "Invalid Steps",
        "experiment_sequence": [{"id": "s1"}]
    }
    is_invalid_step_type_key = manager.validate_config(invalid_config_step_missing_type)
    logger_main.info(f"Validation of invalid_config_step_missing_type: {is_invalid_step_type_key}")
    assert not is_invalid_step_type_key

    # 7. Clean up dummy files
    logger_main.info("\n--- Cleaning up dummy files ---")
    if os.path.exists(dummy_valid_config_path):
        os.remove(dummy_valid_config_path)
        logger_main.info(f"Removed {dummy_valid_config_path}")
    if os.path.exists(dummy_malformed_path):
        os.remove(dummy_malformed_path)
        logger_main.info(f"Removed {dummy_malformed_path}")
    
    logger_main.info("\n--- All tests finished ---")
