from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError
from typing import List, Optional, Dict, Any
import json
import os
import uuid
from dotenv import load_dotenv
import stripe
from printful_client import printful_client

load_dotenv()

app = FastAPI(title="SundAI Merch Shop", description="Simple merchandise shop for SundAI")

stripe_publishable_key_cache = ""

def load_stripe_keys(force_reload: bool = False) -> Dict[str, str]:
    """Load Stripe API keys from the environment and cache them."""
    global stripe_publishable_key_cache

    if force_reload or not stripe.api_key:
        stripe_secret = os.getenv("STRIPE_SECRET_KEY", "")
        stripe.api_key = stripe_secret
        if not stripe_secret:
            print("Warning: STRIPE_SECRET_KEY is not set. Stripe checkout will be unavailable.")

    if force_reload or not stripe_publishable_key_cache:
        stripe_publishable_key_cache = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
        if not stripe_publishable_key_cache:
            print("Warning: STRIPE_PUBLISHABLE_KEY is not set. Client checkout will be unavailable.")

    return {
        "publishable_key": stripe_publishable_key_cache,
        "secret_key": stripe.api_key,
    }

stripe_keys = load_stripe_keys()
ESTIMATED_TAX_RATE = float(os.getenv("ESTIMATED_TAX_RATE", "0.085"))

# Add CORS middleware to handle cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for now
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add session middleware with proper configuration
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "sundai-shop-secret-key-2024"),
    session_cookie="sundai_session",
    max_age=86400,  # 24 hours
    same_site="lax",
    https_only=False  # Set to True for production with HTTPS
)

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Data models
class Product(BaseModel):
    id: int
    name: str
    description: str
    price: float
    price_range: Optional[str] = None
    image_url: str
    sizes: List[str]
    in_stock: bool = True
    printful_product_id: Optional[int] = None
    variants: Optional[List[Dict[str, Any]]] = None

class CartItem(BaseModel):
    product_id: int
    size: str
    quantity: int
    variant_id: Optional[int] = None
    variant_price: Optional[float] = None

class RecipientInfo(BaseModel):
    name: str
    address1: str
    city: str
    state: str
    zip: str
    country: str = "US"
    email: Optional[str] = None
    phone: Optional[str] = None

class CreateCheckoutSessionRequest(BaseModel):
    recipient: RecipientInfo

class CheckoutSuccessRequest(BaseModel):
    session_id: str

# Cache for products
products_cache = []

def build_printful_recipient(recipient: RecipientInfo) -> Dict[str, Any]:
    """Map the recipient info into the structure Printful expects."""
    country_code = recipient.country or "US"
    recipient_payload: Dict[str, Any] = {
        "name": recipient.name,
        "address1": recipient.address1,
        "city": recipient.city,
        "state_code": recipient.state,
        "zip": recipient.zip,
        "country_code": country_code
    }
    if recipient.email:
        recipient_payload["email"] = recipient.email
    if recipient.phone:
        recipient_payload["phone"] = recipient.phone
    return recipient_payload

