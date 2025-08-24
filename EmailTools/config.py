import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    GOOGLE_CREDENTIALS_PATH = os.getenv('GOOGLE_CREDENTIALS_PATH')
    TOKEN_PATH = os.getenv('TOKEN_PATH') # A path to a folder of tokens, use the account name + provider name to store as convention
    EMAIL_ACCOUNTS_PATH = os.getenv('EMAIL_ACCOUNTS_PATH')


