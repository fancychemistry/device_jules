import json
import logging
import asyncio
import re # For parsing array indices
import time # For filenames in CHI tests
from experiment_config_manager import ExperimentConfigManager

logger = logging.getLogger(__name__)

class ExperimentController:
    def __init__(self, devices_dict, broadcaster_instance, global_config):
        self.devices = devices_dict
        self.broadcaster = broadcaster_instance
        self.config = global_config # This is device_tester.config (main FastAPI app's config)
        self.config_manager = ExperimentConfigManager()

        self.current_experiment = None
        self.experiment_status = "idle"  # "idle", "running", "paused", "completed", "error"
        self.current_step_index = -1
        self.current_step_id = None
        self.experiment_task = None  # To hold the asyncio task for _run_sequence

    def load_experiment(self, file_path: str) -> bool:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                experiment_data = json.load(f)
            
            self.current_experiment = experiment_data
            self.experiment_status = "idle"
            self.current_step_index = -1
            self.current_step_id = None
            self.experiment_task = None # Reset task if a new experiment is loaded
        # Initialize loop-related attributes that might be used by sub-sequences or loops
        self.current_loop_iterations = {} # E.g. {"loop1": 2} # Stores current iteration count for named loops
        self.loop_data = {} # E.g. {"loop1": {"current_item": "A", "current_index": 0}} # Stores current item/index for named loops
        
        loaded_data = self.config_manager.load_config(file_path)
        if loaded_data is None:
            # Specific error already logged by config_manager.load_config
            logger.error(f"Failed to load experiment from {file_path} due to issues reported by ExperimentConfigManager.")
            return False

        is_valid = self.config_manager.validate_config(loaded_data)
        if not is_valid:
            # Specific error already logged by config_manager.validate_config
            logger.error(f"Experiment configuration from {file_path} failed validation.")
            self.current_experiment = None
            return False

        self.current_experiment = loaded_data
        self.experiment_status = "idle"
        self.current_step_index = -1
        self.current_step_id = None
        self.experiment_task = None # Reset task if a new experiment is loaded
        self.current_loop_iterations = {} 
        self.loop_data = {}
        logger.info(f"Experiment successfully loaded and validated from {file_path}")
        return True

    def start_experiment(self) -> bool:
        if self.experiment_status == "running" and self.experiment_task and not self.experiment_task.done():
            logger.warning("Experiment is already running.")
            return False
        
        if self.current_experiment is None:
            logger.error("No experiment loaded to start.")
            return False

        self.experiment_status = "running"
        self.current_step_index = -1 # Will be incremented at the start of the loop
        # self.current_step_id = None # Will be set at the start of each step
        self.current_loop_iterations = {}
        self.loop_data = {}
        
        # Cancel any previous task (e.g., if it was paused and now restarted, though pause isn't implemented yet)
        if self.experiment_task and not self.experiment_task.done():
            self.experiment_task.cancel()

        self.experiment_task = asyncio.create_task(self._run_sequence()) # Root call
        logger.info("Experiment sequence started.")
        
        # Initial status broadcast for the main experiment
        total_steps = 0
        if self.current_experiment and "experiment_sequence" in self.current_experiment:
            total_steps = len(self.current_experiment.get("experiment_sequence", []))
        
        # Reset loop context for a new run
        self.current_loop_iterations = {}
        self.loop_data = {}

        asyncio.create_task(self.broadcaster.broadcast({
            "type": "experiment_status", 
            "status": self.experiment_status,
            "experiment_name": self.current_experiment.get("name"),
            "total_steps": total_steps
        }))
        return True

    def _get_value_from_key_path(self, key_path: str, default=None, context_vars=None):
        """
        Retrieves a value from self.current_experiment using a dot-separated key_path.
        Handles basic array indexing like path.to.array[0].
        Also checks context_vars for direct key_path matches (for loop variables etc.).
        """
        if context_vars and key_path in context_vars:
            return context_vars[key_path]

        # Fallback to current_experiment if not in context_vars
        target_dict = self.current_experiment
        if not target_dict:
            return default
        
        # Check for array index
        match = re.match(r"(.+)\[(\d+)\]$", key_path)
        array_index = None
        if match:
            key_path, array_index_str = match.groups()
            array_index = int(array_index_str)

        current_value = target_dict
        try:
            for key_part in key_path.split('.'):
                if not isinstance(current_value, dict):
                    logger.warning(f"Cannot access key '{key_part}' in non-dict: {current_value} (key_path: {key_path})")
                    return default
                current_value = current_value[key_part]
            
            if array_index is not None:
                if isinstance(current_value, list) and array_index < len(current_value):
                    return current_value[array_index]
                else:
                    logger.warning(f"Index {array_index} out of bounds or not a list for key_path: {key_path}")
                    return default
            return current_value
        except (KeyError, TypeError, IndexError) as e:
            logger.warning(f"Could not resolve key_path '{key_path}': {e}")
            return default

    def _resolve_params(self, params_config: dict, context_vars=None) -> dict:
        resolved_params = {}
        if not isinstance(params_config, dict):
            logger.warning("params_config is not a dictionary, cannot resolve.")
            return {}
        
        effective_context = context_vars or {}

        for key, value in params_config.items():
            resolved_value = None
            if isinstance(value, str):
                if key.endswith("_key"):
                    actual_key = key[:-4]
                    # Value is a key_path to look up, first in context_vars, then in self.current_experiment
                    resolved_value = self._get_value_from_key_path(value, context_vars=effective_context)
                    if resolved_value is not None:
                        resolved_params[actual_key] = resolved_value
                    else:
                        logger.warning(f"Could not resolve value for {key}: '{value}' from experiment config or context.")
                        resolved_params[actual_key] = None 
                else:
                    # Regular string value, keep as is for now, placeholder substitution will happen next
                    resolved_params[key] = value 
            else:
                # Non-string value, take as is
                resolved_params[key] = value
        
        # Second pass for placeholder substitution
        for key, value in resolved_params.items():
            if isinstance(value, str):
                # Find all placeholders like {{placeholder_name}}
                placeholders = re.findall(r"\{\{(.*?)\}\}", value)
                temp_value = value
                for placeholder_name in placeholders:
                    if placeholder_name in effective_context:
                        replacement = str(effective_context[placeholder_name]) # Ensure replacement is string
                        temp_value = temp_value.replace(f"{{{{{placeholder_name}}}}}", replacement)
                    else:
                        logger.warning(f"Placeholder '{{{{{placeholder_name}}}}}' not found in context_vars. Leaving as is.")
                resolved_params[key] = temp_value
            elif isinstance(value, list): # Handle lists of strings for placeholder substitution
                new_list = []
                for item_idx, item in enumerate(value):
                    if isinstance(item, str):
                        placeholders = re.findall(r"\{\{(.*?)\}\}", item)
                        temp_item_value = item
                        for placeholder_name in placeholders:
                            if placeholder_name in effective_context:
                                replacement = str(effective_context[placeholder_name])
                                temp_item_value = temp_item_value.replace(f"{{{{{placeholder_name}}}}}", replacement)
                            else:
                                logger.warning(f"Placeholder '{{{{{placeholder_name}}}}}' in list item '{item}' not found in context_vars. Leaving as is.")
                        new_list.append(temp_item_value)
                    else:
                        new_list.append(item) # Keep non-string items as they are
                resolved_params[key] = new_list
            # Note: Placeholders in nested dicts within params are not currently supported by this simple loop.
            # If needed, _resolve_params would need to be recursive.

        return resolved_params

    def _format_voltage_for_filename(self, voltage: float) -> str:
        """Converts a float voltage into a string suitable for filenames."""
        if voltage == 0.0:
            return "0p0"
        # Format to handle up to e.g. 3 decimal places, adjust as needed
        # Replace '.' with 'p', and if negative, prepend 'm' and remove '-'
        s = f"{voltage:.3f}" # Ensure a consistent format, e.g., "1.000", "-0.500"
        s = s.rstrip('0').rstrip('.') # Remove trailing zeros and then dot if it's the last char
        
        if s.startswith('-'):
            return "m" + s[1:].replace('.', 'p')
        else:
            return s.replace('.', 'p')

    async def _run_sequence(self, current_sequence=None, is_sub_sequence=False, loop_context_vars=None):
        if not is_sub_sequence: # This is a top-level call
            if self.current_experiment is None or "experiment_sequence" not in self.current_experiment:
                self.experiment_status = "error"
                logger.error("Experiment data or sequence not found for top-level run.")
                if self.broadcaster: await self.broadcaster.broadcast({"type": "experiment_status", "status": "error", "error_message": "Experiment data or sequence not found."})
                return False # Indicate error
            sequence_steps = self.current_experiment.get("experiment_sequence", [])
            # Initialize base context for the entire experiment run
            base_context_vars = {"project_name": self.current_experiment.get("project_name", "DefaultProject")}
            # Add other global/experiment-level variables to base_context_vars if needed
            # For example, variables from a "global_variables" section in the experiment config
            if "global_variables" in self.current_experiment:
                base_context_vars.update(self.current_experiment["global_variables"])

            if self.experiment_status != "running": self.experiment_status = "running"
        else: # This is a sub-sequence call (e.g., from a loop or conditional step)
            if current_sequence is None:
                logger.error("Sub-sequence called without providing a sequence list.")
                return False # Indicate error
            sequence_steps = current_sequence
            base_context_vars = {} # Sub-sequences inherit context through loop_context_vars primarily

        # Combine base context (from main experiment or empty for sub-seq) with loop-specific context
        combined_context_vars = base_context_vars.copy()
        if loop_context_vars:
            combined_context_vars.update(loop_context_vars)

        default_waits = self.current_experiment.get("default_wait_times", {}) if self.current_experiment else {}

        for index, step_config in enumerate(sequence_steps):
            if not is_sub_sequence and self.experiment_status != "running":
                logger.info(f"Main experiment status changed to {self.experiment_status}, stopping sequence.")
                return False 

            if not is_sub_sequence: # Update main experiment's step index
                self.current_step_index = index
            
            step_id = step_config.get("id", f"step_{index}")
            self.current_step_id = step_id
            description = step_config.get("description", "")
            step_type = step_config.get("type")
            is_enabled = step_config.get("enabled", True)

            await self.broadcaster.broadcast({
                "type": "experiment_step_update", # More general update type
                "step_index": index,
                "step_id": step_id,
                "description": description,
                "status": "pending" # Indicates the controller is about to process this step
            })

            if not is_enabled:
                logger.info(f"Step '{step_id}': '{description}' is disabled, skipping.")
                await self.broadcaster.broadcast({"type": "experiment_step_status", "step_id": step_id, "status": "skipped", "description": description, "step_index": index})
                await asyncio.sleep(0.1) # Small delay for UI to catch up
                continue

            logger.info(f"Executing step {index + 1}/{len(sequence_steps)} (ID: {step_id}): '{description}' of type '{step_type}'")
            await self.broadcaster.broadcast({"type": "experiment_step_status", "step_id": step_id, "status": "running", "description": description, "step_index": index})

            try:
                params_config = step_config.get("params", {})
                resolved_params = self._resolve_params(params_config, context_vars=combined_context_vars)
                logger.debug(f"Step '{step_id}' - Original Params: {params_config}, Resolved Params: {resolved_params}, Context: {combined_context_vars}")

                printer_involved = False
                relay_involved = False
                pump_involved = False
                chi_involved = False

                if step_type == "printer_home":
                    if not self.devices.get("printer") or not self.devices["printer"].initialized:
                        raise ValueError("Printer not available or not initialized for homing.")
                    await self.devices["printer"].home()
                    await asyncio.sleep(default_waits.get("after_printer_home", default_waits.get("after_printer_move", 2.0)))
                    printer_involved = True
                elif step_type == "move_printer_xyz":
                    if not self.devices.get("printer") or not self.devices["printer"].initialized:
                        raise ValueError("Printer not available or not initialized for move_xyz.")
                    x, y, z = resolved_params.get("x"), resolved_params.get("y"), resolved_params.get("z")
                    if x is None or y is None or z is None:
                        raise ValueError(f"Missing x, y, or z parameters for move_printer_xyz. Resolved: {resolved_params}")
                    await self.devices["printer"].move_to(x=float(x), y=float(y), z=float(z))
                    await asyncio.sleep(default_waits.get("after_printer_move", 2.0))
                    printer_involved = True
                elif step_type == "move_printer_grid":
                    if not self.devices.get("printer") or not self.devices["printer"].initialized:
                        raise ValueError("Printer not available or not initialized for move_grid.")
                    grid_num = resolved_params.get("grid_num")
                    if grid_num is None:
                         raise ValueError(f"Missing grid_num parameter for move_printer_grid. Resolved: {resolved_params}")
                    await self.devices["printer"].move_to_grid(int(grid_num))
                    await asyncio.sleep(default_waits.get("after_printer_move", 2.0))
                    printer_involved = True
                elif step_type == "set_valve":
                    if not self.devices.get("relay") or not self.devices["relay"].initialized:
                        raise ValueError("Relay/Valve controller not available or not initialized.")
                    relay_id = resolved_params.get("relay_id")
                    open_to_reservoir = resolved_params.get("open_to_reservoir") # This is the desired state for the valve
                    if relay_id is None or open_to_reservoir is None:
                        raise ValueError(f"Missing relay_id or open_to_reservoir for set_valve. Resolved: {resolved_params}")
                    # Assuming open_to_reservoir=True means relay should be ON, False means OFF. Adjust if logic is inverted.
                    await self.devices["relay"].toggle(int(relay_id), state=bool(open_to_reservoir))
                    await asyncio.sleep(default_waits.get("after_relay", 1.0))
                    relay_involved = True
                elif step_type == "pump_liquid":
                    if not self.devices.get("pump") or not self.devices["pump"].initialized:
                        raise ValueError("Pump not available or not initialized.")
                    volume_ml = resolved_params.get("volume_ml")
                    direction = resolved_params.get("direction", 1) # Default to forward/dispense
                    pump_index = resolved_params.get("pump_index", 0)
                    speed_str = resolved_params.get("speed", "medium")
                    
                    if volume_ml is None:
                        raise ValueError(f"Missing volume_ml for pump_liquid. Resolved: {resolved_params}")

                    speed_map = {"slow": "slow", "medium": "normal", "fast": "fast"}
                    api_speed = speed_map.get(speed_str, "normal")

                    await self.devices["pump"].dispense_auto(
                        pump_index=int(pump_index), 
                        volume=(float(volume_ml) * 1000), # Convert mL to µL
                        speed=api_speed, 
                        direction=int(direction)
                    )
                    # PumpAdapter broadcasts its own status. We wait for completion.
                    # The duration of dispense_auto is internally handled by PumpAdapter's _monitor_pump_progress
                    # We need a way to know when it's done. For now, use a fixed delay from default_waits.
                    # This might need refinement if dispense_auto doesn't block until completion or if we need more precise timing.
                    # Assuming pump operations are awaited within the adapter or we add a specific wait here.
                    # For now, a simple sleep.
                    # TODO: Better synchronization with pump completion if needed.
                    await asyncio.sleep(default_waits.get("after_pump", resolved_params.get("wait_after", 10.0))) 
                    pump_involved = True
                elif step_type == "sequence":
                    actions = step_config.get("actions", [])
                    logger.info(f"Starting sub-sequence for step ID '{step_id}' with {len(actions)} actions.")
                    sub_sequence_success = await self._run_sequence(current_sequence=actions, is_sub_sequence=True, loop_context_vars=combined_context_vars)
                    if not sub_sequence_success:
                        logger.error(f"Sub-sequence for step ID '{step_id}' failed or was stopped.")
                        raise ValueError(f"Sub-sequence '{step_id}' reported an error.")
                    logger.info(f"Sub-sequence for step ID '{step_id}' completed.")
                elif step_type == "chi_measurement":
                    if not self.devices.get("chi") or not self.devices["chi"].initialized:
                        raise ValueError("CHI device not available or not initialized.")
                    
                    chi_method_name = step_config.get("chi_method")
                    if not chi_method_name:
                        raise ValueError("chi_method not specified for chi_measurement step.")
                    
                    # Params for the CHI method itself are nested under "chi_params"
                    chi_params_config = step_config.get("params", {}).get("chi_params", {})
                    resolved_chi_params = self._resolve_params(chi_params_config, context_vars=combined_context_vars)
                    
                    # Handle fileName separately as it's a top-level param for the adapter call, not part of 'params' dict for CHI method
                    file_name_template = step_config.get("params", {}).get("fileName", f"{chi_method_name}_{{current_voltage_file_str}}_{int(time.time())}")
                    file_name = self._resolve_params({"fileName": file_name_template}, context_vars=combined_context_vars).get("fileName")

                    logger.info(f"Running CHI Measurement: Method={chi_method_name}, File='{file_name}', Params={resolved_chi_params}")

                    chi_method_to_call = getattr(self.devices["chi"], f"run_{chi_method_name.lower()}_test", None)
                    if callable(chi_method_to_call):
                        await chi_method_to_call(file_name=file_name, params=resolved_chi_params)
                    else:
                        raise ValueError(f"Unknown or unsupported CHI method: {chi_method_name}")
                    await asyncio.sleep(default_waits.get("chi_stabilization", 2.0))
                    chi_involved = True
                elif step_type == "chi_sequence":
                    if not self.devices.get("chi") or not self.devices["chi"].initialized:
                        raise ValueError("CHI device not available or not initialized.")
                    
                    chi_tests_config = step_config.get("params", {}).get("chi_tests", [])
                    for test_entry_idx, test_entry in enumerate(chi_tests_config):
                        chi_method_name = test_entry.get("method")
                        if not chi_method_name:
                            raise ValueError(f"chi_method not specified for test entry {test_entry_idx} in chi_sequence.")
                        
                        params_config = test_entry.get("params", {})
                        resolved_chi_params = self._resolve_params(params_config, context_vars=combined_context_vars)
                        
                        file_name_template = resolved_chi_params.get("fileName", f"{chi_method_name}_{{current_voltage_file_str}}_{int(time.time())}")
                        # If fileName was in params_config, it's already in resolved_chi_params.
                        # If it was a template, it needs resolving again with context.
                        file_name = self._resolve_params({"fileName": file_name_template}, context_vars=combined_context_vars).get("fileName")
                        resolved_chi_params['fileName'] = file_name # Ensure it's part of the params dict if adapter expects it there

                        logger.info(f"Running CHI Sequence item: Method={chi_method_name}, File='{file_name}', Params={resolved_chi_params}")
                        
                        chi_method_to_call = getattr(self.devices["chi"], f"run_{chi_method_name.lower()}_test", None)
                        if callable(chi_method_to_call):
                            await chi_method_to_call(file_name=file_name, params=resolved_chi_params) # Pass resolved_chi_params which now includes fileName
                        else:
                            raise ValueError(f"Unknown or unsupported CHI method in chi_sequence: {chi_method_name}")
                        await asyncio.sleep(default_waits.get("chi_stabilization", 2.0))
                    chi_involved = True # Mark that CHI operations happened
                elif step_type == "voltage_loop":
                    voltage_source_config = step_config.get("params", {}).get("voltage_source", {})
                    voltages = []
                    if voltage_source_config.get("type") == "config_key":
                        key = voltage_source_config.get("key")
                        voltages = self._get_value_from_key_path(key, default=[], context_vars=combined_context_vars)
                    elif voltage_source_config.get("type") == "list":
                        voltages = voltage_source_config.get("values", [])
                    elif voltage_source_config.get("type") == "range":
                        # Example: {"type": "range", "start": -1.0, "stop": 1.0, "step": 0.5}
                        # Note: range doesn't work well with floats, using a custom approach
                        v_start = voltage_source_config.get("start", 0.0)
                        v_stop = voltage_source_config.get("stop", 0.0)
                        v_step = voltage_source_config.get("step", 0.1)
                        current_v = v_start
                        while (v_step > 0 and current_v <= v_stop) or \
                              (v_step < 0 and current_v >= v_stop) or \
                              (v_step == 0 and current_v == v_stop): # handles single point if step is 0
                            voltages.append(round(current_v, 5)) # Round to avoid float precision issues
                            if v_step == 0: break
                            current_v += v_step
                            if len(voltages) > 500: # Safety break for large ranges/small steps
                                logger.warning("Voltage loop range generated over 500 points, breaking.")
                                break
                    
                    loop_sequence_config = step_config.get("params", {}).get("loop_sequence", [])
                    loop_base_context_vars = combined_context_vars.copy() # Inherit context

                    for v_idx, voltage in enumerate(voltages):
                        current_iter_context = loop_base_context_vars.copy()
                        current_iter_context["current_voltage"] = voltage
                        current_iter_context["current_voltage_file_str"] = self._format_voltage_for_filename(voltage)
                        current_iter_context["loop_index"] = v_idx
                        
                        logger.info(f"Voltage Loop (Index {v_idx}): Voltage={voltage}, FileStr={current_iter_context['current_voltage_file_str']}")
                        
                        loop_successful = await self._run_sequence(current_sequence=loop_sequence_config, is_sub_sequence=True, loop_context_vars=current_iter_context)
                        if not loop_successful:
                            raise ValueError(f"Voltage loop failed at voltage {voltage} (index {v_idx}).")
                elif step_type == "process_chi_data":
                    logger.info(f"Step '{step_id}': Processing CHI data. Params: {resolved_params}. (Actual processing TBD)")
                    # For now, this step is a placeholder and always succeeds.
                    await asyncio.sleep(default_waits.get("after_processing", 0.1))
                else:
                    logger.error(f"Unknown step type: '{step_type}' for step ID '{step_id}'.")
                    raise ValueError(f"Unknown step type: {step_type}")

                await self.broadcaster.broadcast({"type": "experiment_step_status", "step_id": step_id, "status": "completed", "step_index": index})
                if printer_involved and self.devices.get("printer"):
                    try:
                        pos = await self.devices["printer"].get_position()
                        await self.broadcaster.broadcast({"type": "hardware_update_printer", "position": pos, "is_moving": False})
                    except Exception as e_pos:
                        logger.warning(f"Could not get printer position after step {step_id}: {e_pos}")
                
                # General delay after each step if defined
                await asyncio.sleep(default_waits.get("after_each_step", 0.1))


            except Exception as e:
                logger.error(f"Error during step ID '{step_id}': {e}", exc_info=True)
                self.experiment_status = "error"
                await self.broadcaster.broadcast({
                    "type": "experiment_step_status", 
                    "step_id": step_id, 
                    "status": "error", 
                    "error_message": str(e),
                    "step_index": index
                })
                await self.broadcaster.broadcast({
                    "type": "experiment_status", 
                    "status": "error", 
                    "error_message": f"Error on step {step_id}: {str(e)}",
                    "current_step_id": step_id
                })
                break  # Stop experiment on error
        
        # After loop finishes
        if not is_sub_sequence: # Only top-level call sets final status and clears task
            if self.experiment_status == "running": # If loop completed without errors
                self.experiment_status = "completed"
                logger.info("Experiment sequence completed successfully.")
                await self.broadcaster.broadcast({
                    "type": "experiment_status", 
                    "status": "completed",
                    "experiment_name": self.current_experiment.get("name")
                })
            elif self.experiment_status == "error":
                 logger.error(f"Experiment sequence failed with error at step {self.current_step_id}.")
            # No specific broadcast for "paused" here as pause is not implemented.

            self.experiment_task = None # Clear the task reference
        
        return True # Indicate success for this sequence (main or sub)


