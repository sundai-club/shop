import requests
import os
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

load_dotenv()

class PrintfulClient:
    def __init__(self):
        self.api_key = os.getenv("PRINTFUL_API_KEY")
        self.store_id = os.getenv("PRINTFUL_STORE_ID")
        self.base_url = "https://api.printful.com"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        if self.store_id:
            self.headers["X-PF-Store-ID"] = self.store_id

    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict:
        """Make a request to the Printful API"""
        url = f"{self.base_url}{endpoint}"

        try:
            if method == "GET":
                response = requests.get(url, headers=self.headers)
            elif method == "POST":
                response = requests.post(url, headers=self.headers, json=data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"Printful API error: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response content: {e.response.text}")
            raise

    def get_store_info(self) -> Dict:
        """Get store information"""
        return self._make_request("GET", "/stores")

    def get_products(self) -> Dict:
        """Get all products from the store - try catalog products if store products don't exist"""
        try:
            # First try store products (requires store_id)
            if self.store_id:
                return self._make_request("GET", "/store/products")
            else:
                raise Exception("No store ID configured")
        except Exception as e:
            print(f"Store products failed, trying catalog products: {e}")
            # Fall back to catalog products
            return self._make_request("GET", "/products")

    def get_product(self, product_id: int) -> Dict:
        """Get a specific product by ID"""
        return self._make_request("GET", f"/store/products/{product_id}")

    def get_product_variants(self, product_id: int) -> Dict:
        """Get variants for a specific product - try different endpoints"""
        try:
            # Try the main product endpoint first (it includes variants)
            return self._make_request("GET", f"/store/products/{product_id}")
        except Exception as e:
            print(f"Store product variant endpoint failed, trying catalog: {e}")
            # Fall back to catalog variants
            return self._make_request("GET", f"/products/{product_id}/variants")

    def sync_products(self) -> Dict:
        """Sync products from Printful"""
        return self._make_request("POST", "/store/products/sync")

    def create_order(self, order_data: Dict) -> Dict:
        """Create an order (for checkout)"""
        return self._make_request("POST", "/orders", data=order_data)

    def get_shipping_rates(self, recipient: Dict, items: List[Dict]) -> Dict:
        """Get shipping rates for an order"""
        data = {
            "recipient": recipient,
            "items": items
        }
        return self._make_request("POST", "/shipping/rates", data=data)

    def estimate_costs(self, items: List[Dict]) -> Dict:
        """Get cost estimates for items"""
        data = {"items": items}
        return self._make_request("POST", "/orders/estimate", data=data)

    # Removed tax calculation as it's not available in all Printful plans
    # Taxes are typically included in the order estimate

    def confirm_order(self, order_id: int) -> Dict:
        """Confirm an order for fulfillment"""
        return self._make_request("POST", f"/orders/{order_id}/confirm")

    def get_order_status(self, order_id: int) -> Dict:
        """Get order status and tracking information"""
        return self._make_request("GET", f"/orders/{order_id}")

    def get_order_shipments(self, order_id: int) -> Dict:
        """Get shipment information for an order"""
        return self._make_request("GET", f"/orders/{order_id}/shipments")

# Global client instance
printful_client = PrintfulClient()