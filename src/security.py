from cryptography.fernet import Fernet
import logging
from db import get_db_connection
from eth_account import Account

def get_hyperliquid_wallet_address(private_key: str) -> str:
    """Derives the wallet address from a private key."""
    try:
        account = Account.from_key(private_key)
        return account.address
    except Exception as e:
        logging.error(f"Error deriving wallet address: {e}")
        return ""

def generate_key():
    """Generates a new Fernet encryption key."""
    return Fernet.generate_key()

def get_or_generate_encryption_key():
    """
    Retrieves the encryption key from the database.
    If it doesn't exist, a new one is generated and stored.
    """
    conn = get_db_connection()
    key = conn.execute('SELECT key FROM encryption_key').fetchone()
    if key:
        conn.close()
        return key['key']
    else:
        logging.info("No encryption key found. Generating a new one.")
        new_key = generate_key()
        try:
            conn.execute('INSERT INTO encryption_key (key) VALUES (?)', (new_key,))
            conn.commit()
            logging.info("New encryption key stored in the database.")
        except Exception as e:
            logging.error(f"Error saving new encryption key: {e}")
            # In a real-world scenario, we might want to handle this more gracefully
            # For this tool, we'll proceed but logging is critical.
        finally:
            conn.close()
        return new_key

def get_fernet_instance():
    """Creates a Fernet instance with the application's encryption key."""
    key = get_or_generate_encryption_key()
    return Fernet(key)

def encrypt_value(value: str) -> bytes:
    """Encrypts a string value."""
    if not isinstance(value, str):
        raise TypeError("Value to encrypt must be a string.")
    f = get_fernet_instance()
    return f.encrypt(value.encode('utf-8'))

def decrypt_value(encrypted_value: bytes) -> str:
    """Decrypts an encrypted value."""
    if not isinstance(encrypted_value, bytes):
        # The database will store it as text, so we need to handle that.
        # Let's encode it back to bytes before decrypting.
        encrypted_value = encrypted_value.encode('utf-8')

    f = get_fernet_instance()
    try:
        decrypted_bytes = f.decrypt(encrypted_value)
        return decrypted_bytes.decode('utf-8')
    except Exception as e:
        logging.error(f"Failed to decrypt value: {e}. This might happen if the encryption key has changed or the data is corrupt.")
        return "" # Return an empty string or handle as an error