if __name__ == '__main__':
    # Basic test logging (won't run in the actual application this way)
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # --- Mock objects for testing ---
    # Ensure ExperimentConfigManager is available or mock it if necessary for isolated tests
    # For this __main__ block, we'll use the real ExperimentConfigManager to create a test file.
    
    class MockBroadcaster:
        async def broadcast(self, message):
            logger.info(f"BROADCAST: {message}")

    class MockPrinter:
        def __init__(self):
            self.initialized = True
            self.position = {"x":0, "y":0, "z":0}
        async def home(self):
            logger.info("Printer: Homing...")
            await asyncio.sleep(0.1)
            self.position = {"x":0, "y":0, "z":0} # Simulate homing
            logger.info("Printer: Homed.")
        async def move_to(self, x, y, z):
            logger.info(f"Printer: Moving to ({x}, {y}, {z})...")
            await asyncio.sleep(0.1)
            self.position = {"x":x, "y":y, "z":z}
            logger.info("Printer: Moved.")
        async def move_to_grid(self, grid_num):
            logger.info(f"Printer: Moving to grid {grid_num}...")
            await asyncio.sleep(0.1)
            # Simulate grid move, e.g. grid 1 is (10,10,10)
            self.position = {"x":10*grid_num, "y":10*grid_num, "z":10} 
            logger.info(f"Printer: Moved to grid {grid_num}.")
        async def get_position(self):
            return self.position

    class MockRelay:
        def __init__(self):
            self.initialized = True
            self.states = {1: False, 2: False} # relay_id: state (False=off, True=on)
        async def toggle(self, relay_id, state):
            logger.info(f"Relay: Toggling relay {relay_id} to {state}...")
            self.states[relay_id] = bool(state)
            await asyncio.sleep(0.05)
            logger.info(f"Relay: Relay {relay_id} is now {'ON' if self.states[relay_id] else 'OFF'}.")
        async def get_status(self):
            return {str(k): "on" if v else "off" for k, v in self.states.items()}

    class MockPump:
        def __init__(self):
            self.initialized = True
        async def dispense_auto(self, pump_index, volume, speed, direction):
            logger.info(f"Pump: Dispensing {volume}µL from pump {pump_index} at {speed} speed, direction {direction}...")
            # Simulate work based on volume
            await asyncio.sleep(0.1 + (volume / 10000.0)) # Small delay + volume dependent
            logger.info(f"Pump: Dispense complete for pump {pump_index}.")
        # Add other methods like dispense_timed, stop if needed for future tests
    class MockCHI:
        def __init__(self):
            self.initialized = True
        async def run_cv_test(self, file_name, params):
            logger.info(f"CHI: Running CV test. File: '{file_name}', Params: {params}")
            await asyncio.sleep(0.1) # Simulate test duration
            logger.info(f"CHI: CV test '{file_name}' completed.")
        async def run_it_test(self, file_name, params):
            logger.info(f"CHI: Running IT test. File: '{file_name}', Params: {params}")
            await asyncio.sleep(0.1)
            logger.info(f"CHI: IT test '{file_name}' completed.")
        # Add other run_..._test methods if they are defined in CHIAdapter and used in tests

    mock_devices_test = {
        "printer": MockPrinter(),
        "relay": MockRelay(),
        "pump": MockPump(),
        "chi": MockCHI()
    }
    mock_broadcaster_test = MockBroadcaster()
    mock_config_test = {"results_dir": "./test_results", "moonraker_addr": "http://localhost:7125"}

    controller = ExperimentController(mock_devices_test, mock_broadcaster_test, mock_config_test)

    # --- Test _format_voltage_for_filename ---
    logger.info("\n--- Testing _format_voltage_for_filename ---")
    test_voltages = {1.0: "1p0", -0.5: "m0p5", -1.25: "m1p25", 0.0: "0p0", 0.123: "0p123", -0.005: "m0p005"}
    for v_in, v_out_expected in test_voltages.items():
        v_out_actual = controller._format_voltage_for_filename(v_in)
        logger.debug(f"Voltage {v_in} -> '{v_out_actual}' (Expected: '{v_out_expected}')")
        assert v_out_actual == v_out_expected

    # --- Test load_experiment and start_experiment with CHI and Loops ---
    # Create a valid dummy config file using the ExperimentConfigManager for the controller to load
    config_manager_for_test = ExperimentConfigManager()
    dummy_controller_test_file = "dummy_controller_test_config.json"
    test_config_data_for_controller = {
        "project_name": "CHI_Loop_Project_Controller_Test",
        "global_variables": {
            "default_chi_sens": "1e-5"
        },
        "default_wait_times": {
            "chi_stabilization": 0.05, # Faster for tests
            "after_each_step": 0.01
        },
        "configurations": { 
            "cv_voltages_key": [-0.1, 0.0, 0.1], # Shortened for faster test
            "cv_params_base": {
                "ei": 0.0, "eh": 0.5, "el": -0.5, "v": 0.1, "si": 0.01, "cl": 1,
                "sens_key": "global_variables.default_chi_sens" 
            },
            "it_params": {"ei_key": "current_voltage", "st": 1.0, "si": 0.1} 
        },
        "experiment_sequence": [
            {"id": "s1_voltage_loop_cv", "type": "voltage_loop", "enabled": True,
             "params": {
                 "voltage_source": {"type": "config_key", "key": "configurations.cv_voltages_key"},
                 "loop_sequence": [
                     {"id": "s1.1_cv_in_loop", "type": "chi_measurement",
                      "chi_method": "CV",
                      "params": {
                          "fileName": "{{project_name}}_CV_{{current_voltage_file_str}}",
                          "chi_params_key": "configurations.cv_params_base" 
                      }}
                 ]
             }},
            {"id": "s2_process_data", "type": "process_chi_data", "enabled": True,
             "params": {"source_files_pattern": "{{project_name}}*.txt"}}
        ]
    }
    if not config_manager_for_test.save_config(test_config_data_for_controller, dummy_controller_test_file):
        logger.error(f"Failed to create dummy config file for controller test: {dummy_controller_test_file}")
        # Optionally, skip the rest of the tests if file creation fails
        # return

    logger.info("\n--- Testing ExperimentController: load_experiment & start_experiment (Loops & CHI) ---")
    success_load_controller_test = controller.load_experiment(dummy_controller_test_file)
    logger.info(f"controller.load_experiment success: {success_load_controller_test}")
    
    if success_load_controller_test:
        logger.info("Starting experiment via controller...")
        controller.start_experiment()
        
        async def wait_for_controller_experiment():
            if controller.experiment_task:
                try:
                    await controller.experiment_task
                except asyncio.CancelledError:
                    logger.info("Loops & CHI experiment task was cancelled.")
                except Exception as e: 
                    logger.error(f"Loops & CHI experiment task raised an unhandled exception: {e}", exc_info=True)
            logger.info(f"Loops & CHI experiment final status: {controller.experiment_status}")

        asyncio.run(wait_for_controller_experiment())

    # Clean up the dummy file created for this test
    import os
    if os.path.exists(dummy_controller_test_file):
        os.remove(dummy_controller_test_file)
        logger.info(f"Cleaned up {dummy_controller_test_file}")
    
    # Remove other old dummy files if they exist from previous test structures
    old_dummies = [
        "dummy_experiment_run.json", "dummy_experiment_config.json", 
        "malformed_experiment_config.json", "dummy_experiment_config_load_only.json",
        "malformed_experiment_config_load_only.json", "dummy_experiment_advanced.json",
        "dummy_experiment_loops_chi.json" # This was the old name for the test file
    ]
    for f_path in old_dummies:
        if os.path.exists(f_path):
            os.remove(f_path)
            logger.info(f"Cleaned up old dummy: {f_path}")


    logger.info("--- End of __main__ tests for ExperimentController ---")
