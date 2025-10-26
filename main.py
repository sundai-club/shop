from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import json
import os

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
    category: str
    sizes: List[str]
    in_stock: bool = True

class CartItem(BaseModel):
    product_id: int
    size: str
    quantity: int

# Sample product data
products = [
    {
        "id": 1,
        "name": "SundAI Classic Tee",
        "description": "Premium quality t-shirt with SundAI logo",
        "price": 29.99,
        "image_url": "/static/images/tshirt.jpg",
        "category": "apparel",
        "sizes": ["XS", "S", "M", "L", "XL", "XXL"],
        "in_stock": True
    },
    {
        "id": 2,
        "name": "SundAI Hoodie",
        "description": "Comfortable hoodie with minimalist design",
        "price": 59.99,
        "image_url": "/static/images/hoodie.jpg",
        "category": "apparel",
        "sizes": ["S", "M", "L", "XL", "XXL"],
        "in_stock": True
    },
    {
        "id": 3,
        "name": "SundAI Cap",
        "description": "Adjustable cap with embroidered logo",
        "price": 19.99,
        "image_url": "/static/images/cap.jpg",
        "category": "accessories",
        "sizes": ["One Size"],
        "in_stock": True
    },
    {
        "id": 4,
        "name": "SundAI Tote Bag",
        "description": "Eco-friendly canvas tote bag",
        "price": 15.99,
        "image_url": "/static/images/tote.jpg",
        "category": "accessories",
        "sizes": ["One Size"],
        "in_stock": True
    }
]

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
    return products

@app.get("/api/products/{product_id}", response_model=Product)
async def get_product(product_id: int):
    product = next((p for p in products if p["id"] == product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@app.get("/api/products/category/{category}", response_model=List[Product])
async def get_products_by_category(category: str):
    return [p for p in products if p["category"] == category]

@app.post("/api/cart")
async def add_to_cart(item: CartItem):
    # Check if product exists
    product = next((p for p in products if p["id"] == item.product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check if size is available
    if item.size not in product["sizes"]:
        raise HTTPException(status_code=400, detail="Size not available")

    # Add to cart
    cart.append({
        "product_id": item.product_id,
        "size": item.size,
        "quantity": item.quantity,
        "product": product
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

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)