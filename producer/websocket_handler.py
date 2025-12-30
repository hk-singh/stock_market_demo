import websocket
import json
import time
import logging
from typing import Callable, List

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FinnhubWebSocketClient:
    """
    WebSocket client for Finnhub real-time trade data.
    Handles connection, reconnection, and message processing.
    """

    def __init__(self, api_key: str, symbols: List[str], on_message_callback: Callable):
        """
        Initialise WebSocket client.

        Args:
            api_key: Finnhub API key
            symbols: List of symbols to subscribe to (e.g., ['AAPL', 'GOOGL'])
            on_message_callback: Function to call when message received
        """
        self.api_key = api_key
        self.symbols = symbols
        self.on_message_callback = on_message_callback
        self.ws_url = f"wss://ws.finnhub.io?token={api_key}"
        self.ws = None
        self.should_reconnect = True

    def on_message(self, ws, message):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(message)

            # Finnhub sends different message types
            if data.get('type') == 'trade':
                # Process trade data
                trades = data.get('data', [])
                for trade in trades:
                    logger.info(f"Trade: {trade['s']} - Price: ${trade['p']}, Volume: {trade['v']}")
                    # Call the callback with the trade data
                    self.on_message_callback(trade)
            elif data.get('type') == 'ping':
                logger.debug("Received ping")
            else:
                logger.debug(f"Received message: {data}")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse message: {e}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def on_error(self, ws, error):
        """Handle WebSocket errors."""
        logger.error(f"WebSocket error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket connection close."""
        logger.warning(f"WebSocket closed: {close_status_code} - {close_msg}")

        # Attempt to reconnect
        if self.should_reconnect:
            logger.info("Attempting to reconnect in 5 seconds...")
            time.sleep(5)
            self.connect()

    def on_open(self, ws):
        """Handle WebSocket connection open."""
        logger.info("WebSocket connection established")

        # Subscribe to symbols
        for symbol in self.symbols:
            subscribe_message = {
                "type": "subscribe",
                "symbol": symbol
            }
            ws.send(json.dumps(subscribe_message))
            logger.info(f"Subscribed to {symbol}")

    def connect(self):
        """Establish WebSocket connection."""
        logger.info(f"Connecting to Finnhub WebSocket...")

        self.ws = websocket.WebSocketApp(
            self.ws_url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )

        # Run forever (blocking call)
        self.ws.run_forever()

    def disconnect(self):
        """Disconnect WebSocket."""
        logger.info("Disconnecting WebSocket...")
        self.should_reconnect = False
        if self.ws:
            self.ws.close()