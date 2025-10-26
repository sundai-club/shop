# SundAI Merch Shop

A simple merchandise shop for SundAI, built with FastAPI backend and vanilla JavaScript/CSS frontend.

## Features

- **Product Catalog**: Browse SundAI merchandise with categories
- **Shopping Cart**: Add/remove items, adjust quantities
- **Responsive Design**: Works on desktop and mobile
- **Clean UI**: Minimalist design inspired by sundai.club
- **REST API**: Full backend API for products and cart management

## Tech Stack

- **Backend**: FastAPI (Python)
- **Frontend**: Vanilla HTML, CSS, JavaScript
- **Styling**: Custom CSS with Inter font
- **Images**: PIL-generated placeholders

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the application:
```bash
python main.py
```

3. Open your browser and go to `http://localhost:8000`

## API Endpoints

- `GET /api/products` - Get all products
- `GET /api/products/{id}` - Get specific product
- `GET /api/products/category/{category}` - Get products by category
- `GET /api/cart` - Get cart contents
- `POST /api/cart` - Add item to cart
- `DELETE /api/cart/{item_id}` - Remove item from cart

## Project Structure

```
shop/
├── main.py                 # FastAPI application
├── requirements.txt        # Python dependencies
├── static/
│   ├── index.html         # Frontend HTML
│   ├── css/
│   │   └── style.css      # Styles
│   ├── js/
│   │   └── app.js         # Frontend JavaScript
│   └── images/
│       ├── tshirt.jpg     # Product images
│       ├── hoodie.jpg
│       ├── cap.jpg
│       └── tote.jpg
└── README.md              # This file
```

## Customization

- **Products**: Modify the `products` list in `main.py` to add/change products
- **Styling**: Edit `static/css/style.css` to customize the appearance
- **Images**: Replace placeholder images in `static/images/`

## Future Enhancements

- Payment processing integration
- User accounts and authentication
- Order history
- Inventory management
- Admin interface for product management