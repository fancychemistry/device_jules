## Experiment WebSocket Messages

The backend sends various messages to the frontend via WebSocket to provide real-time updates on experiment execution, device statuses, and general logging.

### 1. Experiment Status Updates

These messages indicate changes in the overall status of an experiment.

*   **Type**: `experiment_status_update`
*   **Payload**:
    *   `type: "experiment_status_update"` (string)
    *   `status: str` (string) - The new overall status of the experiment. Examples:
        *   `"idle"`: No experiment is active or loaded.
        *   `"loading"`: Experiment configuration is being loaded.
        *   `"running"`: An experiment is currently active.
        *   `"completed"`: The experiment finished all steps successfully.
        *   `"stopped"`: The experiment was stopped by user command or an error.
        *   `"error"`: An error occurred that halted the experiment or prevented it from starting.
        *   `"warning"`: A non-critical issue occurred (e.g., experiment already running when start is requested).
    *   `message: Optional[str]` (string, optional) - A human-readable message describing the status change (e.g., "Experiment 'TestProject' started.", "Experiment finished successfully.", "Error during experiment: ...").
    *   `config_file_path: Optional[str]` (string, optional) - Path to the loaded configuration file, typically sent when an experiment starts.
    *   `project_name: Optional[str]` (string, optional) - Name of the current project, sent with most status updates.

**Example:**
```json
{
  "type": "experiment_status_update",
  "status": "running",
  "message": "Experiment 'TestProject' started.",
  "config_file_path": "old/test_experiment_config.json",
  "project_name": "TestProject"
}
```

### 2. Experiment Step Updates

These messages provide status updates for individual steps within an experiment sequence.

*   **Type**: `experiment_step_update`
*   **Payload**:
    *   `type: "experiment_step_update"` (string)
    *   `step_id: str` (string) - The unique ID of the step from the experiment configuration.
    *   `description: Optional[str]` (string, optional) - The human-readable description of the step.
    *   `status: str` (string) - The current status of this specific step. Examples:
        *   `"pending"`: The step is waiting to be executed.
        *   `"running"`: The step is currently executing.
        *   `"completed"`: The step finished successfully.
        *   `"skipped"`: The step was skipped (e.g., because it was disabled in the config).
        *   `"error"`: An error occurred during the execution of this step.
    *   `params: Optional[dict]` (object, optional) - The (parsed) parameters of the step, typically sent when the status is `"running"`.
    *   `error_message: Optional[str]` (string, optional) - A message describing the error, if `status` is `"error"`.
    *   `details: Optional[dict]` (object, optional) - Any other relevant details specific to the step or its outcome.

**Example (Step Running):**
```json
{
  "type": "experiment_step_update",
  "step_id": "cv_measure_1",
  "description": "Run a CV Test",
  "status": "running",
  "params": {
    "chi_method": "CV",
    "chi_params": {"ei": 0, "v": 0.1, "cl": 1},
    "file_name": "TestProject_test_CV.txt"
  }
}
```
**Example (Step Error):**
```json
{
  "type": "experiment_step_update",
  "step_id": "pump_main_sample",
  "description": "Pump main sample volume",
  "status": "error",
  "error_message": "Pump adapter not found or lacks 'dispense' method."
}
```

### 3. Configuration Update Status

Indicates the result of an attempt to update the experiment configuration via the API.

*   **Type**: `config_update_status`
*   **Payload**:
    *   `type: "config_update_status"` (string)
    *   `status: str` (string) - Result of the update operation.
        *   `"success"`: Configuration was updated and saved (if applicable).
        *   `"error"`: An error occurred during the update or save.
        *   `"warning"`: Configuration updated in memory but not saved (e.g., no file path).
    *   `message: str` (string) - A human-readable message describing the outcome.
    *   `config_file_path: Optional[str]` (string, optional) - Path to the configuration file if saved.

**Example:**
```json
{
  "type": "config_update_status",
  "status": "success",
  "message": "实验配置已更新并保存。",
  "config_file_path": "old/test_experiment_config.json"
}
```

### 4. Device Status Messages

These messages are typically broadcast by individual device adapters when their state changes or upon request. The `ExperimentExecutionService` itself does not generate these directly but relies on the adapters. Their structure can vary.

*   **`printer_status`**:
    *   `type: "printer_status"`
    *   `position: dict` (e.g., `{"x": 10.1, "y": 20.0, "z": 5.0}`)
    *   `initialized: bool`
*   **`pump_status`**:
    *   `type: "pump_status"`
    *   `status: dict` (Contains fields like `running`, `pump_index`, `volume` (µL), `progress` (0.0-1.0), `direction`, `elapsed_time_seconds`, `total_duration_seconds`, `rpm`, `revolutions`, `raw_response`)
    *   `initialized: bool`
*   **`relay_status`**:
    *   `type: "relay_status"`
    *   `states: dict` (e.g., `{"1": "on", "2": "off", ...}` for each relay ID)
    *   `initialized: bool`
*   **`chi_status`** (from CHI Adapter):
    *   `type: "chi_status"`
    *   `status: dict` (Can include fields like `status` ("idle", "running", "completed", "error"), `test_type`, `file_name`, `progress`, `elapsed_time`, `details`).
    *   `initialized: bool` (Indicates if the CHI software connection is ready)

### 5. General Log Messages (from Backend Service)

The `ExperimentExecutionService` or other backend components might send general log messages.

*   **Type**: `log` (This is a common convention, might vary based on frontend's existing log handler)
*   **Payload**:
    *   `type: "log"` (string)
    *   `level: str` (string) - Log level (e.g., "info", "warning", "error", "debug").
    *   `message: str` (string) - The log message content.
    *   `source: Optional[str]` (string, optional) - Indicates the origin of the log (e.g., "experiment_service", "device_adapter_printer").

**Example:**
```json
{
  "type": "log",
  "level": "info",
  "message": "Experiment sequence started.",
  "source": "experiment_service"
}
```

### 6. Ping/Pong

For maintaining WebSocket connection health.

*   **Server to Client**:
    ```json
    { "type": "ping" }
    ```
*   **Client to Server (Response)**:
    ```json
    { "type": "pong" }
    ```

This document provides a general overview. Specific details for device status messages should be cross-referenced with the actual adapter implementations.
