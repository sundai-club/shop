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

def convert_printful_to_product(printful_product: Dict) -> Product:
    """Convert Printful product to our Product model"""
    # Extract main product info (direct from product, not nested)
    product_id = printful_product.get("id", 0)
    name = printful_product.get("name", "Unknown Product")
    thumbnail_url = printful_product.get("thumbnail_url")
    variants = printful_product.get("variants", [])

    # Get the main image
    image_url = thumbnail_url if thumbnail_url else "/static/images/placeholder.jpg"

    # Extract available sizes from variants
    sizes = []
    for variant in variants:
        size_name = variant.get("name", "One Size")
        if size_name not in sizes:
            sizes.append(size_name)

    # Determine if in stock (check if any variant is in stock)
    in_stock = any(variant.get("in_stock", False) for variant in variants)

    # Get price from first available variant
    price = 0.0
    if variants:
        for variant in variants:
            if variant.get("retail_price"):
                price = float(variant["retail_price"])
                break

    return Product(
        id=product_id,
        name=name,
        description=f"High-quality {name.lower()} from SundAI",
        price=price,
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
        printful_products = response.get("result", [])

        products = []
        for printful_product in printful_products:
            product = convert_printful_to_product(printful_product)
            products.append(product)

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
        "product": product.dict()
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

@app.post("/api/create-order")
async def create_order(order_data: Dict[str, Any]):
    """Create an order in Printful"""
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
        global cart
        cart = []
        return order
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create order: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)