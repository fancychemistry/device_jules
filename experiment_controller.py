import json
import logging
import asyncio
import re
from copy import deepcopy

# logger = logging.getLogger("experiment_run") # Use the same logger as experiment_run.py
# Allow logger to be passed in for testing
logger = logging.getLogger(__name__)


class ExperimentController:
    def __init__(self, config_path="old/experiment_config.json", broadcaster=None, devices=None, config_data=None, logger_instance=None):
        self.logger = logger_instance or logging.getLogger(__name__)
        self.config_path = config_path
        self.broadcaster = broadcaster
        self.devices = devices
        
        if config_data:
            self.config_data = config_data
            self.logger.info("ExperimentController initialized with in-memory config data.")
        else:
            self.config_data = self._load_config()
            self.logger.info(f"ExperimentController initialized with config from {config_path}.")


        self.current_step_id = None
        self.current_step_description = None
        self.is_running = False
        self.error_occurred = False
        self.error_message = None
        self.experiment_flags = self.config_data.get("experiment_flags", {})
        self.total_steps = 0
        self.completed_steps = 0
        self._stop_requested = False
        self.is_paused = False       # Added for pause/resume
        self.pause_requested = False # Added for pause/resume


    def _load_config(self):
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"Experiment config file not found: {self.config_path}")
            raise
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from experiment config file: {self.config_path}")
            raise

    def _resolve_value(self, value_template, loop_vars=None):
        if not isinstance(value_template, str):
            return value_template

        # First, try to resolve from loop_vars
        if loop_vars:
            match = re.fullmatch(r"{{\s*([\w.]+)\s*}}", value_template)
            if match:
                key = match.group(1)
                if key in loop_vars:
                    return loop_vars[key]

        # Then, try to resolve from config_data (configurations, project_name, etc.)
        def replace_config_value(match):
            parts = match.group(1).split('.')
            current_value = self.config_data
            try:
                for part in parts:
                    if '[' in part and part.endswith(']'): # Handle list indices like key[0]
                        key_name, index_str = part[:-1].split('[')
                        index = int(index_str)
                        if key_name: # if there's a key name before index (e.g. configurations.safe_move_xy[0])
                            current_value = current_value[key_name][index]
                        else: # if it's an anonymous list (e.g. direct_list_key[0])
                            current_value = current_value[index]

                    else:
                        current_value = current_value[part]
                return str(current_value) # Ensure the resolved value is a string for re.sub
            except (KeyError, TypeError, IndexError) as e:
                logger.warning(f"Could not resolve template part {match.group(1)}: {e}")
                return match.group(0) # Return original if not found

        # Iteratively replace to handle nested templates if necessary, though simple direct access is more common
        resolved_string = re.sub(r"{{\s*([\w.\[\]]+)\s*}}", replace_config_value, value_template)

        # Try to convert to float or int if the resolved string is a number
        if isinstance(resolved_string, str):
            if re.fullmatch(r"^-?\d+\.\d+$", resolved_string):
                try: return float(resolved_string)
                except ValueError: pass
            if re.fullmatch(r"^-?\d+$", resolved_string):
                try: return int(resolved_string)
                except ValueError: pass
        
        # If the entire template was a single placeholder that resolved to a non-string (e.g. a list or dict from config)
        # the re.sub would have stringified it. We need to re-fetch it if it was a direct lookup.
        single_placeholder_match = re.fullmatch(r"{{\s*([\w.\[\]]+)\s*}}", value_template)
        if single_placeholder_match:
            parts = single_placeholder_match.group(1).split('.')
            current_value = self.config_data
            try:
                for part in parts:
                    if '[' in part and part.endswith(']'):
                        key_name, index_str = part[:-1].split('[')
                        index = int(index_str)
                        if key_name: current_value = current_value[key_name][index]
                        else: current_value = current_value[index]
                    else:
                        current_value = current_value[part]
                if not isinstance(current_value, (str, int, float, bool)) and current_value is not None : # if it was a complex type
                     return current_value # return the original complex type
            except (KeyError, TypeError, IndexError):
                pass # If it failed, we stick with the string version or original if not string

        return resolved_string


    async def _execute_step(self, step_config, loop_vars=None):
        step_id = step_config['id']
        step_type = step_config['type']
        step_description = step_config.get('description', '')
        
        self.current_step_id = step_id
        self.current_step_description = step_description
        logger.info(f"Executing step: {step_id} - {step_description} (Type: {step_type})")
        await self.broadcast_step_status(step_id, 'running', description=step_description)

        try:
            if self._stop_requested:
                logger.info(f"Stop requested, skipping step {step_id}")
                await self.broadcast_step_status(step_id, 'skipped', description=step_description, message="Experiment stopped by user")
                return False # Indicate failure to proceed

            # Resolve params if they exist
            params = {}
            if "params" in step_config:
                for k, v_template in step_config["params"].items():
                    params[k] = self._resolve_value(v_template, loop_vars)
            
            if "chi_params" in step_config: # For chi_measurement
                params["chi_params"] = {}
                for k, v_template in step_config["chi_params"].items():
                    params["chi_params"][k] = self._resolve_value(v_template, loop_vars)
            if "chi_method" in step_config: # For chi_measurement
                params["chi_method"] = self._resolve_value(step_config["chi_method"], loop_vars)


            if step_type == "printer_home":
                if self.devices.get("printer"):
                    await self.devices["printer"].home()
                else:
                    raise ValueError("Printer device not initialized.")
            
            elif step_type == "move_printer_xyz":
                if self.devices.get("printer"):
                    x = params.get("x_key") # Assuming keys directly provide values after resolving
                    y = params.get("y_key")
                    z = params.get("z_key")
                    if x is None or y is None or z is None:
                        raise ValueError("Missing x, y, or z parameters for move_printer_xyz")
                    await self.devices["printer"].move_to(x=float(x), y=float(y), z=float(z))
                else:
                    raise ValueError("Printer device not initialized.")

            elif step_type == "move_printer_grid":
                if self.devices.get("printer"):
                    grid_num = params.get("grid_num_key", params.get("grid_num"))
                    if grid_num is None:
                        raise ValueError("Missing grid_num_key or grid_num for move_printer_grid")
                    await self.devices["printer"].move_to_grid(position=int(grid_num))
                else:
                    raise ValueError("Printer device not initialized.")

            elif step_type == "set_valve":
                if self.devices.get("relay"):
                    relay_id = params.get("relay_id_key")
                    open_to_reservoir = params.get("open_to_reservoir")
                    if relay_id is None or open_to_reservoir is None:
                        raise ValueError("Missing relay_id or open_to_reservoir for set_valve")
                    # Assuming RelayAdapter.toggle expects 'on'/'off' or boolean state for second param
                    await self.devices["relay"].toggle(relay_id=int(relay_id), state=bool(open_to_reservoir))
                else:
                    raise ValueError("Relay device not initialized.")
            
            elif step_type == "pump_liquid":
                if self.devices.get("pump"):
                    volume_ml = params.get("volume_ml_key")
                    direction = params.get("direction")
                    # klipper_params = params.get("klipper_params_key") # This might be used by pump_proxy directly if passed
                    pump_idx = params.get("pump_index", self._resolve_value("{{configurations.default_pump_index}}", loop_vars) or 0) # Default from config or 0
                    speed = params.get("speed", self._resolve_value("{{configurations.default_pump_speed}}", loop_vars) or "medium") # Default from config or medium
                    
                    volume_ml_val = params.get("volume_ml_key") # This is already resolved
                    direction_val = params.get("direction")     # This is already resolved

                    if volume_ml_val is None or direction_val is None:
                        raise ValueError("Missing volume_ml_key or direction for pump_liquid")
                    
                    logger.info(f"Pump details: pump_index={pump_idx}, volume_ml={volume_ml_val}, direction={direction_val}, speed={speed}")

                    # Assuming dispense_auto is the correct method based on previous files.
                    # If dispense_timed or other methods are needed, the config 'type' or params should specify.
                    await self.devices["pump"].dispense_auto(
                        pump_index=int(pump_idx),
                        volume=float(volume_ml_val) * 1000, # Convert mL to µL
                        direction=int(direction_val),
                        speed=str(speed)
                    )
                else:
                    raise ValueError("Pump device not initialized.")

            elif step_type == "chi_measurement": # This is an action type within a loop usually
                if self.devices.get("chi"):
                    method = params.get("chi_method")
                    chi_params_resolved = params.get("chi_params", {})
                    file_name = chi_params_resolved.get("fileName", f"{method}_default_name")
                    
                    # The CHIAdapter's run_test method should handle specific test calls
                    # We pass the raw resolved params dict to it.
                    # It is responsible for picking the correct parameters for the given method.
                    await self.devices["chi"].run_test(
                        test_type=method,
                        params=chi_params_resolved,
                        file_name=file_name
                    )
                    # Wait for CHI test completion
                    await self._wait_for_chi_completion(method_name=method, timeout=params.get("timeout", 300)) # Allow timeout to be configured
                    if self.error_occurred: # If CHI test itself reported an error via status or timeout
                        raise Exception(f"CHI Measurement {method} reported an error or timed out: {self.error_message}")

                else:
                    raise ValueError("CHI device not initialized.")

            elif step_type == "chi_sequence": # This is a top-level sequence type
                if self.devices.get("chi"):
                    chi_tests_config = step_config.get("chi_tests", [])
                    for test_item_config in chi_tests_config:
                        if self._stop_requested:
                            logger.info(f"Stop requested, skipping remaining CHI tests in sequence {step_id}")
                            break
                        
                        method_name = self._resolve_value(test_item_config["method"], loop_vars)
                        current_chi_params_resolved = {}
                        for k, v_template in test_item_config["params"].items():
                            current_chi_params_resolved[k] = self._resolve_value(v_template, loop_vars)
                        
                        # Default filename if not provided in params
                        file_name = current_chi_params_resolved.get("fileName", f"{method_name}_{step_id}_{self.completed_steps}")
                        
                        logger.info(f"Executing CHI sub-test from chi_sequence: {method_name} with params {current_chi_params_resolved}, filename: {file_name}")
                        
                        await self.devices["chi"].run_test(
                            test_type=method_name,
                            params=current_chi_params_resolved, # Pass the fully resolved params
                            file_name=file_name
                        )
                        
                        # Wait for this specific CHI test in the sequence to complete
                        # Allow timeout to be specified in the test_item_config or use a default
                        timeout_seconds = self._resolve_value(test_item_config.get("timeout"), loop_vars) or 300
                        await self._wait_for_chi_completion(method_name=method_name, timeout=float(timeout_seconds))
                        
                        if self.error_occurred: # If CHI test itself reported an error via status or timeout
                            # Decide if one failed test stops the whole chi_sequence or just this test
                            # For now, assume it stops the entire chi_sequence step
                            raise Exception(f"CHI test {method_name} in sequence {step_id} reported an error or timed out: {self.error_message}")
                else:
                    raise ValueError("CHI device not initialized.")
            
            elif step_type == "process_chi_data":
                logger.info(f"Processing CHI data (placeholder for step {step_id}): {params}")
                await asyncio.sleep(0.1) # Simulate work

            elif step_type == "sequence":
                actions = step_config.get("actions", [])
                for action in actions:
                    if self._stop_requested: break
                    action_copy = deepcopy(action) # Avoid modification issues if reused
                    success = await self._execute_step(action_copy, loop_vars)
                    if not success:
                        # If a sub-step fails, the sequence fails.
                        # The error is already broadcasted by the sub-step.
                        return False 
            
            elif step_type == "voltage_loop":
                voltage_source_config = step_config.get("voltage_source", {})
                voltages = []
                if voltage_source_config.get("type") == "config_key":
                    raw_voltages = self._resolve_value(f"{{{{{voltage_source_config['key']}}}}}", loop_vars)
                    if isinstance(raw_voltages, list) and len(raw_voltages) == 2 and all(isinstance(v, (int,float)) for v in raw_voltages):
                        # Assume [start, end] -> generate a simple range for now, could be more complex
                        # This part might need adjustment based on how voltage_range is defined (e.g., num_steps)
                        # For now, let's assume it's a list of voltages [v1, v2, v3] or [start, end, num_steps]
                        # The example config has [-1.2, -1.3] which implies direct values.
                        voltages = raw_voltages # Use as is if it's a list
                    elif isinstance(raw_voltages, list):
                         voltages = raw_voltages
                    else:
                        raise ValueError(f"Could not resolve voltages from {voltage_source_config['key']}")
                else:
                    raise ValueError("Unsupported voltage_source type for voltage_loop")

                output_positions_source_config = step_config.get("output_positions_source", {})
                output_positions = []
                if output_positions_source_config:
                    if output_positions_source_config.get("type") == "config_key":
                        key = output_positions_source_config.get("key")
                        if key: # if key is not None or empty string
                            output_positions = self._resolve_value(f"{{{{{key}}}}}", loop_vars)
                            if not isinstance(output_positions, list) and output_positions is not None : # if key existed but resolved to non-list
                                 logger.warning(f"Output positions key '{key}' resolved to non-list: {output_positions}. Using empty list.")
                                 output_positions = []
                            elif output_positions is None: # if key resolved to None (e.g. key was null in JSON)
                                output_positions = []

                loop_sequence = step_config.get("loop_sequence", [])
                for i, voltage in enumerate(voltages):
                    if self._stop_requested: break
                    
                    current_loop_vars = loop_vars.copy() if loop_vars else {}
                    current_loop_vars["current_voltage"] = voltage
                    current_loop_vars["current_voltage_file_str"] = str(voltage).replace('.', 'p') # e.g., -1.2 -> -1p2
                    current_loop_vars["loop_index"] = i
                    
                    if output_positions and i < len(output_positions):
                        current_loop_vars["current_output_position"] = output_positions[i]
                    elif output_positions: # Fewer positions than voltages
                        logger.warning(f"Fewer output positions ({len(output_positions)}) than voltages ({len(voltages)}). Reusing last available position for loop index {i}.")
                        current_loop_vars["current_output_position"] = output_positions[-1]
                    # else: no output positions defined or needed for this loop

                    logger.info(f"Voltage loop iteration {i+1}/{len(voltages)}: Voltage={voltage}, Vars={current_loop_vars}")
                    
                    for sub_step_config in loop_sequence:
                        if self._stop_requested: break
                        sub_step_copy = deepcopy(sub_step_config)
                        success = await self._execute_step(sub_step_copy, current_loop_vars)
                        if not success:
                            # Optionally, decide if a sub-step failure breaks the whole loop
                            # For now, let's say it does.
                            logger.error(f"Sub-step {sub_step_config['id']} failed in voltage_loop. Stopping loop.")
                            return False # Propagate failure
                    if self._stop_requested: break # Check again after inner loop

            else:
                raise NotImplementedError(f"Step type '{step_type}' is not implemented.")

            # If successful until here
            await self.broadcast_step_status(step_id, 'completed', description=step_description)
            self.completed_steps += 1
            return True

        except Exception as e:
            logger.error(f"Error executing step {step_id} ({step_description}): {e}", exc_info=True)
            self.error_occurred = True
            self.error_message = str(e)
            await self.broadcast_step_status(step_id, 'error', description=step_description, error_message=str(e)) # Broadcast step error
            # Also update overall experiment status to reflect error
            await self.broadcast_experiment_status(status='error', message=f"实验在步骤 {step_id} 失败: {e}")
            return False

    async def _wait_for_chi_completion(self, method_name, timeout=60): # Added method_name for logging
        """Polls CHI status until it's idle or an error occurs, or timeout. Handles pause requests."""
        if not self.devices.get("chi"):
            logger.warning(f"CHI device not available for _wait_for_chi_completion (method {method_name}).")
            return

        start_time = asyncio.get_event_loop().time()
        log_interval = 10 # seconds, how often to log "still waiting"
        last_log_time = start_time

        while True:
            current_time = asyncio.get_event_loop().time()

            # Handle pause request within the wait loop
            if self.pause_requested:
                self.is_paused = True
                self.pause_requested = False
                logger.info(f"Pause requested during CHI test {method_name}. Controller will pause after CHI completion or timeout.")
                await self.broadcast_experiment_status(status='paused', message=f'实验暂停请求已接收 (CHI测试 {method_name} 将继续完成)。')
                # CHI test continues in background, controller pauses here by waiting for resume
                while self.is_paused:
                    if self.stop_requested:
                        logger.info(f"Stop requested while paused during CHI test {method_name}.")
                        await self.broadcast_experiment_status(status='stopping', message='实验在暂停时被停止。')
                        # If CHI is still running, attempt to stop it
                        if self.devices.get("chi"): await self.devices["chi"].stop_test()
                        return # Exits _wait_for_chi_completion, which will lead to run() loop exiting
                    await asyncio.sleep(0.5)
                
                logger.info(f"Experiment resumed during CHI test {method_name}. Continuing to wait for CHI completion.")
                await self.broadcast_experiment_status(status='running', message='实验已恢复。')
                # Reset start_time to adjust timeout fairly after resume, or decide if timeout should include pause duration
                # For simplicity, timeout is effectively extended by pause duration here.

            if self._stop_requested:
                logger.info(f"Stop requested during CHI wait for {method_name}.")
                if self.devices.get("chi"): 
                    await self.devices["chi"].stop_test() 
                self.error_occurred = True 
                self.error_message = f"CHI test {method_name} stopped by user request."
                break
            
            try:
                status_response = await self.devices["chi"].get_status()
                
                chi_internal_status = status_response.get("status", "unknown").lower()
                chi_message = status_response.get("message", "")
                chi_reported_error_flag = status_response.get("error", False) 

                if chi_internal_status in ["idle", "completed"]:
                    logger.info(f"CHI test {method_name} finished. Status: {chi_internal_status}, Message: {chi_message}")
                    if chi_reported_error_flag or "error" in chi_message.lower() or chi_internal_status == "error":
                        self.error_occurred = True
                        self.error_message = f"CHI {method_name} reported error: {chi_message or 'Unknown CHI error'}"
                        logger.error(self.error_message)
                    else:
                        self.error_occurred = False 
                        self.error_message = None
                    break
                elif chi_internal_status == "error": 
                    self.error_occurred = True
                    self.error_message = f"CHI test {method_name} error: {chi_message or 'Unknown CHI error'}"
                    logger.error(self.error_message)
                    break
                
                if current_time - last_log_time > log_interval:
                    logger.info(f"Still waiting for CHI test {method_name} to complete... Current status: {chi_internal_status}")
                    last_log_time = current_time

            except Exception as e:
                logger.error(f"Error while getting CHI status for {method_name}: {e}", exc_info=True)
                self.error_occurred = True
                self.error_message = f"Failed to get CHI status for {method_name}: {e}"
                break 

            if (current_time - start_time) > timeout:
                logger.warning(f"Timeout waiting for CHI test {method_name} completion after {timeout}s.")
                self.error_occurred = True
                self.error_message = f"Timeout waiting for CHI test {method_name} completion."
                if self.devices.get("chi"):
                     await self.devices["chi"].stop_test() 
                break
            
            await asyncio.sleep(0.5) 

    async def run(self):
        self.is_running = True
        self.error_occurred = False
        self.error_message = None
        self._stop_requested = False
        self.is_paused = False       # Reset pause state at the beginning of a run
        self.pause_requested = False # Reset pause request
        self.completed_steps = 0
        
        self.total_steps = 0
        for step_config_item in self.config_data.get("experiment_sequence", []):
            if not step_config_item.get('enabled', True):
                continue
            skip_flag_name = step_config_item.get("skip_if_flag_true")
            if skip_flag_name and self.experiment_flags.get(skip_flag_name, False):
                continue
            self.total_steps += 1 

        await self.broadcast_experiment_status(status='running', message="实验已启动。")

        for step_config in self.config_data.get("experiment_sequence", []):
            # Handle pause request at the beginning of each top-level step
            if self.pause_requested:
                self.is_paused = True
                self.pause_requested = False # Reset request
                logger.info(f"Experiment paused before step {step_config.get('id', 'Unknown')}.")
                await self.broadcast_experiment_status(status='paused', message='实验已暂停。')
                while self.is_paused:
                    if self.stop_requested: # Allow stopping while paused
                        logger.info("Experiment stopped by user while paused.")
                        await self.broadcast_experiment_status(status='stopped', message='实验在暂停时被停止。')
                        self.is_running = False
                        return 
                    await asyncio.sleep(0.5) # Check every 0.5s
                # Resumed
                logger.info(f"Experiment resumed, proceeding with step {step_config.get('id', 'Unknown')}.")
                await self.broadcast_experiment_status(status='running', message='实验已恢复。')

            if self._stop_requested:
                logger.info("Experiment run stopped by user request.")
                await self.broadcast_experiment_status(status='stopped', message='实验已停止。')
                break

            if not step_config.get('enabled', True):
                logger.info(f"Skipping disabled step: {step_config['id']}")
                await self.broadcast_step_status(step_config['id'], 'skipped', description=step_config.get('description', ''), message="Step disabled in config")
                continue

            skip_flag_name = step_config.get("skip_if_flag_true")
            if skip_flag_name and self.experiment_flags.get(skip_flag_name, False):
                logger.info(f"Skipping step {step_config['id']} due to flag: {skip_flag_name}")
                await self.broadcast_step_status(step_config['id'], 'skipped', description=step_config.get('description', ''), message=f"Skipped due to flag {skip_flag_name}")
                continue
            
            step_copy = deepcopy(step_config) 
            success = await self._execute_step(step_copy) 
            
            if not success:
                logger.error(f"Experiment failed at step {step_config['id']}. Stopping.")
                # Error status already broadcast by _execute_step
                break 
        
        self.is_running = False
        if self.error_occurred:
            # Message already set by _execute_step or _wait_for_chi_completion
            await self.broadcast_experiment_status(status='error', message=self.error_message or "实验因错误停止。")
        elif self._stop_requested:
            # Status already broadcast if stopped during pause or regular stop request
            if not (self.is_paused and self._stop_requested): # Avoid double message if stopped during pause
                 await self.broadcast_experiment_status(status='stopped', message='实验已停止。')
        else:
            await self.broadcast_experiment_status(status='completed', message='实验已完成。')
            
        logger.info(f"Experiment run finished. Error: {self.error_occurred}, Stop Requested: {self._stop_requested}, Paused: {self.is_paused}")
        return not self.error_occurred and not self._stop_requested


    async def broadcast_step_status(self, step_id, status, description="", error_message=None, message=None):
        if not self.broadcaster:
            return
        payload = {
            "type": "experiment_step_update",
            "step_id": step_id,
            "description": description or self.current_step_description,
            "status": status, 
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "is_paused": self.is_paused # Also send pause state with step update
        }
        if error_message:
            payload["error_message"] = error_message
        if message:
            payload["message"] = message
        
        if self.total_steps > 0 :
            payload["progress_percent"] = min(100, int((self.completed_steps / self.total_steps) * 100)) if self.total_steps > 0 else 0

        await self.broadcaster.broadcast(payload)

    async def broadcast_experiment_status(self, status, message): # Added status parameter
        if not self.broadcaster:
            self.logger.debug("No broadcaster available for broadcast_experiment_status")
            return
        
        status_payload = self.get_experiment_status() # Gets all current states
        status_payload["type"] = "experiment_status_update" 
        status_payload["status"] = status # Explicitly set the primary status for this message
        status_payload["message"] = message
        status_payload["timestamp"] = datetime.utcnow().isoformat() + "Z"
        
        await self.broadcaster.broadcast(status_payload)


    def get_experiment_status(self):
        return {
            "is_running": self.is_running,
            "is_paused": self.is_paused, 
            "current_step_id": self.current_step_id,
            "current_step_description": self.current_step_description,
            "error_occurred": self.error_occurred,
            "error_message": self.error_message,
            "completed_steps": self.completed_steps,
            "total_steps": self.total_steps, 
            "progress_percent": min(100, int((self.completed_steps / self.total_steps) * 100)) if self.total_steps > 0 else 0,
            "stop_requested": self._stop_requested,
            "pause_requested": self.pause_requested 
        }

    def request_stop(self):
        self.logger.info("Experiment stop requested.")
        self._stop_requested = True
        if self.is_paused: 
            self.is_paused = False 
            self.pause_requested = False
        if self.is_running and self.devices and self.devices.get("chi"):
            asyncio.create_task(self.devices["chi"].stop_test())

    def request_pause(self):
        if self.is_running and not self.is_paused and not self.pause_requested:
            self.logger.info("Experiment pause requested.")
            self.pause_requested = True
        elif self.is_paused:
            self.logger.warning("Pause requested, but experiment is already paused.")
        elif self.pause_requested:
            self.logger.warning("Pause requested, but already pending.")
        elif not self.is_running:
            self.logger.warning("Pause requested, but experiment is not running.")


    async def resume(self): 
        if self.is_running and self.is_paused:
            self.logger.info("Resuming experiment.")
            self.is_paused = False
            self.pause_requested = False 
            await self.broadcast_experiment_status(status='resuming', message='实验正在恢复...')
        elif not self.is_running:
             self.logger.warning("Resume requested, but experiment is not running.")
        elif not self.is_paused:
             self.logger.warning("Resume requested, but experiment is not paused.")


    def update_config(self, new_config_data):
        try:
            # Validate (optional, can be extensive)
            if "experiment_sequence" not in new_config_data or "configurations" not in new_config_data:
                raise ValueError("Invalid configuration structure.")

            self.config_data = new_config_data
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
            logger.info(f"Experiment configuration updated and saved to {self.config_path}")
            # Reload flags or other dependent things if necessary
            self.experiment_flags = self.config_data.get("experiment_flags", {})
            return True
        except Exception as e:
            logger.error(f"Error updating configuration: {e}")
            return False

from datetime import datetime # Add this if not already at the top of the file
import asyncio # ensure this is at the top
```