def compute_order_details(cart: List[Dict[str, Any]], recipient: RecipientInfo) -> Dict[str, Any]:
    """Prepare order details including totals and shipping using Printful data."""
    if not cart:
        raise HTTPException(status_code=400, detail="Cart is empty")

    global products_cache
    if not products_cache:
        products_cache = get_products_from_printful()

    printful_items = []
    cart_entries = []
    subtotal = 0.0

    for cart_item in cart:
        variant_id = cart_item.get("variant_id")
        if not variant_id:
            continue

        product = next((p for p in products_cache if p.id == cart_item["product_id"]), None)
        unit_price = cart_item.get("variant_price")
        if unit_price is None and product:
            unit_price = product.price

        if unit_price is None:
            continue

        quantity = cart_item.get("quantity", 1)
        subtotal += unit_price * quantity

        printful_items.append({
            "variant_id": variant_id,
            "quantity": quantity
        })

        cart_entries.append({
            "product_id": cart_item["product_id"],
            "variant_id": variant_id,
            "quantity": quantity,
            "unit_price": unit_price,
            "size": cart_item.get("size"),
            "name": product.name if product else f"Product {cart_item['product_id']}"
        })

    if not printful_items:
        raise HTTPException(status_code=400, detail="No valid items in cart")

    printful_recipient = build_printful_recipient(recipient)

    shipping_rates: List[Dict[str, Any]] = []
    shipping_rate: Dict[str, Any] = {}
    shipping_cost = 0.0
    shipping_note = ""

    try:
        rates_response = printful_client.get_shipping_rates(printful_recipient, printful_items)
        shipping_rates = rates_response.get("result", [])
        if shipping_rates:
            shipping_rate = shipping_rates[0]
            shipping_cost = float(shipping_rate.get("rate", 0) or 0)
        else:
            shipping_note = "Estimated"
            shipping_cost = 9.99
    except Exception as exc:
        print(f"Error retrieving shipping rates: {exc}")
        shipping_rates = []
        shipping_rate = {}
        shipping_note = "Estimated"
        shipping_cost = 9.99

    tax_amount = subtotal * ESTIMATED_TAX_RATE
    tax_note = "Estimated"

    total_cost = subtotal + shipping_cost + tax_amount

    return {
        "subtotal": round(subtotal, 2),
        "shipping_cost": round(shipping_cost, 2),
        "shipping_note": shipping_note,
        "tax_amount": round(tax_amount, 2),
        "tax_note": tax_note,
        "total": round(total_cost, 2),
        "printful_recipient": printful_recipient,
        "shipping_rates": shipping_rates,
        "selected_shipping_rate": shipping_rate,
        "printful_items": printful_items,
        "cart_entries": cart_entries
    }

def get_user_cart(request: Request) -> List[Dict]:
    """Get or create user's cart from session"""
    if "cart" not in request.session:
        request.session["cart"] = []
        request.session["session_id"] = str(uuid.uuid4())[:8]
        print(f"Created new session with ID: {request.session['session_id']}")
    return request.session["cart"]

def convert_printful_to_product(printful_product: Dict, fetch_variants: bool = True) -> Product:
    """Convert Printful product to our Product model"""
    # Extract main product info (direct from product, not nested)
    product_id = printful_product.get("id", 0)
    name = printful_product.get("name", "Unknown Product")
    thumbnail_url = printful_product.get("thumbnail_url")

    # Handle both store products (variants count) and catalog products (variants array)
    variants_field = printful_product.get("variants", [])

    # If variants is just a count, fetch the actual variants
    variants = []
    if fetch_variants and isinstance(variants_field, int) and variants_field > 0:
        try:
            # Get the full product details which should include variants
            product_response = printful_client.get_product(product_id)
            print(f"Full product response keys: {product_response.keys()}")

            # Check if result contains variants
            result = product_response.get("result", product_response)
            if isinstance(result, dict):
                variants = result.get("variants", result.get("sync_variants", []))
                print(f"Found {len(variants)} variants in product details")
                if variants:
                    print(f"First variant fields: {list(variants[0].keys())}")

            # If still no variants, try the variants endpoint
            if not variants and isinstance(variants_field, int):
                variants_response = printful_client.get_product_variants(product_id)
                variants = variants_response.get("result", [])
                print(f"Fetched {len(variants)} variants from variants endpoint")

        except Exception as e:
            print(f"Error fetching variants for product {product_id}: {e}")
            variants = []
    elif isinstance(variants_field, list):
        variants = variants_field

    # Get the main image
    image_url = thumbnail_url if thumbnail_url else "/static/images/placeholder.jpg"

    # Extract available sizes from variants
    sizes = []
    for variant in variants:
        size_name = variant.get("name", "One Size")
        if size_name not in sizes:
            sizes.append(size_name)

    # Determine if in stock (check if any variant is in stock)
    in_stock = False
    for variant in variants:
        # Check various possible stock fields
        availability = variant.get("availability_status", "available")
        stock_status = variant.get("in_stock", variant.get("available",
                        availability == "available" or availability == "active"))
        if stock_status:
            in_stock = True
            break

    # Get price range from all variants
    min_price = float('inf')
    max_price = 0.0
    if variants:
        print(f"Checking prices for {len(variants)} variants:")
        for i, variant in enumerate(variants):
            variant_price = 0.0
            if variant.get("retail_price"):
                variant_price = float(variant["retail_price"])
            elif variant.get("price"):
                variant_price = float(variant["price"]) / 100  # Convert from cents

            if variant_price > 0:
                min_price = min(min_price, variant_price)
                max_price = max(max_price, variant_price)
                print(f"  Variant {i}: {variant.get('name', 'Unknown')} - ${variant_price}")

        # Ensure all variants have numeric prices in the response
        for variant in variants:
            if variant.get("retail_price"):
                try:
                    variant["retail_price"] = float(variant["retail_price"])
                except (ValueError, TypeError):
                    pass
            if variant.get("price"):
                try:
                    variant["price"] = float(variant["price"])
                except (ValueError, TypeError):
                    pass

    # Use price range if there are multiple prices, otherwise use single price
    if min_price == float('inf'):  # No valid prices found
        price = 0.0
        price_range = None
    elif min_price == max_price:
        price = max_price
        price_range = None
    else:
        price = min_price  # Show starting price
        price_range = f"${min_price:.2f} - ${max_price:.2f}"

    return Product(
        id=product_id,
        name=name,
        description=f"High-quality {name.lower()} from SundAI",
        price=price,
        price_range=price_range,
        image_url=image_url,
        sizes=sizes if sizes else ["One Size"],
        in_stock=in_stock,
        printful_product_id=product_id,
        variants=variants
    )

