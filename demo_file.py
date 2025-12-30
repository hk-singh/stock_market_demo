import os
import finnhub
import pandas as pd
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get API key from environment variable
api_key = os.getenv('FINNHUB_API_KEY')

if not api_key:
    raise ValueError("FINNHUB_API_KEY not found in environment variables")

# Setup client
finnhub_client = finnhub.Client(api_key=api_key)

# Company profile 2
print(finnhub_client.company_profile2(symbol='AAPL'))
