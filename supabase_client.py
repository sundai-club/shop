import os
import json
from typing import Optional, Dict, Any
from supabase import create_client, Client
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger(__name__)

class SupabaseClient:
    def __init__(self):
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_ANON_KEY")
        self.supabase_service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

        self._client: Optional[Client] = None
        self._service_client: Optional[Client] = None

        if not self.supabase_url:
            logger.warning("SUPABASE_URL not set. Supabase logging will be disabled.")
            return

        if not self.supabase_key:
            logger.warning("SUPABASE_ANON_KEY not set. Supabase logging will be disabled.")
            return

    @property
    def client(self) -> Optional[Client]:
        """Get the Supabase client with anon key (for limited operations)"""
        if not self.supabase_url or not self.supabase_key:
            return None

        if not self._client:
            try:
                self._client = create_client(self.supabase_url, self.supabase_key)
                logger.info("Supabase client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Supabase client: {e}")
                return None

        return self._client

    @property
    def service_client(self) -> Optional[Client]:
        """Get the Supabase client with service role key (for admin operations)"""
        if not self.supabase_url or not self.supabase_service_key:
            logger.warning("SUPABASE_SERVICE_ROLE_KEY not set. Using anon key instead.")
            return self.client

        if not self._service_client:
            try:
                self._service_client = create_client(self.supabase_url, self.supabase_service_key)
                logger.info("Supabase service client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Supabase service client: {e}")
                return self.client

        return self._service_client

    def log_order(self, order_data: Dict[str, Any]) -> Optional[str]:
        """
        Log an order to the Supabase orders table

        Args:
            order_data: Dictionary containing order information

        Returns:
            Order ID if successful, None otherwise
        """
        try:
            client = self.service_client or self.client
            if not client:
                logger.error("No Supabase client available for order logging")
                return None

            # Prepare the order record
            order_record = {
                "stripe_checkout_session_id": order_data.get("stripe_checkout_session_id"),
                "printful_order_id": order_data.get("printful_order_id"),
                "app_session_id": order_data.get("app_session_id"),
                "customer_name": order_data.get("customer_name"),
                "customer_email": order_data.get("customer_email"),
                "customer_phone": order_data.get("customer_phone"),
                "shipping_address": order_data.get("shipping_address", {}),
                "order_status": order_data.get("order_status", "pending"),
                "payment_status": order_data.get("payment_status", "pending"),
                "currency": order_data.get("currency", "USD"),
                "subtotal": float(order_data.get("subtotal", 0)),
                "shipping_cost": float(order_data.get("shipping_cost", 0)),
                "tax_amount": float(order_data.get("tax_amount", 0)),
                "total_amount": float(order_data.get("total_amount", 0)),
                "items": order_data.get("items", []),
                "printful_order_data": order_data.get("printful_order_data"),
                "printful_cost_data": order_data.get("printful_cost_data"),
                "printful_retail_costs": order_data.get("printful_retail_costs"),
                "printful_shipping_method_id": order_data.get("printful_shipping_method_id"),
                "shipping_note": order_data.get("shipping_note"),
                "tax_note": order_data.get("tax_note"),
                "cost_source": order_data.get("cost_source", "estimated"),
                "stripe_payment_intent_id": order_data.get("stripe_payment_intent_id"),
                "stripe_customer_id": order_data.get("stripe_customer_id"),
                "metadata": order_data.get("metadata", {}),
                "error_message": order_data.get("error_message")
            }

            # Insert the order
            response = client.table("orders").insert(order_record).execute()

            if response.data:
                order_id = response.data[0].get("id")
                logger.info(f"Order logged successfully: {order_id}")
                return str(order_id)
            else:
                logger.error(f"Failed to log order: {response}")
                return None

        except Exception as e:
            logger.error(f"Error logging order to Supabase: {e}")
            return None

    def update_order_status(self, order_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update order status and other fields

        Args:
            order_id: UUID of the order
            updates: Dictionary of fields to update

        Returns:
            True if successful, False otherwise
        """
        try:
            client = self.service_client or self.client
            if not client:
                logger.error("No Supabase client available for order update")
                return False

            response = client.table("orders").update(updates).eq("id", order_id).execute()

            if response.data:
                logger.info(f"Order {order_id} updated successfully")
                return True
            else:
                logger.error(f"Failed to update order {order_id}: {response}")
                return False

        except Exception as e:
            logger.error(f"Error updating order {order_id} in Supabase: {e}")
            return False

    def get_order_by_stripe_session(self, stripe_session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get order by Stripe checkout session ID

        Args:
            stripe_session_id: Stripe checkout session ID

        Returns:
            Order data if found, None otherwise
        """
        try:
            client = self.service_client or self.client
            if not client:
                logger.error("No Supabase client available for order lookup")
                return None

            response = client.table("orders").select("*").eq("stripe_checkout_session_id", stripe_session_id).execute()

            if response.data:
                return response.data[0]
            else:
                return None

        except Exception as e:
            logger.error(f"Error looking up order by Stripe session {stripe_session_id}: {e}")
            return None

    def get_orders_by_email(self, email: str) -> list:
        """
        Get all orders for a customer email

        Args:
            email: Customer email address

        Returns:
            List of orders
        """
        try:
            client = self.service_client or self.client
            if not client:
                logger.error("No Supabase client available for order lookup")
                return []

            response = client.table("orders").select("*").eq("customer_email", email).order("created_at", desc=True).execute()

            return response.data if response.data else []

        except Exception as e:
            logger.error(f"Error looking up orders by email {email}: {e}")
            return []

# Global Supabase client instance
supabase_client = SupabaseClient()