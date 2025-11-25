"""
Serializers for API request validation.
"""
import re
from django.core.exceptions import ValidationError


class CallWebhookSerializer:
    """
    Serializer for call webhook API requests.
    Validates from, did, and to fields.
    """
    
    def __init__(self, data):
        self.data = data
        self.errors = {}
        self.validated_data = {}
    
    def is_valid(self):
        """
        Validate all fields in the request data.
        Returns True if valid, False otherwise.
        Accepts both new parameter names (from, did, to) and old names (from_number, did_number, to_number).
        """
        self.errors = {}
        self.validated_data = {}
        
        # Validate from (accept both 'from' and 'from_number' for backward compatibility)
        from_number = self.data.get('from') or self.data.get('from_number')
        if not from_number:
            self.errors['from'] = ['This field is required.']
        elif not self._validate_phone_number(from_number):
            self.errors['from'] = ['Must be exactly 10 digits (with or without +91 prefix).']
        else:
            # Extract 10-digit number (remove +91 if present)
            self.validated_data['from'] = self._extract_phone_number(from_number)
        
        # Validate did (accept both 'did' and 'did_number' for backward compatibility)
        did_number = self.data.get('did') or self.data.get('did_number')
        if not did_number:
            self.errors['did'] = ['This field is required.']
        elif not self._validate_phone_number(did_number):
            self.errors['did'] = ['Must be exactly 10 digits (with or without +91 prefix).']
        else:
            # Extract 10-digit number (remove +91 if present)
            self.validated_data['did'] = self._extract_phone_number(did_number)
        
        # Validate to (accept both 'to' and 'to_number' for backward compatibility)
        # 'to' is now optional - will be fetched from Firebase if not provided
        to_number = self.data.get('to') or self.data.get('to_number')
        if to_number:
            if not self._validate_phone_number(to_number):
                self.errors['to'] = ['Must be exactly 10 digits (with or without +91 prefix).']
            else:
                # Extract 10-digit number (remove +91 if present)
                self.validated_data['to'] = self._extract_phone_number(to_number)
        
        return len(self.errors) == 0
    
    def _extract_phone_number(self, phone_number):
        """
        Extract 10-digit phone number from input.
        Accepts numbers with or without +91 prefix, and handles leading zeros.
        Examples: 
        - +919876545678 -> 9876545678
        - 9876545678 -> 9876545678
        - 09876545678 -> 9876545678
        """
        if not phone_number:
            return None
        
        # Convert to string and remove any whitespace
        phone_str = str(phone_number).strip()
        
        # Remove +91 prefix if present
        if phone_str.startswith('+91'):
            phone_str = phone_str[3:]  # Remove +91
        elif phone_str.startswith('91') and len(phone_str) == 12:
            phone_str = phone_str[2:]  # Remove 91 if it's 12 digits total
        
        # Remove leading zero if present (e.g., 09876545678 -> 9876545678)
        if phone_str.startswith('0') and len(phone_str) == 11:
            phone_str = phone_str[1:]
        
        # Remove any remaining whitespace
        phone_str = phone_str.strip()
        
        return phone_str
    
    def _validate_phone_number(self, phone_number):
        """
        Validate that phone number is exactly 10 digits.
        Accepts numbers with or without +91 prefix.
        Examples: +919605949378 or 9605949378
        """
        if not phone_number:
            return False
        
        # Extract the 10-digit number
        phone_str = self._extract_phone_number(phone_number)
        
        if not phone_str:
            return False
        
        # Check if it's exactly 10 digits
        if not re.match(r'^\d{10}$', phone_str):
            return False
        
        return True
