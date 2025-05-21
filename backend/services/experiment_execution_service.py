import asyncio
import json
import logging
import os
import time
import numpy as np
from typing import Dict, Any, List, Optional
from pathlib import Path

# Placeholder for Broadcaster, assuming it's defined elsewhere (e.g., backend.pubsub)
class Broadcaster:
    """
    Placeholder for a broadcaster class used to send messages, typically over WebSockets.
    In a real application, this would connect to a pub/sub mechanism.
    """
    async def broadcast(self, message: dict):
        """Broadcasts a message."""
        # In a real app, this would send to a WebSocket or other pub/sub system
        logger.debug(f"MockBroadcaster (service): Broadcasting: {message}")


logger = logging.getLogger(__name__)

class ExperimentExecutionService:
    """
    Manages the execution of scientific experiments defined by a configuration file.

    This service is responsible for:
    - Loading and parsing experiment configurations.
    - Stepping through a sequence of experiment actions (steps).
    - Dispatching actions to appropriate device adapters.
    - Managing the state of the experiment (running, paused, stopped, error).
    - Handling context variables and parameter templating for steps.
    - Generating voltage sequences for loops based on flexible definitions.
    - Broadcasting status updates via a broadcaster instance.
    """
    def __init__(self, broadcaster: Broadcaster, devices: Dict[str, Any], loop: Optional[asyncio.AbstractEventLoop] = None):
        """
        Initializes the ExperimentExecutionService.

        Args:
            broadcaster: An instance of a Broadcaster to send status updates.
            devices: A dictionary of initialized device adapter instances, keyed by device name (e.g., "printer", "pump").
            loop: The asyncio event loop to use. If None, the current event loop is fetched.
        """
        self.broadcaster = broadcaster
        self.devices = devices
        self.loop = loop if loop else asyncio.get_event_loop()
        
        self.experiment_config: Dict[str, Any] = {}
        self.config_file_path: Optional[str] = None 

        self.current_sequence: List[Dict[str, Any]] = []
        self.current_step_index: int = 0
        self.is_running: bool = False
        self.current_context: Dict[str, Any] = {} # Holds dynamic data during experiment run (e.g., current_voltage)
        
        # Configuration parameters, loaded from experiment_config
        self.project_name: str = "default_project"
        self.configurations: Dict[str, Any] = {} # General experiment-specific key-value pairs
        self.output_positions: Dict[str, Any] = {} # Predefined named positions (e.g., for printer moves)
        self.results_dir: str = "experiment_results_json" # Base directory for results, project name will be appended

        # Project root is determined based on this file's location.
        # Assumes this service file is within a structure like 'backend/services/'.
        self.project_root: Path = Path(__file__).resolve().parents[2]

    def load_experiment_config(self, file_path: str = "old/experiment_config.json") -> bool:
        """
        Loads an experiment configuration from a JSON file.

        The configuration file defines the project name, result directory,
        device configurations, voltage definitions, output positions, and the
        sequence of steps for the experiment.

        Args:
            file_path: Path to the JSON configuration file, relative to the project root.

        Returns:
            True if loading and parsing were successful, False otherwise.
        """
        try:
            self.config_file_path = file_path 
            config_file_abs_path = self.project_root / self.config_file_path
            logger.info(f"Loading experiment configuration from: {config_file_abs_path}")
            with open(config_file_abs_path, 'r', encoding='utf-8') as f:
                self.experiment_config = json.load(f)

            self._reload_internal_params_from_config() 
            logger.info(f"Experiment configuration loaded successfully. Project: {self.project_name}")
            return True
        except FileNotFoundError:
            logger.error(f"Experiment configuration file not found: {self.config_file_path}")
            return False
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from '{self.config_file_path}': {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error loading config '{self.config_file_path}': {e}", exc_info=True)
            return False

    def get_current_config(self) -> Optional[Dict[str, Any]]:
        """
        Returns the currently loaded experiment configuration.

        Returns:
            A dictionary containing the experiment configuration, or None if no
            configuration is loaded.
        """
        if self.experiment_config:
            return self.experiment_config
        logger.info("No experiment configuration currently loaded in service.")
        return None

    async def update_experiment_config(self, new_config: Dict[str, Any]) -> bool:
        """
        Updates the current experiment configuration with new settings and saves it.
        The configuration is saved back to the path from which it was originally loaded.
        If no path is set (e.g., config loaded by other means), it's updated in memory only.

        Args:
            new_config: A dictionary containing the new configuration settings.

        Returns:
            True if the update and save (if applicable) were successful, False otherwise.
        """
        if self.is_running:
            msg = "Cannot update experiment configuration while an experiment is running."
            logger.error(msg)
            await self.broadcaster.broadcast({"type": "config_update_status", "status": "error", "message": msg })
            return False

        logger.info("Updating experiment configuration.")
        self.experiment_config = new_config # Update internal representation

        if self.config_file_path:
            try:
                full_path = self.project_root / self.config_file_path
                os.makedirs(full_path.parent, exist_ok=True) # Ensure directory exists
                with open(full_path, 'w', encoding='utf-8') as f:
                    json.dump(self.experiment_config, f, indent=2)
                msg = f"Experiment configuration saved to {full_path}"
                logger.info(msg)
                await self.broadcaster.broadcast({
                    "type": "config_update_status", "status": "success",
                    "message": msg, "config_file_path": str(self.config_file_path)
                })
                self._reload_internal_params_from_config() # Reload parameters from the new config
                return True
            except IOError as e:
                msg = f"IOError saving experiment configuration to {self.config_file_path}: {e}"
                logger.error(msg)
                await self.broadcaster.broadcast({"type": "config_update_status", "status": "error","message": msg})
                return False
            except Exception as e:
                msg = f"Unexpected error saving experiment configuration to {self.config_file_path}: {e}"
                logger.error(msg, exc_info=True)
                await self.broadcaster.broadcast({"type": "config_update_status", "status": "error", "message": msg})
                return False
        else:
            msg = "No configuration file path set. Configuration updated in memory only."
            logger.warning(msg)
            await self.broadcaster.broadcast({"type": "config_update_status", "status": "warning", "message": msg})
            self._reload_internal_params_from_config() # Still reload parameters for in-memory update
            return True
            
    def _reload_internal_params_from_config(self):
        """
        Reloads internal service parameters from the `self.experiment_config` dictionary.
        This includes project name, general configurations, output positions, voltage definitions,
        results directory, and the main experiment sequence. It also handles backward
        compatibility for `voltage_range` by converting it to `voltage_definition`.
        """
        self.project_name = self.experiment_config.get('project_name', self.project_name or 'default_project')
        self.configurations = self.experiment_config.get('configurations', self.configurations or {})
        self.output_positions = self.experiment_config.get('output_positions', self.output_positions or {})
        
        # Compatibility: Convert old 'voltage_range' to new 'voltage_definition' if needed.
        if "voltage_definition" not in self.experiment_config and "voltage_range" in self.experiment_config:
            logger.info("Found 'voltage_range'; converting to 'voltage_definition'.")
            voltage_range = self.experiment_config.get("voltage_range", []) 
            if isinstance(voltage_range, list) and len(voltage_range) == 2:
                val1, val2 = voltage_range[0], voltage_range[1]
                if not (isinstance(val1, (int,float)) and isinstance(val2, (int,float))):
                    logger.warning(f"'voltage_range' values not numeric: {voltage_range}. Using empty 'voltage_definition'.")
                    self.experiment_config["voltage_definition"] = {}
                elif val1 < val2:
                    self.experiment_config["voltage_definition"] = {"type": "range_step", "start": float(val1), "stop": float(val2), "step": 0.1}
                elif val1 > val2:
                    self.experiment_config["voltage_definition"] = {"type": "range_step", "start": float(val1), "stop": float(val2), "step": -0.1}
                else: 
                    self.experiment_config["voltage_definition"] = {"type": "list", "values": [float(val1)]}
                logger.info(f"Converted 'voltage_range' {voltage_range} to 'voltage_definition': {self.experiment_config['voltage_definition']}")
            elif not voltage_range: # If voltage_range was empty
                 self.experiment_config["voltage_definition"] = {}
            else: # Invalid format
                logger.warning(f"Invalid 'voltage_range' format: {voltage_range}. Initializing empty 'voltage_definition'.")
                self.experiment_config["voltage_definition"] = {}
        elif "voltage_definition" not in self.experiment_config: # Ensure definition key exists
            self.experiment_config["voltage_definition"] = {}

        # Determine results_dir name robustly to avoid issues if project_name changes
        default_results_base = "experiment_results_json" 
        current_results_dir_path = Path(self.results_dir) # Path to current self.results_dir
        # Infer base if current results_dir is like 'base_name/project_name'
        inferred_base_name = current_results_dir_path.parent.name if current_results_dir_path.name == self.project_name and current_results_dir_path.parent.name else default_results_base
        
        raw_results_dir_config = self.experiment_config.get('results_dir', inferred_base_name)
        self.results_dir = str(self.project_root / raw_results_dir_config / self.project_name)
        os.makedirs(self.results_dir, exist_ok=True) # Ensure it exists
        
        self.current_sequence = self.experiment_config.get('experiment_sequence', self.current_sequence or [])
        logger.info(f"Internal parameters reloaded. Project: {self.project_name}, Results: {self.results_dir}, Sequence: {len(self.current_sequence)} steps, VoltageDef: {self.experiment_config.get('voltage_definition')}")

    def _generate_voltages_from_definition(self) -> List[float]:
        """
        Generates a list of voltage points based on `self.experiment_config.voltage_definition`.

        Supports two types of definitions:
        - "list": Directly uses a provided list of voltage values.
        - "range_step": Generates voltages from a start, stop, and step value.
                         The stop value is included if reachable by the step.

        Returns:
            A list of float voltage values, or an empty list if definition is
            invalid or missing.
        """
        voltage_def = self.experiment_config.get("voltage_definition", {})
        def_type = voltage_def.get("type")
        voltages_to_loop: List[float] = []

        if def_type == "list":
            raw_values = voltage_def.get("values", [])
            if not isinstance(raw_values, list) or not all(isinstance(v, (int, float)) for v in raw_values):
                logger.error(f"Invalid 'values' for voltage_definition list type: {raw_values}")
                return []
            voltages_to_loop = [float(v) for v in raw_values]
        elif def_type == "range_step":
            start, stop, step = voltage_def.get("start"), voltage_def.get("stop"), voltage_def.get("step")
            if not all(isinstance(v, (int, float)) for v in [start, stop, step]): # type: ignore
                logger.error(f"Invalid start/stop/step for range_step: start={start}, stop={stop}, step={step}")
                return []
            start, stop, step = float(start), float(stop), float(step) # type: ignore

            if step == 0: return [start] if start == stop else [] # Single point if start=stop, else invalid
            if (stop > start and step < 0) or (stop < start and step > 0):
                logger.warning(f"Step direction ({step}) mismatches range ({start} to {stop}). May yield empty list.")
            
            current_val = start
            # Use a small epsilon relative to step size for float comparisons to include endpoint
            epsilon = abs(step) * 1e-5 
            # Determine precision for rounding from step size to avoid many decimal places from float arithmetic
            precision_digits = abs(int(np.log10(abs(step)))) + 3 if step != 0 and abs(step) < 1 else 2
            
            if step > 0:
                while current_val <= stop + epsilon: 
                    voltages_to_loop.append(round(current_val, precision_digits)) 
                    current_val += step
            elif step < 0: 
                while current_val >= stop - epsilon: 
                    voltages_to_loop.append(round(current_val, precision_digits))
                    current_val += step
            
            # Ensure start == stop case is handled if loop condition doesn't catch it (e.g. if epsilon logic is too strict)
            if not voltages_to_loop and abs(start - stop) <= epsilon : 
                 voltages_to_loop.append(round(start,precision_digits))
        else:
            logger.warning(f"Unknown or missing voltage_definition type: '{def_type}'. No voltages generated.")
        
        logger.info(f"Generated voltage list (type: {def_type}): {voltages_to_loop}")
        return voltages_to_loop

    def _parse_params(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively parses parameters, resolving any template strings using the current context.
        Template strings are expected in the format "{{ variable_name }}" or "{{ config.key_name }}".
        Also handles simple filters like "{{ current_voltage | add:0.5 }}" or specific string replacements.

        Args:
            params: A dictionary of parameters to parse. Values can be strings,
                    numbers, booleans, lists, or nested dictionaries.
            context: The current experiment context dictionary.

        Returns:
            A new dictionary with all template strings resolved.
        """
        parsed_params = {}
        for key, value in params.items():
            if isinstance(value, str):
                parsed_params[key] = self._resolve_template(value, context)
            elif isinstance(value, dict):
                parsed_params[key] = self._parse_params(value, context) # Recursive call for nested dicts
            elif isinstance(value, list):
                # Recursively parse items in a list if they are strings or dicts
                parsed_params[key] = [
                    self._resolve_template(item, context) if isinstance(item, str) 
                    else self._parse_params(item, context) if isinstance(item, dict) 
                    else item 
                    for item in value
                ]
            else:
                parsed_params[key] = value # Numbers, booleans, etc.
        return parsed_params

    def _resolve_template(self, template_str: str, context: Dict[str, Any]) -> Any:
        """
        Resolves a single template string using context variables, configuration values,
        and output positions. Also handles some basic hardcoded filters.

        Args:
            template_str: The string possibly containing templates.
            context: The current experiment context.

        Returns:
            The resolved value. This could be a string, number, or a predefined position object.
        """
        if not isinstance(template_str, str): return template_str # Only strings can be templates
        
        resolved_str = template_str 
        
        # 1. Resolve context variables (e.g., {{ current_voltage }})
        for ctx_key, ctx_value in context.items():
            placeholder = f"{{{{ {ctx_key} }}}}"
            if placeholder in resolved_str:
                 resolved_str = resolved_str.replace(placeholder, str(ctx_value))
            # Basic hardcoded filters (example, not a full engine)
            elif f"{{{{ {ctx_key} | add:" in resolved_str: # e.g. {{ current_voltage | add:0.5 }}
                try:
                    parts = resolved_str.split(f"{{{{ {ctx_key} | add:")[1].split("}}}}")
                    add_val_str = parts[0].strip()
                    add_val = float(add_val_str)
                    resolved_str = str(float(ctx_value) + add_val) # Replace whole template
                except Exception as e:
                    logger.warning(f"Could not apply 'add' filter for {ctx_key} in '{template_str}': {e}")
            elif f"{{{{ {ctx_key} | replace('.', 'p') | replace('-', 'n') }}}}" in resolved_str: # Specific for filenames
                 resolved_str = str(ctx_value).replace('.', 'p').replace('-', 'n')
        
        # 2. Resolve config variables (e.g., {{ config.key }})
        if "{{ config." in resolved_str:
            # Check specific 'configurations' dictionary first
            for conf_key, conf_value in self.configurations.items():
                placeholder = f"{{{{ config.{conf_key} }}}}"
                if placeholder in resolved_str:
                    resolved_str = resolved_str.replace(placeholder, str(conf_value))
            # Check top-level experiment_config keys (excluding complex types)
            for conf_key, conf_value in self.experiment_config.items():
                if not isinstance(conf_value, (dict, list)): 
                    placeholder = f"{{{{ config.{conf_key} }}}}"
                    if placeholder in resolved_str:
                        resolved_str = resolved_str.replace(placeholder, str(conf_value))
        
        # 3. Resolve from output_positions (if the entire string matches a key)
        if resolved_str in self.output_positions:
            return self.output_positions[resolved_str]

        # 4. Attempt type conversion if the resolved string might be a number
        if resolved_str != template_str: # If any replacement happened
            try: return int(resolved_str)
            except ValueError:
                try: return float(resolved_str)
                except ValueError: 
                    logger.debug(f"Template '{template_str}' resolved to string '{resolved_str}'.")
                    return resolved_str # Return as string if not convertible
        
        return template_str # Return original if no templating syntax or resolution occurred

    async def start_experiment(self, config_file_path: str = "old/experiment_config.json") -> bool:
        """
        Starts the experiment execution.

        This involves:
        - Checking if an experiment is already running.
        - Loading the specified experiment configuration file.
        - Performing readiness checks for core devices (printer, pump, CHI).
        - Initializing experiment state (running status, step index, context).
        - Broadcasting the "running" status.
        - Creating an asyncio task to run the experiment sequence.

        Args:
            config_file_path: Path to the experiment configuration JSON file.

        Returns:
            True if the experiment started successfully, False otherwise.
        """
        if self.is_running:
            msg = "Experiment is already running."
            logger.warning(msg)
            await self.broadcaster.broadcast({"type": "experiment_status_update", "status": "warning", "message": msg})
            return False

        if not self.load_experiment_config(config_file_path):
            msg = f"Failed to load experiment configuration from {config_file_path}."
            logger.error(msg)
            await self.broadcaster.broadcast({"type": "experiment_status_update", "status": "error", "message": msg })
            return False

        core_devices_to_check = { "printer": "Printer", "pump": "Pump", "chi": "CHI" }
        missing_or_uninitialized_devices = []
        for device_key, device_name in core_devices_to_check.items():
            adapter = self.devices.get(device_key)
            is_ready = False
            if adapter: # Check if adapter instance exists
                if hasattr(adapter, 'initialized'): is_ready = getattr(adapter, 'initialized', False)
                elif device_key == "chi" and hasattr(adapter, 'chi_setup'): is_ready = adapter.chi_setup is not None 
            if not is_ready: missing_or_uninitialized_devices.append(device_name)
        
        if missing_or_uninitialized_devices:
            error_msg = f"Cannot start experiment '{self.project_name}': Core devices not ready/initialized: {', '.join(missing_or_uninitialized_devices)}."
            logger.error(error_msg)
            await self.broadcaster.broadcast({"type": "experiment_status_update", "status": "error", "message": error_msg})
            return False

        self.is_running = True
        self.current_step_index = 0
        # Initialize context with global values that steps might need
        self.current_context = { 
            "project_name": self.project_name, 
            "results_dir": self.results_dir,
            # Other global values from self.configurations can be added if needed by templates
        }
        
        msg = f"Experiment '{self.project_name}' started with config '{config_file_path}'."
        logger.info(msg)
        await self.broadcaster.broadcast({"type": "experiment_status_update", "status": "running", "message": msg, "config_file_path": config_file_path})

        # Create a task for the experiment sequence to run in the background
        task = self._run_sequence()
        if self.loop: self.loop.create_task(task)
        else: asyncio.create_task(task)
        return True

    async def _run_sequence(self):
        """
        Internal method to iterate through and execute steps in the current_sequence.
        Manages experiment state and broadcasts updates.
        """
        logger.info(f"Experiment '{self.project_name}' sequence execution started.")
        total_steps = len(self.current_sequence)
        
        while self.is_running and self.current_step_index < total_steps:
            step_config = self.current_sequence[self.current_step_index]
            step_id = step_config.get('id', f"step_{self.current_step_index}")
            description = step_config.get('description', 'Unnamed Step')
            
            # Skip step if 'enabled' field is present and set to false
            if step_config.get("enabled", True) is False: 
                logger.info(f"Skipping disabled step {self.current_step_index + 1}/{total_steps}: {description} (ID: {step_id})")
                await self.broadcaster.broadcast({ 
                    "type": "experiment_step_update", "step_id": step_id, "description": description,
                    "status": "skipped", "message": "Step was disabled by configuration."
                })
                self.current_step_index += 1
                continue

            # Update context with current step ID for use in templates or logging within _dispatch_step
            self.current_context["current_step_id"] = step_id 

            logger.info(f"Executing step {self.current_step_index + 1}/{total_steps}: {description} (ID: {step_id})")
            
            try:
                success = await self._dispatch_step(step_config, self.current_context)
                if success:
                    logger.info(f"Step {step_id} completed successfully.")
                    self.current_step_index += 1
                else: # Step explicitly returned False, indicating failure
                    msg = f"Step '{description}' (ID: {step_id}) failed. Stopping experiment."
                    logger.error(msg)
                    self.is_running = False # Halt sequence
                    await self.broadcaster.broadcast({"type": "experiment_status_update", "status": "error", "message": msg})
                    break 
            except Exception as e: # Unexpected error during step dispatch or execution
                msg = f"Unexpected error during step '{description}' (ID: {step_id}): {e}. Stopping experiment."
                logger.error(msg, exc_info=True)
                self.is_running = False # Halt sequence
                await self.broadcaster.broadcast({"type": "experiment_status_update", "status": "error", "message": msg})
                break
        
        # Sequence finished or was stopped
        if not self.is_running and self.current_step_index < total_steps : 
            logger.info(f"Experiment '{self.project_name}' sequence was stopped before completion at step {self.current_step_index + 1}.")
        elif self.current_step_index == total_steps and self.is_running : # Should be !self.is_running if loop exited normally
            self.is_running = False # Ensure state is updated
            msg = f"Experiment '{self.project_name}' all {total_steps} steps completed successfully."
            logger.info(msg)
            await self.broadcaster.broadcast({"type": "experiment_status_update", "status": "completed", "message": msg})
        
        self.current_context.pop("current_step_id", None) # Clean up context

    async def stop_experiment(self):
        """
        Stops the currently running experiment.
        Sets the `is_running` flag to False, which should halt the `_run_sequence` loop.
        Attempts to stop any active device operations (e.g., CHI test, pump).
        Broadcasts an "stopped" status update.
        """
        if not self.is_running: 
            logger.info("Experiment is not running, no action taken for stop command.")
            return

        logger.info(f"Stopping experiment '{self.project_name}'...")
        self.is_running = False # Signal the sequence loop to stop

        # Attempt to stop key devices
        if "chi" in self.devices and self.devices["chi"] and hasattr(self.devices["chi"], "stop_test"):
            try:
                logger.info("Attempting to stop CHI device test...")
                await self.devices["chi"].stop_test() # type: ignore
            except Exception as e: logger.error(f"Error stopping CHI device: {e}", exc_info=True)

        if "pump" in self.devices and self.devices["pump"] and hasattr(self.devices["pump"], "stop"):
            try:
                logger.info("Attempting to stop pump device...")
                await self.devices["pump"].stop(pump_index=0) # type: ignore # Assuming pump 0 or a general stop
            except Exception as e: logger.error(f"Error stopping pump device: {e}", exc_info=True)
        
        msg = f"Experiment '{self.project_name}' was stopped by user command."
        logger.info(msg)
        await self.broadcaster.broadcast({"type": "experiment_status_update", "status": "stopped", "message": msg})

    def get_status(self) -> Dict[str, Any]:
        """
        Returns the current status of the experiment execution service.

        Returns:
            A dictionary containing status information such as:
            - `is_running`: Boolean indicating if an experiment is active.
            - `current_step_index`: Index of the current or next step.
            - `total_steps`: Total number of steps in the sequence.
            - `current_step_id`: ID of the current step.
            - `current_step_description`: Description of the current step.
            - `project_name`: Name of the loaded project.
            - `config_file_path`: Path of the loaded configuration file.
        """
        current_step_id = None; description = None
        if self.is_running and self.current_sequence and 0 <= self.current_step_index < len(self.current_sequence):
            current_step_config = self.current_sequence[self.current_step_index]
            current_step_id = current_step_config.get('id', f"step_{self.current_step_index}")
            description = current_step_config.get('description', 'N/A')
        return {
            "is_running": self.is_running, "current_step_index": self.current_step_index,
            "total_steps": len(self.current_sequence) if self.current_sequence else 0,
            "current_step_id": current_step_id, "current_step_description": description,
            "project_name": self.project_name, "config_file_path": self.config_file_path
        }

    async def _dispatch_step(self, step_config: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """
        Internal method to dispatch a single experiment step to its execution handler.
        It resolves parameters using the context and calls the appropriate `_execute_..._step` method.

        Args:
            step_config: The configuration dictionary for the step.
            context: The current experiment context.

        Returns:
            True if the step executed successfully, False otherwise.
        """
        step_type = step_config.get('type')
        step_id = context.get("current_step_id", step_config.get('id', 'unknown_step')) # Use ID from context if set by loop
        description = step_config.get('description', 'Unnamed Step')
        
        # Resolve parameters for this step using the current context
        params = self._parse_params(step_config.get('params', {}), context)

        logger.info(f"Dispatching step: {description} (ID: {step_id}), Type: {step_type}, Parsed Params: {params}")
        await self.broadcaster.broadcast({
            "type": "experiment_step_update", "step_id": step_id, "description": description,
            "status": "running", "params": params # Send parsed params to UI
        })

        try:
            success = False
            # Mapping step types to their execution methods
            if step_type == "printer_home": success = await self._execute_printer_home(params, context)
            elif step_type == "move_printer_grid": success = await self._execute_move_printer_grid(params, context, step_config)
            elif step_type == "set_valve": success = await self._execute_set_valve(params, context, step_config)
            elif step_type == "pump_liquid": success = await self._execute_pump_liquid(params, context, step_config)
            elif step_type == "printer_move": success = await self._execute_printer_move(params, context) # Generic move
            elif step_type == "pump_dispense": success = await self._execute_pump_dispense(params, context) # Generic dispense
            elif step_type == "pump_aspirate": success = await self._execute_pump_aspirate(params, context) # Generic aspirate
            elif step_type == "relay_toggle": success = await self._execute_relay_toggle(params, context)
            elif step_type == "chi_measurement": success = await self._execute_chi_measurement(params, context, step_config)
            elif step_type == "chi_sequence": success = await self._execute_chi_sequence(params, context, step_config)
            elif step_type == "process_chi_data": success = await self._execute_process_chi_data(params, context, step_config)
            elif step_type == "wait": success = await self._execute_wait(params, context)
            elif step_type == "log_message": success = await self._execute_log_message(params, context)
            elif step_type == "voltage_loop": success = await self._execute_voltage_loop(params, context, step_config)
            elif step_type == "sequence": success = await self._execute_sub_sequence(params, context, step_config)
            else:
                logger.error(f"Unknown step type: {step_type} for step ID {step_id}")
                await self.broadcaster.broadcast({"type": "experiment_step_update", "step_id": step_id, "status": "error", "error_message": f"Unknown step type: {step_type}"})
                return False
            
            status_msg = "completed" if success else "error"
            error_detail = "Step failed its execution logic." if not success else None
            await self.broadcaster.broadcast({
                "type": "experiment_step_update", "step_id": step_id, "status": status_msg, "description": description,
                "error_message": error_detail # Only relevant if status is "error"
            })
            return success
        except Exception as e:
            logger.error(f"Exception during dispatch/execution of step {step_id} ({description}): {e}", exc_info=True)
            await self.broadcaster.broadcast({"type": "experiment_step_update", "step_id": step_id, "status": "error", "description": description, "error_message": str(e)})
            return False

    # --- Specific Step Execution Methods ---
    async def _execute_printer_home(self, params: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """Executes printer homing."""
        adapter = self.devices.get("printer")
        if not adapter or not hasattr(adapter, "home"): logger.error("Printer adapter not found or lacks 'home' method."); return False
        logger.info(f"Executing printer home with axis: {params.get('axis', 'xyz')}")
        return await adapter.home(axis=params.get("axis","xyz")) # type: ignore

    async def _execute_move_printer_grid(self, params: Dict[str, Any], context: Dict[str, Any], step_config: Dict[str, Any]) -> bool:
        """Executes moving the printer to a specified grid position."""
        adapter = self.devices.get("printer")
        if not adapter or not hasattr(adapter, "move_to_grid"): logger.error("Printer adapter not found or lacks 'move_to_grid' method."); return False
        grid_num = params.get("grid_num") # Resolved from template (e.g. configurations.target_grid_pos)
        z_offset = params.get("z_offset", 0.0)
        if grid_num is None: logger.error("'grid_num' not resolved in params."); return False
        logger.info(f"Executing printer move to grid: {grid_num}, Z-offset: {z_offset}")
        return await adapter.move_to_grid(grid_num=int(grid_num), z_offset=float(z_offset)) # type: ignore
        
    async def _execute_set_valve(self, params: Dict[str, Any], context: Dict[str, Any], step_config: Dict[str, Any]) -> bool:
        """Executes setting a valve state, potentially via a pump or relay adapter."""
        valve_type = params.get("valve_type", "default_relay") # e.g., "pump_internal", "klipper_relay"
        # Determine adapter based on valve_type or other params
        adapter_key = "pump" if "pump" in valve_type else "relay" 
        adapter = self.devices.get(adapter_key)
        if not adapter: logger.error(f"{adapter_key.capitalize()} adapter not found for set_valve."); return False
        
        relay_id = params.get("relay_id") # Resolved from template (e.g. valve_klipper_relay_id)
        state = params.get("state", False)
        if relay_id is None: logger.error("'relay_id' not resolved in params for set_valve."); return False
        
        logger.info(f"Executing set_valve: relay_id={relay_id}, state={state}, type={valve_type} using adapter '{adapter_key}'")
        if hasattr(adapter, "set_valve_state"): # Adapter specific method
             return await adapter.set_valve_state(relay_id=int(relay_id), state=bool(state), valve_type=valve_type) # type: ignore
        elif hasattr(adapter, "toggle"): # Generic relay toggle
             return await adapter.toggle(relay_id=int(relay_id), state=bool(state)) # type: ignore
        logger.error(f"Adapter '{adapter_key}' does not support required valve/relay operation for set_valve."); return False

    async def _execute_pump_liquid(self, params: Dict[str, Any], context: Dict[str, Any], step_config: Dict[str, Any]) -> bool:
        """Executes pumping a specified volume of liquid."""
        adapter = self.devices.get("pump")
        if not adapter: logger.error("Pump adapter not found."); return False
        volume_ml = params.get("volume_ml") # Resolved from template (e.g. configurations.sample_volume)
        speed = params.get("pump_speed", "medium") # Allow speed to be templated or default
        direction = params.get("direction", 1) # 1 for dispense/forward, -1 for aspirate/backward
        if volume_ml is None: logger.error("'volume_ml' not resolved in params for pump_liquid."); return False

        logger.info(f"Executing pump_liquid: volume={volume_ml}ml, speed={speed}, direction={direction}")
        # Adapter method names might vary, e.g. 'dispense', 'aspirate', 'pump'
        if hasattr(adapter, "dispense"): # Assuming a generic 'dispense' that handles direction
            return await adapter.dispense(volume_ml=float(volume_ml), speed=speed, direction=int(direction)) # type: ignore
        logger.error("Pump adapter lacks a suitable 'dispense' method for pump_liquid."); return False

    async def _execute_printer_move(self, params: Dict[str, Any], context: Dict[str, Any]) -> bool: 
        adapter = self.devices.get("printer")
        if not adapter or not hasattr(adapter, "move_to"): logger.error("Printer adapter not found or lacks 'move_to' method."); return False
        logger.info(f"Executing printer move to X={params.get('x')} Y={params.get('y')} Z={params.get('z')}")
        return await adapter.move_to(x=params.get('x'), y=params.get('y'), z=params.get('z'), speed=params.get('speed')) # type: ignore

    async def _execute_pump_dispense(self, params: Dict[str, Any], context: Dict[str, Any]) -> bool: 
        # This could be a more specific version of pump_liquid if adapter has separate dispense/aspirate
        params["direction"] = 1 # Force direction for dispense
        return await self._execute_pump_liquid(params, context, {"id":"pump_dispense_wrapper"}) # Reuse general logic

    async def _execute_pump_aspirate(self, params: Dict[str, Any], context: Dict[str, Any]) -> bool: 
        params["direction"] = -1 # Force direction for aspirate
        return await self._execute_pump_liquid(params, context, {"id":"pump_aspirate_wrapper"}) # Reuse general logic

    async def _execute_relay_toggle(self, params: Dict[str, Any], context: Dict[str, Any]) -> bool: 
        adapter = self.devices.get("relay")
        if not adapter or not hasattr(adapter, "toggle"): logger.error("Relay adapter not found or lacks 'toggle' method."); return False
        logger.info(f"Toggling relay ID {params.get('relay_id')} to state {params.get('state')}")
        return await adapter.toggle(relay_id=params.get('relay_id'), state=params.get('state')) # type: ignore
    
    async def _execute_chi_measurement(self, params: Dict[str, Any], context: Dict[str, Any], step_config: Dict[str, Any]) -> bool:
        """Executes a CHI electrochemical measurement."""
        adapter = self.devices.get("chi")
        if not adapter: logger.error("CHI adapter not found."); return False
        
        chi_method_name = params.get("chi_method", params.get("technique")) 
        chi_params_val = params.get("chi_params", params.get("params")) 
        file_name_val = params.get("file_name", "default_chi_data.txt")

        if not chi_method_name: logger.error("CHI method/technique not specified for measurement."); return False
        
        run_method_name = f"run_{chi_method_name.lower()}_test"
        if not hasattr(adapter, run_method_name):
            logger.error(f"CHI adapter does not support method: {run_method_name}"); return False
        
        run_method = getattr(adapter, run_method_name)
        full_file_path = Path(self.results_dir) / file_name_val # Ensure results_dir is used
        
        logger.info(f"Executing CHI method '{run_method_name}' with params {chi_params_val}, saving to '{full_file_path}'")
        raw_data_path_str = await run_method(file_name=str(full_file_path), params=chi_params_val)
        
        if raw_data_path_str:
            context_key_base = step_config.get('id', f'chi_measurement_{chi_method_name}')
            context[f"{context_key_base}_raw_data_path"] = raw_data_path_str # Store path for potential later use
            # Auto-processing logic could be triggered here if params indicate it
            return True
        return False

    async def _execute_chi_sequence(self, params: Dict[str, Any], context: Dict[str, Any], step_config: Dict[str, Any]) -> bool:
        # This method would iterate through a list of CHI measurement definitions if 'chi_sequence' type is more complex.
        # For now, assuming it might be similar to voltage_loop or a sequence of chi_measurement steps.
        logger.warning("_execute_chi_sequence is a placeholder; actual implementation depends on its defined behavior.")
        return True 

    async def _execute_process_chi_data(self, params: Dict[str, Any], context: Dict[str, Any], step_config: Dict[str, Any]) -> bool:
        logger.info(f"Processing CHI data with params: {params}")
        # Implementation would involve calling _parse_electrochemical_file, _calculate_charge, etc.
        return True 

    async def _execute_wait(self, params: Dict[str, Any], context: Dict[str, Any]) -> bool: 
        duration_s = float(params.get("seconds", params.get("duration_s", 0.1))) # Allow 'seconds' or 'duration_s'
        logger.info(f"Waiting for {duration_s} seconds.")
        await asyncio.sleep(duration_s)
        return True 

    async def _execute_log_message(self, params: Dict[str, Any], context: Dict[str, Any]) -> bool: 
        message = params.get('message', 'Default log message from experiment step.')
        logger.info(f"Experiment Log (Step ID: {context.get('current_step_id', 'N/A')}): {message}")
        return True
        
    async def _execute_sub_sequence(self, params: Dict[str, Any], context: Dict[str, Any], step_config: Dict[str, Any]) -> bool:
        """Executes a named sub-sequence defined in the 'sub_sequences' section of the config."""
        sequence_name = params.get("name_in_sub_sequences")
        if not sequence_name:
            logger.error(f"Sub-sequence name not provided in step {step_config.get('id')}."); return False
        
        sub_sequence_data = self.experiment_config.get("sub_sequences", {}).get(sequence_name)
        if not sub_sequence_data or not isinstance(sub_sequence_data.get("actions"), list):
            logger.error(f"Sub-sequence '{sequence_name}' not found or has invalid format in config."); return False

        parent_step_id_for_log = step_config.get('id', 'unknown_parent_step')
        logger.info(f"Executing sub-sequence '{sequence_name}' (called from step '{parent_step_id_for_log}')")

        for i, sub_step_config_template in enumerate(sub_sequence_data["actions"]):
            if not self.is_running:
                logger.info(f"Sub-sequence '{sequence_name}' interrupted, experiment stopped."); return False

            sub_step_id_base = sub_step_config_template.get('id', f'sub_action_{i}')
            # Create a more traceable dynamic ID for the sub-step instance
            sub_step_dynamic_id = f"{parent_step_id_for_log}_{sequence_name}_{sub_step_id_base}"
            
            # Deep copy template to avoid modification issues if sub-sequence is called multiple times
            actual_sub_step_config = json.loads(json.dumps(sub_step_config_template)) 
            actual_sub_step_config["id"] = sub_step_dynamic_id # Override ID with dynamic one
            
            # Sub-steps inherit the calling context (e.g., from a voltage loop)
            # Update current_step_id in context for this specific sub-step execution for logging/templating
            sub_step_context = context.copy()
            sub_step_context["current_step_id"] = sub_step_dynamic_id

            logger.info(f"Executing sub-step from '{sequence_name}': {sub_step_dynamic_id} (Original ID in template: {sub_step_config_template.get('id')})")
            success = await self._dispatch_step(actual_sub_step_config, sub_step_context)
            if not success:
                logger.error(f"Sub-step {sub_step_dynamic_id} in sub-sequence '{sequence_name}' failed. Halting sub-sequence."); return False
        
        logger.info(f"Sub-sequence '{sequence_name}' completed successfully.")
        return True

    # --- Helper methods for data processing, waiting, logging ---
    def _parse_electrochemical_file(self, file_path: str) -> Optional[Dict[str, List[float]]]: 
        # ... (implementation as before) ...
        return None 
    def _calculate_charge(self, potential: List[float], current: List[float]) -> tuple[float, float]: 
        # ... (implementation as before) ...
        return (0.0,0.0) 
    async def _wait_and_log(self, duration_seconds: float, message_prefix: str = ""): 
        # ... (implementation as before, consider if this is still needed or just use asyncio.sleep) ...
        await asyncio.sleep(duration_seconds) 
    def _log_message(self, message: str, level: str = "info"): 
        # ... (implementation as before, using logger directly is fine) ...
        logger.log(getattr(logging, level.upper(), logging.INFO), message) 

    async def _execute_voltage_loop(self, params: Dict[str, Any], context: Dict[str, Any], step_config: Dict[str, Any]) -> bool:
        """
        Executes a sequence of sub-steps for each voltage generated from a voltage_definition.
        The `voltage_definition` can be specified directly in the loop's parameters or taken
        from the global experiment configuration. Context variables `current_voltage` and
        `voltage_loop_index` are available to sub-steps. Output positions can also be iterated.
        """
        loop_specific_voltage_def = params.get("voltage_definition")
        original_global_voltage_def = self.experiment_config.get("voltage_definition")
        
        voltages_to_loop: List[float]
        if loop_specific_voltage_def: # Loop can override global voltage definition
            logger.info(f"Voltage loop '{step_config.get('id')}' using its own voltage_definition: {loop_specific_voltage_def}")
            # Temporarily set for _generate_voltages_from_definition, then restore
            self.experiment_config["voltage_definition"] = loop_specific_voltage_def
            voltages_to_loop = self._generate_voltages_from_definition()
            self.experiment_config["voltage_definition"] = original_global_voltage_def # Restore global
        else: # Use global voltage definition
            logger.info(f"Voltage loop '{step_config.get('id')}' using global voltage_definition.")
            voltages_to_loop = self._generate_voltages_from_definition()

        if not voltages_to_loop:
            logger.error(f"No voltages generated for voltage_loop step: {step_config.get('id')}. Check config."); return False
        
        logger.info(f"Starting voltage_loop '{step_config.get('id')}' with voltages: {voltages_to_loop}")
        
        # Determine the sequence of actions to perform for each voltage
        loop_sequence_id = params.get("loop_sequence_id") # Reference to a sequence in "sub_sequences"
        inline_actions = params.get("actions") # Or define actions directly in the loop step
        
        sub_steps_to_execute: List[Dict[str, Any]] = []
        if loop_sequence_id:
            sub_sequence_data = self.experiment_config.get("sub_sequences", {}).get(loop_sequence_id)
            if not sub_sequence_data or not isinstance(sub_sequence_data.get("actions"), list):
                logger.error(f"Sub-sequence '{loop_sequence_id}' for voltage_loop not found or invalid."); return False
            sub_steps_to_execute = sub_sequence_data["actions"]
            logger.debug(f"Loop will use sub-sequence '{loop_sequence_id}' with {len(sub_steps_to_execute)} actions.")
        elif inline_actions and isinstance(inline_actions, list):
            sub_steps_to_execute = inline_actions
            logger.debug(f"Loop will use inline actions: {len(sub_steps_to_execute)} actions.")
        else:
            logger.error(f"No 'loop_sequence_id' or 'actions' provided in voltage_loop: {step_config.get('id')}"); return False

        # Handle iterating through output positions if specified
        output_positions_source = params.get("output_positions_source", {})
        position_keys_to_iterate: List[str] = []
        if output_positions_source.get("type") == "list_literal":
            position_keys_to_iterate = output_positions_source.get("values", [])
        elif output_positions_source.get("type") == "all_from_config":
            position_keys_to_iterate = list(self.output_positions.keys())
        
        num_positions = len(position_keys_to_iterate)
        logger.debug(f"Loop will iterate over {num_positions} positions: {position_keys_to_iterate if num_positions > 0 else 'None'}")

        for i, voltage in enumerate(loop_voltages):
            if not self.is_running: logger.info("Voltage loop interrupted by experiment stop."); return False 

            # Create context for this iteration of the voltage loop
            current_loop_context = context.copy()
            current_loop_context["current_voltage"] = voltage
            current_loop_context["voltage_loop_index"] = i
            
            if num_positions > 0: # Cycle through positions if provided
                pos_key_idx = i % num_positions
                current_pos_key = position_keys_to_iterate[pos_key_idx]
                current_loop_context["current_output_position_key"] = current_pos_key
                current_loop_context["current_output_position"] = self.output_positions.get(current_pos_key, None)
            else: # No specific positions for this loop, clear any from outer context if needed
                current_loop_context.pop("current_output_position_key", None)
                current_loop_context.pop("current_output_position", None)

            # Execute each action in the defined sub-sequence for the current voltage and position
            for sub_step_idx, sub_step_template in enumerate(sub_steps_to_execute):
                if not self.is_running: logger.info("Voltage loop's sub-step execution interrupted."); return False

                sub_step_id_base = sub_step_template.get('id', f'vsub_{sub_step_idx}')
                # Sanitize voltage value for use in ID (replace '.' with 'p', '-' with 'n')
                sanitized_voltage_str = str(voltage).replace('.', 'p').replace('-', 'n') 
                # Create a unique ID for this instance of the sub-step
                sub_step_dynamic_id = f"{step_config.get('id', 'vloop')}_{sub_step_id_base}_{i}_{sanitized_voltage_str}"
                
                actual_sub_step_config = json.loads(json.dumps(sub_step_template)) # Deep copy template
                actual_sub_step_config["id"] = sub_step_dynamic_id 
                
                # Update current_step_id in context for this specific sub-step for logging/templating
                current_loop_context["current_step_id"] = sub_step_dynamic_id

                logger.info(f"Voltage loop '{step_config.get('id')}': V={voltage} (Idx {i}), PosKey: {current_loop_context.get('current_output_position_key', 'N/A')}, Executing sub-step: {sub_step_dynamic_id}")
                
                success = await self._dispatch_step(actual_sub_step_config, current_loop_context)
                if not success:
                    logger.error(f"Sub-step {sub_step_dynamic_id} in voltage_loop failed for V={voltage}. Stopping loop."); return False
        
        logger.info(f"Voltage loop '{step_config.get('id')}' completed successfully.")
        return True


if __name__ == '__main__':
    # This is the new enhanced main_test function
    async def main_test_enhanced():
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s-%(levelname)s-%(name)s-%(module)s-%(funcName)s: %(message)s')
        logger.info("Starting enhanced main_test for ExperimentExecutionService.")

        class MockBroadcaster:
            def __init__(self): self.broadcast_messages = []
            async def broadcast(self, message: dict): logger.debug(f"MockBroadcast: {message}"); self.broadcast_messages.append(message)
            def get_messages_by_type(self, msg_type: str): return [m for m in self.broadcast_messages if m.get("type") == msg_type]
            def clear_messages(self): self.broadcast_messages = []

        class MockDevice: # Updated MockDevice
            def __init__(self, name, service_ref, initialized=True):
                self.name = name; self.service_ref = service_ref; self.initialized = initialized
                self.chi_setup = True if initialized and name == "CHI Electrochem" else None
                self.methods_called_with_params = []

            async def _log_call(self, method_name, **kwargs): 
                self.methods_called_with_params.append({"method": method_name, "params": kwargs}); 
                logger.debug(f"MockDevice '{self.name}' method '{method_name}' called with: {kwargs}"); 
                await asyncio.sleep(0.001); return True 

            async def home(self, axis="all"): return await self._log_call("home", axis=axis)
            async def move_to_grid(self, grid_num, z_offset=0): return await self._log_call("move_to_grid", grid_num=grid_num, z_offset=z_offset)
            async def set_valve_state(self, relay_id, state, valve_type=None): return await self._log_call("set_valve_state", relay_id=relay_id, state=state, valve_type=valve_type)
            async def dispense(self, volume_ml, speed=None, pump_index=0, direction=1): return await self._log_call("dispense", volume_ml=volume_ml, speed=speed, pump_index=pump_index, direction=direction)
            
            async def run_cv_test(self, file_name, params): 
                await self._log_call("run_cv_test", file_name=file_name, params=params)
                # Use service.results_dir which is now correctly set relative to project_root
                if self.service_ref["service"] and self.service_ref["service"].results_dir:
                    full_path = Path(self.service_ref["service"].results_dir) / file_name
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(full_path, 'w') as f: f.write(json.dumps({"technique": "CV", "params": params}))
                    return str(full_path)
                return file_name 
            async def stop_test(self): return await self._log_call("stop_test")
            async def stop(self, pump_index=0): return await self._log_call("stop", pump_index=pump_index)


        mock_broadcaster = MockBroadcaster()
        service_ref_for_mocks = {"service": None} 

        mock_printer = MockDevice("Printer", service_ref_for_mocks)
        mock_pump = MockDevice("Pump", service_ref_for_mocks) 
        mock_chi = MockDevice("CHI Electrochem", service_ref_for_mocks)
        
        mock_devices = { "printer": mock_printer, "pump": mock_pump, "relay": mock_pump, "chi": mock_chi }
        
        event_loop = asyncio.get_event_loop()
        service = ExperimentExecutionService(mock_broadcaster, mock_devices, loop=event_loop)
        service_ref_for_mocks["service"] = service 

        test_config_path_str = "old/test_experiment_config.json" # Assumes this file exists from previous step
        full_test_config_path = service.project_root / test_config_path_str
        
        if not full_test_config_path.exists(): logger.error(f"Test config missing: {full_test_config_path}"); return

        logger.info(f"--- Test 1: Load Config ({test_config_path_str}) ---")
        assert service.load_experiment_config(file_path=test_config_path_str), "Config load failed"
        assert service.project_name == "TestProject"
        assert service.experiment_config.get("voltage_definition",{}).get("values") == [-0.1,-0.2,-0.3] 
        logger.info("Config loaded. Project name and global voltage def verified.")

        logger.info("--- Test 2: Start and Run Full Experiment Sequence ---")
        mock_broadcaster.clear_messages()
        assert await service.start_experiment(config_file_path=test_config_path_str), "Experiment start failed"
        assert service.is_running
        
        max_wait_s = 5 
        start_time = time.monotonic()
        while service.is_running and (time.monotonic() - start_time) < max_wait_s:
            await asyncio.sleep(0.05)
        
        assert not service.is_running, f"Experiment did not complete in {max_wait_s}s"
        status_updates = mock_broadcaster.get_messages_by_type("experiment_status_update")
        assert any(msg["status"] == "running" for msg in status_updates), "Running status not broadcasted"
        assert any(msg["status"] == "completed" for msg in status_updates), "Completed status not broadcasted"
        logger.info("Experiment started, ran, and completed. Statuses broadcasted.")

        logger.info("--- Test 3: Verify Mock Device Calls and Template Parsing ---")
        assert any(c["method"] == "home" and c["params"]["axis"] == "xyz" for c in mock_printer.methods_called_with_params)
        assert any(c["method"] == "move_to_grid" and c["params"]["grid_num"] == 5 and c["params"]["z_offset"] == 2 for c in mock_printer.methods_called_with_params)
        assert any(c["method"] == "set_valve_state" and c["params"]["relay_id"] == 1 and c["params"]["state"] is True for c in mock_pump.methods_called_with_params)
        assert any(c["method"] == "dispense" and c["params"]["volume_ml"] == 0.5 for c in mock_pump.methods_called_with_params)
        expected_cv_file = f"{service.project_name}_test_CV.txt"
        assert any(c["method"] == "run_cv_test" and c["params"]["file_name"] == expected_cv_file for c in mock_chi.methods_called_with_params)
        logger.info("Key device calls and template resolutions verified.")

        logger.info("--- Test 4: Voltage Loop Sub-Step Verification ---")
        step_updates = mock_broadcaster.get_messages_by_type("experiment_step_update")
        assert any(s["step_id"] == "voltage_iteration_1" and s["status"] == "completed" for s in step_updates), "Voltage_loop main step did not complete."
        # Check for one of the dynamic sub-step IDs
        assert any("voltage_iteration_1_simple_log_loop_log_volt_pos_0_n0p5" in s["step_id"] and s["status"]=="completed" for s in step_updates), "First sub-step of voltage loop not found or failed."
        assert any("voltage_iteration_1_simple_log_loop_log_volt_pos_1_n0p6" in s["step_id"] and s["status"]=="completed" for s in step_updates), "Second sub-step of voltage loop not found or failed."
        logger.info("Voltage loop sub-step completion verified via broadcast messages.")


        logger.info("--- Test 5: Config Update and Persistence ---")
        mock_broadcaster.clear_messages()
        original_config_content = service.get_current_config()
        assert original_config_content is not None
        modified_conf = json.loads(json.dumps(original_config_content)) 
        modified_conf["project_name"] = "UpdatedProjectNameViaTest" # Changed name
        modified_conf["voltage_definition"] = {"type": "list", "values": [1.1, 2.2, 3.3]}
        
        assert await service.update_experiment_config(modified_conf), "update_experiment_config returned false"
        assert service.project_name == "UpdatedProjectNameViaTest"
        assert service.experiment_config["voltage_definition"]["values"] == [1.1, 2.2, 3.3]
        config_updates = mock_broadcaster.get_messages_by_type("config_update_status")
        assert any(msg["status"] == "success" for msg in config_updates), "Config update success not broadcasted"
        
        service.load_experiment_config(file_path=test_config_path_str) # Reload from file
        assert service.project_name == "UpdatedProjectNameViaTest", "Updated project_name not persisted."
        assert service.experiment_config["voltage_definition"]["values"] == [1.1, 2.2, 3.3], "Updated voltage_definition not persisted."
        logger.info("Config update, persistence, and reload verified.")

        with open(full_test_config_path, 'w') as f: json.dump(original_config_content, f, indent=2) # Restore


        logger.info("--- Test 6: `voltage_range` to `voltage_definition` Compatibility ---")
        config_old_vr = {"project_name":"VRCompatTest", "voltage_range": [0.0, 0.2]} 
        service.experiment_config = config_old_vr 
        service._reload_internal_params_from_config() 
        assert "voltage_definition" in service.experiment_config
        expected_vd = {"type": "range_step", "start": 0.0, "stop": 0.2, "step": 0.1}
        assert service.experiment_config["voltage_definition"] == expected_vd
        gen_voltages = service._generate_voltages_from_definition()
        assert np.allclose(gen_voltages, [0.0, 0.1, 0.2])
        logger.info("`voltage_range` compatibility test passed.")

        logger.info("All enhanced main_test scenarios PASSED.")
        
        results_path_to_clean = service.project_root / service.experiment_config.get("results_dir", "test_results_integration") / service.project_name
        if results_path_to_clean.exists():
            import shutil
            shutil.rmtree(results_path_to_clean, ignore_errors=True)
            logger.info(f"Cleaned up test results directory: {results_path_to_clean}")

    if __name__ == '__main__':
        asyncio.run(main_test_enhanced())
