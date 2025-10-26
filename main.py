from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import json
import os
from printful_client import printful_client

app = FastAPI(title="SundAI Merch Shop", description="Simple merchandise shop for SundAI")

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

# Cache for products
products_cache = []

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

# In-memory cart (in production, use a database)
cart = []

@app.get("/")
async def read_root():
    return FileResponse("static/index.html")

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
async def add_to_cart(item: CartItem):
    global products_cache
    if not products_cache:
        products_cache = get_products_from_printful()

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

    # Add to cart
    cart.append({
        "product_id": item.product_id,
        "size": item.size,
        "quantity": item.quantity,
        "variant_id": variant_id,
        "product": product.model_dump()
    })
    return {"message": "Item added to cart"}

@app.get("/api/cart")
async def get_cart():
    return cart

@app.delete("/api/cart/{item_id}")
async def remove_from_cart(item_id: int):
    global cart
    if 0 <= item_id < len(cart):
        cart.pop(item_id)
        return {"message": "Item removed from cart"}
    raise HTTPException(status_code=404, detail="Cart item not found")

@app.post("/api/estimate-shipping")
async def estimate_shipping(recipient: Dict[str, str]):
    """Estimate shipping rates for cart items"""
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
async def estimate_costs():
    """Estimate total costs for cart items"""
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

@app.get("/api/store-info")
async def get_store_info():
    """Get Printful store information"""
    try:
        stores = printful_client.get_store_info()
        return stores
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get store info: {str(e)}")

@app.post("/api/create-order")
async def create_order(order_data: Dict[str, Any]):
    """Create an order in Printful"""
    global cart

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
        cart = []
        return order
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create order: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)