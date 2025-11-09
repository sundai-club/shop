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
    sync_variant_id: Optional[int] = None

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
countries_cache: List[Dict[str, str]] = []

def _to_float(value: Any, default: float = 0.0) -> float:
    """Coerce Printful monetary strings into floats."""
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default

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

    def normalize_costs(cost_dict: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {}
        if not cost_dict:
            return normalized
        for key, value in cost_dict.items():
            if key == "currency":
                normalized[key] = value or "USD"
            else:
                normalized[key] = _to_float(value, 0.0)
        return normalized

    printful_items = []
    cart_entries = []
    retail_subtotal = 0.0

    for cart_item in cart:
        product = next((p for p in products_cache if p.id == cart_item["product_id"]), None)

        variant_id = cart_item.get("variant_id")
        sync_variant_id = cart_item.get("sync_variant_id")
        matched_variant = None

        if product and product.variants:
            for variant in product.variants:
                variant_sync_id = variant.get("id")
                if sync_variant_id is not None and str(variant_sync_id) == str(sync_variant_id):
                    matched_variant = variant
                    break

            if not matched_variant and variant_id is not None:
                for variant in product.variants:
                    candidate_id = variant.get("variant_id") or variant.get("id")
                    if candidate_id is not None and str(candidate_id) == str(variant_id):
                        matched_variant = variant
                        break

            if not matched_variant:
                for variant in product.variants:
                    if variant.get("name") == cart_item.get("size"):
                        matched_variant = variant
                        break

            if matched_variant:
                variant_id = matched_variant.get("variant_id") or matched_variant.get("id")
                sync_variant_id = matched_variant.get("id")
                cart_item["variant_id"] = variant_id
                cart_item["sync_variant_id"] = sync_variant_id

        if not variant_id:
            continue

        try:
            variant_id_int = int(variant_id)
        except (TypeError, ValueError):
            continue
        cart_item["variant_id"] = variant_id_int

        unit_price = cart_item.get("variant_price")
        if unit_price is None and product:
            unit_price = product.price

        if unit_price is None:
            continue

        try:
            unit_price = float(unit_price)
        except (TypeError, ValueError):
            continue

        quantity = int(cart_item.get("quantity", 1) or 1)
        retail_subtotal += unit_price * quantity

        # Build Printful item with sync_variant_id if available
        printful_item = {
            "quantity": quantity
        }

        # Add sync_variant_id if available (for synced products)
        if sync_variant_id:
            printful_item["sync_variant_id"] = int(sync_variant_id)
            printful_item["source"] = "sync"
        else:
            # Fallback to variant_id for non-synced products
            printful_item["variant_id"] = variant_id_int

        printful_items.append(printful_item)

        cart_entries.append({
            "product_id": cart_item["product_id"],
            "variant_id": variant_id_int,
            "quantity": quantity,
            "unit_price": round(unit_price, 2),
            "size": cart_item.get("size"),
            "name": product.name if product else f"Product {cart_item['product_id']}"
        })

    if not printful_items:
        raise HTTPException(status_code=400, detail="No valid items in cart")

    # Create separate items array for shipping rates API (different format)
    shipping_items = []
    for cart_item in cart:
        if cart_item.get("variant_id"):
            shipping_items.append({
                "variant_id": str(cart_item["variant_id"]),  # Shipping API expects string
                "quantity": cart_item["quantity"],
                "value": str(cart_item.get("variant_price", "0.00"))  # Required field
            })

    printful_recipient = build_printful_recipient(recipient)

    shipping_rates: List[Dict[str, Any]] = []
    shipping_rate: Dict[str, Any] = {}
    shipping_cost = 0.0
    shipping_note = ""

    try:
        rates_response = printful_client.get_shipping_rates(printful_recipient, shipping_items)
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

    # Use actual shipping cost from Printful shipping rates API
    if shipping_rates:
        # We have actual shipping costs from Printful
        shipping_note = f"{shipping_rate.get('name', 'Standard')} via Printful"
    else:
        # Fallback shipping
        shipping_note = "Fallback estimate"

    # Calculate tax - for now use estimated rate, but this could be improved
    tax_amount = retail_subtotal * ESTIMATED_TAX_RATE
    tax_note = "Estimated"

    subtotal = retail_subtotal
    total_cost = subtotal + shipping_cost + tax_amount

    def format_money(value: float) -> str:
        return f"{value:.2f}"

    retail_breakdown = {
        "currency": "USD",
        "subtotal": round(retail_subtotal, 2),
        "shipping": round(shipping_cost, 2),
        "tax": round(tax_amount, 2),
        "discount": 0.0,
        "total": round(total_cost, 2)
    }

    retail_costs_payload = {
        "currency": retail_breakdown["currency"],
        "subtotal": format_money(retail_breakdown["subtotal"]),
        "discount": format_money(retail_breakdown["discount"]),
        "shipping": format_money(retail_breakdown["shipping"]),
        "tax": format_money(retail_breakdown["tax"]),
        "total": format_money(retail_breakdown["total"])
    }

    printful_costs: Dict[str, Any] = {}
    printful_retail_costs: Dict[str, Any] = {}
    shipping_method_id = shipping_rate.get("id") if shipping_rate else None

    try:
        estimate_response = printful_client.estimate_costs(
            recipient=printful_recipient,
            items=printful_items,
            shipping=shipping_method_id,
            retail_costs=retail_costs_payload
        )
        estimate_result = estimate_response.get("result", estimate_response)
        printful_costs = normalize_costs(estimate_result.get("costs"))
        printful_retail_costs = normalize_costs(estimate_result.get("retail_costs"))
    except Exception as exc:
        print(f"Error retrieving Printful cost estimate: {exc}")

    if printful_costs:
        subtotal = round(printful_costs.get("subtotal", subtotal), 2)
        shipping_cost = round(printful_costs.get("shipping", shipping_cost), 2)
        tax_amount = round(
            printful_costs.get("tax", printful_costs.get("vat", tax_amount)),
            2
        )
        total_cost = round(
            printful_costs.get("total", subtotal + shipping_cost + tax_amount),
            2
        )
        tax_note = "Printful"
        if not shipping_rates:
            shipping_note = "Printful rate"

        desired_subtotal = subtotal
        if desired_subtotal > 0 and cart_entries:
            current_line_total = round(sum(
                entry["unit_price"] * entry["quantity"] for entry in cart_entries
            ), 2)
            adjusted_line_total = 0.0

            if current_line_total > 0:
                multiplier = desired_subtotal / current_line_total
                for entry in cart_entries:
                    entry["unit_price"] = round(entry["unit_price"] * multiplier, 2)
                    adjusted_line_total += entry["unit_price"] * entry["quantity"]
            else:
                total_quantity = sum(entry["quantity"] for entry in cart_entries)
                if total_quantity > 0:
                    per_unit = round(desired_subtotal / total_quantity, 2)
                    for entry in cart_entries:
                        entry["unit_price"] = per_unit
                        adjusted_line_total += entry["unit_price"] * entry["quantity"]

            diff = round(desired_subtotal - adjusted_line_total, 2)
            if abs(diff) >= 0.01 and cart_entries:
                last_entry = cart_entries[-1]
                per_unit_adjustment = diff / max(last_entry["quantity"], 1)
                last_entry["unit_price"] = round(
                    last_entry["unit_price"] + per_unit_adjustment, 2
                )
    else:
        subtotal = round(subtotal, 2)
        shipping_cost = round(shipping_cost, 2)
        tax_amount = round(tax_amount, 2)
        total_cost = round(total_cost, 2)

    return {
        "subtotal": subtotal,
        "shipping_cost": shipping_cost,
        "shipping_note": shipping_note,
        "tax_amount": tax_amount,
        "tax_note": tax_note,
        "total": total_cost,
        "cost_source": "printful" if printful_costs else "estimated",
        "retail_subtotal": round(retail_subtotal, 2),
        "printful_costs": printful_costs,
        "retail_costs": printful_retail_costs if printful_retail_costs else retail_breakdown,
        "shipping_method_id": shipping_method_id,
        "printful_recipient": printful_recipient,
        "shipping_rates": shipping_rates,
        "selected_shipping_rate": shipping_rate,
        "printful_items": printful_items,
        "cart_entries": cart_entries
    }

def get_available_countries() -> List[Dict[str, str]]:
    """Retrieve and cache the list of countries supported by Printful."""
    global countries_cache
    if countries_cache:
        return countries_cache

    try:
        countries_response = printful_client.get_countries()
        results = countries_response.get("result", [])
        countries_cache = [
            {"code": country.get("code"), "name": country.get("name")}
            for country in results
            if country.get("code") and country.get("name")
        ]
    except Exception as exc:
        print(f"Failed to load countries from Printful: {exc}")
        countries_cache = []

    return countries_cache

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
    catalog_category = None
    catalog_subcategory = None
    catalog_gender = None
    catalog_name_prefix = None

    if variants:
        mockup_url = None
        fallback_variant_image = None
        for variant in variants:
            files = variant.get("files") or []
            mockup_file = next((f for f in files if f.get("type") in {"mockup", "preview"} and f.get("preview_url")), None)
            if mockup_file:
                mockup_url = mockup_file.get("preview_url")
                break
            product_image = variant.get("product", {}).get("image") or variant.get("product", {}).get("preview_image")
            if product_image and not fallback_variant_image:
                fallback_variant_image = product_image
            if not catalog_category:
                product_meta = variant.get("product", {})
                catalog_name_prefix = catalog_name_prefix or product_meta.get("name")
                product_id = product_meta.get("product_id")
                variant_id = product_meta.get("variant_id")
                if product_id and variant_id:
                    try:
                        catalog_response = printful_client._make_request("GET", f"/products/{product_id}")
                        catalog_result = catalog_response.get("result", {})
                        main_category = catalog_result.get("main_category")
                        if main_category:
                            catalog_category = main_category.get("name")
                            catalog_gender = main_category.get("gender")
                            catalog_subcategory = main_category.get("parent", {}).get("name")
                    except Exception as catalog_exc:
                        print(f"Failed to fetch catalog metadata for product {product_id}: {catalog_exc}")

        image_url = mockup_url or fallback_variant_image or image_url

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

@app.get("/api/countries")
async def get_countries():
    countries = get_available_countries()
    if not countries:
        raise HTTPException(status_code=500, detail="Failed to load countries from Printful")

    sorted_countries = sorted(countries, key=lambda c: c["name"])
    return {"countries": sorted_countries}

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
    sync_variant_id = None
    if product.variants:
        for variant in product.variants:
            if variant.get("name") == item.size:
                variant_id = variant.get("variant_id") or variant.get("id")
                sync_variant_id = variant.get("id")
                break

    if not variant_id:
        raise HTTPException(status_code=400, detail="Selected variant is unavailable")

    # Add to cart - store minimal data to avoid cookie size limits
    cart.append({
        "product_id": item.product_id,
        "size": item.size,
        "quantity": item.quantity,
        "variant_id": variant_id,
        "variant_price": item.variant_price,
        "sync_variant_id": sync_variant_id
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
async def estimate_costs(order_data: Dict[str, Any], request: Request):
    """Estimate total costs for the current cart using Printful data."""
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
        raise HTTPException(status_code=500, detail=f"Failed to estimate costs: {str(exc)}") from exc

    return {
        "printful_costs": order_details.get("printful_costs"),
        "retail_costs": order_details.get("retail_costs"),
        "cost_source": order_details.get("cost_source"),
        "subtotal": order_details.get("subtotal"),
        "shipping": order_details.get("shipping_cost"),
        "tax": order_details.get("tax_amount"),
        "total": order_details.get("total")
    }

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

    response = {
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
        "selected_shipping_rate": order_details["selected_shipping_rate"],
        "cost_source": order_details.get("cost_source", "estimated")
    }

    if order_details.get("printful_costs"):
        response["printful_costs"] = order_details["printful_costs"]
    if order_details.get("retail_costs"):
        response["retail_costs"] = order_details["retail_costs"]
    if order_details.get("retail_subtotal") is not None:
        response["retail_subtotal"] = order_details["retail_subtotal"]

    return response

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

    recipient_country = (payload.recipient.country or "US").upper()
    shipping_address = {
        "line1": payload.recipient.address1,
        "city": payload.recipient.city,
        "state": payload.recipient.state,
        "postal_code": payload.recipient.zip,
        "country": recipient_country,
    }
    shipping_address = {k: v for k, v in shipping_address.items() if v}

    metadata_payload = {
        "recipient_name": payload.recipient.name,
        "recipient_city": payload.recipient.city,
        "recipient_state": payload.recipient.state,
        "recipient_zip": payload.recipient.zip
    }
    metadata_payload = {k: v for k, v in metadata_payload.items() if v}

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
        },
        "billing_address_collection": "auto",
        "customer_creation": "if_required",
        "payment_intent_data": {}
    }

    payment_intent_data: Dict[str, Any] = session_kwargs["payment_intent_data"]
    if metadata_payload:
        payment_intent_data["metadata"] = metadata_payload

    if shipping_address:
        shipping_payload: Dict[str, Any] = {
            "name": payload.recipient.name,
            "address": shipping_address
        }
        if payload.recipient.phone:
            shipping_payload["phone"] = payload.recipient.phone
        payment_intent_data["shipping"] = shipping_payload
    else:
        session_kwargs["shipping_address_collection"] = {
            "allowed_countries": [recipient_country]
        }

    if not payment_intent_data:
        session_kwargs.pop("payment_intent_data")

    recipient_email = payload.recipient.email
    if recipient_email:
        session_kwargs["customer_email"] = recipient_email

    try:
        checkout_session = stripe.checkout.Session.create(**session_kwargs)
    except stripe.error.StripeError as exc:
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(exc)}") from exc

    selected_shipping = order_details.get("selected_shipping_rate") or {}
    shipping_method = order_details.get("shipping_method_id") or selected_shipping.get("id") or "STANDARD"

    request.session["pending_order"] = {
        "checkout_session_id": checkout_session.id,
        "printful_order": {
            "recipient": order_details["printful_recipient"],
            "items": order_details["printful_items"],
            "shipping": shipping_method,
            "retail_costs": {
                "currency": "USD",
                "subtotal": order_details["subtotal"],
                "shipping": order_details["shipping_cost"],
                "tax": order_details["tax_amount"],
                "total": order_details["total"]
            },
            "confirm": True
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

    # Debug: Log the order data being sent to Printful
    print(f"DEBUG: Sending order to Printful: {printful_order}")

    try:
        printful_response = printful_client.create_order(printful_order)
    except Exception as exc:
        # Check if it's the specific "no print files" error
        error_msg = str(exc)
        if "print files" in error_msg.lower():
            detailed_error = (
                "This product variant doesn't have design files configured in Printful. "
                "Your payment was successful, but we need to configure the design files. "
                "Please contact support with your order details for assistance."
            )
            raise HTTPException(status_code=400, detail=detailed_error) from exc
        else:
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

    # Prepare items for Printful API (same logic as checkout)
    items = []
    for cart_item in cart:
        if cart_item.get("variant_id") or cart_item.get("sync_variant_id"):
            # Build Printful item with sync_variant_id if available
            item = {
                "quantity": cart_item["quantity"]
            }

            # Add sync_variant_id if available (for synced products)
            if cart_item.get("sync_variant_id"):
                item["sync_variant_id"] = cart_item["sync_variant_id"]
                item["source"] = "sync"
            else:
                # Fallback to variant_id for non-synced products
                item["variant_id"] = cart_item["variant_id"]

            items.append(item)

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
        # Check if it's the specific "no print files" error
        error_msg = str(e)
        if "print files" in error_msg.lower():
            detailed_error = (
                "This product variant doesn't have design files configured in Printful. "
                "Please add design files to this product variant in your Printful dashboard "
                f"or contact support. Details: {error_msg}"
            )
            raise HTTPException(status_code=400, detail=detailed_error) from e
        else:
            raise HTTPException(status_code=500, detail=f"Failed to create order: {str(e)}") from e

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
