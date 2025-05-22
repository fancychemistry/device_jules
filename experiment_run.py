from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
import device_tester
from backend.pubsub import Broadcaster # For isinstance check

router = APIRouter()

@router.get("/")
async def read_root():
    return {"message": "Experiment Run API operational"}

@router.get("/test_shared_components")
async def test_shared_components():
    response_data = {}

    # Access device_tester.config
    try:
        if device_tester.config and isinstance(device_tester.config, dict):
            response_data["moonraker_addr_from_config"] = device_tester.config.get("moonraker_addr", "Not set or config not ready")
        else:
            response_data["moonraker_addr_from_config"] = "device_tester.config is not a dict or not available"
    except AttributeError:
        response_data["moonraker_addr_from_config"] = "device_tester.config not found"
    except Exception as e:
        response_data["moonraker_addr_from_config"] = f"Error accessing config: {str(e)}"

    # Access device_tester.devices
    try:
        if device_tester.devices and isinstance(device_tester.devices, dict):
            response_data["number_of_device_keys"] = len(device_tester.devices)
            response_data["chi_adapter_initialized_in_devices"] = device_tester.devices.get("chi") is not None
        else:
            response_data["number_of_device_keys"] = 0
            response_data["chi_adapter_initialized_in_devices"] = False
            response_data["devices_status"] = "device_tester.devices is not a dict or not available"
    except AttributeError:
        response_data["number_of_device_keys"] = 0
        response_data["chi_adapter_initialized_in_devices"] = False
        response_data["devices_status"] = "device_tester.devices not found"
    except Exception as e:
        response_data["number_of_device_keys"] = 0
        response_data["chi_adapter_initialized_in_devices"] = False
        response_data["devices_status"] = f"Error accessing devices: {str(e)}"


    # Access device_tester.broadcaster
    try:
        if device_tester.broadcaster and isinstance(device_tester.broadcaster, Broadcaster):
            # Assuming 'connections' is the attribute storing WebSocket connections
            response_data["broadcaster_connection_count"] = len(device_tester.broadcaster.connections)
        elif hasattr(device_tester, 'broadcaster') and device_tester.broadcaster is None:
            response_data["broadcaster_connection_count"] = 0
            response_data["broadcaster_status"] = "device_tester.broadcaster is None"
        else: # broadcaster object exists but not of expected type, or connections attribute missing
            response_data["broadcaster_connection_count"] = 0
            response_data["broadcaster_status"] = "device_tester.broadcaster is not a Broadcaster instance or 'connections' attribute is missing"
    except AttributeError: # device_tester.broadcaster itself doesn't exist
        response_data["broadcaster_connection_count"] = 0
        response_data["broadcaster_status"] = "device_tester.broadcaster not found"
    except Exception as e: # Other potential errors
        response_data["broadcaster_connection_count"] = 0
        response_data["broadcaster_status"] = f"Error accessing broadcaster: {str(e)}"
        
    return JSONResponse(content=response_data)