def get_products_from_printful() -> List[Product]:
    """Fetch products from Printful API"""
    try:
        response = printful_client.get_products()
        print(f"Printful API response keys: {response.keys()}")

        # Handle both V1 (result) and V2 (data) response formats
        result = response.get("result", response.get("data", []))
        print(f"Products result type: {type(result)}")

        # Handle both array and single product cases
        if isinstance(result, list):
            printful_products = result
        elif isinstance(result, dict):
            printful_products = [result]  # Wrap single product in list
        else:
            print(f"No products found. Response: {response}")
            return []

        print(f"Found {len(printful_products)} products")
        products = []
        for printful_product in printful_products:
            try:
                product = convert_printful_to_product(printful_product)
                products.append(product)
            except Exception as e:
                print(f"Error converting product {printful_product}: {e}")
                continue

        return products
    except Exception as e:
        print(f"Error fetching products from Printful: {e}")
        return []


@app.get("/")
async def read_root():
    return FileResponse("static/index.html")

@app.get("/checkout-success")
async def checkout_success_page():
    return FileResponse("static/checkout-success.html")

@app.get("/checkout-cancel")
async def checkout_cancel_page():
    return FileResponse("static/checkout-cancel.html")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "SundAI Merch Shop"}

@app.get("/api/products", response_model=List[Product])
async def get_products():
    global products_cache
    if not products_cache:
        products_cache = get_products_from_printful()
    return products_cache

