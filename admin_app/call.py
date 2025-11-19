"""
Free Phone Call Module
Uses Python built-in libraries to open system phone dialer
100% FREE - No API keys, no subscriptions, no costs
"""

import os
import subprocess
import platform
import logging

logger = logging.getLogger(__name__)


def make_call(caller_name, receiver_number):
    """
    Opens the system phone dialer with the receiver number pre-filled.
    
    Args:
        caller_name (str): Name of the caller/app (for logging purposes)
        receiver_number (str): Phone number to dial (can include spaces, dashes, parentheses)
    
    Returns:
        bool: True if dialer was opened successfully, False otherwise
    
    Note:
        This function opens the system dialer but does NOT automatically make the call.
        The user must click "Call" in the dialer to actually place the call.
        Uses the device's phone service (not internet-based calling).
    """
    try:
        # Clean the phone number - remove spaces, dashes, parentheses
        receiver_number = receiver_number.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        
        # Get the operating system type
        os_type = platform.system().lower()
        
        logger.info(f"Attempting to open dialer for {caller_name} to call {receiver_number} on {os_type}")
        
        # Open dialer based on OS
        if os_type == "windows":
            # Windows: Use tel: protocol
            os.startfile(f"tel:{receiver_number}")
        elif os_type == "darwin":
            # macOS: Use open command with tel: protocol
            subprocess.Popen(["open", f"tel:{receiver_number}"])
        else:
            # Linux and other Unix-like systems: Use xdg-open
            subprocess.Popen(["xdg-open", f"tel:{receiver_number}"])
        
        logger.info(f"Successfully opened dialer for {receiver_number}")
        return True
        
    except Exception as e:
        logger.error(f"Error opening phone dialer: {e}")
        return False