@app.get("/api/products/{product_id}", response_model=Product)
async def get_product(product_id: int):
    global products_cache
    if not products_cache:
        products_cache = get_products_from_printful()

    product = next((p for p in products_cache if p.id == product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@app.post("/api/sync-products")
async def sync_products():
    """Force sync products from Printful"""
    try:
        # Sync products
        printful_client.sync_products()

        # Clear cache and reload
        global products_cache
        products_cache = get_products_from_printful()

        return {"message": "Products synced successfully", "count": len(products_cache)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync products: {str(e)}")

@app.post("/api/cart")
async def add_to_cart(item: CartItem, request: Request):
    print(f"Cart add request received: {item}")
    print(f"Session ID: {request.session.get('session_id', 'no-session')}")
    global products_cache
    if not products_cache:
        products_cache = get_products_from_printful()

    # Get user's cart from session
    cart = get_user_cart(request)

    # Check if product exists
    product = next((p for p in products_cache if p.id == item.product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check if size is available
    if item.size not in product.sizes:
        raise HTTPException(status_code=400, detail="Size not available")

    # Find the variant ID for the selected size
    variant_id = None
    if product.variants:
        for variant in product.variants:
            if variant.get("name") == item.size:
                variant_id = variant.get("id")
                break

    # Add to cart - store minimal data to avoid cookie size limits
    cart.append({
        "product_id": item.product_id,
        "size": item.size,
        "quantity": item.quantity,
        "variant_id": variant_id,
        "variant_price": item.variant_price
        # Don't store full product object - will fetch when needed
    })

    # Save cart to session
    request.session["cart"] = cart
    print(f"Saved cart to session. Session data: {dict(request.session)}")
    return {"message": "Item added to cart"}

@app.get("/api/cart")
async def get_cart(request: Request):
    cart = get_user_cart(request)

    # Enrich cart items with full product data (session stores minimal data)
    enriched_cart = []
    global products_cache
    if not products_cache:
        products_cache = get_products_from_printful()

    for cart_item in cart:
        product = next((p for p in products_cache if p.id == cart_item["product_id"]), None)
        if product:
            enriched_item = cart_item.copy()
            enriched_item["product"] = product.model_dump()
            enriched_cart.append(enriched_item)

    print(f"Cart get request: session has {len(cart)} items, returning {len(enriched_cart)} enriched items")
    return enriched_cart

@app.delete("/api/cart/{item_id}")
async def remove_from_cart(item_id: int, request: Request):
    cart = get_user_cart(request)
    if 0 <= item_id < len(cart):
        cart.pop(item_id)
        # Save updated cart to session
        request.session["cart"] = cart
        return {"message": "Item removed from cart"}
    raise HTTPException(status_code=404, detail="Cart item not found")

@app.post("/api/estimate-shipping")
async def estimate_shipping(recipient: Dict[str, str], request: Request):
    """Estimate shipping rates for cart items"""
    cart = get_user_cart(request)
    if not cart:
        raise HTTPException(status_code=400, detail="Cart is empty")

    # Prepare items for Printful API
    items = []
    for cart_item in cart:
        if cart_item.get("variant_id"):
            items.append({
                "variant_id": cart_item["variant_id"],
                "quantity": cart_item["quantity"]
            })

    if not items:
        raise HTTPException(status_code=400, detail="No valid items in cart")

    try:
        rates = printful_client.get_shipping_rates(recipient, items)
        return rates
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get shipping rates: {str(e)}")

@app.post("/api/estimate-costs")
async def estimate_costs(request: Request):
    """Estimate total costs for cart items"""
    cart = get_user_cart(request)
    if not cart:
        raise HTTPException(status_code=400, detail="Cart is empty")

    # Prepare items for Printful API
    items = []
    for cart_item in cart:
        if cart_item.get("variant_id"):
            items.append({
                "variant_id": cart_item["variant_id"],
                "quantity": cart_item["quantity"]
            })

    if not items:
        raise HTTPException(status_code=400, detail="No valid items in cart")

    try:
        costs = printful_client.estimate_costs(items)
        return costs
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to estimate costs: {str(e)}")

@app.post("/api/calculate-total-cost")
async def calculate_total_cost(order_data: Dict[str, Any], request: Request):
    """
    Calculate total order cost including products, shipping, and taxes

    Expected payload:
    {
        "recipient": {
            "name": "John Doe",
            "address1": "123 Main St",
            "city": "New York",
            "state": "NY",
            "country": "US",
            "zip": "10001"
        },
        "shipping_method": "STANDARD" // optional
    }
    """
    cart = get_user_cart(request)
    if not cart:
        raise HTTPException(status_code=400, detail="Cart is empty")

    recipient_payload = order_data.get("recipient")
    if not recipient_payload:
        raise HTTPException(status_code=400, detail="Recipient information is required")

    try:
        recipient_info = RecipientInfo(**recipient_payload)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid recipient information: {exc.errors()}") from exc

    try:
        order_details = compute_order_details(cart, recipient_info)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to calculate total cost: {str(exc)}") from exc

    return {
        "breakdown": {
            "subtotal": order_details["subtotal"],
            "shipping": order_details["shipping_cost"],
            "shipping_note": order_details["shipping_note"],
            "taxes": order_details["tax_amount"],
            "tax_note": order_details["tax_note"]
        },
        "total": order_details["total"],
        "currency": "USD",
        "available_shipping_rates": order_details["shipping_rates"],
        "selected_shipping_rate": order_details["selected_shipping_rate"]
    }

@app.get("/api/stripe-config")
async def get_stripe_config():
    """Expose Stripe publishable key to the frontend."""
    keys = load_stripe_keys(force_reload=True)
    publishable = keys["publishable_key"]
    if not publishable:
        raise HTTPException(status_code=500, detail="Stripe publishable key is not configured")
    return {"publishableKey": publishable}

@app.post("/api/create-checkout-session")
async def create_checkout_session(payload: CreateCheckoutSessionRequest, request: Request):
    """Create a Stripe checkout session for the current cart."""
    keys = load_stripe_keys(force_reload=True)
    publishable_key = keys["publishable_key"]

    if not keys["secret_key"] or not publishable_key:
        raise HTTPException(status_code=500, detail="Stripe credentials are not configured")

    cart = get_user_cart(request)
    if not cart:
        raise HTTPException(status_code=400, detail="Cart is empty")

    try:
        order_details = compute_order_details(cart, payload.recipient)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to prepare order: {str(exc)}") from exc

    line_items = []
    for entry in order_details["cart_entries"]:
        unit_amount = int(round(entry["unit_price"] * 100))
        if unit_amount <= 0:
            continue

        product_data = {
            "name": entry["name"],
        }
        if entry.get("size"):
            product_data["description"] = f"Size: {entry['size']}"

        line_items.append({
            "price_data": {
                "currency": "usd",
                "unit_amount": unit_amount,
                "product_data": product_data
            },
            "quantity": entry["quantity"]
        })

    if order_details["shipping_cost"] > 0:
        line_items.append({
            "price_data": {
                "currency": "usd",
                "unit_amount": int(round(order_details["shipping_cost"] * 100)),
                "product_data": {"name": "Shipping"}
            },
            "quantity": 1
        })

    if order_details["tax_amount"] > 0:
        line_items.append({
            "price_data": {
                "currency": "usd",
                "unit_amount": int(round(order_details["tax_amount"] * 100)),
                "product_data": {"name": "Taxes"}
            },
            "quantity": 1
        })

    if not line_items:
        raise HTTPException(status_code=400, detail="Unable to create checkout session without priced items")

    base_url = str(request.base_url).rstrip("/")
    success_url = f"{base_url}/checkout-success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base_url}/checkout-cancel"

    session_kwargs: Dict[str, Any] = {
        "mode": "payment",
        "line_items": line_items,
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": request.session.get("session_id"),
        "metadata": {
            "app_session_id": request.session.get("session_id", ""),
            "shipping_note": order_details["shipping_note"],
            "tax_note": order_details["tax_note"]
        }
    }

    recipient_email = payload.recipient.email
    if recipient_email:
        session_kwargs["customer_email"] = recipient_email

    try:
        checkout_session = stripe.checkout.Session.create(**session_kwargs)
    except stripe.error.StripeError as exc:
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(exc)}") from exc

    request.session["pending_order"] = {
        "checkout_session_id": checkout_session.id,
        "printful_order": {
            "recipient": order_details["printful_recipient"],
            "items": order_details["printful_items"],
            "shipping": order_details["selected_shipping_rate"].get("id") or "STANDARD",
            "retail_costs": {
                "currency": "USD",
                "subtotal": order_details["subtotal"],
                "shipping": order_details["shipping_cost"],
                "tax": order_details["tax_amount"],
                "total": order_details["total"]
            },
            "confirm": True,
            "external_id": checkout_session.id
        },
        "summary": {
            "subtotal": order_details["subtotal"],
            "shipping": order_details["shipping_cost"],
            "tax": order_details["tax_amount"],
            "total": order_details["total"]
        },
        "fulfilled": False
    }

    return {
        "checkout_session_id": checkout_session.id,
        "publishableKey": publishable_key
    }

@app.post("/api/checkout-success")
async def complete_checkout(payload: CheckoutSuccessRequest, request: Request):
    """Finalize the order after Stripe confirms payment."""
    keys = load_stripe_keys()
    if not keys["secret_key"]:
        raise HTTPException(status_code=500, detail="Stripe is not configured")

    pending_order = request.session.get("pending_order")
    if not pending_order or pending_order.get("checkout_session_id") != payload.session_id:
        raise HTTPException(status_code=404, detail="No matching pending order found")

    if pending_order.get("fulfilled"):
        return {
            "message": "Order already fulfilled",
            "order_id": pending_order.get("order_id"),
            "summary": pending_order.get("summary")
        }

    try:
        checkout_session = stripe.checkout.Session.retrieve(payload.session_id)
    except stripe.error.StripeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid checkout session: {str(exc)}") from exc

    if checkout_session.payment_status != "paid":
        raise HTTPException(status_code=400, detail="Payment not completed")

    printful_order = pending_order["printful_order"]

    try:
        printful_response = printful_client.create_order(printful_order)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create Printful order: {str(exc)}") from exc

    request.session["cart"] = []
    order_result = printful_response.get("result", {})
    order_summary = pending_order.get("summary")
    pending_order_record = {
        "checkout_session_id": payload.session_id,
        "fulfilled": True,
        "order_id": order_result.get("id"),
        "summary": order_summary
    }
    request.session["pending_order"] = pending_order_record

    return {
        "message": "Order fulfilled successfully",
        "order": printful_response,
        "summary": order_summary
    }
@app.get("/api/store-info")
async def get_store_info():
    """Get Printful store information"""
    try:
        stores = printful_client.get_store_info()
        return stores
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get store info: {str(e)}")

@app.get("/api/catalog-products")
def get_catalog_products():
    """Get all catalog products from Printful"""
    try:
        # Get catalog products (all available products, not just store products)
        response = printful_client._make_request("GET", "/products")
        return {
            "catalog_products": response.get("result", []),
            "count": len(response.get("result", [])),
            "store_products": get_products_from_printful()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get catalog products: {str(e)}")

@app.get("/api/store-products")
async def get_store_products_only():
    """Get only store products (your synced products)"""
    try:
        store_products = await get_products_from_printful()
        return {
            "store_products": store_products,
            "count": len(store_products)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get store products: {str(e)}")

@app.post("/api/confirm-order/{order_id}")
async def confirm_order(order_id: int):
    """Confirm an order for fulfillment"""
    try:
        order = printful_client.confirm_order(order_id)
        return {"message": "Order confirmed for fulfillment", "order": order}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to confirm order: {str(e)}")

@app.get("/api/order-status/{order_id}")
async def get_order_status(order_id: int):
    """Get order status and tracking information"""
    try:
        order = printful_client.get_order_status(order_id)
        shipments = printful_client.get_order_shipments(order_id)
        return {"order": order, "shipments": shipments}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get order status: {str(e)}")

@app.post("/api/create-order")
async def create_order(order_data: Dict[str, Any], request: Request):
    """Create an order in Printful"""
    cart = get_user_cart(request)

    if not cart:
        raise HTTPException(status_code=400, detail="Cart is empty")

    # Prepare items for Printful API
    items = []
    for cart_item in cart:
        if cart_item.get("variant_id"):
            items.append({
                "variant_id": cart_item["variant_id"],
                "quantity": cart_item["quantity"]
            })

    if not items:
        raise HTTPException(status_code=400, detail="No valid items in cart")

    # Prepare order data
    printful_order = {
        "recipient": order_data.get("recipient"),
        "items": items,
        "shipping": order_data.get("shipping", "STANDARD"),
        "retail_price": order_data.get("retail_price", 0)
    }

    try:
        order = printful_client.create_order(printful_order)
        # Clear cart after successful order creation
        request.session["cart"] = []
        return {
            "message": "Order created successfully",
            "order_id": order.get("result", {}).get("id"),
            "status": order.get("result", {}).get("status"),
            "order": order
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create order: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
